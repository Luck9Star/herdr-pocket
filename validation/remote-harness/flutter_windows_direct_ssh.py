#!/usr/bin/env python3
"""Run a Windows Flutter integration test on an interactive Win32 desktop."""
import argparse
from contextlib import contextmanager
import ctypes
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageGrab, ImageStat
from direct_ssh_fixture import DirectSshFixture
from flutter_linux_direct_ssh import (
    FLUTTER_COMMIT, FLUTTER_ROOT, FLUTTER_VERSION, PENDING_PIXELS, PHASES as UI_PHASES, SHARED_STEPS,
    locked_dependencies, read_exchange,
)
from paired_gui import GuiFailure, wait_for
from tauri_linux_direct_ssh import probe_evidence, require, session_evidence, verify_shell
from terminal_screenshot_gate import ScreenshotGateError, verify_terminal_screenshot

if sys.platform == 'win32':
    import pywintypes
    import win32api
    import win32con
    import win32gui
    import win32job
    import win32process
    import win32service
    import win32ts

TEST = 'windows_direct_ssh_test.dart'
PHASES = ('probe', 'connected', 'capture', 'disconnect', 'complete')
PUBLICKEY_PHASES = ('probe', 'key_entry', 'connected', 'capture', 'disconnect', 'complete')
RETURN_STEPS = frozenset('return_home_' + stage for stage in (
    'button_checking', 'button_missing', 'button_multiple', 'button_disabled', 'button_not_hit', 'button_unstable',
    'button_ready', 'button_enabled', 'tap', 'route', 'catalog', 'entry', 'entry_disabled', 'notice',
    'catalog_identity', 'receipt', 'flutter_exception', 'geometry', 'publish', 'acknowledged',
))
FRAMEWORK_KINDS = {'FlutterError', 'AssertionError', 'StateError', 'TypeError', 'ArgumentError',
                   'PlatformException', 'MissingPluginException', 'Other'}
FRAMEWORK_LIBRARIES = {'rendering', 'widgets', 'scheduler', 'services', 'gestures', 'foundation', 'test', 'other'}
FRAMEWORK_ANCHORS = {'app-sidebar', 'direct-form', 'direct-page-header', 'direct-trust-header',
                     'direct-closed-feedback', 'direct-active-target', 'host-catalog-list',
                     'home-empty-card', 'home-ssh-closed'}
FRAMEWORK_CREATORS = {'Column', 'Row', 'Flex', 'Stack', 'ListView'}
FRAMEWORK_SOURCES = {'direct_ssh_page', 'host_catalog_page', 'main', 'design_tokens'}
WINDOW_TITLE = 'herdr_flutter_probe'
WINDOW_CLASS = 'FLUTTER_RUNNER_WIN32_WINDOW'
CAPTURE = 'Win32 visible desktop framebuffer, clipped to FLUTTERVIEW client pixels'
WIN_ERRORS = {2, 3, 5, 6, 8, 13, 32, 50, 87, 109, 122, 123, 126, 127,
              193, 216, 233, 267, 740, 995, 1114, 1314, 1450, 1453, 1460, 1816}
RUNNER_ERRORS = (AttributeError, BrokenPipeError, FileNotFoundError, KeyError, OSError, PermissionError,
                 subprocess.CalledProcessError, subprocess.TimeoutExpired, TypeError, ValueError)
TCP_TABLE_OWNER_PID_LISTENER = 3
MIB_TCP_STATE_LISTEN = 2
ERROR_INSUFFICIENT_BUFFER = 122


class TcpOwnerRow(ctypes.Structure):
    _fields_ = [(field, ctypes.c_uint32) for field in (
        'state', 'local_address', 'local_port', 'remote_address', 'remote_port', 'owning_pid',
    )]


class TcpOwnerTable(ctypes.Structure):
    _fields_ = [('count', ctypes.c_uint32), ('rows', TcpOwnerRow * 1)]


def loopback_listener_owners(table, port):
    offset = TcpOwnerTable.rows.offset
    row_size = ctypes.sizeof(TcpOwnerRow)
    error = 'windows_direct_listener_table_invalid'
    require(len(table) >= offset, error)
    count = ctypes.c_uint32.from_buffer_copy(table).value
    require(count <= (len(table) - offset) // row_size, error)
    loopback = int.from_bytes(socket.inet_aton('127.0.0.1'), sys.byteorder)
    owners = []
    for index in range(count):
        row = TcpOwnerRow.from_buffer_copy(table, offset + index * row_size)
        # Only sockets covering this IPv4 destination are relevant. The top
        # sixteen bits of dwLocalPort can contain uninitialized data.
        if row.local_address in (0, loopback) and socket.ntohs(row.local_port & 0xffff) == port:
            require(row.state == MIB_TCP_STATE_LISTEN, error)
            owners.append((row.local_address == loopback, row.owning_pid))
    return owners


def windows_loopback_listener_owners(port):
    table_api = ctypes.WinDLL('iphlpapi').GetExtendedTcpTable
    table_api.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int32,
                          ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    table_api.restype = ctypes.c_uint32
    size = ctypes.c_uint32(16384)
    error = 'windows_direct_listener_table_unavailable'
    for _ in range(3):
        require(0 < size.value <= 16 * 1024 * 1024, error)
        buffer = ctypes.create_string_buffer(size.value)
        result = table_api(buffer, ctypes.byref(size), False, socket.AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0)
        if result == 0:
            return loopback_listener_owners(buffer, port)
        require(result == ERROR_INSUFFICIENT_BUFFER, error)
    raise GuiFailure(error)


def loopback_connect_outcome(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        # A short connect timeout can expire before Windows reports refusal.
        # Only an actual refusal is evidence, even with the longer deadline.
        client.settimeout(5)
        try:
            client.connect(('127.0.0.1', port))
        except ConnectionRefusedError:
            return 'refused'
        except TimeoutError:
            return 'timeout'
        except OSError as error:
            code = getattr(error, 'winerror', error.errno)
            if code in (errno.ECONNREFUSED, 10061):  # WSAECONNREFUSED
                return 'refused'
            if code in (errno.ETIMEDOUT, 10060):  # WSAETIMEDOUT
                return 'timeout'
            return 'other_error'
    return 'connected'


def verify_listener_release(fixture, evidence):
    evidence['fixtureResourcesClosed'] = fixture.local_resources_released()
    require(evidence['fixtureResourcesClosed'], 'windows_direct_fixture_resources_unconfirmed')
    evidence['absentFromWin32Table'] = not windows_loopback_listener_owners(fixture.port)
    require(evidence['absentFromWin32Table'], 'windows_direct_peer_listener_still_present')
    evidence['connectProbe'] = loopback_connect_outcome(fixture.port)
    require(evidence['connectProbe'] == 'refused', 'windows_direct_peer_listener_unconfirmed')


def runner_failure(error):
    # pywintypes.error carries (winerror, funcname, strerror). Only the fixed
    # class and allowlisted numeric value are public, never those strings.
    native = sys.platform == 'win32' and isinstance(error, pywintypes.error)
    category = error.__class__.__name__ if type(error) in RUNNER_ERRORS else 'OtherError'
    detail = {'exceptionClass': 'PyWinTypesError' if native else category}
    if native or isinstance(error, OSError):
        code = getattr(error, 'winerror', None)
        if type(code) is int and code in WIN_ERRORS:
            detail['winError'] = code
    return detail


def prepare(app, source, flutter, log, env):
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    with log.open('wb') as stream:
        version = subprocess.run([flutter, '--version', '--machine'], cwd=app, env=env,
                                 stdout=subprocess.PIPE, stderr=stream, check=True, timeout=120)
        sdk = json.loads(version.stdout)
        require(sdk.get('frameworkVersion') == FLUTTER_VERSION and sdk.get('frameworkRevision') == FLUTTER_COMMIT,
                'windows_direct_sdk_mismatch')
        generated = json.loads((app / '.herdr-generated-probe.json').read_text(encoding='utf-8'))
        require(generated == {'kind': 'herdr-flutter-validation', 'sourceCommit': source},
                'windows_direct_scaffold_mismatch')
        lock = app / 'pubspec.lock'
        base_lock = lock.read_text(encoding='utf-8')
        manifest = json.loads((app / 'candidate-manifest.json').read_text(encoding='utf-8'))
        require(manifest.get('sourceCommit') == source and manifest.get('variant') == 'experimental-patched'
                and manifest.get('candidateLockSha256') == digest(lock), 'windows_direct_candidate_lock_unverified')
        product = {p.relative_to(FLUTTER_ROOT / 'lib'): p for p in (FLUTTER_ROOT / 'lib').rglob('*.dart')}
        actual = {p.relative_to(app / 'lib'): p for p in (app / 'lib').rglob('*.dart')}
        require(bool(product) and actual.keys() == product.keys()
                and all(not actual[name].is_symlink() and digest(actual[name]) == digest(path)
                        for name, path in product.items()),
                'windows_direct_product_sources_mismatch')

        tests = app / 'integration_test'
        tests.mkdir()
        names = (TEST, 'linux_direct_ssh_test.dart', SHARED_STEPS)
        for name in names:
            shutil.copyfile(FLUTTER_ROOT / 'integration_test' / name, tests / name)
        pubspec = app / 'pubspec.yaml'
        original = pubspec.read_text(encoding='utf-8')
        require(original.count('dev_dependencies:\n') == 1 and '  integration_test:' not in original,
                'windows_direct_scaffold_pubspec_invalid')
        replacement = 'dev_dependencies:\n  integration_test:\n    sdk: flutter\n'
        pubspec.write_text(original.replace('dev_dependencies:\n', replacement), encoding='utf-8')
        subprocess.run([flutter, 'pub', 'get'], cwd=app, env=env, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=240)
    return {'flutterVersion': FLUTTER_VERSION, 'flutterCommit': FLUTTER_COMMIT,
            'productionDartFilesMatched': len(product), 'candidateLockSha256': manifest['candidateLockSha256'],
            'integrationLockSha256': digest(lock), 'integrationPackages': locked_dependencies(
                base_lock, lock.read_text(encoding='utf-8')),
            'testSourceSha256': {name: digest(tests / name) for name in names}}


def check_desktop():
    def info(handle, attribute):
        return win32service.GetUserObjectInformation(handle, attribute)

    try:
        session = win32ts.ProcessIdToSessionId(os.getpid())
        require(session != 0 and win32ts.WTSQuerySessionInformation(
            win32ts.WTS_CURRENT_SERVER_HANDLE, session, win32ts.WTSConnectState) == win32ts.WTSActive,
            'windows_direct_desktop_unavailable')
        # Detach borrowed handles before the Python wrappers can close them.
        station = win32service.GetProcessWindowStation().Detach()
        thread_desktop = win32service.GetThreadDesktop(win32api.GetCurrentThreadId()).Detach()
        require(info(station, win32con.UOI_NAME).casefold() == 'winsta0'
                and info(station, win32con.UOI_FLAGS)['Flags'] & win32con.WSF_VISIBLE,
                'windows_direct_desktop_unavailable')
        active = win32service.OpenInputDesktop(0, False, win32con.DESKTOP_READOBJECTS)
        try:
            require(info(thread_desktop, win32con.UOI_NAME).casefold() ==
                    info(active, win32con.UOI_NAME).casefold() == 'default',
                    'windows_direct_desktop_unavailable')
        finally:
            active.CloseDesktop()
    except pywintypes.error as exc:
        raise GuiFailure('windows_direct_desktop_unavailable') from exc


@contextmanager
def owned_job(command, *, cwd, env, log, report):
    # Gate the launcher on stdin until Win32 has assigned it to the job.
    # Every descendant (including the app) then inherits job membership.
    # On Windows a venv's python.exe creates the interpreter as a child before
    # this gate is read. Start the actual interpreter to close that race.
    launcher = 'import subprocess, sys; sys.exit(subprocess.call(sys.argv[1:]) if sys.stdin.read() == "run" else 1)'
    report['checkpoint'] = 'job_create'
    # pywin32's WCHAR* typemap requires a string for the name.
    job = win32job.CreateJobObject(None, f'herdr-pocket-direct-{secrets.token_hex(16)}')
    process = None
    assigned = False
    failed = False
    try:
        report['checkpoint'] = 'job_read_limits'
        limit_class = win32job.JobObjectExtendedLimitInformation
        limits = win32job.QueryInformationJobObject(job, limit_class)
        limits['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        report['checkpoint'] = 'job_set_limits'
        win32job.SetInformationJobObject(job, limit_class, limits)
        report['checkpoint'] = 'job_open_log'
        with log.open('wb') as stream:
            report['checkpoint'] = 'job_spawn'
            process = subprocess.Popen([sys._base_executable, '-I', '-S', '-c', launcher, *command], cwd=cwd, env=env,
                                       stdin=subprocess.PIPE, stdout=stream, stderr=subprocess.STDOUT)
            with process.stdin as launch_gate:
                report['checkpoint'] = 'job_open_process'
                handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE,
                                              False, process.pid)
                try:
                    report['checkpoint'] = 'job_assign_process'
                    win32job.AssignProcessToJobObject(job, handle)
                    assigned = True
                finally:
                    handle.Close()
                report['checkpoint'] = 'job_check_membership'
                processes = win32job.QueryInformationJobObject(job, win32job.JobObjectBasicProcessIdList)
                require(process.pid in processes, 'windows_direct_launcher_unowned')
                report['checkpoint'] = 'job_release_gate'
                launch_gate.write(b'run')
            yield process, job
    except BaseException:
        failed = True
        raise
    finally:
        try:
            try:
                def empty():
                    info = win32job.QueryInformationJobObject(job, win32job.JobObjectBasicAccountingInformation)
                    return info['ActiveProcesses'] == 0

                if process is not None:
                    if assigned and not empty():
                        win32job.TerminateJobObject(job, 1)
                    if not assigned and process.poll() is None:
                        process.kill()
                    process.wait(timeout=12)
                    wait_for(empty, 'windows_direct_process_cleanup_unconfirmed', timeout=12)
            finally:
                job.Close()
        except Exception as error:
            report['jobCleanupFailure'] = runner_failure(error)
            if not failed:
                report['checkpoint'] = 'job_cleanup'
                raise


def find_window(process_id):
    candidates = []

    def visit(hwnd, _):
        if (win32process.GetWindowThreadProcessId(hwnd)[1] == process_id
                and win32gui.GetClassName(hwnd) == WINDOW_CLASS
                and win32gui.GetWindowText(hwnd) == WINDOW_TITLE):
            candidates.append(hwnd)
        return True

    win32gui.EnumWindows(visit, None)
    require(len(candidates) <= 1, 'windows_direct_native_window_ambiguous')
    return candidates[0] if candidates and win32gui.IsWindowVisible(candidates[0]) else None


def framebuffer(hwnd, process_id):
    check_desktop()
    require(find_window(process_id) == hwnd and not win32gui.IsIconic(hwnd)
            and win32gui.GetForegroundWindow() == hwnd, 'windows_direct_native_window_not_foreground')
    view = win32gui.FindWindowEx(hwnd, 0, 'FLUTTERVIEW', None)
    require(view and win32process.GetWindowThreadProcessId(view)[1] == process_id
            and win32gui.IsWindowVisible(view), 'windows_direct_flutter_view_unconfirmed')
    rect = win32gui.GetClientRect(view)
    left, top = win32gui.ClientToScreen(view, rect[:2])
    right, bottom = win32gui.ClientToScreen(view, rect[2:])
    monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONULL)
    require(monitor, 'windows_direct_window_off_screen')
    x0, y0, x1, y1 = win32api.GetMonitorInfo(monitor)['Monitor']
    require(x0 <= left < right <= x1 and y0 <= top < bottom <= y1
            and right - left >= 960 and bottom - top >= 600, 'windows_direct_window_off_screen')
    return view, (left, top, right, bottom)


def evidence_rect(pixels, size, *, minimum):
    require(isinstance(pixels, list) and len(pixels) == 4
            and all(type(value) is int for value in pixels), 'windows_direct_geometry_invalid')
    x, y, width, height = pixels
    require(x >= 0 and y >= 0 and width >= minimum[0] and height >= minimum[1]
            and x + width <= size[0] and y + height <= size[1], 'windows_direct_geometry_invalid')
    return pixels


def grab(hwnd, process_id, value, *, terminal):
    before = framebuffer(hwnd, process_id)
    view, (left, top, right, bottom) = before
    size = [right - left, bottom - top]
    minima = {'terminalBounds': (300, 160), 'targetBounds': (40, 12)} if terminal else {'outcomeBounds': (1, 1)}
    require(set(value) == {'surface', *minima} and value['surface'] == size
            and all(type(each) is int for each in value['surface']),
            'windows_direct_surface_mismatch')
    bounds = {key: evidence_rect(value[key], size, minimum=minimum) for key, minimum in minima.items()}
    # Ensure the evidence areas are on the foreground FLUTTERVIEW and check
    # again after copying visible screen pixels (no PrintWindow/offscreen read).
    def uncovered():
        for x, y, width, height in bounds.values():
            for px, py in ((x, y), (x + width - 1, y), (x, y + height - 1),
                           (x + width - 1, y + height - 1), (x + width // 2, y + height // 2)):
                require(win32gui.WindowFromPoint((left + px, top + py)) == view,
                        'windows_direct_window_occluded')

    uncovered()
    image = ImageGrab.grab(bbox=before[1], include_layered_windows=True, all_screens=True)
    require(list(image.size) == size and framebuffer(hwnd, process_id) == before,
            'windows_direct_window_changed_during_capture')
    uncovered()
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    png = stream.getvalue()
    evidence = {'imageSize': size, 'imageSha256': hashlib.sha256(png).hexdigest(), 'capture': CAPTURE, **bounds}
    if not terminal:
        x, y, width, height = bounds['outcomeBounds']
        require(max(ImageStat.Stat(image.crop((x, y, x + width, y + height))).var) > 1,
                'windows_direct_outcome_frame_blank')
    return png, evidence


def terminal_capture(hwnd, process_id, value, token):
    for attempt in (1, 2):
        png, evidence = grab(hwnd, process_id, value, terminal=True)
        try:
            ocr = verify_terminal_screenshot(png, expected_token=token, bounds=evidence['terminalBounds'])
            return png, {**evidence, **ocr, 'captureAttempts': attempt}
        except ScreenshotGateError as exc:
            if str(exc) not in PENDING_PIXELS or attempt == 2:
                raise
            time.sleep(.15)


def read_ui_stage(root):
    value = read_exchange(root, 'stage')
    if value is not None and value.keys() == {'phase'}:
        phase = value['phase']
        if isinstance(phase, str) and (phase in UI_PHASES or phase in RETURN_STEPS):
            return phase


def read_framework_error(root):
    value = read_exchange(root, 'framework-error')
    if value is None:
        return None
    # Treat the driver record as untrusted. Every exported dimension, token
    # and frame is bounded, with no pass-through of text from Flutter.
    required = {'phase', 'returnTapStarted', 'kind', 'library'}
    optional = {'viewportPx', 'dprMilli', 'overflow', 'frame', 'creator', 'renderSize', 'anchor'}

    def label(item, choices):
        return isinstance(item, str) and item in choices

    def dimension(item):
        return isinstance(item, list) and len(item) == 2 and all(type(n) is int and 0 <= n <= 16384 for n in item)

    def valid(condition):
        require(condition, 'windows_direct_framework_record_invalid')

    valid(required <= value.keys() <= (required | optional)
          and label(value['phase'], {*UI_PHASES, *RETURN_STEPS, 'window'})
          and type(value['returnTapStarted']) is bool
          and label(value['kind'], FRAMEWORK_KINDS)
          and label(value['library'], FRAMEWORK_LIBRARIES))
    for key in ('viewportPx', 'renderSize'):
        if key in value:
            valid(dimension(value[key]))
    if 'dprMilli' in value:
        valid(type(value['dprMilli']) is int and 1 <= value['dprMilli'] <= 8000)
    if 'creator' in value:
        valid(label(value['creator'], FRAMEWORK_CREATORS))
    if 'anchor' in value:
        valid(label(value['anchor'], FRAMEWORK_ANCHORS))
    if 'overflow' in value:
        overflow = value['overflow']
        valid(value['kind'] == 'FlutterError' and value['library'] == 'rendering'
              and isinstance(overflow, dict) and overflow.keys() == {'side', 'pixels'}
              and label(overflow['side'], {'top', 'bottom', 'left', 'right'})
              and type(overflow['pixels']) in (int, float) and 0 <= overflow['pixels'] < 100000)
    if 'frame' in value:
        frame = value['frame']
        valid(isinstance(frame, dict) and frame.keys() == {'source', 'line'}
              and label(frame['source'], FRAMEWORK_SOURCES)
              and type(frame['line']) is int and 1 <= frame['line'] <= 99999)
    return value


def request(process, root, name, report, *, timeout=45):
    def available():
        value = read_exchange(root, name)
        exit_code = process.poll()
        if exit_code is not None:
            report['launcherExit'] = 'success' if exit_code == 0 else 'failure'
            # A rename can race the first read. Presence after process exit is
            # diagnostic only: the live foreground capture still needs an app.
            report['checkpointPublishedAtExit'] = value is not None or read_exchange(root, name) is not None
            raise GuiFailure('windows_direct_application_ended_early')
        return (value,) if value is not None else None

    return wait_for(available, f'windows_direct_checkpoint_timeout_{name}', timeout=timeout)[0]


def exchange(process, job, root, fixture, report, images, *, publickey=False):
    report['checkpoint'] = 'window'
    owner = request(process, root, 'window', report, timeout=900)
    process_id = owner.get('processId')
    require(set(owner) == {'processId'} and type(process_id) is int and process_id > 0 and process_id in
            win32job.QueryInformationJobObject(job, win32job.JobObjectBasicProcessIdList),
            'windows_direct_unowned_application')
    hwnd = wait_for(lambda: find_window(process_id), 'windows_direct_visible_window_missing', timeout=20)
    # Keep the test-owned window inside the monitor even with a 1024x768 runner.
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    probe_view = None
    def verify_session(facts, *, sent, closed):
        if publickey:
            probe_evidence(facts, 2)
            verify_shell(facts, 2, 'A', sent=sent, closed=closed, publickey=True)
        else:
            session_evidence(facts, sent=sent, closed=closed)

    for phase in PUBLICKEY_PHASES if publickey else PHASES:
        report['checkpoint'] = phase
        # Return has separate control and receipt waits in the live app.
        value = request(process, root, phase, report, timeout=100 if phase == 'complete' else 45)
        if publickey and phase != 'probe':
            require(framebuffer(hwnd, process_id)[0] == probe_view, 'windows_direct_publickey_view_changed')
        if phase == 'probe':
            native_view = framebuffer(hwnd, process_id)
            if publickey:
                probe_view = native_view[0]
            require(value.keys() == {'algorithm'} and value['algorithm'] in ('ssh-rsa', 'rsa-sha2-256', 'rsa-sha2-512'),
                    'windows_direct_displayed_algorithm_invalid')
            require(fixture.wait_for_connections_closed(1), 'windows_direct_probe_not_closed')
            probe_evidence(fixture.snapshot(), 1)
            report.update(fingerprintMatchedBeforeConfirm=True, displayedHostKeyAlgorithm=value['algorithm'])
        elif phase == 'key_entry':
            require(value.keys() == {'privateKeyExact', 'passphraseEmpty'} and all(v is True for v in value.values()),
                    'windows_direct_publickey_entry_unproven')
            require(not os.path.lexists(root / 'target.json'), 'windows_direct_target_file_unconsumed')
            probe_evidence(fixture.snapshot(), 1)
            report.update(credentialEntry='focusedFlutterTextInput', privateKeyExact=True, passphraseEmpty=True)
        elif phase == 'connected':
            require(value == {}, 'windows_direct_connected_payload_invalid')
            def ready():
                facts = fixture.snapshot()
                events = facts['connectionEvents']
                return facts if len(events) == 2 and events[1]['outputBytes'] > 0 else None

            facts = wait_for(ready, 'windows_direct_shell_output_missing', timeout=5)
            verify_session(facts, sent=False, closed=False)
            report['fingerprintConfirmed'] = True
        elif phase == 'capture':
            verify_session(fixture.snapshot(), sent=True, closed=False)
            png, evidence = terminal_capture(hwnd, process_id, value, fixture.screen_token)
            verify_session(fixture.snapshot(), sent=True, closed=False)
            images['ordinary-terminal.png'], report['terminal'] = png, evidence
        else:
            require(fixture.wait_for_connections_closed(2), 'windows_direct_peer_close_unconfirmed')
            verify_session(fixture.snapshot(), sent=True, closed=True)
            name = 'disconnect' if phase == 'disconnect' else 'home'
            png, evidence = grab(hwnd, process_id, value, terminal=False)
            verify_session(fixture.snapshot(), sent=True, closed=True)
            images[f'ordinary-{name}.png'], report[f'{name}Outcome'] = png, evidence
        (root / f'{phase}.ok').touch(exist_ok=False)
    require(process.wait(timeout=30) == 0, 'windows_direct_test_failed_after_home')
    report.update(returnedHome=True, credentialFieldsCleared=True)


def restrict_fixture_directory(root):
    import ntsecuritycon
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), ntsecuritycon.TOKEN_QUERY)
    try:
        user, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
    finally:
        token.Close()
    acl = win32security.ACL()
    flags = win32security.CONTAINER_INHERIT_ACE | win32security.OBJECT_INHERIT_ACE
    mask = ntsecuritycon.FILE_ALL_ACCESS
    acl.AddAccessAllowedAceEx(acl.GetAclRevision(), flags, mask, user)
    info = win32security.DACL_SECURITY_INFORMATION
    kind = win32security.SE_FILE_OBJECT
    win32security.SetNamedSecurityInfo(str(root), kind, info | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                                       None, None, acl, None)
    descriptor = win32security.GetNamedSecurityInfo(str(root), kind, info)
    actual = descriptor.GetSecurityDescriptorDacl()
    code = 'windows_direct_fixture_acl_unproven'
    require(descriptor.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED
            and actual is not None and actual.GetAceCount() == 1, code)
    ace, access, sid = actual.GetAce(0)
    require(ace == (win32security.ACCESS_ALLOWED_ACE_TYPE, flags) and access == mask
            and win32security.ConvertSidToStringSid(sid) == win32security.ConvertSidToStringSid(user), code)


@contextmanager
def windows_fixture(*, publickey):
    options = {'screen_proof': True, 'channel_deadline': time.monotonic() + 1250}
    if not publickey:
        with DirectSshFixture(**options) as fixture:
            yield fixture, {'password': fixture.password}
        return
    # Generate the disposable key in memory, independent of user keys or agents.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from tauri_ios_direct_ssh import SingleCommandFixture

    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    credentials = {'privateKey': key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                                   serialization.NoEncryption()).decode('ascii')}
    del key
    try:
        with SingleCommandFixture(client_public_key=public.decode('ascii').split()[1], **options) as fixture:
            yield fixture, credentials
    finally:
        credentials.clear()


def run(app, source, report, base, images, *, publickey=False):
    report['checkpoint'] = 'desktop'
    check_desktop()
    user32 = ctypes.windll.user32
    user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    require(user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)), 'windows_direct_dpi_unavailable')
    report['interactiveDesktop'] = True
    flutter = shutil.which('flutter.bat')
    require(flutter and shutil.which('tesseract'), 'windows_direct_toolchain_missing')
    with tempfile.TemporaryDirectory(prefix='hp-flutter-windows-direct-', dir=base) as directory:
        root = Path(directory)
        if publickey:
            report['checkpoint'] = 'fixture_privacy'
            restrict_fixture_directory(root)
            report['fixtureDirectoryRestricted'] = True
        env = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_') and
               k not in ('SSH_AUTH_SOCK', 'SSH_AGENT_PID')}
        report['checkpoint'] = 'prepare'
        report['sourceVerification'] = prepare(app, source, flutter, root / 'pub.log', env)
        report['checkpoint'] = 'fixture'
        with windows_fixture(publickey=publickey) as (fixture, credentials):
            report['checkpoint'] = 'fixture_listener'
            listener = report['listener'] = {
                'ownedBeforeLaunch': windows_loopback_listener_owners(fixture.port) == [(True, os.getpid())],
            }
            require(listener['ownedBeforeLaunch'], 'windows_direct_unowned_peer_listener')
            with (root / 'target.json').open('x', encoding='utf-8') as stream:
                json.dump({'port': fixture.port, 'fingerprint': fixture.fingerprint, **credentials}, stream)
            credentials.clear()
            report['target'] = {'host': '127.0.0.1', 'port': fixture.port, 'username': fixture.username,
                                'fingerprint': fixture.fingerprint}
            command = [flutter, 'test', '--no-pub', '--reporter', 'expanded', '-d', 'windows',
                       f'--dart-define=HERDR_FLUTTER_WINDOWS_DIRECT_DIR={root}', f'integration_test/{TEST}']
            if publickey:
                command.insert(-1, '--dart-define=HERDR_FLUTTER_WINDOWS_DIRECT_PUBLICKEY=true')
            try:
                with owned_job(command, cwd=app, env=env, log=root / 'flutter.log', report=report) as (process, job):
                    try:
                        exchange(process, job, root, fixture, report, images, publickey=publickey)
                    finally:
                        report['peer'] = fixture.snapshot()  # Before any forced process teardown.
                        stage = read_ui_stage(root)
                        if stage is not None:
                            report['uiStage'] = stage
                        try:
                            framework_error = read_framework_error(root)
                            if framework_error is not None:
                                report['frameworkError'] = framework_error
                        except (GuiFailure, OSError, ValueError):
                            report['frameworkErrorRecord'] = 'invalid'
            finally:
                if 'peer' not in report:
                    report['peerAfterFailedLaunch'] = fixture.snapshot()
            require(not (root / 'target.json').exists(), 'windows_direct_target_file_unconsumed')
        report['checkpoint'] = 'cleanup'
        verify_listener_release(fixture, listener)
        require(fixture.password == '', 'windows_direct_fixture_password_cleanup_unconfirmed')
    require(not root.exists(), 'windows_direct_fixture_directory_remains')
    report['cleanup'] = {'ownedProcessJobEmpty': True, 'peerListenerReleased': True,
                         'fixturePasswordCleared': True, 'fixtureDirectoryRemoved': True}
    if publickey:
        report['cleanup']['fixtureKeyFileRemoved'] = True


def save_partial_crops(output, frames, report):
    # At both capture points the Dart driver has already proved that the
    # password controller is empty. Retain only the confirmed evidence region,
    # excluding the rest of the desktop image, if a later step fails.
    for name, section, bounds in (
        ('terminal', 'terminal', 'terminalBounds'), ('disconnect', 'disconnectOutcome', 'outcomeBounds'),
    ):
        png = frames.get(f'ordinary-{name}.png')
        if png is None:
            continue
        evidence = report[section]
        source_hash = hashlib.sha256(png).hexdigest()
        require(source_hash == evidence['imageSha256'], 'windows_direct_partial_source_mismatch')
        with Image.open(io.BytesIO(png)) as frame:
            size = list(frame.size)
            require(size == evidence['imageSize'], 'windows_direct_partial_source_mismatch')
            x, y, width, height = evidence_rect(evidence[bounds], size, minimum=(1, 1))
            crop = frame.crop((x, y, x + width, y + height))
            stream = io.BytesIO()
            crop.save(stream, format='PNG')
        data = stream.getvalue()
        filename = f'partial-{name}-crop.png'
        (output / filename).write_bytes(data)
        report.setdefault('partialFrames', {})[name] = {
            'file': filename, 'imageSha256': hashlib.sha256(data).hexdigest(),
            'sourceImageSha256': source_hash, 'sourceBounds': [x, y, width, height],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--publickey-only', action='store_true')
    args = parser.parse_args()
    app, output = args.app.resolve(), args.output.resolve()
    base = Path(os.environ.get('RUNNER_TEMP', tempfile.gettempdir())).resolve()
    if (sys.platform != 'win32' or not re.fullmatch(r'[0-9a-f]{40}', args.source_sha)
            or (os.environ.get('GITHUB_ACTIONS') == 'true' and args.source_sha != os.environ.get('GITHUB_SHA'))
            or app == base or not app.is_relative_to(base) or (app / '.git').exists()
            or output == base or not output.is_relative_to(base) or output.is_relative_to(app)):
        parser.error('use Windows with a fresh generated scaffold and output under the runner or system temp directory')
    output.mkdir(parents=True, exist_ok=False)
    report = {'schemaVersion': 1, 'sourceSHA': args.source_sha, 'platform': 'Windows Flutter debug Win32',
              'authentication': 'publickey' if args.publickey_only else 'password',
              'scope': 'native Win32 window, Flutter integration test input and desktop pixels',
              'interactiveDesktop': False, 'physicalImeVerified': False, 'status': 'failed'}
    images = {}
    try:
        run(app, args.source_sha, report, base, images, publickey=args.publickey_only)
        for name, png in images.items():
            (output / name).write_bytes(png)
        report.update(status='passed', checkpoint='complete')
    except ScreenshotGateError as error:
        report.update(errorCode=str(error), terminalFailure=error.evidence)
    except GuiFailure as error:
        report['errorCode'] = str(error)
    except Exception as error:  # Tool logs may contain fixture data; do not publish them.
        report['errorCode'] = 'windows_direct_runner_failed'
        report['runnerFailure'] = runner_failure(error)
    if report['status'] == 'failed':
        try:
            save_partial_crops(output, images, report)
        except (GuiFailure, OSError, ValueError):
            report['partialCaptureError'] = 'windows_direct_partial_export_failed'
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if report['status'] == 'failed':
        print(f"Windows ordinary SSH failed at {report['checkpoint']}: {report['errorCode']}", flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
