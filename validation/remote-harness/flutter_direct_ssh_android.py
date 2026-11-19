#!/usr/bin/env python3
"""Explicit CI-only Android ordinary SSH UI acceptance on one disposable AVD.

Only sanitized result JSON and post-credential screenshots are exported. Private
build defines and Flutter logs remain in RUNNER_TEMP and are never artifacts.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import struct
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = 'dev.herdr.herdr_flutter_probe'
SERIAL = 'emulator-5554'
TARGET = 'integration_test/android_direct_ssh_test.dart'
PUBLIC_FIELDS = {'schemaVersion', 'platform', 'homepageEntry', 'fingerprintMatched', 'explicitTrustRequired',
                 'realTerminalView', 'normalTextInputCommit', 'remoteEchoVisible', 'disconnectUiConfirmed',
                 'credentialsCleared', 'physicalImeVerified', 'platformKeyboardOpenedAndClosed',
                 'boardNetworkSettingsReturnedToSameTerminal'}
ROTATION_PUBLIC_FIELDS = {'schemaVersion', 'platform', 'homepageEntry', 'sameTarget',
    'oldFingerprintMatchedIndependentA', 'changedFingerprintMatchedIndependentB',
    'rejectedBeforeAuthentication', 'reviewNavigationBlocked', 'cancelKeepsOldTrust',
    'credentialsLockedBeforeApproval', 'noAutomaticConnection', 'freshProbeMatchedIndependentB',
    'explicitRotatedTrustRequired', 'realTerminalView', 'normalTextInputCommit',
    'remoteEchoVisible', 'disconnectUiConfirmed', 'credentialsCleared', 'physicalImeVerified'}
ROTATION_PHASES = {'rejected': 2, 'cancelled': 2, 'reprobed': 3, 'complete': 4}
ORDINARY_MOBILE_PHASES = ('keyboard_shown', 'keyboard_hidden', 'board_visible', 'board_returned',
                         'network_visible', 'network_returned', 'settings_visible', 'settings_returned')


class Failure(ValueError):
    pass


def checked_paths(app, output, env):
    if (env.get('GITHUB_ACTIONS') != 'true' or not env.get('GITHUB_REF', '').startswith('refs/heads/codex/') or
            not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', '')) or
            not re.fullmatch(r'\d+', env.get('GITHUB_RUN_ID', '')) or
            env.get('ANDROID_SERIAL') != SERIAL or not env.get('RUNNER_TEMP')):
        raise Failure('direct_android_ci_and_owned_avd_required')
    base = Path(env['RUNNER_TEMP']).resolve()
    app, output = Path(app).resolve(), Path(output).resolve()
    if app == base or output == base or not app.is_relative_to(base) or not output.is_relative_to(base) or app == output:
        raise Failure('direct_android_paths_not_isolated')
    if not app.is_dir() or (app / '.git').exists() or output.exists():
        raise Failure('direct_android_app_or_output_not_fresh')
    return app, output


def safe_result(raw):
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise Failure('direct_android_device_result_not_json') from None
    if (not isinstance(result, dict) or set(result) != PUBLIC_FIELDS or
            type(result['schemaVersion']) is not int or result['schemaVersion'] != 1 or
            result['platform'] != 'android-api35-emulator'):
        raise Failure('direct_android_invalid_device_result')
    if result['physicalImeVerified'] is not False or any(result[key] is not True for key in PUBLIC_FIELDS - {'schemaVersion', 'platform', 'physicalImeVerified'}):
        raise Failure('direct_android_incomplete_device_result')
    return result


def ordinary_session_evidence(fixture, *, closed, await_initial_output=False):
    counts = dict(authAttempts=1, authSuccesses=1, ptyRequests=1, shellRequests=1, inputBytes=9 if closed else 0)
    probe = dict.fromkeys(counts, 0)
    probe.update(id=1, hostKey='A', outputBytes=0, authAccepted=False, markerReceived=False,
                 sessionClosed=False)
    # The first transport's cleanup bookkeeping can lag the next handshake.
    if closed:
        probe['closed'] = True
    session = counts.copy()
    session.update(id=2, hostKey='A', authAccepted=True, markerReceived=closed,
                   sessionClosed=closed, closed=closed)
    # The client can receive the banner before sendall's counter is published.
    # Only that zero counter at the first live checkpoint can be in flight.
    deadline = time.monotonic() + 1.0 if await_initial_output and not closed else None
    while True:
        facts = fixture.snapshot()
        events = facts['connectionEvents']
        if (type(facts['connections']) is not int or facts['connections'] != 2
                or facts['connectionsClosed'] is not closed or len(events) != 2
                or any(type(event.get(key)) is not type(value) or event[key] != value
                       for event, expected in zip(events, (probe, session)) for key, value in expected.items())):
            break
        output_bytes = events[1].get('outputBytes')
        if type(output_bytes) is not int or output_bytes < 0:
            break
        if output_bytes > 0:
            return {key: events[1][key] for key in ('id', *counts, 'markerReceived', 'closed')}
        if deadline is None:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(.02, remaining))
        if time.monotonic() >= deadline:
            break
    raise Failure('direct_ssh_ordinary_session_evidence_invalid')


def ordinary_mobile_checkpoint(fixture, value, completed):
    if (not isinstance(value, dict) or set(value) != {'phase'} or
            type(value['phase']) is not str or value['phase'] not in ORDINARY_MOBILE_PHASES):
        raise Failure('direct_ssh_mobile_stage_invalid')
    phase = value['phase']
    if completed and phase == next(reversed(completed)):
        return None
    if len(completed) >= len(ORDINARY_MOBILE_PHASES) or phase != ORDINARY_MOBILE_PHASES[len(completed)]:
        raise Failure('direct_ssh_mobile_stage_out_of_order')
    return phase, ordinary_session_evidence(fixture, closed=False, await_initial_output=not completed)


def require_ordinary_mobile_checkpoints(completed):
    if tuple(completed) != ORDINARY_MOBILE_PHASES:
        raise Failure('direct_ssh_mobile_checkpoints_incomplete')


def safe_rotation_result(raw):
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise Failure('direct_android_rotation_result_not_json') from None
    if (not isinstance(result, dict) or set(result) != ROTATION_PUBLIC_FIELDS
            or type(result['schemaVersion']) is not int or result['schemaVersion'] != 1
            or result['platform'] != 'android-api35-emulator'):
        raise Failure('direct_android_rotation_result_invalid')
    if (result['physicalImeVerified'] is not False or any(result[key] is not True
            for key in ROTATION_PUBLIC_FIELDS - {'schemaVersion', 'platform', 'physicalImeVerified'})):
        raise Failure('direct_android_rotation_result_incomplete')
    return result


def checked_rotation_stage(value, completed):
    if (not isinstance(value, dict) or set(value) != {'phase', 'stage'}
            or type(value['phase']) is not str or value['phase'] not in ROTATION_PHASES
            or type(value['stage']) is not int
            or value['stage'] != ROTATION_PHASES[value['phase']]):
        raise Failure('direct_android_rotation_stage_invalid')
    phase = value['phase']
    if phase not in completed and (len(completed) >= len(ROTATION_PHASES)
            or phase != list(ROTATION_PHASES)[len(completed)]):
        raise Failure('direct_android_rotation_stage_out_of_order')
    return phase, value['stage']


def rotation_checkpoint(fixture, value, completed):
    phase, stage = checked_rotation_stage(value, completed)
    if phase in completed:
        return None
    if not fixture.wait_for_connections_closed(stage):
        raise Failure('direct_android_rotation_connection_not_closed')
    try:
        return fixture.rotation_evidence(stage)
    except ValueError:
        raise Failure('direct_android_rotation_server_evidence_invalid') from None


def adb(*args, check=True, data=None):
    result = subprocess.run(['adb', '-s', SERIAL, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, input=data, timeout=30)
    if check and result.returncode:
        raise Failure('direct_android_adb_failed')
    return result


def text(*args):
    return adb(*args).stdout.decode().strip()


# Fixed, read-only package query only; never replay installation, input or cleanup.
PACKAGE_QUERY_RETRIES = []
def package_present():
    from flutter_android_gui import ADB_TRANSIENT_STDERR, ADB_TRANSIENT_RETRY_DELAYS
    first = None
    for attempt in range(3):
        result = adb('shell', 'pm', 'list', 'packages', PACKAGE, check=False)
        if result.returncode == 0:
            try:
                lines = result.stdout.decode('utf-8', errors='strict').splitlines()
            except UnicodeError:
                raise Failure('direct_android_package_query_invalid') from None
            if result.stderr or any(not re.fullmatch(r'package:[A-Za-z0-9_.]+', line) for line in lines):
                raise Failure('direct_android_package_query_invalid')
            if first is not None:
                PACKAGE_QUERY_RETRIES.append({'first':first, 'attempts':attempt+1, 'recovered':True})
            return 'package:' + PACKAGE in lines
        reason = result.stderr.decode('utf-8', errors='replace').strip()
        known = reason in ADB_TRANSIENT_STDERR and not result.stdout
        if first is None:
            first = {'exitCode':int(result.returncode), 'knownTransient':known,
                     'stdoutBytes':len(result.stdout), 'stderrBytes':len(result.stderr)}
        if not known or attempt == 2:
            PACKAGE_QUERY_RETRIES.append({'first':first, 'attempts':attempt+1, 'recovered':False})
            raise Failure('direct_android_adb_failed')
        time.sleep(ADB_TRANSIENT_RETRY_DELAYS[attempt])


def forward_set():
    return set(text('forward', '--list').splitlines())


def checked_public_reply(reply, relative, limit):
    # Share the already verified pending diagnostics from the paired Android
    # runner. exec-out can report status zero with run-as errors as stdout.
    from flutter_android_gui import public_file_pending
    if public_file_pending(reply, relative):
        return None
    if len(reply.stdout) > limit or len(reply.stderr) > limit:
        raise Failure('direct_android_public_json_oversize')
    if reply.returncode or reply.stderr:
        raise Failure('direct_android_public_json_read_failed')
    if not reply.stdout.strip():
        raise Failure('direct_android_public_json_empty')
    try:
        value = json.loads(reply.stdout)
    except (ValueError, UnicodeError):
        raise Failure('direct_android_public_json_invalid') from None
    if not isinstance(value, dict):
        raise Failure('direct_android_public_json_invalid')
    return value


def read_public_json(relative, limit=4096):
    if not re.fullmatch(r'cache/herdr-direct-ssh-[0-9]+/(?:(?:rotation-)?(?:result|stage)|'
                        r'ordinary-mobile-stage|failure|screen-request)\.json', relative):
        raise Failure('direct_android_public_path_invalid')
    if not package_present():
        return None
    exists = adb('shell', '-T', 'run-as', PACKAGE, 'test', '-f', relative, check=False)
    if exists.returncode == 1 and not exists.stdout.strip() and not exists.stderr.strip():
        return None
    from flutter_android_gui import public_file_pending
    if public_file_pending(exists, relative):
        return None
    if exists.returncode or exists.stdout.strip() or exists.stderr.strip():
        raise Failure('direct_android_public_file_probe_failed')
    reply = adb('shell', '-T', 'run-as', PACKAGE, 'head', '-c', str(limit + 1), relative, check=False)
    return checked_public_reply(reply, relative, limit)


def screen_checkpoint(request, completed, fixture, rotation_fixture, relative, output):
    # Device writes the actual surface first and publishes this fixed-shape
    # request atomically. Each acknowledgement refers to exactly one frame.
    if (not isinstance(request, dict) or set(request) != {'tag', 'attempt', 'bounds', 'viewSize', 'observedTarget'}
            or request['tag'] not in ('ordinary', 'key-rotation')
            or type(request['attempt']) is not int or not 1 <= request['attempt'] <= 12
            or not isinstance(request['viewSize'], list) or len(request['viewSize']) != 2
            or any(type(n) is not int or n <= 0 for n in request['viewSize'])
            or not isinstance(request['bounds'], list) or len(request['bounds']) != 4
            or any(type(n) is not int for n in request['bounds'])
            or request['bounds'][0] < 0 or request['bounds'][1] < 0
            or request['bounds'][2] <= 0 or request['bounds'][3] <= 0):
        raise Failure('direct_android_screen_request_invalid')
    tag, attempt = request['tag'], request['attempt']
    peer = fixture if tag == 'ordinary' else rotation_fixture
    expected_target = f'{peer.username}@127.0.0.1:{peer.port}'
    if type(request['observedTarget']) is not str or request['observedTarget'] != expected_target:
        raise Failure('direct_android_active_target_mismatch')
    if tag in completed and attempt <= completed[tag]['attempt']:
        return
    expected = 1 if tag not in completed else completed[tag]['attempt'] + 1
    if attempt != expected or (tag == 'ordinary' and not completed.get('key-rotation', {}).get('accepted')):
        raise Failure('direct_android_screen_request_out_of_order')
    if tag in completed and completed[tag]['accepted']:
        raise Failure('direct_android_screen_already_accepted')
    name = 'connected' if tag == 'ordinary' else 'rotation-connected'
    png = adb('exec-out', 'run-as', PACKAGE, 'cat', relative + '/' + name + '.png').stdout
    if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 8_000_000:
        raise Failure('direct_android_screenshot_invalid')
    # Capture Android's displayed framebuffer while the SSH screen remains
    # active; this is independent of integration_test's surface conversion.
    device_png = adb('exec-out', 'screencap', '-p').stdout
    if not device_png.startswith(b'\x89PNG\r\n\x1a\n') or len(device_png) > 8_000_000:
        raise Failure('direct_android_screenshot_invalid')
    # Both screenshots must use the Flutter view's full physical dimensions.
    # Preserve originals and geometry for diagnosing a cropped surface or inset.
    sizes = {}
    for source, image in (('integration', png), ('device', device_png)):
        sizes[source] = (list(struct.unpack('>II', image[16:24]))
                         if len(image) >= 24 and image[12:16] == b'IHDR' else None)
    if any(size != request['viewSize'] for size in sizes.values()):
        (output / (tag + '-geometry-integration.png')).write_bytes(png)
        (output / (tag + '-geometry-device.png')).write_bytes(device_png)
        (output / (tag + '-geometry.json')).write_text(json.dumps({
            'tag': tag, 'attempt': attempt, 'bounds': request['bounds'],
            'viewSize': request['viewSize'], 'expectedTarget': expected_target, 'imageSizes': sizes,
        }, indent=2) + '\n')
        raise Failure('direct_android_screenshot_geometry_mismatch')
    from terminal_screenshot_gate import ScreenshotGateError, verify_terminal_screenshot
    checks = {}
    for source, image in (('integration', png), ('device', device_png)):
        try:
            checks[source] = {'status': 'passed', 'evidence': verify_terminal_screenshot(
                image, expected_token=peer.screen_token, bounds=tuple(request['bounds']))}
        except ScreenshotGateError as error:
            checks[source] = {'status': 'failed', 'code': str(error), 'evidence': error.evidence}
    accepted = checks['device']['status'] == 'passed'
    if attempt == 1 and any(check['status'] == 'failed' for check in checks.values()):
        (output / (tag + '-first-failed-integration.png')).write_bytes(png)
        (output / (tag + '-first-failed-device.png')).write_bytes(device_png)
        (output / (tag + '-first-failed.json')).write_text(json.dumps({
            'tag': tag, 'attempt': attempt, 'expectedTarget': expected_target, 'checks': checks,
        }, indent=2) + '\n')
    if accepted:
        (output / (name + '.png')).write_bytes(png)
        (output / (name + '-device.png')).write_bytes(device_png)
        (output / (tag + '-screen-proof.json')).write_text(json.dumps({
            'tag': tag, 'attempt': attempt, 'bounds': request['bounds'],
            'viewSize': request['viewSize'], 'expectedTarget': expected_target, 'checks': checks,
        }, indent=2) + '\n')
    completed[tag] = {'attempt': attempt, 'accepted': accepted, 'expectedTarget': expected_target}
    reply = json.dumps({'tag': tag, 'attempt': attempt, 'accepted': accepted}).encode()
    pending = relative + '/screen-' + tag + '-' + str(attempt) + '.new'
    adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending, data=reply)
    adb('shell', 'run-as', PACKAGE, 'mv', pending, pending[:-4] + '.json')


def safe_failure(error, phase):
    # Exception classes and source locations are diagnostic facts; exception
    # messages/locals may contain credentials and must never be exported.
    frames = []
    trace = error.__traceback__
    while trace is not None:
        file = Path(trace.tb_frame.f_code.co_filename).name
        if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', file):
            frames.append({'file': file, 'line': trace.tb_lineno})
        trace = trace.tb_next
    kind = type(error).__name__
    return {'phase': phase, 'exceptionClass': kind if re.fullmatch(r'[A-Za-z0-9_]{1,80}', kind) else 'Exception',
            'sourceLocations': frames[-4:]}


def verify_prepared(app, env):
    tool_path = ROOT / 'validation/flutter/tool/android_device_test.py'
    sys.path.insert(0, str(tool_path.parent))
    spec = importlib.util.spec_from_file_location('herdr_android_device_preparation', tool_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify_lock(app, env)
    for relative in (TARGET, 'integration_test/direct_ssh_ui_steps.dart'):
        if ((app / relative).is_symlink() or not (app / relative).is_file() or
                (app / relative).read_bytes() != (ROOT / 'validation/flutter' / relative).read_bytes()):
            raise Failure('direct_android_integration_source_mismatch')
    version = json.loads(subprocess.run(['flutter', '--version', '--machine'], capture_output=True, check=True, timeout=60).stdout)
    if version.get('frameworkRevision') != module.FLUTTER_COMMIT or version.get('frameworkVersion') != module.FLUTTER_VERSION:
        raise Failure('direct_android_flutter_version_mismatch')


def run(args, env):
    app, output = checked_paths(args.project, args.output, env)
    verify_prepared(app, env)
    devices = [line.split()[:2] for line in text('devices').splitlines()[1:] if line.strip()]
    if devices != [[SERIAL, 'device']] or text('shell', 'getprop', 'ro.kernel.qemu') != '1' or text('shell', 'getprop', 'ro.build.version.sdk') != '35' or text('shell', 'am', 'get-current-user') != '0':
        raise Failure('direct_android_not_single_api35_emulator')
    if package_present():
        raise Failure('direct_android_package_already_present')
    output.mkdir(mode=0o700)
    before = forward_set()
    cleanup = {'reverseRemoved': False, 'packageRemoved': False, 'ownedForwardsRemoved': False,
               'fixtureClosed': False, 'flutterToolStopped': False, 'rawLogsUploaded': False}
    report = {'schemaVersion': 1, 'sourceSHA': env['GITHUB_SHA'], 'kind': 'flutter-android-ordinary-ssh',
              'status': 'failed', 'cleanup': cleanup, 'physicalImeVerified': False}
    primary = None
    phase = 'fixture_start'
    from direct_ssh_fixture import DirectSshFixture
    fixture = DirectSshFixture(screen_proof=True)
    rotation_fixture = DirectSshFixture(rotate_after_probe=True, screen_proof=True)
    screens = {}
    rotation = {'checkpoints': {}}
    report['rotation'] = rotation
    mobile = report['ordinaryMobileCheckpoints'] = {}
    reverses = []
    process = None
    private = None
    try:
        phase = 'software_keyboard_setup'
        adb('shell', 'settings', 'put', 'secure', 'show_ime_with_hard_keyboard', '1')
        if text('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard') != '1':
            raise Failure('direct_android_software_keyboard_setup_failed')
        with fixture, rotation_fixture:
            phase = 'reverse_setup'
            for peer in (fixture, rotation_fixture):
                reverse = 'tcp:' + str(peer.port)
                if any(reverse in line.split()[1:2] for line in text('reverse', '--list').splitlines()):
                    raise Failure('direct_android_reverse_already_present')
                adb('reverse', reverse, reverse)
                reverses.append(reverse)
            phase = 'private_defines'
            private = Path(tempfile.mkdtemp(prefix='herdr-direct-android-private-', dir=env['RUNNER_TEMP']))
            defines = private / 'defines.json'
            defines.write_text(json.dumps({'HERDR_ANDROID_DIRECT_SSH': '1', 'HERDR_ANDROID_RUN_ID': env['GITHUB_RUN_ID'],
                'HERDR_ANDROID_DIRECT_TARGET': json.dumps({'host': '127.0.0.1', 'port': fixture.port,
                    'username': fixture.username, 'password': fixture.password, 'fingerprint': fixture.fingerprint}),
                'HERDR_ANDROID_ROTATION_TARGET': json.dumps({'host': '127.0.0.1', 'port': rotation_fixture.port,
                    'username': rotation_fixture.username, 'password': rotation_fixture.password,
                    'fingerprint': rotation_fixture.fingerprint,
                    'rotatedFingerprint': rotation_fixture.rotated_fingerprint})}))
            defines.chmod(0o600)
            relative = 'cache/herdr-direct-ssh-' + env['GITHUB_RUN_ID']
            command = ['flutter', 'test', '--no-pub', '--no-uninstall', '--reporter', 'expanded', '-d', SERIAL,
                       '--dart-define-from-file=' + str(defines), TARGET]
            phase = 'driver_start'
            with (private / 'flutter-private.log').open('wb') as log:
                process = subprocess.Popen(command, cwd=app, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                deadline = time.monotonic() + 1200
                peer_confirmed = False
                while process.poll() is None and time.monotonic() < deadline:
                    phase = 'await_device_result'
                    screen = read_public_json(relative + '/screen-request.json')
                    if screen is not None:
                        screen_checkpoint(screen, screens, fixture, rotation_fixture, relative, output)
                    checkpoint = read_public_json(relative + '/rotation-stage.json')
                    if checkpoint is not None:
                        evidence = rotation_checkpoint(rotation_fixture, checkpoint, rotation['checkpoints'])
                        if evidence is not None:
                            phase_name, stage = checked_rotation_stage(checkpoint, rotation['checkpoints'])
                            phase = 'rotation_' + phase_name
                            if fixture.snapshot()['connections'] != 0:
                                raise Failure('direct_android_rotation_touched_ordinary_peer')
                            if process.poll() is not None:
                                raise Failure('direct_android_driver_exited_before_rotation_confirmation')
                            if phase_name == 'complete':
                                device = read_public_json(relative + '/rotation-result.json')
                                if device is None:
                                    raise Failure('direct_android_rotation_result_missing')
                                rotation['device'] = safe_rotation_result(json.dumps(device))
                                rotation['peerClosedBeforeDriverExit'] = True
                            rotation['checkpoints'][phase_name] = evidence
                            reply = json.dumps({'phase': phase_name, 'stage': stage,
                                                'serverEvidenceAccepted': True}).encode()
                            pending = relative + '/rotation-' + phase_name + '-confirmed.new'
                            adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending, data=reply)
                            adb('shell', 'run-as', PACKAGE, 'mv', pending,
                                relative + '/rotation-' + phase_name + '-confirmed.json')
                    mobile_stage = read_public_json(relative + '/ordinary-mobile-stage.json')
                    if mobile_stage is not None:
                        checkpoint = ordinary_mobile_checkpoint(fixture, mobile_stage, mobile)
                        if checkpoint is not None:
                            phase_name, evidence = checkpoint
                            phase = 'ordinary_mobile_' + phase_name
                            if process.poll() is not None:
                                raise Failure('direct_android_driver_exited_before_mobile_confirmation')
                            mobile[phase_name] = evidence
                            reply = json.dumps({'phase': phase_name, 'serverEvidenceAccepted': True}).encode()
                            pending = relative + '/ordinary-mobile-' + phase_name + '-confirmed'
                            adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending + '.new', data=reply)
                            adb('shell', 'run-as', PACKAGE, 'mv', pending + '.new', pending + '.json')
                    public = read_public_json(relative + '/result.json')
                    if public is not None:
                        safe_result(json.dumps(public))
                        require_ordinary_mobile_checkpoints(mobile)
                        if set(screens) != {'ordinary', 'key-rotation'} or not all(x['accepted'] for x in screens.values()):
                            raise Failure('direct_android_screen_proof_missing')
                        if 'device' not in rotation or set(rotation['checkpoints']) != set(ROTATION_PHASES):
                            raise Failure('direct_android_rotation_confirmation_missing')
                        phase = 'peer_close_confirmation'
                        if (not fixture.wait_for('markerReceived') or not fixture.wait_for('sessionClosed')
                                or not fixture.wait_for_connections_closed(2)):
                            raise Failure('direct_android_remote_input_or_close_missing')
                        ordinary_session_evidence(fixture, closed=True)
                        if process.poll() is not None:
                            raise Failure('direct_android_driver_exited_before_peer_confirmation')
                        # The device test is still alive and waiting here, so
                        # driver shutdown cannot masquerade as the UI's close.
                        reply = b'{"protocolAccepted":true,"peerClosedBeforeDriverExit":true}'
                        pending = relative + '/peer-confirmed.new'
                        adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending, data=reply)
                        adb('shell', 'run-as', PACKAGE, 'mv', pending, relative + '/peer-confirmed.json')
                        peer_confirmed = True
                        report['peerClosedBeforeDriverExit'] = True
                        break
                    time.sleep(.5)
                phase = 'await_driver_exit'
                try:
                    code = process.wait(timeout=max(1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    raise Failure('direct_android_flutter_timeout') from None
                if code == 0 and not peer_confirmed:
                    raise Failure('direct_android_peer_confirmation_missing')
            cleanup['flutterToolStopped'] = True
            if code:
                # Stage is an enum from our test; never export the raw test log.
                failure = read_public_json(relative + '/failure.json', 256)
                if failure is not None:
                    stage = failure.get('stage', '')
                    if isinstance(stage, str) and re.fullmatch(r'[a-z_]{1,40}', stage):
                        report['failureStage'] = stage
                raise Failure('direct_android_device_test_failed')
            phase = 'read_device_result'
            public = read_public_json(relative + '/result.json')
            if public is None:
                raise Failure('direct_android_device_result_missing')
            report['device'] = safe_result(json.dumps(public))
            if 'device' not in rotation or set(rotation['checkpoints']) != set(ROTATION_PHASES):
                raise Failure('direct_android_rotation_confirmation_missing')
            try:
                rotation['protocol'] = rotation_fixture.rotation_evidence(4)
            except ValueError:
                raise Failure('direct_android_rotation_server_evidence_invalid') from None
            if not fixture.wait_for('markerReceived') or not fixture.wait_for('sessionClosed'):
                raise Failure('direct_android_remote_input_or_close_missing')
            evidence = fixture.snapshot()
            if not all(evidence[name] for name in ('authAccepted', 'ptyRequested', 'shellRequested', 'markerReceived', 'sessionClosed')):
                raise Failure('direct_android_protocol_evidence_incomplete')
            ordinary_session_evidence(fixture, closed=True)
            report['protocol'] = evidence
            phase = 'read_screenshots'
            for name in ('home', 'connected', 'disconnected', 'rotation-rejected', 'rotation-connected'):
                png = adb('exec-out', 'run-as', PACKAGE, 'cat', relative + '/' + name + '.png').stdout
                if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 8_000_000:
                    raise Failure('direct_android_screenshot_invalid')
                (output / (name + '.png')).write_bytes(png)
            report['status'] = 'passed'
    except Exception as error:
        primary = str(error) if isinstance(error, Failure) else 'direct_android_runner_failed'
        report['failureCode'] = primary
        report['diagnostic'] = safe_failure(error, phase)
    finally:
        report['lastPhase'] = phase
        report['protocol'] = fixture.snapshot()
        rotation['finalSnapshot'] = rotation_fixture.snapshot()
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        cleanup['flutterToolStopped'] = process is None or process.poll() is not None
        try:
            for reverse in reverses:
                adb('reverse', '--remove', reverse)
            remaining = text('reverse', '--list').splitlines()
            cleanup['reverseRemoved'] = not any(reverse in line.split()[1:2]
                for reverse in reverses for line in remaining)
            if package_present():
                adb('shell', 'am', 'force-stop', PACKAGE)
                adb('uninstall', PACKAGE)
            cleanup['packageRemoved'] = not package_present()
            for line in forward_set() - before:
                parts = line.split()
                if len(parts) == 3 and parts[0] == SERIAL and re.fullmatch(r'tcp:\d+', parts[1]):
                    adb('forward', '--remove', parts[1])
            cleanup['ownedForwardsRemoved'] = forward_set() == before
        except Failure:
            report['cleanupCode'] = 'direct_android_adb_cleanup_failed'
        fixture.close()
        rotation_fixture.close()
        cleanup['fixtureClosed'] = (fixture.snapshot()['connectionsClosed']
                                    and rotation_fixture.snapshot()['connectionsClosed'])
        if not all(cleanup[key] for key in cleanup if key != 'rawLogsUploaded'):
            report['status'] = 'failed'
            report['cleanupCode'] = 'direct_android_cleanup_incomplete'
        if private is not None:
            shutil.rmtree(private)
        if PACKAGE_QUERY_RETRIES:
            report['packageQueryRetries'] = PACKAGE_QUERY_RETRIES[-8:]
        # Only completed gate observations are known; missing tags are not zero.
        report['screenProof'] = {tag: {field: screens[tag][field] for field in
            ('attempt', 'accepted', 'expectedTarget')}
            for tag in ('key-rotation', 'ordinary') if tag in screens}
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    if report['status'] != 'passed':
        raise Failure(primary or 'direct_android_cleanup_incomplete')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        report = run(args, dict(os.environ))
        print(json.dumps({'status': report['status'], 'kind': report['kind']}))
    except Exception as error:
        print(str(error) if isinstance(error, Failure) else 'direct_android_runner_failed', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
