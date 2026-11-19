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
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from PIL import ImageGrab, ImageStat
from direct_ssh_fixture import DirectSshFixture
from flutter_linux_direct_ssh import (
    FLUTTER_COMMIT, FLUTTER_ROOT, FLUTTER_VERSION, PENDING_PIXELS, SHARED_STEPS,
    locked_dependencies, read_exchange, read_ui_stage,
)
from paired_gui import GuiFailure, wait_for
from tauri_linux_direct_ssh import probe_evidence, require, session_evidence
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
WINDOW_TITLE = 'herdr_flutter_probe'
WINDOW_CLASS = 'FLUTTER_RUNNER_WIN32_WINDOW'
CAPTURE = 'Win32 visible desktop framebuffer, clipped to FLUTTERVIEW client pixels'


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
def owned_job(command, *, cwd, env, log):
    # Gate the launcher on stdin until Win32 has assigned it to the job.
    # Every descendant (including the app) then inherits job membership.
    launcher = 'import subprocess, sys; sys.exit(subprocess.call(sys.argv[1:]) if sys.stdin.read() == "run" else 1)'
    job = win32job.CreateJobObject(None, None)
    limit_class = win32job.JobObjectExtendedLimitInformation
    process = None
    assigned = False
    try:
        limits = win32job.QueryInformationJobObject(job, limit_class)
        limits['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, limit_class, limits)
        with log.open('wb') as stream:
            process = subprocess.Popen([sys.executable, '-c', launcher, *command], cwd=cwd, env=env,
                                       stdin=subprocess.PIPE, stdout=stream, stderr=subprocess.STDOUT)
            with process.stdin as launch_gate:
                handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE,
                                              False, process.pid)
                try:
                    win32job.AssignProcessToJobObject(job, handle)
                    assigned = True
                finally:
                    handle.Close()
                launch_gate.write(b'run')
            yield process, job
    finally:
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


def exchange(process, job, root, fixture, report):
    def request(name, timeout=45):
        def available():
            value = read_exchange(root, name)
            if value is not None:
                return (value,)
            require(process.poll() is None, 'windows_direct_application_ended_early')
            return None
        return wait_for(available, f'windows_direct_checkpoint_timeout_{name}', timeout=timeout)[0]

    images = {}
    report['checkpoint'] = 'window'
    owner = request('window', timeout=900)
    process_id = owner.get('processId')
    require(set(owner) == {'processId'} and type(process_id) is int and process_id > 0 and process_id in
            win32job.QueryInformationJobObject(job, win32job.JobObjectBasicProcessIdList),
            'windows_direct_unowned_application')
    hwnd = wait_for(lambda: find_window(process_id), 'windows_direct_visible_window_missing', timeout=20)
    # Keep the test-owned window inside the monitor even with a 1024x768 runner.
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    for phase in PHASES:
        report['checkpoint'] = phase
        value = request(phase)
        if phase == 'probe':
            framebuffer(hwnd, process_id)
            require(value.keys() == {'algorithm'} and value['algorithm'] in ('ssh-rsa', 'rsa-sha2-256', 'rsa-sha2-512'),
                    'windows_direct_displayed_algorithm_invalid')
            require(fixture.wait_for_connections_closed(1), 'windows_direct_probe_not_closed')
            probe_evidence(fixture.snapshot(), 1)
            report.update(fingerprintMatchedBeforeConfirm=True, displayedHostKeyAlgorithm=value['algorithm'])
        elif phase == 'connected':
            require(value == {}, 'windows_direct_connected_payload_invalid')
            def ready():
                facts = fixture.snapshot()
                events = facts['connectionEvents']
                return facts if len(events) == 2 and events[1]['outputBytes'] > 0 else None

            facts = wait_for(ready, 'windows_direct_shell_output_missing', timeout=5)
            session_evidence(facts, sent=False, closed=False)
            report['fingerprintConfirmed'] = True
        elif phase == 'capture':
            session_evidence(fixture.snapshot(), sent=True, closed=False)
            images['ordinary-terminal.png'], report['terminal'] = terminal_capture(hwnd, process_id, value,
                                                                                 fixture.screen_token)
            session_evidence(fixture.snapshot(), sent=True, closed=False)
        else:
            require(fixture.wait_for_connections_closed(2), 'windows_direct_peer_close_unconfirmed')
            session_evidence(fixture.snapshot(), sent=True, closed=True)
            name = 'disconnect' if phase == 'disconnect' else 'home'
            images[f'ordinary-{name}.png'], report[f'{name}Outcome'] = grab(hwnd, process_id, value, terminal=False)
            session_evidence(fixture.snapshot(), sent=True, closed=True)
        (root / f'{phase}.ok').touch(exist_ok=False)
    require(process.wait(timeout=30) == 0, 'windows_direct_test_failed_after_home')
    report.update(returnedHome=True, credentialFieldsCleared=True)
    return images


def run(app, source, report, base):
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
        env = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_') and
               k not in ('SSH_AUTH_SOCK', 'SSH_AGENT_PID')}
        report['checkpoint'] = 'prepare'
        report['sourceVerification'] = prepare(app, source, flutter, root / 'pub.log', env)
        with DirectSshFixture(screen_proof=True, channel_deadline=time.monotonic() + 1250) as fixture:
            with (root / 'target.json').open('x', encoding='utf-8') as stream:
                json.dump({'port': fixture.port, 'fingerprint': fixture.fingerprint, 'password': fixture.password}, stream)
            report['target'] = {'host': '127.0.0.1', 'port': fixture.port, 'username': fixture.username,
                                'fingerprint': fixture.fingerprint}
            command = [flutter, 'test', '--no-pub', '--reporter', 'expanded', '-d', 'windows',
                       f'--dart-define=HERDR_FLUTTER_WINDOWS_DIRECT_DIR={root}', f'integration_test/{TEST}']
            with owned_job(command, cwd=app, env=env, log=root / 'flutter.log') as (process, job):
                try:
                    images = exchange(process, job, root, fixture, report)
                finally:
                    report['peer'] = fixture.snapshot()  # Before any forced teardown.
                    stage = read_ui_stage(root)
                    if stage is not None:
                        report['uiStage'] = stage
            require(not (root / 'target.json').exists(), 'windows_direct_target_file_unconsumed')
        report['checkpoint'] = 'cleanup'
        with socket.socket() as client:
            client.settimeout(.4)
            require(client.connect_ex(('127.0.0.1', fixture.port)) in
                    (errno.ECONNREFUSED, errno.WSAECONNREFUSED), 'windows_direct_peer_listener_unconfirmed')
        require(fixture.password == '', 'windows_direct_fixture_password_cleanup_unconfirmed')
    require(not root.exists(), 'windows_direct_fixture_directory_remains')
    report['cleanup'] = {'ownedProcessJobEmpty': True, 'peerListenerReleased': True,
                         'fixturePasswordCleared': True, 'fixtureDirectoryRemoved': True}
    return images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', required=True, type=Path)
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
              'authentication': 'password', 'scope': 'native Win32 window, Flutter integration test input and desktop pixels',
              'interactiveDesktop': False, 'physicalImeVerified': False, 'status': 'failed'}
    try:
        for name, png in run(app, args.source_sha, report, base).items():
            (output / name).write_bytes(png)
        report.update(status='passed', checkpoint='complete')
    except ScreenshotGateError as error:
        report.update(errorCode=str(error), terminalFailure=error.evidence)
    except GuiFailure as error:
        report['errorCode'] = str(error)
    except Exception:  # Tool logs may contain fixture data; do not publish them.
        report['errorCode'] = 'windows_direct_runner_failed'
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if report['status'] == 'failed':
        print(f"Windows ordinary SSH failed at {report['checkpoint']}: {report['errorCode']}", flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
