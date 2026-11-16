#!/usr/bin/env python3
"""Private control and independent host-audit checks for Flutter device QA.

The caller supplies only an owned helper process and synthetic expected input.
No request, authorization URL, or raw bytes are written to public evidence.
"""
import subprocess


class DualOverlayDeviceFailure(RuntimeError):
    pass



def audit_baseline(result, expected_length):
    """Capture the one approved active session, permitting earlier closed sessions."""
    sessions = result.get('sessions')
    count = result.get('acceptedSessions')
    if (type(count) is not int or count < 1 or not isinstance(sessions, list)
            or len(sessions) != count or any(not isinstance(item, dict) for item in sessions)
            or result.get('authorizationActive') is not True
            or result.get('exactBytes') is not True or type(result.get('capturedBytes')) is not int
            or result.get('capturedBytes') != expected_length):
        raise DualOverlayDeviceFailure('host_audit_baseline_invalid')
    active = [item for item in sessions if isinstance(item, dict) and item.get('active') is True]
    if len(active) != 1 or active[0].get('approvedDevice') is not True:
        raise DualOverlayDeviceFailure('host_audit_active_session_invalid')
    ordinal = active[0].get('ordinal')
    if type(ordinal) is not int or not 1 <= ordinal <= count:
        raise DualOverlayDeviceFailure('host_audit_ordinal_invalid')
    return count, ordinal


def audit_unchanged_session(result, baseline, expected_length, *, active=True):
    """Require no new authentication and the same approved session on this host."""
    count, ordinal = baseline
    sessions = result.get('sessions')
    if (type(result.get('acceptedSessions')) is not int or result.get('acceptedSessions') != count
            or type(result.get('newSessions')) is not int or result.get('newSessions') != 0
            or type(result.get('capturedBytes')) is not int or result.get('capturedBytes') != expected_length or result.get('exactBytes') is not True
            or result.get('authorizationActive') is not True or not isinstance(sessions, list)
            or len(sessions) != count or any(not isinstance(item, dict) for item in sessions)):
        raise DualOverlayDeviceFailure('host_audit_session_changed')
    selected = [item for item in sessions if isinstance(item, dict) and item.get('ordinal') == ordinal]
    if (len(selected) != 1 or selected[0].get('approvedDevice') is not True
            or selected[0].get('active') is not active
            or any(item.get('active') is True for item in sessions if item is not selected[0])):
        raise DualOverlayDeviceFailure('host_audit_session_changed')


def prepare_private_ca(adb, serial, certificate, *, run):
    """Install QA trust before the app's TS native library can be loaded.

    The caller must first install a fresh isolated debug package; `run-as`
    confines these files to that package. Neither certificate contents nor
    command output are included in raised errors.
    """
    if (not isinstance(serial, str) or not serial or any(c not in
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_:.' for c in serial)
            or not isinstance(certificate, bytes) or not 0 < len(certificate) <= 16384
            or b'-----BEGIN CERTIFICATE-----' not in certificate
            or b'PRIVATE KEY' in certificate):
        raise DualOverlayDeviceFailure('private_ca_input_invalid')
    prefix = [str(adb), '-s', serial, 'shell', '-T', 'run-as', 'dev.herdr.herdr_flutter_probe']
    commands = [
        ('private_ca_mkdir_failed', ['mkdir', '-p', 'files/empty-dual-overlay-ca'], None),
        ('private_ca_cert_failed', ['tee', 'files/dual-overlay-ca.pem'], certificate),
        ('private_ca_permissions_failed', ['chmod', '600', 'files/dual-overlay-ca.pem'], None),
        ('private_ca_readback_failed', ['cat', 'files/dual-overlay-ca.pem'], None),
        ('private_ca_marker_failed', ['touch', 'files/enable-dual-overlay-private-ca'], None),
        ('private_ca_marker_failed', ['chmod', '600', 'files/enable-dual-overlay-private-ca'], None),
    ]
    for failure_code, command, data in commands:
        try:
            result = run(prefix + command, input=data, stdout=-1, stderr=-1, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise DualOverlayDeviceFailure(failure_code) from None
        if result.returncode != 0 or (failure_code == 'private_ca_readback_failed' and result.stdout != certificate):
            raise DualOverlayDeviceFailure(failure_code)



EXCHANGE_FILES = frozenset({'config.json', 'et-response.json', 'ts-response.json',
                            'ts-authorized.txt', 'et-audit.txt', 'ts-audit.txt', 'stopped-audit.txt', 'final-audit.txt'})


def write_exchange(adb, serial, name, data, *, run):
    """Send fixture material over stdin to a fixed app-private exchange file."""
    if (name not in EXCHANGE_FILES or not isinstance(data, bytes) or len(data) > 65536
            or not isinstance(serial, str) or not serial or any(c not in
                'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_:.' for c in serial)):
        raise DualOverlayDeviceFailure('private_exchange_input_invalid')
    prefix = [str(adb), '-s', serial, 'shell', '-T', 'run-as', 'dev.herdr.herdr_flutter_probe']
    relative = 'files/dual-overlay-exchange/' + name
    commands = [(['mkdir', '-p', 'files/dual-overlay-exchange'], None),
                (['tee', relative + '.new'], data),
                (['chmod', '600', relative + '.new'], None),
                (['mv', relative + '.new', relative], None)]
    for command, content in commands:
        try:
            result = run(prefix + command, input=content, stdout=-1, stderr=-1, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise DualOverlayDeviceFailure('private_exchange_write_failed') from None
        if result.returncode != 0:
            raise DualOverlayDeviceFailure('private_exchange_write_failed')



READABLE_EXCHANGE = frozenset({'stage', 'et-request.json', 'ts-request.json', 'ts-url.txt', 'result.json', 'failure.json'})


def read_exchange(adb, serial, name, *, run):
    """Read only a fixed private exchange entry; never log its contents."""
    if (name not in READABLE_EXCHANGE or not isinstance(serial, str) or not serial or any(c not in
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_:.' for c in serial)):
        raise DualOverlayDeviceFailure('private_exchange_input_invalid')
    command = [str(adb), '-s', serial, 'exec-out', 'run-as', 'dev.herdr.herdr_flutter_probe',
               'cat', 'files/dual-overlay-exchange/' + name]
    try:
        result = run(command, stdout=-1, stderr=-1, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise DualOverlayDeviceFailure('private_exchange_read_failed') from None
    if result.returncode != 0:
        return None
    if not isinstance(result.stdout, bytes) or len(result.stdout) > 65536:
        raise DualOverlayDeviceFailure('private_exchange_read_failed')
    return result.stdout


def handle_stage(stage, *, session, adb, serial, run, first_stop, baselines, audit_records=None):
    """Answer one blocked GUI checkpoint using independent host facts."""
    import base64
    import json
    from flutter_android_gui import public_host_fingerprint

    if stage == 'ts_wait_authorization':
        raw = read_exchange(adb, serial, 'ts-url.txt', run=run)
        if raw is None:
            return False
        try:
            url = raw.decode('utf-8')
        except UnicodeDecodeError:
            raise DualOverlayDeviceFailure('ts_authorization_invalid') from None
        result = session.control.call({'op': 'complete_ts_auth', 'authorize': True, 'url': url})
        if result.get('event') != 'ts_authorized' or result.get('ok') is not True:
            raise DualOverlayDeviceFailure('ts_authorization_failed')
        write_exchange(adb, serial, 'ts-authorized.txt', b'authorized', run=run)
        return True
    if stage in ('et_pair_review', 'ts_pair_review'):
        role = stage[:2]
        raw = read_exchange(adb, serial, role + '-request.json', run=run)
        if raw is None:
            return False
        try:
            request = raw.decode('utf-8')
            data = json.loads(request)
            if not isinstance(data, dict):
                raise ValueError('pairing request must be an object')
            host_pin = public_host_fingerprint(session.read_host_profile(role)['expectedHostKey'])
            device_pin = public_host_fingerprint(data['public_key'])
        except (UnicodeDecodeError, ValueError, KeyError, TypeError):
            raise DualOverlayDeviceFailure('pairing_review_invalid') from None
        review = session.control.call({'op': 'review_pairing', 'role': role, 'request': request})
        if (review.get('event') != 'pairing_review' or review.get('role') != role
                or review.get('requestId') != data.get('request_id')
                or review.get('hostFingerprint') != host_pin or review.get('deviceFingerprint') != device_pin):
            raise DualOverlayDeviceFailure('pairing_review_mismatch')
        approval = session.control.call({'op': 'approve_pairing', 'role': role, 'request': request,
            'requestId': data['request_id'], 'deviceFingerprint': device_pin, 'reviewed': True})
        if approval.get('event') != 'pairing_approved' or approval.get('role') != role:
            raise DualOverlayDeviceFailure('pairing_approval_failed')
        response = approval.get('response')
        if not isinstance(response, str) or not response or len(response.encode()) > 65536:
            raise DualOverlayDeviceFailure('pairing_approval_failed')
        write_exchange(adb, serial, role + '-response.json', response.encode(), run=run)
        return True

    def audit(role, expected):
        event = session.control.call({'op': 'audit', 'role': role,
            'expectedBase64': base64.b64encode(expected).decode('ascii')})
        if event.get('event') != 'host_audit' or event.get('role') != role:
            raise DualOverlayDeviceFailure('host_audit_role_invalid')
        if audit_records is not None:
            sessions = event.get('sessions')
            if (not isinstance(sessions, list) or len(sessions) > 64
                    or any(not isinstance(item, dict) for item in sessions)
                    or any(type(event.get(key)) is not int or not 0 <= event[key] <= 1000000
                           for key in ('acceptedSessions', 'newSessions', 'capturedBytes', 'newInputBytes'))
                    or any(type(event.get(key)) is not bool for key in ('exactBytes', 'authorizationActive'))
                    or any(type(item.get('ordinal')) is not int or not 1 <= item['ordinal'] <= 64
                           or type(item.get('approvedDevice')) is not bool or type(item.get('active')) is not bool
                           for item in sessions)):
                raise DualOverlayDeviceFailure('host_audit_role_invalid')
            audit_records.append({'checkpoint': stage, 'role': role,
                'acceptedSessions': event.get('acceptedSessions'), 'newSessions': event.get('newSessions'),
                'capturedBytes': event.get('capturedBytes'), 'newInputBytes': event.get('newInputBytes'),
                'exactBytes': event.get('exactBytes'), 'authorizationActive': event.get('authorizationActive'),
                'sessions': [{key: item.get(key) for key in ('ordinal', 'approvedDevice', 'active')} for item in sessions]})
        return event

    if stage in ('et_baseline', 'ts_baseline'):
        role = stage[:2]
        expected = b'E' if role == 'et' else b'T'
        baselines[role] = audit_baseline(audit(role, expected), len(expected))
        write_exchange(adb, serial, role + '-audit.txt', b'accepted', run=run)
        return True
    if stage in ('stopped_audit', 'final_audit'):
        if set(baselines) != {'et', 'ts'} or first_stop not in ('et', 'ts'):
            raise DualOverlayDeviceFailure('host_audit_baseline_missing')
        survivor = 'ts' if first_stop == 'et' else 'et'
        for role in ('et', 'ts'):
            expected = b'E' if role == 'et' else b'T'
            if stage == 'final_audit' and role == survivor:
                expected += b'e' if role == 'et' else b't'
            audit_unchanged_session(audit(role, expected), baselines[role], len(expected), active=role == survivor)
        write_exchange(adb, serial, 'stopped-audit.txt' if stage == 'stopped_audit' else 'final-audit.txt',
                       b'accepted', run=run)
        return True
    return False


UI_STAGES = frozenset({'host_board', 'et_network_create', 'ts_network_create', 'ts_login_open',
    'ts_wait_authorization', 'et_pair_profile', 'ts_pair_profile', 'et_pair_review', 'ts_pair_review',
    'et_open_host', 'ts_open_host', 'et_input', 'ts_input', 'et_baseline', 'ts_baseline',
    'et_resume', 'ts_resume', 'et_stop_network', 'ts_stop_network', 'stopped_audit', 'final_audit',
    'et_network_save', 'ts_network_save', 'et_identity_open', 'ts_identity_open',
    'et_identity_load', 'ts_identity_load',
    'et_bind_open', 'ts_bind_open', 'et_bind_preview', 'ts_bind_preview',
    'et_bind_confirm', 'ts_bind_confirm', 'et_bind_save', 'ts_bind_save',
    'et_pair_page', 'ts_pair_page', 'et_pair_input', 'ts_pair_input',
    'et_pair_preview', 'ts_pair_preview', 'et_pair_fill', 'ts_pair_fill',
    'et_pair_target_review', 'ts_pair_target_review', 'et_pair_create', 'ts_pair_create',
    'et_pair_request', 'ts_pair_request',
    'et_response_enter', 'ts_response_enter', 'et_response_finish_edit', 'ts_response_finish_edit',
    'et_response_preview', 'ts_response_preview', 'et_response_source', 'ts_response_source',
    'et_response_accept', 'ts_response_accept', 'et_response_saved', 'ts_response_saved',
    'et_identity_review', 'ts_identity_review', 'et_identity_create', 'ts_identity_create',
    'et_node_refresh', 'ts_node_refresh', 'et_node_start', 'ts_node_start',
    'et_node_wait', 'ts_node_wait', 'ts_node_ready_refresh'})


def safe_ui_failure(raw):
    import json
    try:
        detail = json.loads(raw)
        basic = {'stage', 'kind'}
        diagnostic = {'nodeState', 'statusPresent', 'editPresent', 'editEnabled', 'addPresent', 'addEnabled', 'notice'}
        optional = {'responseReceived', 'stackFrames', 'responseCheck', 'bindingCheck', 'bindingSelectionMatches'}
        if (isinstance(detail, dict) and set(detail) - optional in (basic, basic | diagnostic)
                and isinstance(detail['stage'], str) and detail['stage'] in UI_STAGES
                and isinstance(detail['kind'], str)
                and detail['kind'] in {'test_failure', 'flutter_error', 'state_error', 'assertion_error', 'other'}):
            if 'responseReceived' in detail and type(detail['responseReceived']) is not bool:
                return None
            if 'bindingSelectionMatches' in detail and type(detail['bindingSelectionMatches']) is not bool:
                return None
            if 'bindingCheck' in detail:
                binding = detail['bindingCheck']
                fields = {'hostPresent', 'hostEnabled', 'bindingMatches', 'catalogReady', 'catalogWriting', 'addPresent', 'addEnabled'}
                if not isinstance(binding, dict) or set(binding) != fields or any(type(binding[k]) is not bool for k in fields):
                    return None
            if 'responseCheck' in detail:
                check = detail['responseCheck']
                if (not isinstance(check, dict) or set(check) != {'inputMatches', 'fieldPresent', 'pagePresent', 'foreground', 'category', 'futureSeconds'}
                        or any(type(check[k]) is not bool for k in ('inputMatches', 'fieldPresent', 'pagePresent', 'foreground'))
                        or check['category'] not in {'valid', 'future', 'expired', 'invalid', 'oversize'}
                        or type(check['futureSeconds']) is not int or not 0 <= check['futureSeconds'] <= 600
                        or ((check['category'] == 'future') != (check['futureSeconds'] > 0))):
                    return None
            if 'stackFrames' in detail:
                frames = detail['stackFrames']
                if (not isinstance(frames, list) or len(frames) > 6 or any(
                        not isinstance(frame, dict) or set(frame) != {'file', 'line'}
                        or frame['file'] not in {'dual_overlay_ui_steps.dart', 'android_dual_overlay_test.dart', 'android_pairing_observe_test.dart'}
                        or type(frame['line']) is not int or not 1 <= frame['line'] <= 999999 for frame in frames)):
                    return None
            if set(detail) - optional == basic:
                return detail
            if (detail['nodeState'] in {'engine_started', 'needs_login', 'needs_machine_auth', 'running',
                                        'starting', 'closing', 'stopped', 'unknown', 'unavailable', 'other'}
                    and all(type(detail[key]) is bool for key in ('statusPresent', 'editPresent', 'editEnabled', 'addPresent', 'addEnabled'))
                    and detail['notice'] in {'not_visible', 'start_unconfirmed', 'public_unsupported', 'other'}):
                return detail
    except (ValueError, UnicodeDecodeError, TypeError):
        pass
    return None


def drive_checkpoints(session, process, adb, serial, first_stop, *, run, timeout=900, report_stage=None, report_failure=None, audit_records=None):
    """Drive bounded, ordered UI checkpoints; the host facts gate each reply."""
    import json
    import time

    if first_stop not in ('et', 'ts') or timeout <= 0 or timeout > 1200:
        raise DualOverlayDeviceFailure('device_run_invalid')
    checkpoints = ('ts_wait_authorization', 'et_pair_review', 'ts_pair_review',
                   'et_baseline', 'ts_baseline', 'stopped_audit', 'final_audit')
    deadline = time.monotonic() + timeout
    index = 0
    baselines = {}
    while time.monotonic() < deadline:
        raw = read_exchange(adb, serial, 'stage', run=run)
        if raw is not None:
            try:
                stage = raw.decode('ascii')
            except UnicodeDecodeError:
                raise DualOverlayDeviceFailure('device_stage_invalid') from None
            if report_stage is not None:
                report_stage(stage if stage in UI_STAGES else 'other')
            if index < len(checkpoints) and stage == checkpoints[index]:
                if handle_stage(stage, session=session, adb=adb, serial=serial, run=run,
                                first_stop=first_stop, baselines=baselines, audit_records=audit_records):
                    index += 1
            elif stage in checkpoints[index + 1:]:
                raise DualOverlayDeviceFailure('device_stage_out_of_order')
        if index == len(checkpoints):
            result = read_exchange(adb, serial, 'result.json', run=run)
            if result is not None:
                try:
                    value = json.loads(result)
                except (ValueError, UnicodeDecodeError):
                    raise DualOverlayDeviceFailure('device_result_invalid') from None
                expected = {'status': 'passed', 'firstStop': first_stop, 'twoReviewedTargets': True,
                    'observedBothUpdates': True, 'responseMarkersMatched': True,
                    'explicitTsAuthorization': True, 'newFullAfterResume': True,
                    'stoppedTabRetired': True, 'survivorStopped': True,
                    'initialInputsAccepted': True, 'survivorInputAccepted': True}
                if value != expected:
                    raise DualOverlayDeviceFailure('device_result_invalid')
                try:
                    exit_code = process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    raise DualOverlayDeviceFailure('device_test_exit_timeout') from None
                if exit_code != 0:
                    raise DualOverlayDeviceFailure('device_test_failed')
                return expected
        if process.poll() is not None:
            failure = read_exchange(adb, serial, 'failure.json', run=run)
            if failure is not None and report_failure is not None:
                detail = safe_ui_failure(failure)
                if detail is not None:
                    report_failure(detail)
            raise DualOverlayDeviceFailure('device_test_exited_early')
        time.sleep(0.25)
    raise DualOverlayDeviceFailure('device_run_timeout')


def sample_ts_control(session):
    """Return only bounded public categories from the fixture's read-only counters."""
    keys = ('keyRequests', 'noiseRequests', 'registerRequests', 'mapRequests',
            'tlsHandshakeErrors', 'authCompletions')
    try:
        event = session.control.call({'op': 'ts_diagnostics'})
        if (not isinstance(event, dict) or set(event) != {'event', 'secondClientRegistered', *keys}
                or event.get('event') != 'ts_diagnostics' or type(event.get('secondClientRegistered')) is not bool
                or any(type(event.get(key)) is not int or not 0 <= event[key] <= 1000000 for key in keys)):
            return {'available': False}
        return {'available': True, **{key: event[key] for key in keys},
                'secondClientRegistered': event['secondClientRegistered']}
    except Exception:
        return {'available': False}


def installed_apk_evidence(device, bundle, destination, verify):
    """Inspect the installed app without publishing its private package path."""
    import re
    try:
        output = device.adb('shell', 'pm', 'path', device.PACKAGE).stdout.decode('ascii').strip()
    except (UnicodeError, AttributeError):
        raise DualOverlayDeviceFailure('installed_apk_path_invalid') from None
    match = re.fullmatch(r'package:(/data/app/[A-Za-z0-9_./+=~-]+/base\.apk)', output)
    if match is None or '..' in match.group(1).split('/'):
        raise DualOverlayDeviceFailure('installed_apk_path_invalid')
    data = device.adb('exec-out', 'cat', match.group(1)).stdout
    if not isinstance(data, bytes) or not 0 < len(data) <= 300 * 1024 * 1024:
        raise DualOverlayDeviceFailure('installed_apk_invalid')
    destination.write_bytes(data)
    return verify(bundle, destination)


def run_device(args, env):
    """Run two fresh owned-device cases; publish only fixed result categories."""
    import json
    import os
    from pathlib import Path
    import re
    import signal
    import sys
    import tempfile

    import flutter_direct_ssh_android as device
    from android_dual_overlay_session import AndroidDualOverlaySession

    app, output = device.checked_paths(args.project, args.output, env)
    device.verify_prepared(app, env)
    if (env.get('ANDROID_AVD_HOME') is None or
            not Path(env['ANDROID_AVD_HOME']).resolve().is_relative_to(Path(env['RUNNER_TEMP']).resolve()) or
            not re.fullmatch('[0-9a-f]{40}', args.host_source)):
        raise DualOverlayDeviceFailure('owned_avd_required')
    for name in ('android_dual_overlay_test.dart', 'dual_overlay_ui_steps.dart'):
        expected = Path(__file__).resolve().parents[1] / 'flutter/integration_test' / name
        actual = app / 'integration_test' / name
        if actual.is_symlink() or not actual.is_file() or actual.read_bytes() != expected.read_bytes():
            raise DualOverlayDeviceFailure('integration_source_mismatch')
    devices = [line.split()[:2] for line in device.text('devices').splitlines()[1:] if line.strip()]
    if (devices != [['emulator-5554', 'device']] or device.text('shell', 'getprop', 'ro.kernel.qemu') != '1'
            or device.text('shell', 'getprop', 'ro.build.version.sdk') != '35'
            or device.text('shell', 'getprop', 'ro.product.cpu.abi') != 'x86_64'
            or device.text('shell', 'am', 'get-current-user') != '0' or device.package_present()):
        raise DualOverlayDeviceFailure('fresh_api35_avd_required')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'flutter/tool'))
    import dual_overlay_apk
    output.mkdir(mode=0o700)
    report = {'schemaVersion': 1, 'kind': 'flutter-android-dual-overlay', 'status': 'failed',
              'uiSource': env['GITHUB_SHA'], 'nativeSource': args.native_source,
              'hostSource': args.host_source, 'hostArtifactId': 14171011473,
              'hostArtifactSha256': '4bdc54843a9f438896db3717bd002859021fab51cbe60339c35e8a62a5bd6698',
              'nativeVariant': 'test-only-private-ca-x86_64', 'apiLevel': 35,
              'physicalDevice': False, 'rawLogsUploaded': False, 'cases': []}
    before_forwards = device.forward_set()
    with tempfile.TemporaryDirectory(prefix='flutter-dual-private-', dir=env['RUNNER_TEMP']) as private:
        private = Path(private)
        for first_stop in ('et', 'ts'):
            case = {'firstStop': first_stop, 'status': 'failed', 'stage': 'build'}
            report['cases'].append(case)
            process = None
            session = None
            try:
                flags = ['--dart-define=HERDR_ANDROID_DUAL_OVERLAY=true',
                         '--dart-define=HERDR_ANDROID_DUAL_RUN_ID=' + env['GITHUB_RUN_ID'],
                         '--dart-define=HERDR_ANDROID_DUAL_FIRST_STOP=' + first_stop]
                with (private / (first_stop + '-build.log')).open('wb') as log:
                    command = ['flutter', 'build', 'apk', '--debug', '--target-platform', 'android-x64',
                               '-t', 'integration_test/android_dual_overlay_test.dart', *flags]
                    result = subprocess.run(command, cwd=app, stdout=log, stderr=subprocess.STDOUT,
                                            timeout=600, check=False)
                if result.returncode != 0:
                    raise DualOverlayDeviceFailure('device_apk_build_failed')
                built = app / 'build/app/outputs/flutter-apk/app-debug.apk'
                apk_evidence = dual_overlay_apk.verify(args.qa_bundle, built)
                case['instrumentationApkSha256'] = apk_evidence['apkSha256']
                case['stage'] = 'install'
                device.adb('install', '-r', str(built))
                with tempfile.TemporaryDirectory(prefix=first_stop + '-', dir=private) as work:
                    case['stage'] = 'host_start'
                    session = AndroidDualOverlaySession(args.host_bundle, work, host_source=args.host_source,
                        source_checkout=args.host_checkout, device='emulator-5554', lifetime=900)
                    with session:
                        case['tsControlBefore'] = sample_ts_control(session)
                        case['stage'] = 'private_setup'
                        prepare_private_ca('adb', 'emulator-5554', session.read_ca(), run=subprocess.run)
                        material = session.materials
                        network = material['etNetwork']
                        config = {'runId': env['GITHUB_RUN_ID'], 'firstStop': first_stop,
                                  'etProfile': json.dumps(session.read_host_profile('et')),
                                  'tsProfile': json.dumps(session.read_host_profile('ts')),
                                  'controlUrl': material['controlUrl'], 'networkName': network['networkName'],
                                  'networkSecret': network['networkSecret'], 'peerUrl': network['peerUrl']}
                        write_exchange('adb', 'emulator-5554', 'config.json', json.dumps(config).encode(), run=subprocess.run)
                        case['stage'] = 'device_ui'
                        case['hostAudits'] = []
                        with (private / (first_stop + '-flutter.log')).open('wb') as log:
                            process = subprocess.Popen(['flutter', 'test', '--no-pub', '--no-uninstall',
                                '--reporter', 'expanded', '-d', 'emulator-5554',
                                'integration_test/android_dual_overlay_test.dart', *flags], cwd=app,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                            try:
                                case['ui'] = drive_checkpoints(session, process, 'adb', 'emulator-5554',
                                                               first_stop, run=subprocess.run,
                                                               report_stage=lambda stage: case.update(uiStage=stage),
                                                               report_failure=lambda failure: case.update(uiFailure=failure),
                                                               audit_records=case['hostAudits'])
                            finally:
                                if process.poll() is None:
                                    try: os.killpg(process.pid, signal.SIGTERM)
                                    except ProcessLookupError: pass
                                    try: process.wait(timeout=10)
                                    except subprocess.TimeoutExpired:
                                        try: os.killpg(process.pid, signal.SIGKILL)
                                        except ProcessLookupError: pass
                                        process.wait(timeout=10)
                                case['tsControlAfter'] = sample_ts_control(session)
                        installed = private / (first_stop + '-installed.apk')
                        installed_evidence = installed_apk_evidence(device, args.qa_bundle, installed, dual_overlay_apk.verify)
                        case['installedApkSha256'] = installed_evidence['apkSha256']
                        case['stage'] = 'host_cleanup'
                    cleanup = session.report.get('cleanup', {})
                    if not cleanup or any(value is not True for value in cleanup.values()):
                        raise DualOverlayDeviceFailure('host_cleanup_incomplete')
                    case['hostCleanup'] = True
                case['status'] = 'passed'; case['stage'] = 'complete'
            except Exception as error:
                case['errorCode'] = str(error) if isinstance(error, DualOverlayDeviceFailure) else 'device_runner_failed'
            finally:
                if session is not None:
                    session_report = getattr(session, 'report', {})
                    known_stages = {'device-and-bundle', 'namespace', 'host-controller',
                                    'host-only-ready', 'relay-and-reverse', 'host-relay-only-ready', 'ready'}
                    stage = session_report.get('stage')
                    case['sharedStage'] = stage if isinstance(stage, str) and stage in known_stages else 'unknown'
                    for key in ('deviceApi35Verified', 'hostReady'):
                        if type(session_report.get(key)) is bool: case[key] = session_report[key]
                    for key in ('relayRoles', 'reverseMappings'):
                        if type(session_report.get(key)) is int and 0 <= session_report[key] <= 3: case[key] = session_report[key]
                    relay_codes = {'owned_runner_required', 'private_manifest_path_required', 'private_manifest_permissions_required',
                        'private_manifest_invalid', 'owned_namespace_required', 'owned_ports_required', 'owned_processes_required',
                        'namespace_check_failed', 'owned_namespace_missing', 'listener_check_failed', 'owned_listener_required',
                        'relay_already_started', 'safe_listener_port_unavailable', 'relay_thread_cleanup_failed',
                        'listener_process_stat_failed', 'listener_process_uid_mismatch', 'listener_process_namespace_mismatch',
                        'listener_process_namespace_unreadable', 'controlled_relay_failed'}
                    relay_failure = session_report.get('relayFailure')
                    if isinstance(relay_failure, str) and relay_failure in relay_codes: case['relayFailure'] = relay_failure
                    cleanup_report = session_report.get('cleanup', {})
                    case['sharedCleanup'] = {key: value for key, value in cleanup_report.items()
                        if key in {'reverseRemoved', 'relayStopped', 'controllerStopped', 'namespaceRemoved',
                                   'hostPrivateDirectoryRemoved', 'controlReaderStopped', 'privateFilesRemoved'}
                        and type(value) is bool}
                    case['hostCleanup'] = bool(cleanup_report) and all(value is True for value in cleanup_report.values())
                    if not case['hostCleanup']:
                        case['status'] = 'failed'; case['errorCode'] = 'host_cleanup_incomplete'
                if process is not None and process.poll() is None:
                    try: os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=10)
                    except (OSError, subprocess.TimeoutExpired): pass
                try:
                    if device.package_present():
                        device.adb('shell', 'am', 'force-stop', device.PACKAGE)
                        device.adb('uninstall', device.PACKAGE)
                    case['packageRemoved'] = not device.package_present()
                    for line in device.forward_set() - before_forwards:
                        parts = line.split()
                        if len(parts) == 3 and parts[0] == 'emulator-5554' and re.fullmatch(r'tcp:\d+', parts[1]):
                            device.adb('forward', '--remove', parts[1])
                    case['forwardsRestored'] = device.forward_set() == before_forwards
                except Exception:
                    case['packageRemoved'] = False; case['forwardsRestored'] = False
                if not case.get('packageRemoved') or not case.get('forwardsRestored'):
                    case['status'] = 'failed'; case['errorCode'] = 'device_cleanup_incomplete'
    if all(case['status'] == 'passed' for case in report['cases']) and len(report['cases']) == 2:
        report['status'] = 'passed'
    (output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    import argparse
    import json
    import os
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'qa-bundle', 'host-bundle', 'host-checkout', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--host-source', required=True)
    parser.add_argument('--native-source', required=True)
    args = parser.parse_args()
    try:
        if args.native_source != 'a9be92d98b8c26b15ccbc7f6faa240ed3d674929':
            raise DualOverlayDeviceFailure('native_source_invalid')
        if args.host_source != '5404adfb3c86f5174edda38f1d0c63c8d81996c5':
            raise DualOverlayDeviceFailure('host_source_invalid')
        result = run_device(args, os.environ)
    except Exception as error:
        code = str(error) if isinstance(error, DualOverlayDeviceFailure) else 'device_precondition_failed'
        safe = {'schemaVersion': 1, 'kind': 'flutter-android-dual-overlay',
                'status': 'failed', 'errorCode': code}
        try:
            base = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
            target = args.output.resolve()
            if target != base and target.is_relative_to(base) and not args.output.is_symlink():
                target.mkdir(mode=0o700, exist_ok=True)
                manifest = target / 'manifest.json'
                if not manifest.exists() and not manifest.is_symlink():
                    manifest.write_text(json.dumps(safe, indent=2) + '\n')
        except (KeyError, OSError):
            pass
        print(json.dumps(safe))
        return 1
    print(json.dumps({'status': result['status']}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
