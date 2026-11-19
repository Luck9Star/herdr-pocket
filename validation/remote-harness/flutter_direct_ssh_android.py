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
import threading
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
    return closed_rotation_evidence(fixture, stage)


def closed_rotation_evidence(fixture, stage):
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


def read_public_json(relative, limit=4096, *, package_known=False):
    if not re.fullmatch(r'cache/herdr-direct-ssh-[0-9]+/(?:(?:rotation-|encrypted-)?(?:result|stage)|'
                        r'ordinary-mobile-stage|encrypted-diagnostic|encrypted-connect-diagnostic|failure|screen-request)\.json', relative):
        raise Failure('direct_android_public_path_invalid')
    if not package_known and not package_present():
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


def screen_checkpoint(request, completed, fixture, rotation_fixture, relative, output, *, require_rotation=True):
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
    if not require_rotation and tag != 'ordinary':
        raise Failure('direct_android_screen_request_invalid')
    peer = fixture if tag == 'ordinary' else rotation_fixture
    expected_target = f'{peer.username}@127.0.0.1:{peer.port}'
    if type(request['observedTarget']) is not str or request['observedTarget'] != expected_target:
        raise Failure('direct_android_active_target_mismatch')
    if tag in completed and attempt <= completed[tag]['attempt']:
        return
    expected = 1 if tag not in completed else completed[tag]['attempt'] + 1
    if attempt != expected or (require_rotation and tag == 'ordinary' and not completed.get('key-rotation', {}).get('accepted')):
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



ENCRYPTED_PUBLIC_FIELDS = {
    'schemaVersion', 'platform', 'homepageEntry', 'fingerprintMatched',
    'explicitTrustRequired', 'privateKeyPasted', 'passphraseObscured',
    'wrongPassphraseRejectedLocally', 'realTerminalView', 'normalTextInputCommit',
    'remoteEchoVisible', 'disconnectUiConfirmed', 'credentialsCleared',
    'privateInputRemoved', 'clipboardCleared', 'physicalImeVerified',
}
ENCRYPTED_ROTATION_PUBLIC_FIELDS = (ENCRYPTED_PUBLIC_FIELDS - {'wrongPassphraseRejectedLocally'}) | ROTATION_PUBLIC_FIELDS
ENCRYPTED_CHECKPOINTS = ('review', 'rejected')
ENCRYPTED_ROTATION_CHECKPOINTS = ('review', 'rejected', 'cancelled', 'reprobed')


def safe_encrypted_result(raw, *, rotating=False):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise Failure('direct_android_encrypted_result_not_json') from None
    fields = ENCRYPTED_ROTATION_PUBLIC_FIELDS if rotating else ENCRYPTED_PUBLIC_FIELDS
    if (not isinstance(value, dict) or set(value) != fields
            or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
            or value['platform'] != 'android-api35-emulator'
            or value['physicalImeVerified'] is not False
            or any(value[key] is not True for key in fields -
                   {'schemaVersion', 'platform', 'physicalImeVerified'})):
        raise Failure('direct_android_encrypted_result_invalid')
    return value


def encrypted_probe_evidence(fixture):
    if not fixture.wait_for_connections_closed(1):
        raise Failure('direct_android_encrypted_probe_not_closed')
    value = fixture.snapshot()
    events = value['connectionEvents']
    if (type(value['connections']) is not int or value['connections'] != 1
            or value['connectionsClosed'] is not True or len(events) != 1):
        raise Failure('direct_android_encrypted_probe_invalid')
    event = events[0]
    expected = {'id': 1, 'hostKey': 'A', 'authAttempts': 0, 'authSuccesses': 0,
                'ptyRequests': 0, 'shellRequests': 0, 'inputBytes': 0, 'outputBytes': 0,
                'authAccepted': False, 'markerReceived': False, 'sessionClosed': False,
                'closed': True}
    if any(type(event.get(key)) is not type(item) or event[key] != item
           for key, item in expected.items()):
        raise Failure('direct_android_encrypted_probe_invalid')
    return expected


def checked_encrypted_stage(value, completed, *, rotating=False):
    phases = ENCRYPTED_ROTATION_CHECKPOINTS if rotating else ENCRYPTED_CHECKPOINTS
    if (not isinstance(value, dict) or set(value) != {'phase'}
            or type(value['phase']) is not str or value['phase'] not in phases):
        raise Failure('direct_android_encrypted_stage_invalid')
    name = value['phase']
    if name in completed:
        if rotating and name != next(reversed(completed)):
            raise Failure('direct_android_encrypted_stage_out_of_order')
        return None
    if len(completed) >= len(phases) or name != phases[len(completed)]:
        raise Failure('direct_android_encrypted_stage_out_of_order')
    return name


def encrypted_rotation_final_evidence(fixture):
    try:
        evidence = fixture.public_key_auth_evidence()
    except ValueError:
        raise Failure('direct_android_encrypted_rotation_evidence_invalid') from None
    # The fixture recognizes a complete hp-check line. Exact bytes rule out
    # extra input and ensure that the accepted command was sent only once.
    if (type(evidence.get('authAttempts')) is not int or evidence['authAttempts'] != 1
            or type(evidence.get('inputBytes')) is not int or evidence['inputBytes'] != len(b'hp-check\r')):
        raise Failure('direct_android_encrypted_rotation_evidence_invalid')
    return evidence


ENCRYPTED_UI_PHASES = {
    'encrypted_wait_terminal', 'encrypted_wait_welcome', 'encrypted_wait_idle_ime',
    'encrypted_keyboard_show', 'encrypted_input', 'encrypted_enter',
    'encrypted_wait_echo', 'encrypted_keyboard_hide', 'encrypted_capture',
}
ENCRYPTED_UI_BOOLEAN_FIELDS = {
    'terminalHit', 'disconnectHit', 'toggleHit', 'enterHit', 'headerHit', 'terminalFocused',
    'testInputRegistered', 'testClientSet', 'welcomeVisible', 'echoVisible',
}


def safe_encrypted_diagnostic(value):
    fields = {'phase', 'terminalCount', 'toggleState', 'insetBottomPx', 'viewSizePx',
              'terminalRectPt', 'enterRectPt', 'columns', 'rows'} | ENCRYPTED_UI_BOOLEAN_FIELDS
    if (not isinstance(value, dict) or set(value) != fields
            or type(value['phase']) is not str or value['phase'] not in ENCRYPTED_UI_PHASES
            or value['toggleState'] not in ('open', 'close', 'missing', 'other')
            or any(type(value[key]) is not bool for key in ENCRYPTED_UI_BOOLEAN_FIELDS)
            or any(type(value[key]) is not int or not 0 <= value[key] <= 10000
                   for key in ('terminalCount', 'insetBottomPx', 'columns', 'rows'))
            or not isinstance(value['viewSizePx'], list) or len(value['viewSizePx']) != 2
            or any(type(n) is not int or not 1 <= n <= 10000 for n in value['viewSizePx'])
            or any(rect is not None and
                   (not isinstance(rect, list) or len(rect) != 4
                    or any(type(n) is not int or not -10000 <= n <= 10000 for n in rect)
                    or rect[2] < 0 or rect[3] < 0)
                   for rect in (value['terminalRectPt'], value['enterRectPt']))):
        raise Failure('direct_android_encrypted_diagnostic_invalid')
    return value


ENCRYPTED_CONNECT_BOOLEAN_FIELDS = {
    'stable', 'enabled', 'hit', 'privateKeyEmpty', 'passphraseEmpty', 'keyAuth',
    'targetValid', 'busy', 'reviewRequired', 'fingerprintPresent', 'targetMatches',
    'credentialReady', 'canConnect',
}


def safe_encrypted_connect_diagnostic(value):
    fields = {'status', 'rectPt', 'viewSizePx', 'viewSizePt', 'insetBottomPx'} | ENCRYPTED_CONNECT_BOOLEAN_FIELDS
    if (not isinstance(value, dict) or set(value) != fields
            or value['status'] not in ('checking', 'missing', 'multiple', 'disabled', 'not_hit', 'unstable', 'replaced', 'ready')
            or any(type(value[key]) is not bool for key in ENCRYPTED_CONNECT_BOOLEAN_FIELDS)
            or type(value['insetBottomPx']) is not int or not 0 <= value['insetBottomPx'] <= 10000
            or any(not isinstance(value[k], list) or len(value[k]) != 2
                   or any(type(n) is not int or not 1 <= n <= 10000 for n in value[k])
                   for k in ('viewSizePx', 'viewSizePt'))
            or (value['rectPt'] is not None and
                (not isinstance(value['rectPt'], list) or len(value['rectPt']) != 4
                 or any(type(n) is not int or not -10000 <= n <= 10000 for n in value['rectPt'])
                 or value['rectPt'][2] < 0 or value['rectPt'][3] < 0))):
        raise Failure('direct_android_encrypted_connect_diagnostic_invalid')
    return value


# Inspect only fixed tool events in memory. Raw tool output can contain
# private UI data, so no line, fragment, exception message or log is retained.
TOOL_MARKERS = {
    'startupLock': (b'waiting for another flutter command',),
    'gradleStarted': (b"running gradle task 'assembledebug'",),
    'gradleCompleted': (b'built build/app/outputs/',),
    'installationStarted': (b'installing build/app/outputs/',),
    'testLoading': (b'loading ', b'android_direct_ssh_test.dart'),
    'markerTestStarted': (b'terminal markers respect soft and hard line boundaries',),
    'uiTestStarted': (b'android homepage host key rotation, ordinary ssh input, echo and disconnect',),
    'gradleFailed': (b'build failed',),
    'deviceOffline': (b'error: device offline',),
}


class SanitizedToolProgress:
    def __init__(self, stream):
        self._lock = threading.Lock()
        self._markers = dict.fromkeys(TOOL_MARKERS, False)
        self._state = 'running'
        self._thread = threading.Thread(target=self._drain, args=(stream,), daemon=True)
        self._thread.start()

    def _drain(self, stream):
        tail = b''
        try:
            while True:
                chunk = stream.read1(4096)
                if not isinstance(chunk, bytes):
                    raise TypeError('invalid_tool_stream')
                if not chunk:
                    break
                window = (tail + chunk).lower()
                with self._lock:
                    for name, patterns in TOOL_MARKERS.items():
                        if all(pattern in window for pattern in patterns):
                            self._markers[name] = True
                tail = window[-512:]
            state = 'eof'
        except (OSError, ValueError, TypeError):
            state = 'error'
        finally:
            tail = b''
        with self._lock:
            self._state = state

    def snapshot(self):
        with self._lock:
            return {'streamState': self._state, 'markers': dict(self._markers)}

    def finish(self):
        self._thread.join(timeout=2)
        return self.snapshot()


def encrypted_device_state():
    try:
        result = adb('get-state', check=False)
    except subprocess.TimeoutExpired:
        return 'timeout'
    except (Failure, OSError):
        return 'error'
    if result.returncode == 0 and not result.stderr and result.stdout.strip() == b'device':
        return 'device'
    if result.stderr.strip() == b'error: device offline' or result.stdout.strip() == b'offline':
        return 'offline'
    if result.stderr.strip() == b'error: device unauthorized':
        return 'unauthorized'
    return 'unavailable'


ENCRYPTED_APP_STAGES = ENCRYPTED_UI_PHASES | {
    'fixture_validation', 'encrypted_waiting_private', 'encrypted_home',
    'encrypted_probe', 'encrypted_review', 'encrypted_prepare_rejection', 'encrypted_rejected',
    'encrypted_prepare_connect', 'encrypted_connect', 'encrypted_disconnect',
    'rotation_home', 'rotation_initial_probe', 'rotation_rejected',
    'rotation_cancelled', 'rotation_fresh_probe',
}


def safe_encrypted_app_stage(value):
    if (not isinstance(value, dict) or set(value) != {'stage'}
            or type(value['stage']) is not str or value['stage'] not in ENCRYPTED_APP_STAGES):
        raise Failure('direct_android_encrypted_app_stage_invalid')
    return value['stage']


def safe_encrypted_app_failure(value):
    classes = ('TestFailure', 'FlutterError', 'StateError', 'AssertionError', 'TypeError',
               'FileSystemException', 'PlatformException', 'other')
    files = ('android_direct_ssh_test.dart', 'direct_ssh_ui_steps.dart')
    if (not isinstance(value, dict) or set(value) != {'stage', 'code', 'exceptionClass', 'sourceLocations'}
            or type(value['stage']) is not str or value['stage'] not in ENCRYPTED_APP_STAGES
            or value['code'] != 'direct_ssh_android_ui_failed' or value['exceptionClass'] not in classes
            or not isinstance(value['sourceLocations'], list) or len(value['sourceLocations']) > 4
            or any(not isinstance(frame, dict) or set(frame) != {'file', 'line'}
                   or frame['file'] not in files or type(frame['line']) is not int or not 1 <= frame['line'] <= 99999
                   for frame in value['sourceLocations'])):
        raise Failure('direct_android_encrypted_app_failure_invalid')
    return value


def read_encrypted_app_failure(relative, *, package_known=False):
    value = read_public_json(relative + '/failure.json', 1024, package_known=package_known)
    return None if value is None else safe_encrypted_app_failure(value)


def encrypted_app_observation(relative, *, check_failure=True):
    # Before installation, do not issue run-as/file probes or send credentials.
    if not package_present():
        return False, None, None
    stage = read_public_json(relative + '/stage.json', 256, package_known=True)
    name = safe_encrypted_app_stage(stage) if stage is not None else None
    failure = read_encrypted_app_failure(relative, package_known=True) if check_failure else None
    return True, name, failure


def deliver_encrypted_credentials(fixture, run_id):
    if not re.fullmatch(r'\d+', run_id):
        raise Failure('direct_android_invalid_run_id')
    payload = json.dumps({'privateKey': fixture.private_key,
                          'passphrase': fixture.passphrase}).encode()
    pending = 'cache/herdr-key-' + run_id + '.pending'
    adb('shell', 'run-as', PACKAGE, 'mkdir', '-p', 'cache')
    adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending, data=payload)
    adb('shell', 'run-as', PACKAGE, 'chmod', '600', pending)
    adb('shell', 'run-as', PACKAGE, 'mv', pending, pending[:-8] + '.json')


def cleanup_encrypted_device(reverse, before):
    cleanup = {'reverseRemoved': reverse is None, 'packageRemoved': False,
               'ownedForwardsRemoved': False}
    checks = {'reverse': 'not_owned' if reverse is None else 'unproven',
              'package': 'unproven', 'forwards': 'unproven'}
    errors = (Failure, subprocess.SubprocessError, OSError, UnicodeError)
    if reverse is not None:
        try:
            # One removal only; a failed or timed-out write is never replayed.
            adb('reverse', '--remove', reverse)
            remaining = text('reverse', '--list').splitlines()
            cleanup['reverseRemoved'] = not any(reverse in line.split()[1:2] for line in remaining)
            if cleanup['reverseRemoved']:
                checks['reverse'] = 'verified'
        except errors:
            pass
    try:
        if package_present():
            adb('shell', 'am', 'force-stop', PACKAGE)
            adb('uninstall', PACKAGE)
        cleanup['packageRemoved'] = not package_present()
        if cleanup['packageRemoved']:
            checks['package'] = 'verified'
    except errors:
        pass
    try:
        for line in forward_set() - before:
            parts = line.split()
            if len(parts) == 3 and parts[0] == SERIAL and re.fullmatch(r'tcp:\d+', parts[1]):
                adb('forward', '--remove', parts[1])
        cleanup['ownedForwardsRemoved'] = forward_set() == before
        if cleanup['ownedForwardsRemoved']:
            checks['forwards'] = 'verified'
    except errors:
        pass
    return cleanup, checks


def run_encrypted(args, env, *, rotating=False):
    if rotating and env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch':
        raise Failure('direct_android_encrypted_rotation_requires_manual_dispatch')
    app, output = checked_paths(args.project, args.output, env)
    verify_prepared(app, env)
    devices = [line.split()[:2] for line in text('devices').splitlines()[1:] if line.strip()]
    if (devices != [[SERIAL, 'device']] or text('shell', 'getprop', 'ro.kernel.qemu') != '1'
            or text('shell', 'getprop', 'ro.build.version.sdk') != '35'
            or text('shell', 'am', 'get-current-user') != '0'):
        raise Failure('direct_android_not_single_api35_emulator')
    if package_present():
        raise Failure('direct_android_package_already_present')
    output.mkdir(mode=0o700)
    before = forward_set()
    cleanup = {'reverseRemoved': False, 'packageRemoved': False, 'ownedForwardsRemoved': False,
               'fixtureClosed': False, 'temporaryKeyRemoved': False,
               'flutterToolStopped': False, 'rawLogsUploaded': False}
    kind = 'flutter-android-encrypted-ed25519-rotation' if rotating else 'flutter-android-encrypted-ed25519'
    report = {'schemaVersion': 1, 'sourceSHA': env['GITHUB_SHA'], 'kind': kind, 'status': 'failed',
              'cleanup': cleanup, 'physicalImeVerified': False}
    if rotating:
        from tauri_encrypted_key_fixture import RotatingEncryptedKeyFixture
        fixture = RotatingEncryptedKeyFixture()
    else:
        from tauri_encrypted_key_fixture import EncryptedKeyFixture
        fixture = EncryptedKeyFixture(screen_proof=True)
    screen_tag = 'key-rotation' if rotating else 'ordinary'
    expected_phases = ENCRYPTED_ROTATION_CHECKPOINTS if rotating else ENCRYPTED_CHECKPOINTS
    screens, checkpoints = {}, {}
    report['checkpoints'] = checkpoints
    primary = None
    phase = 'fixture_start'
    reverse = None
    process = None
    private = None
    fixture_path = None
    progress = None
    startup = {'deviceState': 'not_checked', 'packageObserved': False,
               'appStageObserved': False, 'appStage': 'not_observed',
               'privateInputDelivered': False}
    report['startup'] = startup
    try:
        phase = 'software_keyboard_setup'
        adb('shell', 'settings', 'put', 'secure', 'show_ime_with_hard_keyboard', '1')
        if text('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard') != '1':
            raise Failure('direct_android_software_keyboard_setup_failed')
        with fixture:
            fixture_path = Path(fixture._temp.name)
            # This peer's existing echo marker is extended with the same public,
            # per-session OCR proof used by the ordinary screen gate.
            if not rotating:
                from screen_proof_token import token_lines
                fixture.echo_marker += '\r\n' + '\r\n'.join(token_lines(fixture.screen_token))
            phase = 'reverse_setup'
            candidate = 'tcp:' + str(fixture.port)
            if any(candidate in line.split()[1:2] for line in text('reverse', '--list').splitlines()):
                raise Failure('direct_android_reverse_already_present')
            adb('reverse', '--no-rebind', candidate, candidate)
            reverse = candidate
            phase = 'private_defines'
            private = Path(tempfile.mkdtemp(prefix='herdr-direct-android-key-', dir=env['RUNNER_TEMP']))
            defines = private / 'defines.json'
            target = {'host': '127.0.0.1', 'port': fixture.port,
                      'username': fixture.username, 'fingerprint': fixture.fingerprint}
            if rotating:
                target['rotatedFingerprint'] = fixture.rotated_fingerprint
            defines.write_text(json.dumps({'HERDR_ANDROID_DIRECT_SSH': '1',
                'HERDR_ANDROID_RUN_ID': env['GITHUB_RUN_ID'],
                'HERDR_ANDROID_ENCRYPTED_KEY_CASE': 'rotation' if rotating else '1',
                'HERDR_ANDROID_ENCRYPTED_KEY_TARGET': json.dumps(target)}))
            defines.chmod(0o600)
            relative = 'cache/herdr-direct-ssh-' + env['GITHUB_RUN_ID']
            command = ['flutter', 'test', '--no-pub', '--no-uninstall', '--reporter', 'expanded', '-d', SERIAL,
                       '--dart-define-from-file=' + str(defines), TARGET]
            phase = 'driver_start'
            process = subprocess.Popen(command, cwd=app, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            progress = SanitizedToolProgress(process.stdout)
            deadline = time.monotonic() + 1200
            next_device_check = 0.0
            peer_confirmed = False
            credential_sent = False
            while process.poll() is None and time.monotonic() < deadline:
                phase = 'await_device_result'
                now = time.monotonic()
                if now >= next_device_check:
                    startup['deviceState'] = encrypted_device_state()
                    if startup['deviceState'] != 'device':
                        raise Failure('direct_android_encrypted_device_unavailable')
                    next_device_check = now + 15
                present, current_stage, early_failure = encrypted_app_observation(
                    relative, check_failure=not credential_sent)
                if not present:
                    time.sleep(1)
                    continue
                startup['packageObserved'] = True
                if current_stage is not None:
                    startup['appStageObserved'] = True
                    startup['appStage'] = current_stage
                if not credential_sent:
                    if early_failure is not None:
                        report.update(failureStage=early_failure['stage'], deviceFailure=early_failure)
                        raise Failure('direct_android_device_test_failed')
                    if current_stage is None:
                        time.sleep(1)
                        continue
                    if current_stage != 'encrypted_waiting_private':
                        raise Failure('direct_android_encrypted_startup_stage_invalid')
                    # Send once, only after the real integration test is waiting.
                    # Secrets never enter defines, build artifacts or exported logs.
                    deliver_encrypted_credentials(fixture, env['GITHUB_RUN_ID'])
                    credential_sent = True
                    startup['privateInputDelivered'] = True
                screen = read_public_json(relative + '/screen-request.json', package_known=True)
                if screen is not None:
                    if rotating and (screen.get('tag') != screen_tag or tuple(checkpoints) != expected_phases):
                        raise Failure('direct_android_encrypted_rotation_screen_unexpected')
                    screen_checkpoint(screen, screens, fixture, fixture if rotating else None,
                                      relative, output, require_rotation=rotating)
                if current_stage == 'encrypted_connect':
                    connect_diagnostic = read_public_json(relative + '/encrypted-connect-diagnostic.json', 2048, package_known=True)
                    if connect_diagnostic is not None:
                        report['connectDiagnostic'] = safe_encrypted_connect_diagnostic(connect_diagnostic)
                diagnostic = read_public_json(relative + '/encrypted-diagnostic.json', 2048, package_known=True)
                if diagnostic is not None:
                    report['uiDiagnostic'] = safe_encrypted_diagnostic(diagnostic)
                checkpoint = read_public_json(relative + '/encrypted-stage.json', package_known=True)
                if checkpoint is not None:
                    name = checked_encrypted_stage(checkpoint, checkpoints, rotating=rotating)
                    if name is not None:
                        if rotating and name != 'review':
                            checkpoints[name] = closed_rotation_evidence(fixture, ROTATION_PHASES[name])
                        else:
                            checkpoints[name] = encrypted_probe_evidence(fixture)
                        if process.poll() is not None:
                            raise Failure('direct_android_driver_exited_before_encrypted_confirmation')
                        reply = json.dumps({'phase': name, 'serverEvidenceAccepted': True}).encode()
                        pending = relative + '/encrypted-' + name + '-confirmed.new'
                        adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending, data=reply)
                        adb('shell', 'run-as', PACKAGE, 'mv', pending, pending[:-4] + '.json')
                public = read_public_json(relative + '/encrypted-result.json', package_known=True)
                if public is not None:
                    report['device'] = safe_encrypted_result(json.dumps(public), rotating=rotating)
                    if not credential_sent or tuple(checkpoints) != expected_phases:
                        raise Failure('direct_android_encrypted_checkpoints_incomplete')
                    if set(screens) != {screen_tag} or screens[screen_tag]['accepted'] is not True:
                        raise Failure('direct_android_screen_proof_missing')
                    phase = 'peer_close_confirmation'
                    if (not fixture.wait_for('markerReceived') or not fixture.wait_for('sessionClosed')
                            or not fixture.wait_for_connections_closed(4 if rotating else 2)):
                        raise Failure('direct_android_remote_input_or_close_missing')
                    if rotating:
                        report['rotatedSessionEvidence'] = encrypted_rotation_final_evidence(fixture)
                    else:
                        ordinary_session_evidence(fixture, closed=True)
                    report['authenticationMethod'] = 'publickey'
                    if process.poll() is not None:
                        raise Failure('direct_android_driver_exited_before_peer_confirmation')
                    reply = b'{"protocolAccepted":true,"peerClosedBeforeDriverExit":true}'
                    pending = relative + '/encrypted-peer-confirmed.new'
                    adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending, data=reply)
                    adb('shell', 'run-as', PACKAGE, 'mv', pending, relative + '/encrypted-peer-confirmed.json')
                    report['peerClosedBeforeDriverExit'] = True
                    peer_confirmed = True
                    break
                time.sleep(.5)
            phase = 'await_driver_exit'
            try:
                code = process.wait(timeout=max(1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise Failure('direct_android_flutter_timeout') from None
            if code:
                failure = read_encrypted_app_failure(relative)
                if failure is not None:
                    report.update(failureStage=failure['stage'], deviceFailure=failure)
                else:
                    stage = read_public_json(relative + '/stage.json', 256)
                    if stage is not None:
                        report['failureStage'] = safe_encrypted_app_stage(stage)
                connect_diagnostic = read_public_json(relative + '/encrypted-connect-diagnostic.json', 2048)
                if connect_diagnostic is not None:
                    report['connectDiagnostic'] = safe_encrypted_connect_diagnostic(connect_diagnostic)
                diagnostic = read_public_json(relative + '/encrypted-diagnostic.json', 2048)
                if diagnostic is not None:
                    report['uiDiagnostic'] = safe_encrypted_diagnostic(diagnostic)
                raise Failure('direct_android_device_test_failed')
            if not peer_confirmed:
                raise Failure('direct_android_peer_confirmation_missing')
            cleanup['flutterToolStopped'] = True
            phase = 'read_screenshots'
            for name in (('home', 'disconnected') if rotating else ('home', 'connected', 'disconnected')):
                png = adb('exec-out', 'run-as', PACKAGE, 'cat', relative + '/' + name + '.png').stdout
                if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 8_000_000:
                    raise Failure('direct_android_screenshot_invalid')
                (output / (name + '.png')).write_bytes(png)
            report['protocol'] = fixture.snapshot()
            report['status'] = 'passed'
    except Exception as error:
        primary = str(error) if isinstance(error, Failure) else 'direct_android_runner_failed'
        report['failureCode'] = primary
        report['diagnostic'] = safe_failure(error, phase)
        if process is not None:
            startup['deviceState'] = encrypted_device_state()
    finally:
        report['lastPhase'] = phase
        report['protocol'] = fixture.snapshot()
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
        if process is not None:
            exit_code = process.poll()
            if type(exit_code) is int and -255 <= exit_code <= 255:
                startup['toolExitCode'] = exit_code
        if progress is not None:
            startup['tool'] = progress.finish()
            # EOF proves no inherited tool writer still holds this pipe open.
            cleanup['flutterToolStopped'] = (cleanup['flutterToolStopped'] and
                                             startup['tool']['streamState'] == 'eof')
        device_cleanup, report['cleanupChecks'] = cleanup_encrypted_device(reverse, before)
        cleanup.update(device_cleanup)
        fixture.close()
        cleanup['fixtureClosed'] = fixture.snapshot()['connectionsClosed']
        cleanup['temporaryKeyRemoved'] = (fixture_path is None or not fixture_path.exists()) and not getattr(fixture, 'private_key', '') and not getattr(fixture, 'passphrase', '')
        if private is not None:
            shutil.rmtree(private)
        if not all(cleanup[key] for key in cleanup if key != 'rawLogsUploaded'):
            report['status'] = 'failed'
            report['cleanupCode'] = 'direct_android_cleanup_incomplete'
        report['screenProof'] = {}
        if screen_tag in screens:
            report['screenProof'][screen_tag] = {
                field: screens[screen_tag][field] for field in ('attempt', 'accepted', 'expectedTarget')
            }
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    if report['status'] != 'passed':
        raise Failure(primary or 'direct_android_cleanup_incomplete')
    return report

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--output', required=True)
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument('--encrypted-key', action='store_true')
    auth.add_argument('--encrypted-key-rotation', action='store_true')
    args = parser.parse_args()
    try:
        env = dict(os.environ)
        report = (run_encrypted(args, env, rotating=args.encrypted_key_rotation)
                  if args.encrypted_key or args.encrypted_key_rotation else run(args, env))
        print(json.dumps({'status': report['status'], 'kind': report['kind']}))
    except Exception as error:
        print(str(error) if isinstance(error, Failure) else 'direct_android_runner_failed', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
