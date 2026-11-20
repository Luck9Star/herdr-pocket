#!/usr/bin/env python3
"""Exercise the packaged Windows Tauri WebView2 window with an isolated SSH peer."""
import argparse
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager, suppress

from PIL import ImageGrab, ImageStat
import tauri_linux_direct_ssh as linux
from flutter_windows_direct_ssh import (check_desktop, owned_job, require, runner_failure,
    verify_listener_release, windows_fixture, windows_loopback_listener_owners, loopback_connect_outcome)
from paired_gui import GuiFailure, WebDriver, wait_for
from terminal_screenshot_gate import ScreenshotGateError, verify_terminal_screenshot

if sys.platform == 'win32':
    import win32api
    import win32con
    import win32gui
    import win32job
    import win32process

CAPTURE = 'Win32 foreground desktop framebuffer, native Tauri client pixels'

class WindowsDriver(linux.DesktopDriver):
    def __init__(self):
        super().__init__()
        self.focus_guard = None

    def call(self, method, path, data=None):
        if self.focus_guard is not None and method == 'POST' and path.endswith(('/click','/clear','/value','/actions')):
            self.focus_guard()
        return super().call(method, path, data)

    def start(self, binary):
        def ready():
            try:
                return self.call('GET', '/status')
            except (OSError, ValueError):
                return False
        wait_for(ready, 'webdriver_unavailable')
        reply = self.call('POST', '/session', {'capabilities': {'alwaysMatch': {
            'tauri:options': {'application': str(binary.resolve())}}}})
        require(isinstance(reply, dict) and isinstance(reply.get('sessionId'), str), 'windows_tauri_session_invalid')
        self.session = '/session/' + reply['sessionId']


def listeners_owned(ports, pids, lookup):
    for port in ports:
        owners = lookup(port)
        if len(owners) != 1 or owners[0][0] is not True or owners[0][1] not in pids:
            return False
    return True


def owned_window(job):
    owners = set(win32job.QueryInformationJobObject(job, win32job.JobObjectBasicProcessIdList))
    windows = []
    def visit(hwnd, _):
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        if pid in owners and win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == 'Herdr Pocket':
            windows.append((hwnd, pid))
        return True
    win32gui.EnumWindows(visit, None)
    require(len(windows) <= 1, 'windows_tauri_window_ambiguous')
    return windows[0] if windows else None


def foreground_is_owned(job, hwnd, pid):
    check_desktop()
    require(owned_window(job) == (hwnd, pid), 'windows_tauri_window_owner_changed')
    return win32gui.GetForegroundWindow() == hwnd and not win32gui.IsIconic(hwnd)


def request_foreground(hwnd):
    user32 = ctypes.windll.user32
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.restype = ctypes.c_int
    return bool(user32.SetForegroundWindow(ctypes.c_void_p(hwnd)))


def caption_hit(hwnd, x, y):
    # WM_NCHITTEST is read-only. Bound both the wait and the signed screen coordinates.
    if not (-32768 <= x <= 32767 and -32768 <= y <= 32767): return False
    user32 = ctypes.windll.user32
    fn = user32.SendMessageTimeoutW
    fn.argtypes = [ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t,
                   ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_size_t)]
    fn.restype = ctypes.c_ssize_t
    result = ctypes.c_size_t()
    packed = (x & 0xffff) | ((y & 0xffff) << 16)
    return bool(fn(ctypes.c_void_p(hwnd), 0x84, 0, packed, 0x2, 1000, ctypes.byref(result))) and result.value == 2


def mouse_capture_free():
    # Check the foreground thread's mouse capture before any user click.
    class Rect(ctypes.Structure):
        _fields_ = [('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
    class GuiThreadInfo(ctypes.Structure):
        _fields_ = [('cbSize',ctypes.c_uint32),('flags',ctypes.c_uint32),
                    *[(field,ctypes.c_void_p) for field in ('active','focus','capture','menu','move','caret')],
                    ('rect',Rect)]
    info = GuiThreadInfo(); info.cbSize = ctypes.sizeof(info)
    fn = ctypes.windll.user32.GetGUIThreadInfo
    fn.argtypes = [ctypes.c_uint32,ctypes.POINTER(GuiThreadInfo)]; fn.restype = ctypes.c_int
    return bool(fn(0,ctypes.byref(info))) and not info.capture


def click_once():
    # One standard mouse down/up pair, never replayed on an unknown result.
    class MouseInput(ctypes.Structure):
        _fields_ = [('dx',ctypes.c_long),('dy',ctypes.c_long),('mouseData',ctypes.c_uint32),
                    ('flags',ctypes.c_uint32),('time',ctypes.c_uint32),('extra',ctypes.c_size_t)]
    class KeyboardInput(ctypes.Structure):
        _fields_ = [('vk',ctypes.c_uint16),('scan',ctypes.c_uint16),('flags',ctypes.c_uint32),
                    ('time',ctypes.c_uint32),('extra',ctypes.c_size_t)]
    class HardwareInput(ctypes.Structure):
        _fields_ = [('message',ctypes.c_uint32),('low',ctypes.c_uint16),('high',ctypes.c_uint16)]
    class InputData(ctypes.Union):
        _fields_ = [('mouse',MouseInput),('keyboard',KeyboardInput),('hardware',HardwareInput)]
    class Input(ctypes.Structure):
        _fields_ = [('kind',ctypes.c_uint32),('data',InputData)]
    events = (Input * 2)()
    events[0].data.mouse.flags = 0x2; events[1].data.mouse.flags = 0x4
    fn = ctypes.windll.user32.SendInput
    fn.argtypes = [ctypes.c_uint,ctypes.POINTER(Input),ctypes.c_int]; fn.restype = ctypes.c_uint
    return fn(2,events,ctypes.sizeof(Input)) == 2


def caption_point(job, hwnd, pid):
    require(owned_window(job) == (hwnd,pid) and win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd),
            'windows_tauri_window_owner_changed')
    left,top,right,bottom = win32gui.GetWindowRect(hwnd)
    _,client_top = win32gui.ClientToScreen(hwnd,(0,0))
    monitor = win32api.MonitorFromWindow(hwnd,win32con.MONITOR_DEFAULTTONULL)
    require(monitor, 'windows_tauri_caption_unavailable')
    x0,y0,x1,y1 = win32api.GetMonitorInfo(monitor)['Monitor']
    caption_top = max(top,y0); caption_bottom = min(client_top,y1,bottom)
    require(right > left and caption_bottom-caption_top >= 4, 'windows_tauri_caption_unavailable')
    x = (max(left,x0)+min(right,x1))//2; y = (caption_top+caption_bottom)//2
    require(x0 <= x < x1 and y0 <= y < y1, 'windows_tauri_caption_unavailable')
    hit = win32gui.WindowFromPoint((x,y))
    require(hit and win32gui.GetAncestor(hit,win32con.GA_ROOT) == hwnd and
            win32process.GetWindowThreadProcessId(hit)[1] == pid and caption_hit(hwnd,x,y),
            'windows_tauri_caption_unavailable')
    return (x,y)


def activate_owned_window(job, hwnd, pid, report):
    check_desktop()
    require(owned_window(job) == (hwnd,pid), 'windows_tauri_window_owner_changed')
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    def wait_foreground(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if foreground_is_owned(job,hwnd,pid): return True
            time.sleep(.05)
        return foreground_is_owned(job,hwnd,pid)
    if foreground_is_owned(job,hwnd,pid):
        report['windowActivation'] = 'already_foreground'; return
    request_foreground(hwnd)
    if wait_foreground(1):
        report['windowActivation'] = 'set_foreground'; return
    point = caption_point(job,hwnd,pid)
    require(mouse_capture_free(), 'windows_tauri_mouse_capture_unavailable')
    win32api.SetCursorPos(point)
    require(win32api.GetCursorPos() == point and caption_point(job,hwnd,pid) == point and mouse_capture_free(),
            'windows_tauri_caption_unavailable')
    require(click_once(), 'windows_tauri_activation_click_unconfirmed')
    require(wait_foreground(2), 'windows_tauri_window_not_foreground')
    report['windowActivation'] = 'caption_click'


def framebuffer(job, hwnd, pid, viewport, rectangles):
    check_desktop()
    require(owned_window(job) == (hwnd, pid) and win32gui.GetForegroundWindow() == hwnd and
            not win32gui.IsIconic(hwnd), 'windows_tauri_window_not_foreground')
    rect = win32gui.GetClientRect(hwnd)
    left, top = win32gui.ClientToScreen(hwnd, rect[:2])
    right, bottom = win32gui.ClientToScreen(hwnd, rect[2:])
    require([right-left, bottom-top] == viewport and viewport[0] >= 960 and viewport[1] >= 600,
            'windows_tauri_viewport_mismatch')
    monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONULL)
    require(monitor, 'windows_tauri_window_offscreen')
    x0,y0,x1,y1 = win32api.GetMonitorInfo(monitor)['Monitor']
    require(x0 <= left < right <= x1 and y0 <= top < bottom <= y1, 'windows_tauri_window_offscreen')
    for x,y,w,h in rectangles:
        require(all(type(n) in (int,float) for n in (x,y,w,h)) and x >= 0 and y >= 0 and
                w > 0 and h > 0 and x+w <= viewport[0] and y+h <= viewport[1], 'windows_tauri_geometry_invalid')
        for px,py in ((x,y), (x+w-1,y), (x,y+h-1), (x+w-1,y+h-1), (x+w/2,y+h/2)):
            child = win32gui.WindowFromPoint((left+int(px),top+int(py)))
            require(child and win32gui.GetAncestor(child, win32con.GA_ROOT) == hwnd,
                    'windows_tauri_window_occluded')
    return (left,top,right,bottom)


def capture(driver, job, hwnd, pid, geometry, rectangles):
    before = framebuffer(job, hwnd, pid, geometry['viewport'], rectangles)
    image = ImageGrab.grab(bbox=before, include_layered_windows=True, all_screens=True)
    require(list(image.size) == geometry['viewport'] and framebuffer(job, hwnd, pid, geometry['viewport'], rectangles) == before,
            'windows_tauri_capture_changed')
    stream = io.BytesIO(); image.save(stream, format='PNG'); data = stream.getvalue()
    return data, image


def capture_terminal(driver, job, hwnd, pid, endpoint, token):
    for attempt in range(1, 4):
        before = wait_for(lambda: linux.terminal_geometry(driver, endpoint), 'direct_ssh_terminal_geometry_missing')
        png, _ = capture(driver, job, hwnd, pid, before, [before['bounds'], before['endpointBounds']])
        require(linux.terminal_geometry(driver, endpoint) == before, 'direct_ssh_terminal_geometry_changed')
        try:
            evidence = verify_terminal_screenshot(png, expected_token=token, bounds=before['bounds'])
            return png, {**evidence, 'captureAttempt': attempt, 'capture': CAPTURE,
                         'targetBounds': before['endpointBounds']}
        except ScreenshotGateError as error:
            if str(error) not in linux.RENDER_PENDING or attempt == 3: raise
            time.sleep(.2)


def capture_outcome(driver, job, hwnd, pid, selector):
    def geometry():
        return driver.observe('''const el=node(arguments[0]);
          if (!visible(el) || document.hidden || !document.hasFocus() || devicePixelRatio !== 1) return null;
          const r=el.getBoundingClientRect(); return {viewport:[innerWidth,innerHeight],bounds:[r.left,r.top,r.width,r.height]};''', selector)
    before = wait_for(geometry, 'direct_ssh_outcome_geometry_missing')
    png, image = capture(driver, job, hwnd, pid, before, [before['bounds']])
    require(geometry() == before, 'direct_ssh_outcome_geometry_changed')
    x,y,w,h = before['bounds']
    require(max(ImageStat.Stat(image.crop((int(x),int(y),int(x+w),int(y+h)))).var) > 1,
            'windows_tauri_outcome_blank')
    return png, {'imageSha256':hashlib.sha256(png).hexdigest(), 'imageSize':before['viewport'],
                 'bounds':before['bounds'], 'capture':CAPTURE}


SAFE_FAILURE_CODES = frozenset({
    'webdriver_unavailable', 'windows_tauri_driver_listener_unowned',
    'windows_tauri_session_invalid', 'windows_tauri_visible_window_missing',
    'windows_tauri_window_owner_changed', 'windows_tauri_caption_unavailable',
    'windows_tauri_activation_unconfirmed',
    'windows_tauri_mouse_capture_unavailable', 'windows_tauri_activation_click_unconfirmed',
    'windows_tauri_window_ambiguous', 'windows_tauri_window_not_foreground',
    'windows_tauri_viewport_mismatch', 'windows_tauri_window_offscreen',
    'windows_tauri_geometry_invalid', 'windows_tauri_window_occluded',
    'windows_tauri_capture_changed', 'windows_tauri_temp_cleanup_unconfirmed',
    'windows_tauri_dpi_unavailable', 'windows_tauri_toolchain_missing',
    'windows_tauri_driver_port_collision', 'windows_tauri_unowned_peer_listener',
    'windows_tauri_password_cleanup_unconfirmed', 'windows_tauri_driver_ports_unreleased',
    'windows_tauri_temporary_directory_remains', 'windows_tauri_receipt_incomplete',
    'windows_tauri_listener_receipt_invalid', 'windows_tauri_cleanup_receipt_invalid',
    'windows_tauri_images_missing', 'windows_tauri_image_receipt_invalid',
    'terminal_screenshot_token_invalid', 'terminal_screenshot_bounds_invalid',
    'terminal_screenshot_pillow_missing', 'terminal_screenshot_png_invalid',
    'terminal_screenshot_ocr_missing', 'terminal_screenshot_ocr_failed',
    'terminal_screenshot_echo_not_visible', 'terminal_screenshot_token_not_visible',
    'terminal_screenshot_proof_not_adjacent',
})

def safe_failure_code(error):
    code = str(error)
    if code in SAFE_FAILURE_CODES: return code
    if code.startswith('webdriver_'): return 'windows_tauri_webdriver_error'
    if code.startswith('direct_ssh_'): return 'windows_tauri_gui_evidence_failed'
    if code.startswith('windows_direct_'): return 'windows_tauri_native_evidence_failed'
    return 'windows_tauri_unclassified'

FAILURE_PHASES = frozenset({'desktop','fixture','launch','driver_listeners','driver_session',
    'native_window','window_activation','interaction','driver_close','job_teardown','fixture_cleanup','temp_cleanup'})

def set_phase(report, phase):
    if phase not in FAILURE_PHASES: raise ValueError('invalid failure phase')
    report['failurePhase'] = phase
    report['checkpoint'] = phase

def record_failure(report, phase, error, *, key='primaryFailure'):
    # Never serialize exception messages, paths, raw driver logs or remote data.
    if key in report:
        return
    failure = {'phase': phase if phase in FAILURE_PHASES else 'launch'}
    if isinstance(error, (GuiFailure, ScreenshotGateError)):
        failure['code'] = safe_failure_code(error)
    else:
        failure.update(runner_failure(error))
    report[key] = failure

@contextmanager
def private_temporary_directory(base, report):
    root = Path(tempfile.mkdtemp(prefix='hp-tauri-windows-direct-', dir=base))
    failed = False
    try:
        yield root
    except BaseException as error:
        failed = True
        record_failure(report, report.get('failurePhase','launch'), error)
        raise
    finally:
        last = None
        for attempt in range(5):
            try:
                shutil.rmtree(root)
                last = None
                break
            except OSError as error:
                if isinstance(error, FileNotFoundError) and not os.path.lexists(root):
                    last = None
                    break
                last = error
                # Antivirus or a just-exited child can briefly retain a handle.
                # Retry only this owned directory and only the sharing violation.
                if getattr(error,'winerror',None) != 32 or attempt == 4:
                    break
                time.sleep(.25 * (attempt + 1))
        if last is not None:
            record_failure(report, 'temp_cleanup', last, key='temporaryCleanupFailure')
            if not failed:
                raise GuiFailure('windows_tauri_temp_cleanup_unconfirmed') from None


@contextmanager
def key_fixture(mode):
    if mode == 'plain':
        with windows_fixture(publickey=True) as (fixture, credentials):
            try:
                yield fixture, credentials
            finally:
                credentials.clear()
    else:
        from ios_encrypted_key_fixture import EncryptedKeyFixture
        with EncryptedKeyFixture(screen_proof=True, channel_deadline=time.monotonic()+1250) as fixture:
            credentials = {'privateKey':fixture.private_key, 'passphrase':fixture.passphrase}
            try:
                yield fixture, credentials
            finally:
                credentials.clear()


def publickey_session(facts, *, sent, closed):
    linux.probe_evidence(facts, 2)
    linux.verify_shell(facts, 2, 'A', sent=sent, closed=closed, publickey=True)


def execute_key(driver, fixture, credentials, report, *, encrypted):
    host='127.0.0.1'; endpoint=f'{fixture.username}@{host}:{fixture.port}'
    algorithm=fixture.public_key.split(' ',1)[0]
    report['stage']='dashboard'
    wait_for(lambda:driver.observe(linux.DASHBOARD_WITNESS),'direct_ssh_empty_dashboard_entry_unavailable')
    driver.click('#host-empty-add')
    report['stage']='connection_choice'
    wait_for(lambda:driver.observe(linux.CHOICE_WITNESS),'direct_ssh_connection_choice_unavailable')
    driver.click('#add-ssh')
    report['stage']='target'
    wait_for(lambda:driver.observe(linux.TARGET_WITNESS),'direct_ssh_target_form_unavailable')
    for selector,value in (('#ssh-host',host),('#ssh-port',str(fixture.port)),('#ssh-user',fixture.username)):
        driver.fill(selector,value)
    require(driver.observe('return ["#ssh-password", "#ssh-connect", "#ssh-review"].every(s => node(s).disabled);'),
            'direct_ssh_credentials_ungated_before_probe')
    report['stage']='probe';driver.click('#ssh-probe')
    wait_for(lambda:driver.observe(linux.REVIEW_WITNESS,endpoint,algorithm,fixture.fingerprint),
             'direct_ssh_fingerprint_not_visible_or_mismatched')
    require(fixture.wait_for_connections_closed(1),'direct_ssh_probe_not_closed')
    linux.probe_evidence(fixture.snapshot(),1)
    report['target']={'host':host,'port':fixture.port,'username':fixture.username,
                      'algorithm':algorithm,'fingerprint':fixture.fingerprint}
    report['fingerprintReviewed']=True
    driver.click('#ssh-trust-confirm')
    wait_for(lambda:driver.observe('return visible(node("#ssh-auth-key")) && node("#ssh-review").checked;'),
             'direct_ssh_key_choice_unavailable')
    driver.click('#ssh-auth-key')
    report['stage']='key_entry'
    wait_for(lambda:driver.observe(linux.KEY_FIELDS_WITNESS,endpoint),'direct_ssh_key_fields_unproven')
    require(driver.observe('return node("#ssh-passphrase").type === "password" && '+linux.CLEARED_KEY_CONTROLS+
                           ' && arguments[0].every(s => node(s).value === "");',linux.SECRET_FIELDS),
            'direct_ssh_key_fields_not_empty')
    private_key=credentials['privateKey']
    require(isinstance(private_key,str) and private_key.count('\n') >= 3 and private_key.endswith('\n'),
            'windows_tauri_fixture_key_invalid')
    driver.fill('#ssh-key',private_key)
    if encrypted:
        require(driver.observe('return node("#ssh-connect").disabled && node("#ssh-passphrase").value === "";'),
                'direct_ssh_encrypted_key_did_not_require_passphrase')
    driver.click('#ssh-passphrase')
    require(driver.observe(linux.KEY_COLLAPSED_WITNESS),'direct_ssh_pem_collapse_unproven')
    driver.click('#ssh-key-summary')
    wait_for(lambda:driver.observe(linux.KEY_REDRAFT_WITNESS,private_key),'direct_ssh_pem_redraft_mismatch')
    driver.click('#ssh-passphrase')
    require(driver.observe(linux.KEY_COLLAPSED_WITNESS),'direct_ssh_pem_recollapse_unproven')
    if encrypted:
        driver.fill('#ssh-passphrase',credentials['passphrase'])
        require(driver.observe('return node("#ssh-passphrase").type === "password" && node("#ssh-passphrase").value === arguments[0];',
                               credentials['passphrase']), 'direct_ssh_passphrase_mask_unproven')
    require(driver.observe(linux.KEY_FIELDS_WITNESS,endpoint),'direct_ssh_key_review_changed')
    wait_for(lambda:driver.observe('return actionableButton(node("#ssh-connect"), "连接 SSH");'),
             'direct_ssh_key_connect_not_actionable')
    report['keyEntry']={'multilineExact':True,'passphraseMasked':True,'collapsed':True,
                        'summaryHit':True,'reopenedExactFocused':True,'collapsedAgain':True}
    private_key=''
    linux.probe_evidence(fixture.snapshot(),1)
    report['stage']='connect';driver.click('#ssh-connect')
    require(fixture.wait_for('shellRequested'),'direct_ssh_shell_not_requested')
    wait_for(lambda:bool(fixture.snapshot()['connectionEvents'][-1]['outputBytes']),'direct_ssh_shell_no_output')
    publickey_session(fixture.snapshot(),sent=False,closed=False)
    report['publicKeyAuthenticated']=True
    wait_for(lambda:driver.observe('const el = node("#ssh-live-endpoint"); return visible(el) && el.innerText === arguments[0];',endpoint),
             'direct_ssh_live_target_mismatched')
    report['stage']='input';driver.click('#ssh-terminal .xterm-screen')
    wait_for(lambda:linux.terminal_geometry(driver,endpoint),'direct_ssh_input_target_unproven')
    driver.send_test_line()
    require(fixture.wait_for('markerReceived'),'direct_ssh_marker_not_received')
    publickey_session(fixture.snapshot(),sent=True,closed=False)
    report['stage']='capture';png,screen=linux.capture_terminal(driver,endpoint,fixture.screen_token)
    publickey_session(fixture.snapshot(),sent=True,closed=False)
    report['stage']='disconnect';driver.click('#ssh-disconnect')
    wait_for(lambda:driver.observe('''const card=node('#ssh-closed-feedback'), title=node('#ssh-closed-title'), detail=node('#ssh-closed-detail');
      return visible(card) && visible(title) && visible(detail) && card.contains(title) && card.contains(detail) &&
      card.dataset.phase === 'confirmed' && actionableButton(node('#ssh-return-home'),'返回首页') &&
      title.innerText === '本机已断开' && detail.innerText === '凭据已清空，重连时请重新填写。' &&
      !visible(node('#ssh-live')) && node('#ssh-live-endpoint').innerText === '';'''),
      'direct_ssh_ui_disconnect_unconfirmed')
    require(fixture.wait_for_connections_closed(2),'direct_ssh_peer_disconnect_unconfirmed')
    publickey_session(fixture.snapshot(),sent=True,closed=True)
    require(driver.observe('return '+linux.CLEARED_KEY_CONTROLS+
      ' && arguments[0].every(s => node(s).value === "") && node("#ssh-connect").disabled;',linux.SECRET_FIELDS),
      'direct_ssh_credentials_not_cleared')
    outcome_png,outcome=linux.capture_outcome(driver,'#ssh-closed-feedback')
    publickey_session(fixture.snapshot(),sent=True,closed=True)
    report['stage']='return_home';driver.click('#ssh-return-home')
    wait_for(lambda:driver.observe('''const home=node('#home-dashboard'), result=node('#host-ssh-disconnected');
      const empty=node('#host-empty'), add=node('#host-empty-add'), shortcut=node('#home-open-ssh');
      return visible(home) && visible(result) && home.contains(result) && result.innerText === '本机已断开' &&
      result.dataset.phase === 'confirmed' && visible(empty) && home.contains(empty) && empty.contains(add) &&
      actionableButton(add,'添加主机') && home.contains(shortcut) && actionableButton(shortcut,'普通 SSH') &&
      !visible(node('#home-ssh'));'''),'direct_ssh_home_not_restored')
    home_png,home=linux.capture_outcome(driver,'#host-ssh-disconnected')
    publickey_session(fixture.snapshot(),sent=True,closed=True)
    report.update(terminal=screen,disconnectOutcome=outcome,homeOutcome=home,returnedHome=True,credentialFieldsCleared=True)
    return {'ordinary-terminal.png':png,'ordinary-disconnect.png':outcome_png,'ordinary-home.png':home_png}


def run(app, report, base, *, authentication="password"):
    report['stage'] = 'desktop'; check_desktop()
    ctypes.windll.user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    require(ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)), 'windows_tauri_dpi_unavailable')
    driver_bin = shutil.which('tauri-driver.exe'); edge = shutil.which('msedgedriver.exe')
    require(driver_bin and edge and shutil.which('tesseract'), 'windows_tauri_toolchain_missing')
    driver = WindowsDriver(); port, native_port = linux.driver_port(), linux.driver_port()
    require(port != native_port, 'windows_tauri_driver_port_collision')
    driver.base = f'http://127.0.0.1:{port}'
    with private_temporary_directory(base, report) as root:
        env = {k:v for k,v in os.environ.items() if not k.startswith('HERDR_') and k not in ('SSH_AUTH_SOCK','SSH_AGENT_PID')}
        for name in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
            path = root / name; path.mkdir(); env[name] = str(path)
        report['stage'] = 'fixture'
        fixture_context = windows_fixture(publickey=False) if authentication == 'password' else key_fixture(authentication)
        with fixture_context as (fixture, credentials):
            if authentication == 'password': credentials.clear()
            listener = report['listener'] = {'ownedBeforeLaunch': windows_loopback_listener_owners(fixture.port) == [(True, os.getpid())]}
            require(listener['ownedBeforeLaunch'], 'windows_tauri_unowned_peer_listener')
            set_phase(report, 'launch')
            command = [driver_bin, '--port', str(port), '--native-port', str(native_port), '--native-driver', edge]
            try:
                with owned_job(command, cwd=root, env=env, log=root/'driver.log', report=report) as (_,job):
                    close_attempted = False
                    set_phase(report, 'driver_listeners')
                    try:
                        def owned_listeners():
                            pids = set(win32job.QueryInformationJobObject(job, win32job.JobObjectBasicProcessIdList))
                            return listeners_owned((port, native_port), pids, windows_loopback_listener_owners)
                        wait_for(owned_listeners, 'windows_tauri_driver_listener_unowned')
                        set_phase(report, 'driver_session')
                        driver.start(app)
                        set_phase(report, 'native_window')
                        hwnd, pid = wait_for(lambda: owned_window(job), 'windows_tauri_visible_window_missing')
                        set_phase(report, 'window_activation')
                        activate_owned_window(job,hwnd,pid,report)
                        def ensure_foreground():
                            require(foreground_is_owned(job,hwnd,pid), 'windows_tauri_window_not_foreground')
                        driver.focus_guard = ensure_foreground
                        original_terminal, original_outcome = linux.capture_terminal, linux.capture_outcome
                        linux.capture_terminal = lambda d,e,t: capture_terminal(d,job,hwnd,pid,e,t)
                        linux.capture_outcome = lambda d,s: capture_outcome(d,job,hwnd,pid,s)
                        try:
                            set_phase(report, 'interaction')
                            images = (linux.execute(driver, fixture, report) if authentication == 'password' else
                                      execute_key(driver, fixture, credentials, report, encrypted=authentication == 'encrypted'))
                        finally:
                            linux.capture_terminal, linux.capture_outcome = original_terminal, original_outcome
                        report['peer'] = fixture.snapshot()
                        close_attempted = True
                        set_phase(report, 'driver_close')
                        driver.close()
                        set_phase(report, 'job_teardown')
                    except BaseException as error:
                        record_failure(report, report.get('failurePhase','launch'), error)
                        report['peer'] = fixture.snapshot()
                        if driver.session and not close_attempted:
                            with suppress(GuiFailure, OSError, ValueError): driver.close()
                        raise
            finally:
                if 'peer' not in report: report['peerAfterFailedLaunch'] = fixture.snapshot()
        report['stage'] = 'cleanup'; set_phase(report, 'fixture_cleanup')
        verify_listener_release(fixture, listener)
        require(fixture.password == '', 'windows_tauri_password_cleanup_unconfirmed')
        if authentication == 'encrypted':
            require(fixture.private_key == '' and fixture.passphrase == '' and fixture.wrong_passphrase == '',
                    'windows_tauri_key_cleanup_unconfirmed')
        require(not credentials, 'windows_tauri_key_cleanup_unconfirmed')
        wait_for(lambda: loopback_connect_outcome(port) == 'refused' and loopback_connect_outcome(native_port) == 'refused',
                 'windows_tauri_driver_ports_unreleased', timeout=10)
    require(not root.exists(), 'windows_tauri_temporary_directory_remains')
    report['cleanup'] = {'ownedProcessJobEmpty':True,'peerListenerReleased':True,
                         'fixturePasswordCleared':True,'driverPortsReleased':True,'privateDirectoryRemoved':True}
    return images


def validate_success(report, images):
    require(report.get('windowActivation') in ('already_foreground','set_foreground','caption_click'),
            'windows_tauri_activation_unconfirmed')
    require(report.get('fingerprintReviewed') is True and report.get('returnedHome') is True and
            report.get('credentialFieldsCleared') is True, 'windows_tauri_receipt_incomplete')
    if report.get('authentication') == 'password':
        linux.session_evidence(report.get('peer', {}), sent=True, closed=True)
    else:
        require(report.get('authentication') == 'publickey' and report.get('keyEncryption') in ('none','openssh') and
                report.get('publicKeyAuthenticated') is True and
                report.get('keyEntry') == {'multilineExact':True,'passphraseMasked':True,'collapsed':True,
                                           'summaryHit':True,'reopenedExactFocused':True,'collapsedAgain':True},
                'windows_tauri_key_receipt_incomplete')
        publickey_session(report.get('peer', {}), sent=True, closed=True)
    require(report.get('listener', {}).get('ownedBeforeLaunch') is True and
            report.get('listener', {}).get('fixtureResourcesClosed') is True and
            report.get('listener', {}).get('absentFromWin32Table') is True and
            report.get('listener', {}).get('connectProbe') == 'refused', 'windows_tauri_listener_receipt_invalid')
    require(report.get('cleanup') == {'ownedProcessJobEmpty':True,'peerListenerReleased':True,
        'fixturePasswordCleared':True,'driverPortsReleased':True,'privateDirectoryRemoved':True},
        'windows_tauri_cleanup_receipt_invalid')
    require(set(images) == {'ordinary-terminal.png','ordinary-disconnect.png','ordinary-home.png'},
            'windows_tauri_images_missing')
    for name, section in (('ordinary-terminal.png','terminal'),('ordinary-disconnect.png','disconnectOutcome'),
                          ('ordinary-home.png','homeOutcome')):
        evidence = report.get(section, {})
        require(evidence.get('capture') == CAPTURE and
                evidence.get('imageSha256') == hashlib.sha256(images[name]).hexdigest(),
                'windows_tauri_image_receipt_invalid')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--authentication', choices=('password','plain','encrypted'), default='password')
    args = parser.parse_args(); app=args.app.resolve(); output=args.output.resolve()
    base=Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir())).resolve()
    if (sys.platform != 'win32' or not re.fullmatch(r'[0-9a-f]{40}',args.source_sha) or not app.is_file()
        or not output.is_relative_to(base) or output == base or
        (os.environ.get('GITHUB_ACTIONS') == 'true' and args.source_sha != os.environ.get('GITHUB_SHA'))):
        parser.error('requires Windows, a native executable, full matching SHA and fresh temporary output')
    output.mkdir(parents=True,exist_ok=False)
    report={'schemaVersion':1,'sourceSHA':args.source_sha,'executableSHA256':hashlib.sha256(app.read_bytes()).hexdigest(),
            'platform':'Windows Tauri WebView2',
            'authentication':'password' if args.authentication == 'password' else 'publickey',
            **({'keyEncryption':'none' if args.authentication == 'plain' else 'openssh'} if args.authentication != 'password' else {}),
            'scope':'native window, WebDriver input, desktop pixels and isolated SSH',
            'status':'failed'}
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    try:
        images=run(app,report,base,authentication=args.authentication)
        validate_success(report,images)
        for name,png in images.items(): (output/name).write_bytes(png)
        report.update(status='passed',stage='complete')
    except (GuiFailure,ScreenshotGateError) as error: report['errorCode']=safe_failure_code(error)
    except Exception as error:
        report.update(errorCode='windows_tauri_runner_failed',runnerFailure=runner_failure(error))
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if report['status'] != 'passed':
        print(f"Windows Tauri ordinary SSH failed at {report.get('stage')}: {report['errorCode']}",flush=True); return 1
    return 0

if __name__ == '__main__': raise SystemExit(main())
