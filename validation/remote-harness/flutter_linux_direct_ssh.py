#!/usr/bin/env python3
"""Run the native Flutter Linux test window against one disposable SSH peer."""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from direct_ssh_fixture import DirectSshFixture
from paired_gui import GuiFailure, owned_process, wait_for
from PIL import ImageGrab
from tauri_linux_direct_ssh import (
    port_is_released,
    probe_evidence,
    require,
    session_evidence,
)
from terminal_screenshot_gate import ScreenshotGateError, verify_terminal_screenshot

FLUTTER_ROOT = Path(__file__).resolve().parents[1] / 'flutter'
sys.path.insert(0, str(FLUTTER_ROOT / 'tool'))
from android_device_test import (
    ALLOWED_ADDITIONS,
    FLUTTER_COMMIT,
    FLUTTER_VERSION,
    SDK_ADDITIONS,
)
from candidate import lock_packages

TEST = 'linux_direct_ssh_test.dart'
SHARED_STEPS = 'direct_ssh_ui_steps.dart'
PHASES = ('home', 'form', 'probe', 'password', 'connected', 'input', 'capture', 'disconnect', 'return_home')
PENDING_PIXELS = {'terminal_screenshot_echo_not_visible', 'terminal_screenshot_token_not_visible',
                  'terminal_screenshot_proof_not_adjacent'}


def locked_dependencies(before, after):
    old, new = lock_packages(before), lock_packages(after)
    extra = new.keys() - old.keys()
    require(all(new.get(name) == block for name, block in old.items()) and
            SDK_ADDITIONS <= extra <= ALLOWED_ADDITIONS, 'flutter_linux_dependency_drift')
    for name in extra:
        lines = new[name].splitlines()
        if name in SDK_ADDITIONS:
            require('    source: sdk' in lines and '    version: "0.0.0"' in lines, 'flutter_linux_integration_not_sdk')
        else:
            require('    source: hosted' in lines and '      url: "https://pub.dev"' in lines and
                    re.search(r'^      sha256: "?[0-9a-f]{64}"?$', new[name], re.MULTILINE),
                    'flutter_linux_integration_dependency_unlocked')
    return sorted(extra)


def prepare(app, source, env, log):
    tool = subprocess.run(['flutter', '--version', '--machine'], cwd=app, env=env, capture_output=True,
                          check=True, timeout=30)
    sdk = json.loads(tool.stdout)
    require(sdk.get('frameworkVersion') == FLUTTER_VERSION and sdk.get('frameworkRevision') == FLUTTER_COMMIT,
            'flutter_linux_unexpected_sdk')
    lock = app / 'pubspec.lock'
    before = lock.read_text(encoding='utf-8')
    manifest = json.loads((app / 'candidate-manifest.json').read_text(encoding='utf-8'))
    require(manifest.get('sourceCommit') == source and manifest.get('variant') == 'experimental-patched' and
            manifest.get('candidateLockSha256') == hashlib.sha256(lock.read_bytes()).hexdigest(),
            'flutter_linux_candidate_lock_unverified')
    generated = json.loads((app / '.herdr-generated-probe.json').read_text(encoding='utf-8'))
    require(generated == {'kind': 'herdr-flutter-validation', 'sourceCommit': source}, 'flutter_linux_scaffold_mismatch')
    product = {p.relative_to(FLUTTER_ROOT / 'lib'): p for p in (FLUTTER_ROOT / 'lib').rglob('*.dart')}
    actual = {p.relative_to(app / 'lib'): p for p in (app / 'lib').rglob('*.dart')}
    require(bool(product) and actual.keys() == product.keys() and
            all(not actual[name].is_symlink() and actual[name].read_bytes() == path.read_bytes()
                for name, path in product.items()), 'flutter_linux_scaffold_source_changed')
    entries = app / 'integration_test'
    entries.mkdir()
    for file in (TEST, SHARED_STEPS):
        shutil.copyfile(FLUTTER_ROOT / 'integration_test' / file, entries / file)
    pubspec = app / 'pubspec.yaml'
    text = pubspec.read_text(encoding='utf-8')
    require(text.count('dev_dependencies:\n') == 1 and '  integration_test:' not in text,
            'flutter_linux_invalid_scaffold_pubspec')
    pubspec.write_text(text.replace('dev_dependencies:\n', 'dev_dependencies:\n  integration_test:\n    sdk: flutter\n'),
                       encoding='utf-8')
    with log.open('wb') as stream:
        subprocess.run(['flutter', 'pub', 'get'], cwd=app, env=env, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=240)
    added = locked_dependencies(before, lock.read_text(encoding='utf-8'))
    return {'flutterVersion': FLUTTER_VERSION, 'flutterCommit': FLUTTER_COMMIT,
            'productionDartFilesMatched': len(product),
            'candidateLockSha256': manifest['candidateLockSha256'], 'integrationLockSha256':
            hashlib.sha256(lock.read_bytes()).hexdigest(), 'integrationPackages': added,
            'testSha256': hashlib.sha256((entries / TEST).read_bytes()).hexdigest(),
            'uiStepsSha256': hashlib.sha256((entries / SHARED_STEPS).read_bytes()).hexdigest()}


def read_exchange(root, name):
    path = root / f'{name}.json'
    if not path.exists():
        return None
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 1024,
            'flutter_linux_invalid_exchange')
    value = json.loads(path.read_bytes())
    require(isinstance(value, dict), 'flutter_linux_invalid_exchange')
    return value


def window_geometry(raw):
    window = re.findall(r'^xwininfo: Window id: (0x[0-9a-f]+) "herdr_flutter_probe"\s*$', raw, re.MULTILINE)
    fields = dict(re.findall(r'^\s*(Absolute upper-left X|Absolute upper-left Y|Width|Height|Border width):\s*(-?\d+)\s*$', raw, re.MULTILINE))
    keys = ('Absolute upper-left X', 'Absolute upper-left Y', 'Width', 'Height', 'Border width')
    require(len(window) == 1 and set(keys) == fields.keys() and
            bool(re.search(r'^\s*Map State: IsViewable\s*$', raw, re.MULTILINE)), 'flutter_linux_window_not_viewable')
    x, y, width, height, border = (int(fields[key]) for key in keys)
    require(x >= 0 and y >= 0 and width >= 960 and height >= 600 and border == 0,
            'flutter_linux_window_geometry_invalid')
    return window[0], (x, y, width, height)


def native_window():
    result = subprocess.run(['xwininfo', '-name', 'herdr_flutter_probe', '-stats'], capture_output=True,
                            env=dict(os.environ, LC_ALL='C'), check=True, timeout=8)
    return window_geometry(result.stdout.decode('ascii'))


def capture_geometry(request, window, screen):
    x, y, width, height = window
    require(request.keys() == {'surface', 'terminalBounds', 'targetBounds'} and
            request['surface'] == [width, height] and x + width <= screen[0] and y + height <= screen[1],
            'flutter_linux_window_surface_mismatch')

    def translate(field, minimum):
        bounds = request[field]
        require(isinstance(bounds, list) and len(bounds) == 4 and all(type(n) is int for n in bounds),
                'flutter_linux_terminal_bounds_invalid')
        left, top, w, h = bounds
        require(left >= 0 and top >= 0 and w >= minimum[0] and h >= minimum[1] and
                left + w <= width and top + h <= height, 'flutter_linux_terminal_bounds_invalid')
        return [x + left, y + top, w, h]

    target, terminal = translate('targetBounds', (40, 12)), translate('terminalBounds', (300, 160))
    require(target[1] + target[3] <= terminal[1], 'flutter_linux_target_overlaps_terminal')
    return terminal, target


def capture(request, token):
    first = native_window()
    for attempt in range(1, 4):
        try:
            frame = ImageGrab.grab(xdisplay=os.environ['DISPLAY'])
        except OSError:
            raise GuiFailure('flutter_linux_x11_framebuffer_unavailable') from None
        with frame as image:
            require(native_window() == first, 'flutter_linux_window_changed_during_capture')
            bounds, target = capture_geometry(request, first[1], image.size)
            with io.BytesIO() as output:
                # Retain all Xvfb framebuffer pixels. OCR crops only in memory.
                image.save(output, format='PNG')
                png = output.getvalue()
        try:
            verified = verify_terminal_screenshot(png, expected_token=token, bounds=bounds)
            return png, {**verified, 'capture': 'unscaled X11 Xvfb framebuffer PNG', 'captureAttempt': attempt,
                         'windowBounds': list(first[1]), 'targetBounds': target}
        except ScreenshotGateError as error:
            if str(error) not in PENDING_PIXELS or attempt == 3:
                raise
            time.sleep(.2)


def capture_outcome(request):
    first = native_window()
    try:
        frame = ImageGrab.grab(xdisplay=os.environ['DISPLAY'])
    except OSError:
        raise GuiFailure('flutter_linux_x11_framebuffer_unavailable') from None
    with frame as image:
        require(native_window() == first, 'flutter_linux_window_changed_during_capture')
        x, y, width, height = first[1]
        require(request.keys() == {'surface', 'outcomeBounds'} and request['surface'] == [width, height] and
                x + width <= image.width and y + height <= image.height,
                'flutter_linux_outcome_surface_mismatch')
        bounds = request['outcomeBounds']
        require(isinstance(bounds, list) and len(bounds) == 4 and all(type(n) is int for n in bounds),
                'flutter_linux_outcome_bounds_invalid')
        left, top, w, h = bounds
        require(left >= 0 and top >= 0 and w > 0 and h > 0 and left + w <= width and top + h <= height,
                'flutter_linux_outcome_bounds_invalid')
        with io.BytesIO() as output:
            image.save(output, format='PNG')
            png = output.getvalue()
        evidence = {'imageSha256': hashlib.sha256(png).hexdigest(), 'imageSize': list(image.size),
                    'windowBounds': list(first[1]), 'bounds': [x + left, y + top, w, h],
                    'capture': 'unscaled X11 Xvfb framebuffer PNG'}
    return png, evidence


def exchange(process, root, fixture, report):
    def request(name, *, timeout=45):
        def available():
            result = read_exchange(root, name)
            if result is not None:
                return (result,)
            require(process.poll() is None, 'flutter_linux_application_ended_early')
            return None
        return wait_for(available, f'flutter_linux_checkpoint_timeout_{name}', timeout=timeout)[0]

    images = {}
    for phase in ('probe', 'connected', 'capture', 'disconnect', 'complete'):
        report['checkpoint'] = phase
        value = request(phase, timeout=1000 if phase == 'probe' else 45)
        require(phase in ('probe', 'capture', 'disconnect', 'complete') or value == {},
                'flutter_linux_unexpected_exchange_fields')
        if phase == 'probe':
            require(value.keys() == {'algorithm'} and value['algorithm'] in ('ssh-rsa', 'rsa-sha2-256', 'rsa-sha2-512'),
                    'flutter_linux_displayed_algorithm_invalid')
            require(fixture.wait_for_connections_closed(1), 'flutter_linux_probe_not_closed')
            probe_evidence(fixture.snapshot(), 1)
            report['fingerprintMatchedBeforeConfirm'] = True
            report['displayedHostKeyAlgorithm'] = value['algorithm']
        elif phase == 'connected':
            wait_for(lambda: len(fixture.snapshot()['connectionEvents']) == 2 and fixture.snapshot()[
                'connectionEvents'][1]['outputBytes'] > 0, 'flutter_linux_shell_output_missing', timeout=5)
            session_evidence(fixture.snapshot(), sent=False, closed=False)
            report['fingerprintConfirmed'] = True
        elif phase == 'capture':
            session_evidence(fixture.snapshot(), sent=True, closed=False)
            images['ordinary-terminal.png'], report['terminal'] = capture(value, fixture.screen_token)
            session_evidence(fixture.snapshot(), sent=True, closed=False)
        else:
            require(fixture.wait_for_connections_closed(2), 'flutter_linux_peer_close_unconfirmed')
            session_evidence(fixture.snapshot(), sent=True, closed=True)
            name = 'disconnect' if phase == 'disconnect' else 'home'
            images[f'ordinary-{name}.png'], report[f'{name}Outcome'] = capture_outcome(value)
            session_evidence(fixture.snapshot(), sent=True, closed=True)
        (root / f'{phase}.ok').touch(exist_ok=False)
    require(process.wait(timeout=40) == 0, 'flutter_linux_test_failed_after_home')
    report.update(returnedHome=True, credentialFieldsCleared=True)
    return images


def run(app, source, report):
    with tempfile.TemporaryDirectory(prefix='hp-flutter-linux-direct-') as temp:
        root = Path(temp)
        env = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_') and k not in ('SSH_AUTH_SOCK', 'SSH_AGENT_PID')}
        for kind in ('CONFIG', 'DATA', 'STATE', 'CACHE', 'RUNTIME'):
            path = root / kind.lower()
            path.mkdir(mode=0o700)
            env[f'XDG_{kind}_{"DIR" if kind == "RUNTIME" else "HOME"}'] = str(path)
        report['checkpoint'] = 'prepare'
        report['sourceVerification'] = prepare(app, source, env, root / 'pub.log')
        with DirectSshFixture(screen_proof=True, channel_deadline=time.monotonic() + 1400) as fixture:
            target = root / 'target.json'
            target.write_text(json.dumps({'port': fixture.port, 'fingerprint': fixture.fingerprint,
                                          'password': fixture.password}), encoding='utf-8')
            target.chmod(0o600)
            report['target'] = {'host': '127.0.0.1', 'port': fixture.port, 'username': fixture.username,
                                'algorithm': 'ssh-rsa', 'fingerprint': fixture.fingerprint}
            args = ['flutter', 'test', '--no-pub', '--reporter', 'expanded', '-d', 'linux',
                    f'--dart-define=HERDR_FLUTTER_LINUX_DIRECT_DIR={root}', f'integration_test/{TEST}']
            with owned_process(args, cwd=app, env=env, log=root / 'flutter.log') as process:
                try:
                    images = exchange(process, root, fixture, report)
                finally:
                    report['peer'] = fixture.snapshot()  # Before any forced teardown.
                    stage = read_exchange(root, 'stage')
                    if stage is not None and stage.keys() == {'phase'} and stage['phase'] in PHASES:
                        report['uiStage'] = stage['phase']
        report['checkpoint'] = 'cleanup'
        require(process.poll() is not None and port_is_released(fixture.port) and fixture.password == '',
                'flutter_linux_cleanup_unconfirmed')
    require(not root.exists(), 'flutter_linux_fixture_directory_remains')
    report['cleanup'] = {'ownedFlutterProcessStopped': True, 'peerListenerReleased': True,
                         'fixturePasswordCleared': True, 'fixtureDirectoryRemoved': True}
    return images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    app = args.app.resolve()
    temp = Path(os.environ.get('RUNNER_TEMP', '/')).resolve()
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or not os.environ.get('RUNNER_TEMP') or
            not re.fullmatch(r':\d+(?:\.0)?', os.environ.get('DISPLAY', '')) or
            not re.fullmatch(r'[0-9a-f]{40}', args.source_sha) or args.source_sha != os.environ.get('GITHUB_SHA') or
            app == temp or not app.is_relative_to(temp) or (app / '.git').exists()):
        parser.error('use the isolated Linux Flutter workflow and its generated scaffold')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'schemaVersion': 1, 'sourceSHA': args.source_sha, 'platform': 'Linux Flutter debug GTK / Xvfb',
              'authentication': 'password', 'scope': 'native Flutter integration_test with Flutter test input and X11 pixels',
              'physicalImeVerified': False, 'status': 'failed'}
    try:
        images = run(app, args.source_sha, report)
        for name, png in images.items():
            (args.output / name).write_bytes(png)
        report.update(status='passed', checkpoint='complete')
    except ScreenshotGateError as error:
        report['errorCode'] = str(error)
        report['terminalFailure'] = error.evidence
    except GuiFailure as error:
        report['errorCode'] = str(error)
    except Exception:  # noqa: BLE001 - tooling logs and exception text are private.
        report['errorCode'] = 'flutter_linux_runner_failed'
    (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if report['status'] != 'passed':
        print(f"Flutter Linux ordinary SSH failed at {report['checkpoint']}: {report['errorCode']}", flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
