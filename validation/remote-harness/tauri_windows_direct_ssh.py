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


def run(app, report, base):
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
        with windows_fixture(publickey=False) as (fixture, credentials):
            credentials.clear()
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
                        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                        require(win32gui.GetForegroundWindow() == hwnd, 'windows_tauri_window_not_foreground')
                        original_terminal, original_outcome = linux.capture_terminal, linux.capture_outcome
                        linux.capture_terminal = lambda d,e,t: capture_terminal(d,job,hwnd,pid,e,t)
                        linux.capture_outcome = lambda d,s: capture_outcome(d,job,hwnd,pid,s)
                        try:
                            set_phase(report, 'interaction')
                            images = linux.execute(driver, fixture, report)
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
        wait_for(lambda: loopback_connect_outcome(port) == 'refused' and loopback_connect_outcome(native_port) == 'refused',
                 'windows_tauri_driver_ports_unreleased', timeout=10)
    require(not root.exists(), 'windows_tauri_temporary_directory_remains')
    report['cleanup'] = {'ownedProcessJobEmpty':True,'peerListenerReleased':True,
                         'fixturePasswordCleared':True,'driverPortsReleased':True,'privateDirectoryRemoved':True}
    return images


def validate_success(report, images):
    require(report.get('fingerprintReviewed') is True and report.get('returnedHome') is True and
            report.get('credentialFieldsCleared') is True, 'windows_tauri_receipt_incomplete')
    linux.session_evidence(report.get('peer', {}), sent=True, closed=True)
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
    args = parser.parse_args(); app=args.app.resolve(); output=args.output.resolve()
    base=Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir())).resolve()
    if (sys.platform != 'win32' or not re.fullmatch(r'[0-9a-f]{40}',args.source_sha) or not app.is_file()
        or not output.is_relative_to(base) or output == base or
        (os.environ.get('GITHUB_ACTIONS') == 'true' and args.source_sha != os.environ.get('GITHUB_SHA'))):
        parser.error('requires Windows, a native executable, full matching SHA and fresh temporary output')
    output.mkdir(parents=True,exist_ok=False)
    report={'schemaVersion':1,'sourceSHA':args.source_sha,'executableSHA256':hashlib.sha256(app.read_bytes()).hexdigest(),
            'platform':'Windows Tauri WebView2',
            'authentication':'password','scope':'native window, WebDriver input, desktop pixels and isolated SSH',
            'status':'failed'}
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    try:
        images=run(app,report,base)
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
