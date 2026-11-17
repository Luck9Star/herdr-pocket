#!/usr/bin/env python3
"""Installed Tauri iOS app, native XCUITest UI, disposable loopback SSH only.

--project is the generated Apple directory (or its .xcodeproj); it is read only.
--app is a built, installable aarch64 Simulator.app, never an archive/device app.
Requires full Xcode, an iOS simulator runtime, xcodegen, paramiko, Pillow and
Tesseract/eng. GITHUB_SHA (or --source-sha) supplies the checked-out source SHA.
All driver sources, synthetic credentials, XCTest logs and results are private
temporary files. Only the fixed public manifest, safe system PNGs and unchanged
shared OCR criteria are written to --output. Nothing invokes git or cloud CI.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from terminal_screenshot_gate import ScreenshotGateError, verify_terminal_screenshot
from direct_ssh_fixture import DirectSshFixture

HERE = Path(__file__).resolve().parent
BUNDLE_ID = 'dev.herdrpocket.tauriprobe'
PNG_FILES = ('ordinary-terminal.png', 'key-change-review.png', 'key-change-terminal.png')
STAGES = ('ordinary_form', 'ordinary_probe', 'ordinary_password', 'ordinary_input',
          'ordinary_terminal', 'ordinary_disconnect_attempt', 'ordinary_disconnected',
          'key_change_form', 'key_change_probe_a', 'key_change_password_a',
          'key_change_review', 'key_change_cancelled', 'key_change_probe_b',
          'key_change_password_b', 'key_change_input', 'key_change_terminal',
          'key_change_disconnect_attempt', 'key_change_disconnected', 'complete')
NATIVE_PHASES = frozenset(prefix + '_' + phase for prefix in ('ordinary', 'key_change') for phase in (
    'launch', 'open_add', 'open_ssh', 'host', 'port', 'username', 'probe', 'fingerprint',
    'password', 'connect', 'terminal_focus', 'terminal_input', 'terminal_capture', 'disconnect',
    'review_capture', 'cancel', 'cancel_check', 'reprobe', 'new_fingerprint'))
NATIVE_FAILURES = frozenset((
    'native_tree_limit', 'native_expected_text_missing', 'native_control_missing',
    'native_control_not_visible', 'native_control_disabled', 'native_unexpected_existing_input',
    'native_port_control_ambiguous', 'native_input_keyboard_missing', 'native_input_value_invalid',
    'native_review_lock_invalid', 'native_review_value_invalid', 'native_old_fingerprint_stale',
    'native_secret_exposed', 'native_geometry_ambiguous', 'native_window_missing',
    'native_webview_ambiguous', 'native_visible_frame_invalid', 'native_form_visible_in_capture',
    'native_review_clipped', 'native_review_exits_invalid', 'native_target_clipped',
    'native_terminal_frame_invalid', 'native_screen_frame_invalid', 'native_capture_geometry_changed',
    'native_app_launch_failed', 'native_credentials_visible_after_connect',
    'native_terminal_keyboard_missing', 'native_cancel_lost_old_trust',
    'native_cancel_accepted_new_trust', 'native_cancel_credentials_live', 'native_cancel_submit_live',
    'native_reprobe_old_key_stale', 'native_reprobe_secret_stale'))


class SingleCommandFixture(DirectSshFixture):
    """Observe real server recv bytes without retaining or changing their content.

    The wrapper instruments only the owned SSH server's accepted channel. The
    product's Rust/IPC/terminal are untouched; each read reaches the original
    Paramiko channel and the existing fixture protocol consumes those same bytes.
    A digest over all received chunks distinguishes extra leading newlines or
    repeated commands from exactly one marker line, even at equal byte counts.
    """
    def _handle(self, transport):
        expected = {hashlib.sha256((self.marker + ending).encode()).digest()
                    for ending in ('\r', '\n', '\r\n')}
        digest = hashlib.sha256()
        original_accept = transport.accept
        owner = self
        self._connection_record(transport, 'singleMarkerLineExact', False)

        class ObservedChannel:
            def __init__(self, channel):
                self.channel = channel

            def __getattr__(self, name):
                return getattr(self.channel, name)

            def recv(self, size):
                data = self.channel.recv(size)
                digest.update(data)
                owner._connection_record(transport, 'singleMarkerLineExact', digest.digest() in expected)
                return data

        def accept(timeout=None):
            channel = original_accept(timeout)
            return ObservedChannel(channel) if channel is not None else None

        transport.accept = accept
        try:
            super()._handle(transport)
        finally:
            transport.accept = original_accept


class Failure(RuntimeError):
    """Only fixed codes constructed by this module cross the public boundary."""


def require(condition, code):
    if not condition:
        raise Failure(code)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def command(args, *, log=None, timeout=180, cwd=None):
    try:
        result = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE if log is None else log,
                                stderr=subprocess.PIPE if log is None else subprocess.STDOUT,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Failure('tauri_ios_command_unavailable_or_timeout') from None
    require(result.returncode == 0, 'tauri_ios_command_failed')
    return result.stdout if log is None else b''


def validate_inputs(project, app, source_sha):
    require(bool(re.fullmatch(r'[0-9a-fA-F]{40}', source_sha or '')), 'tauri_ios_source_sha_invalid')
    project, app = Path(project).resolve(), Path(app).resolve()
    projects = [project] if project.suffix == '.xcodeproj' else list(project.glob('*.xcodeproj'))
    require(len(projects) == 1 and (projects[0] / 'project.pbxproj').is_file(),
            'tauri_ios_generated_project_missing')
    require(app.is_dir() and app.suffix == '.app', 'tauri_ios_simulator_app_missing')
    try:
        info = plistlib.loads((app / 'Info.plist').read_bytes())
        executable = app / info['CFBundleExecutable']
        require(info.get('CFBundleIdentifier') == BUNDLE_ID, 'tauri_ios_bundle_identity_invalid')
        require(info.get('CFBundleSupportedPlatforms') == ['iPhoneSimulator']
                and executable.is_file(), 'tauri_ios_app_is_not_simulator')
    except (OSError, KeyError, ValueError, plistlib.InvalidFileException):
        raise Failure('tauri_ios_app_metadata_invalid') from None
    # Read-only provenance: bind the exact generated project and installed binary.
    return {'bundleIdentifier': BUNDLE_ID,
            'executableSha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'projectSha256': hashlib.sha256((projects[0] / 'project.pbxproj').read_bytes()).hexdigest()}


def select_simulator(runtimes, device_types):
    choices = [r for r in runtimes if r.get('isAvailable') is True
               and r.get('identifier', '').startswith('com.apple.CoreSimulator.SimRuntime.iOS-')]
    require(bool(choices), 'tauri_ios_runtime_missing')
    runtime = max(choices, key=lambda r: tuple(int(n) for n in r.get('version', '0').split('.')))
    phones = [d for d in device_types if 'iPhone' in d.get('name', '') and 'Pro Max' in d.get('name', '')]
    require(bool(phones), 'tauri_ios_device_type_missing')
    components = [int(n) for n in runtime.get('version', '0').split('.')]
    version = sum(n << shift for n, shift in zip((components + [0, 0])[:3], (16, 8, 0)))
    compatible = [d for d in phones if int(d.get('minRuntimeVersion', 0)) <= version
                  and int(d.get('maxRuntimeVersion', 0xFFFFFFFF)) >= version]
    require(bool(compatible), 'tauri_ios_compatible_device_missing')
    device = max(compatible, key=lambda d: tuple(int(n) for n in re.findall(r'\d+', d['name'])))
    return runtime['identifier'], device['identifier']


def measured_bounds(payload, image_size):
    def numbers(name, length):
        value = payload.get(name)
        require(isinstance(value, list) and len(value) == length
                and all(type(n) in (float, int) and math.isfinite(n) for n in value),
                'tauri_ios_native_geometry_invalid')
        return value
    screen = numbers('screenSize', 2)
    require(all(n > 0 for n in screen), 'tauri_ios_native_geometry_invalid')
    sx, sy = image_size[0] / screen[0], image_size[1] / screen[1]
    require(1 <= sx <= 4 and abs(sx - sy) < .001, 'tauri_ios_native_scale_invalid')
    safe = numbers('safeFrame', 4)
    def inside(rect, outer):
        x, y, w, h = rect
        a, b, c, d = outer
        return w > 0 and h > 0 and x >= a and y >= b and x + w <= a + c and y + h <= b + d
    require(inside(safe, [0, 0, *screen]), 'tauri_ios_native_visible_frame_invalid')
    def pixels(rect):
        # Round inward: only actual, measured terminal pixels reach OCR.
        x, y, w, h = rect
        left, top = math.ceil(x * sx), math.ceil(y * sy)
        return [left, top, math.floor((x + w) * sx) - left, math.floor((y + h) * sy) - top]
    if 'reviewFrames' in payload:
        frames = payload['reviewFrames']
        require(isinstance(frames, list) and len(frames) == 7, 'tauri_ios_review_geometry_invalid')
        for frame in frames:
            require(isinstance(frame, list) and len(frame) == 4
                    and all(type(n) in (float, int) and math.isfinite(n) for n in frame)
                    and inside(frame, safe), 'tauri_ios_review_geometry_invalid')
        return {'reviewBounds': [pixels(f) for f in frames], 'nativeScale': sx}
    terminal, target = numbers('terminalFrame', 4), numbers('targetFrame', 4)
    require(inside(terminal, safe) and inside(target, safe), 'tauri_ios_terminal_or_target_clipped')
    tx, ty, tw, th = terminal
    x, y, w, h = target
    require(tx + tw <= x or x + w <= tx or ty + th <= y or y + h <= ty,
            'tauri_ios_terminal_target_overlap')
    bounds = pixels(terminal)
    require(bounds[2] > 0 and bounds[3] > 0, 'tauri_ios_native_geometry_invalid')
    return {'terminalBounds': bounds, 'targetBounds': pixels(target), 'nativeScale': sx}


def wait_peer(fixture, predicate, code, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        facts = fixture.snapshot()
        if predicate(facts):
            return facts
        time.sleep(.02)
    raise Failure(code)


def ordinary_evidence(fixture, *, closed):
    facts = fixture.snapshot()
    events = facts['connectionEvents']
    require(facts['connections'] == 2 and len(events) == 2, 'tauri_ios_ordinary_connection_count_invalid')
    probe, session = events
    counters = ('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes')
    require(probe['hostKey'] == 'A' and probe['closed'] is True
            and all(probe[k] == 0 for k in counters), 'tauri_ios_ordinary_probe_not_empty')
    require(session['hostKey'] == 'A' and session['authSuccesses'] == 1 and session['authAttempts'] == 1
            and session['ptyRequests'] == 1 and session['shellRequests'] == 1
            and session['markerReceived'] is True and session['outputBytes'] > 0
            and session.get('singleMarkerLineExact') is True
            and session['inputBytes'] in (len(fixture.marker) + 1, len(fixture.marker) + 2),
            'tauri_ios_ordinary_session_incomplete')
    require(session['sessionClosed'] is closed and session['closed'] is closed,
            'tauri_ios_ordinary_close_order_invalid')
    return facts


def rotation_session_evidence(fixture, *, closed):
    facts = fixture.snapshot()
    require(facts['connections'] == 4 and len(facts['connectionEvents']) == 4,
            'tauri_ios_rotation_connection_count_invalid')
    event = facts['connectionEvents'][-1]
    require(event['hostKey'] == 'B' and event['authAttempts'] == 1 and event['authSuccesses'] == 1
            and event['ptyRequests'] == 1 and event['shellRequests'] == 1
            and event['markerReceived'] is True and event['outputBytes'] > 0
            and event.get('singleMarkerLineExact') is True
            and event['inputBytes'] in (len(fixture.marker) + 1, len(fixture.marker) + 2),
            'tauri_ios_rotation_single_command_or_auth_invalid')
    require(event['closed'] is closed and event['sessionClosed'] is closed
            and facts['connectionsClosed'] is closed, 'tauri_ios_rotation_close_order_invalid')
    return facts


class Checkpoints:
    def __init__(self, ordinary, rotation, output, result):
        self.ordinary, self.rotation, self.output, self.result = ordinary, rotation, Path(output), result
        self.index, self.failure = 0, None
        self.disconnects = set()
        self.secret = secrets.token_hex(32)

    def capture(self, stage, payload, fixture):
        review = stage == 'key_change_review'
        case = self.result['cases']['keyChange' if stage.startswith('key_change') else 'ordinary']
        require(payload.get('identityVerified') is True and payload.get('noCredentialsVisible') is True,
                'tauri_ios_capture_identity_unverified')
        try:
            from PIL import Image
            data = base64.b64decode(payload.get('pngBase64', ''), validate=True)
            require(data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) <= 8_000_000,
                    'tauri_ios_capture_png_invalid')
            with Image.open(io.BytesIO(data)) as image:
                require(image.format == 'PNG' and image.width * image.height <= 16_000_000,
                        'tauri_ios_capture_png_invalid')
                image.load()
                geometry = measured_bounds(payload, image.size)
        except (ValueError, OSError):
            raise Failure('tauri_ios_capture_png_invalid') from None
        name = ('key-change-review.png' if review else
                'key-change-terminal.png' if stage.startswith('key_change') else 'ordinary-terminal.png')
        require(not (self.output / name).exists(), 'tauri_ios_capture_replay_rejected')
        (self.output / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.result['artifacts'][name] = digest
        reference = {'imageFile': name, 'imageSha256': digest, **geometry,
                     'targetVisible': True, 'expectedTarget': f'{fixture.username}@127.0.0.1:{fixture.port}',
                     'systemCapture': 'XCUIScreen.main', 'noCredentialsVisible': True}
        if review:
            reference['purpose'] = 'S10 design review after refusal and before cancellation; no terminal OCR'
            case['reviewScreenshot'] = reference
            return
        criteria_name = name.replace('.png', '-ocr.json')
        case['terminalScreenshot'] = {**reference, 'criteriaFile': criteria_name}
        try:
            criteria = verify_terminal_screenshot(data, expected_token=fixture.screen_token,
                                                  bounds=geometry['terminalBounds'])
        except ScreenshotGateError as error:
            if error.evidence:
                write_json(self.output / criteria_name, error.evidence)
                case['terminalScreenshot'].update(error.evidence)
            raise Failure('tauri_ios_terminal_ocr_failed') from None
        require(criteria['imageSha256'] == digest, 'tauri_ios_capture_hash_mismatch')
        # Preserve shared gate schema verbatim in its standalone criteria file.
        write_json(self.output / criteria_name, criteria)
        case['terminalScreenshot'].update(criteria)
        case['terminalScreenshot']['criteriaSha256'] = hashlib.sha256((self.output / criteria_name).read_bytes()).hexdigest()

    def accept(self, payload):
        stage = payload.get('stage')
        if stage in ('native_progress', 'native_failure'):
            phase = payload.get('nativeCheckpoint')
            require(self.failure is None and phase in NATIVE_PHASES, 'tauri_ios_native_diagnostic_invalid')
            self.result['nativeCheckpoint'] = phase
            if 'nativePortType' in payload:
                require(phase.endswith('_port') and payload['nativePortType'] in ('textField', 'stepperTextField', 'other'),
                        'tauri_ios_native_diagnostic_invalid')
                self.result['nativePortType'] = payload['nativePortType']
            if stage == 'native_failure':
                code = payload.get('nativeFailureCode')
                require(code in NATIVE_FAILURES, 'tauri_ios_native_diagnostic_invalid')
                self.result['nativeFailureCode'] = code
                self.failure = 'tauri_ios_native_check_failed'
            return
        require(self.failure is None and self.index < len(STAGES) and stage == STAGES[self.index],
                'tauri_ios_checkpoint_order_invalid')
        self.result['stage'] = stage
        ordinary, rotation = self.ordinary, self.rotation
        fixture = rotation if stage.startswith('key_change') else ordinary
        if stage == 'ordinary_probe':
            require(ordinary.wait_for_connections_closed(1, timeout=30), 'tauri_ios_probe_not_closed')
            events = ordinary.snapshot()['connectionEvents']
            require(len(events) == 1 and events[0]['hostKey'] == 'A'
                    and all(events[0][k] == 0 for k in ('authAttempts', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes')),
                    'tauri_ios_probe_not_empty')
        if stage == 'ordinary_password':
            self.result['cases']['ordinary']['fingerprintReviewed'] = True
        if stage == 'key_change_password_b':
            self.result['cases']['keyChange']['freshFingerprintConfirmed'] = True
        if stage in ('key_change_review', 'key_change_cancelled', 'key_change_probe_b'):
            count = 3 if stage == 'key_change_probe_b' else 2
            require(rotation.wait_for_connections_closed(count, timeout=30), 'tauri_ios_rotation_not_closed')
            try:
                evidence = rotation.rotation_evidence(count)
            except ValueError:
                raise Failure('tauri_ios_rotation_evidence_invalid') from None
            if stage != 'key_change_cancelled':
                self.result['cases']['keyChange'].setdefault('rotationEvidence', []).append(evidence)
            else:
                self.result['cases']['keyChange']['cancelKeptTrust'] = True
        if stage.endswith('_input'):
            wait_peer(fixture, lambda f: f['markerReceived'] is True,
                      'tauri_ios_peer_input_missing')
        if stage in ('ordinary_terminal', 'key_change_terminal') or stage.endswith('_disconnect_attempt'):
            if fixture is ordinary:
                ordinary_evidence(fixture, closed=False)
            else:
                rotation_session_evidence(fixture, closed=False)
        if stage in ('ordinary_terminal', 'key_change_review', 'key_change_terminal'):
            self.capture(stage, payload, fixture)
        if stage.endswith('_disconnect_attempt'):
            self.disconnects.add(stage.split('_disconnect_attempt')[0])
        if stage.endswith('_disconnected'):
            prefix = stage.split('_disconnected')[0]
            require(prefix in self.disconnects, 'tauri_ios_disconnect_not_requested')
            count = 4 if fixture is rotation else 2
            require(fixture.wait_for_connections_closed(count, timeout=30), 'tauri_ios_peer_disconnect_missing')
            case = self.result['cases']['keyChange' if fixture is rotation else 'ordinary']
            if fixture is rotation:
                try:
                    case['rotationEvidence'].append(rotation.rotation_evidence(4))
                except ValueError:
                    raise Failure('tauri_ios_rotation_evidence_invalid') from None
                case['peer'] = rotation_session_evidence(fixture, closed=True)
            else:
                case['peer'] = ordinary_evidence(fixture, closed=True)
            case.update(status='passed', disconnected=True, terminalInputReceived=True)
        self.index += 1


def start_checkpoints(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if not secrets.compare_digest(self.headers.get('Authorization', ''), state.secret):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                require(0 < length <= 12_000_000, 'tauri_ios_checkpoint_payload_invalid')
                payload = json.loads(self.rfile.read(length))
                require(isinstance(payload, dict), 'tauri_ios_checkpoint_payload_invalid')
                state.accept(payload)
                ok = True
            except Failure as error:
                state.failure, ok = str(error), False
            except Exception:
                state.failure, ok = 'tauri_ios_checkpoint_invalid', False
            body = json.dumps({'ok': ok}).encode()
            self.send_response(200 if ok else 409)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def prepare_driver(private, config):
    private = Path(private)
    encoded = base64.b64encode(json.dumps(config).encode()).decode()
    source = (HERE / 'tauri_ios_direct_ssh.swift').read_text()
    require(source.count('__HP_CONFIG_BASE64__') == 1, 'tauri_ios_driver_template_invalid')
    (private / 'UITests').mkdir()
    (private / 'UITests/Driver.swift').write_text(source.replace('__HP_CONFIG_BASE64__', encoded))
    # Xcode UI tests need a target application. This inert, separate test host
    # is not the tested product; the driver explicitly launches the installed app.
    (private / 'Host').mkdir()
    (private / 'Host/Host.swift').write_text('import UIKit\n@main final class Host: UIResponder, UIApplicationDelegate {}\n')
    spec = {'name': 'PocketUI', 'options': {'deploymentTarget': {'iOS': '15.0'}},
            'settings': {'base': {'CODE_SIGNING_ALLOWED': 'NO', 'SWIFT_VERSION': '5.0',
                                  'GENERATE_INFOPLIST_FILE': 'YES', 'TARGETED_DEVICE_FAMILY': '1,2'}},
            'targets': {
                'DriverHost': {'type': 'application', 'platform': 'iOS', 'sources': ['Host'],
                               'settings': {'base': {'PRODUCT_BUNDLE_IDENTIFIER': 'dev.herdrpocket.uidriver.host'}}},
                'PocketUITests': {'type': 'bundle.ui-testing', 'platform': 'iOS', 'sources': ['UITests'],
                                  'dependencies': [{'target': 'DriverHost'}],
                                  'settings': {'base': {'TEST_TARGET_NAME': 'DriverHost',
                                                       'PRODUCT_BUNDLE_IDENTIFIER': 'dev.herdrpocket.uidriver.tests'}}}},
            'schemes': {'PocketUI': {'build': {'targets': {'DriverHost': 'all', 'PocketUITests': ['test']}},
                                     'test': {'targets': [{'name': 'PocketUITests', 'parallelizable': False}],
                                              'gatherCoverageData': False}}}}
    write_json(private / 'project.json', spec)


def run(project, app, output, *, source_sha=None, env=None):
    env = os.environ if env is None else env
    output = Path(output).resolve()
    require(not output.exists() or not any(output.iterdir()), 'tauri_ios_output_not_empty')
    output.mkdir(parents=True, exist_ok=True)
    candidate_sha = source_sha or env.get('GITHUB_SHA')
    public_sha = candidate_sha if re.fullmatch(r'[0-9a-fA-F]{40}', candidate_sha or '') else None
    result = {'schemaVersion': 1, 'status': 'failed', 'platform': 'ios-simulator', 'client': 'tauri',
              'sourceSHA': public_sha, 'scope': 'owned_loopback_ordinary_ssh',
              'stage': 'input_validation', 'artifacts': {},
              'cases': {'ordinary': {'status': 'not_run'}, 'keyChange': {'status': 'not_run'}},
              'cleanup': {'simulatorDeleted': False, 'fixturesClosed': False, 'privateFilesRemoved': False}}
    device, server, server_thread, ordinary, rotation, private, state = None, None, None, None, None, None, None
    create_attempted = False
    device_name = 'herdr-tauri-ssh-' + uuid.uuid4().hex
    try:
        result['application'] = validate_inputs(project, app, candidate_sha)
        require(env.get('GITHUB_ACTIONS') == 'true' and env.get('RUNNER_OS') == 'macOS',
                'tauri_ios_requires_macos_ci')
        require(all(shutil.which(t) for t in ('xcrun', 'xcodebuild', 'xcodegen', 'tesseract')),
                'tauri_ios_dependencies_missing')
        result['stage'] = 'simulator_selection'
        runtimes = json.loads(command(['xcrun', 'simctl', 'list', 'runtimes', '--json']))['runtimes']
        types = json.loads(command(['xcrun', 'simctl', 'list', 'devicetypes', '--json']))['devicetypes']
        runtime, kind = select_simulator(runtimes, types)
        result['stage'] = 'simulator_create'
        create_attempted = True
        device = command(['xcrun', 'simctl', 'create', device_name, kind, runtime]).decode().strip()
        require(bool(re.fullmatch(r'[A-Fa-f0-9-]{36}', device)), 'tauri_ios_device_identifier_invalid')
        result['stage'] = 'simulator_boot'
        command(['xcrun', 'simctl', 'boot', device])
        command(['xcrun', 'simctl', 'bootstatus', device, '-b'], timeout=240)
        result['stage'] = 'app_install'
        command(['xcrun', 'simctl', 'install', device, str(Path(app).resolve())])
        result['stage'] = 'fixture_start'
        ordinary = SingleCommandFixture(screen_proof=True).__enter__()
        rotation = SingleCommandFixture(rotate_after_probe=True, screen_proof=True).__enter__()
        state = Checkpoints(ordinary, rotation, output, result)
        server, server_thread = start_checkpoints(state)
        private = Path(tempfile.mkdtemp(prefix='herdr-tauri-ios-private-'))
        private.chmod(0o700)
        config = {'bundleIdentifier': BUNDLE_ID,
                  'checkpointURL': f'http://127.0.0.1:{server.server_port}/checkpoint',
                  'checkpointSecret': state.secret,
                  'ordinaryPort': ordinary.port, 'ordinaryPassword': ordinary.password,
                  'ordinaryFingerprint': ordinary.fingerprint,
                  'rotationPort': rotation.port, 'rotationPassword': rotation.password,
                  'fingerprintA': rotation.fingerprint, 'fingerprintB': rotation.rotated_fingerprint}
        prepare_driver(private, config)
        result['stage'] = 'xctest_build'
        with (private / 'xctest-private.log').open('wb') as log:
            command(['xcodegen', 'generate', '--spec', 'project.json'], cwd=private, log=log)
            build = ['xcodebuild', '-project', str(private / 'PocketUI.xcodeproj'), '-scheme', 'PocketUI',
                     '-configuration', 'Debug', '-sdk', 'iphonesimulator', '-destination', 'id=' + device,
                     '-derivedDataPath', str(private / 'derived'), 'CODE_SIGNING_ALLOWED=NO',
                     '-parallel-testing-enabled', 'NO', '-maximum-concurrent-test-simulator-destinations', '1']
            command([*build, 'build-for-testing'], log=log, timeout=600)
            result['stage'] = 'xctest_launch'
            try:
                command([*build, 'test-without-building', '-resultBundlePath', str(private / 'run.xcresult'),
                         '-only-testing:PocketUITests/TauriDirectSSHUITests/testOrdinaryAndKeyChange'],
                        log=log, timeout=900)
            except Failure:
                raise Failure(state.failure or 'tauri_ios_xctest_failed') from None
        require(state.index == len(STAGES) and state.failure is None, 'tauri_ios_checkpoints_incomplete')
        require(set(result['artifacts']) == set(PNG_FILES), 'tauri_ios_artifacts_incomplete')
        result['status'] = 'passed'
    except Failure as error:
        result['error'] = str(error)
    except Exception:
        # Never serialize exception text, raw XCTest output or an accessibility tree.
        result['error'] = 'tauri_ios_driver_failed'
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)
        for fixture in (ordinary, rotation):
            if fixture is not None:
                fixture.close()
        result['cleanup']['fixturesClosed'] = all(f is None or f.snapshot()['connectionsClosed']
                                                 for f in (ordinary, rotation))
        if not result['cleanup']['fixturesClosed']:
            result['status'], result['error'] = 'failed', 'tauri_ios_fixture_cleanup_failed'
        if device is not None:
            try:
                command(['xcrun', 'simctl', 'shutdown', device], timeout=60)
            except Failure:
                pass
            try:
                command(['xcrun', 'simctl', 'delete', device], timeout=60)
                result['cleanup']['simulatorDeleted'] = True
            except Failure:
                result['status'], result['error'] = 'failed', 'tauri_ios_simulator_cleanup_failed'
        elif create_attempted:
            # A timed-out create might have succeeded: recover only our unique name.
            try:
                devices = json.loads(command(['xcrun', 'simctl', 'list', 'devices', '--json'], timeout=60))['devices']
                owned = [d['udid'] for group in devices.values() for d in group if d.get('name') == device_name]
                for owned_device in owned:
                    command(['xcrun', 'simctl', 'delete', owned_device], timeout=60)
                result['cleanup']['simulatorDeleted'] = True
            except Exception:
                pass
        if private is not None:
            try:
                shutil.rmtree(private)
            except OSError:
                result['status'], result['error'] = 'failed', 'tauri_ios_private_cleanup_failed'
        result['cleanup']['privateFilesRemoved'] = private is None or not private.exists()
        write_json(output / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-sha', default=None)
    args = parser.parse_args()
    try:
        result = run(args.project, args.app, args.output, source_sha=args.source_sha)
    except Failure:
        print('tauri_ios_output_not_empty')
        return 1
    print('tauri_ios_' + result['status'])
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
