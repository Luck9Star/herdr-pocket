#!/usr/bin/env python3
"""Private control and independent host-audit checks for Flutter device QA.

The caller supplies only an owned helper process and synthetic expected input.
No request, authorization URL, or raw bytes are written to public evidence.
"""
import errno
import re
import subprocess
import shlex


class DualOverlayDeviceFailure(RuntimeError):
    pass


class PrivateExchangeReadFailure(DualOverlayDeviceFailure):
    def __init__(self, entry, reason):
        super().__init__('private_exchange_read_failed')
        self.diagnostic = {'entry': entry, 'reason': reason}


NATIVE_SOURCE_SHA='547106ea172dfd055c3bf9fdb2f4e2a27c9ff2f8'
HOST_SOURCE_SHA='5404adfb3c86f5174edda38f1d0c63c8d81996c5'


def validate_source_pins(native_source,host_source):
    """Offline admission only: exactly the reviewed native and host commits."""
    if native_source!=NATIVE_SOURCE_SHA:raise DualOverlayDeviceFailure('native_source_invalid')
    if host_source!=HOST_SOURCE_SHA:raise DualOverlayDeviceFailure('host_source_invalid')


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


def stopped_session_pending(result, baseline, expected_length, *, already_closed=False):
    """Allow only the original session to remain active; all other drift fails."""
    try:
        audit_unchanged_session(result, baseline, expected_length, active=False)
        return False
    except DualOverlayDeviceFailure:
        audit_unchanged_session(result, baseline, expected_length, active=True)
        if already_closed:
            raise DualOverlayDeviceFailure('host_audit_session_changed')
        return True


def wait_for_stopped_with_survivor(audit, baselines, first_stop, progress, *, timeout=10.0,
                                   interval=0.25, monotonic=None, sleep=None):
    """First retain proof of the survivor input, then wait only for original closure."""
    import time
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    if set(baselines) != {'et', 'ts'} or first_stop not in ('et', 'ts') or timeout <= 0 or interval <= 0:
        raise DualOverlayDeviceFailure('host_audit_baseline_missing')
    survivor = 'ts' if first_stop == 'et' else 'et'
    single = {'et': b'E', 'ts': b'T'}
    second = {'et': b'Ee', 'ts': b'Tt'}
    # Save this separately even if the other side later times out.
    audit_unchanged_session(audit(survivor, second[survivor]), baselines[survivor], 2, active=True)
    progress['survivorSecondInputConfirmed'] = True
    deadline = monotonic() + timeout
    while True:
        pending = stopped_session_pending(audit(first_stop, single[first_stop]), baselines[first_stop], 1,
                                          already_closed=progress.get('stoppedCloseConfirmed') is True)
        if not pending:
            progress['stoppedCloseConfirmed'] = True
        # Never infer the survivor stayed live while waiting.
        audit_unchanged_session(audit(survivor, second[survivor]), baselines[survivor], 2, active=True)
        if not pending:
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise DualOverlayDeviceFailure('host_audit_close_timeout')
        sleep(min(interval, remaining))


def wait_for_both_stopped(audit, baselines, first_stop, *, timeout=10.0, interval=0.25,
                          monotonic=None, sleep=None, initially_closed=()):
    """Read-only wait for original sessions to close; all other drift fails immediately."""
    import time
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    if set(baselines) != {'et', 'ts'} or first_stop not in ('et', 'ts') or timeout <= 0 or interval <= 0:
        raise DualOverlayDeviceFailure('host_audit_baseline_missing')
    survivor = 'ts' if first_stop == 'et' else 'et'
    deadline = monotonic() + timeout
    previously_closed = set(initially_closed)
    while True:
        pending = set()
        for role in ('et', 'ts'):
            expected = (b'E' if role == 'et' else b'T')
            if role == survivor:
                expected += b'e' if role == 'et' else b't'
            result = audit(role, expected)
            try:
                audit_unchanged_session(result, baselines[role], len(expected), active=False)
                previously_closed.add(role)
            except DualOverlayDeviceFailure:
                # Only the original session remaining active is a waitable state.
                # Every count, identity, byte or other active session still fails.
                audit_unchanged_session(result, baselines[role], len(expected), active=True)
                if role in previously_closed:
                    raise DualOverlayDeviceFailure('host_audit_session_changed')
                pending.add(role)
        if not pending:
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise DualOverlayDeviceFailure('host_audit_close_timeout')
        sleep(min(interval, remaining))


SHARED_SCENARIO = 'shared-easytier'
SHARED_CHECKPOINTS = ('et_pair_review', 'ts_pair_review', 'shared_ready', 'shared_a_released',
                      'shared_b_released', 'shared_node_stopped')
SHARED_UI_RESULT = {'status': 'passed', 'scenario': SHARED_SCENARIO, 'sameReviewedBinding': True,
    'bothInitialFrames': True, 'survivorAdvancedOnOriginalView': True, 'noAutomaticInput': True,
    'bothTabsClosedBeforeNodeStop': True, 'nodeExplicitlyStopped': True}
PEER_CLOSE_KINDS = ('unconfirmed', 'peer_eof', 'client_disconnect', 'peer_reset')


def require_shared_host_closed(audit, baselines, closed, *, timeout=10.0, interval=0.25,
                               monotonic=None, sleep=None):
    import time
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    deadline = monotonic() + timeout
    while True:
        resolved = True
        for role in ('et', 'ts'):
            result = audit(role, b'')
            expected_close = role in closed
            pending = stopped_session_pending(result, baselines[role], 0) if expected_close else False
            if not expected_close:
                audit_unchanged_session(result, baselines[role], 0)
            kind = result['sessions'][0].get('peerClose')
            if kind not in PEER_CLOSE_KINDS:
                raise DualOverlayDeviceFailure('shared_peer_close_evidence_invalid')
            if expected_close and kind == 'peer_reset':
                raise DualOverlayDeviceFailure('shared_peer_closed_by_reset')
            if expected_close and (pending or kind not in ('peer_eof', 'client_disconnect')):
                resolved = False
            if not expected_close and kind != 'unconfirmed':
                raise DualOverlayDeviceFailure('shared_survivor_closed')
        if resolved:
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise DualOverlayDeviceFailure('shared_peer_close_unconfirmed')
        sleep(min(interval, remaining))


def shared_relay_state(relay, ensure_app_running, *, active, timeout=10.0, monotonic=None, sleep=None):
    import time
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    deadline = monotonic() + timeout
    while True:
        ensure_app_running()
        counts = relay.active_connections()
        if set(counts) != {'easytier', 'easytierSecond'} or any(
                type(count) is not int or not 0 <= count <= 16 for count in counts.values()):
            raise DualOverlayDeviceFailure('shared_relay_evidence_invalid')
        if all((count > 0) == active for count in counts.values()):
            ensure_app_running()
            return {'a': counts['easytier'], 'b': counts['easytierSecond']}
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise DualOverlayDeviceFailure('shared_relay_live_missing' if active else 'shared_relay_close_unconfirmed')
        sleep(min(0.25, remaining))


def shared_checkpoint(stage, audit, baselines, progress):
    if stage == 'shared_ready':
        for role in ('et', 'ts'):
            baselines[role] = audit_baseline(audit(role, b''), 0)
            if baselines[role] != (1, 1):
                raise DualOverlayDeviceFailure('shared_original_ssh_not_unique')
        progress['bothOriginalSshLive'] = True
    elif stage == 'shared_a_released':
        if set(baselines) != {'et', 'ts'}:
            raise DualOverlayDeviceFailure('host_audit_baseline_missing')
        audit_unchanged_session(audit('ts', b''), baselines['ts'], 0)
        progress['survivorFreshFrameOnOriginalSsh'] = True
        require_shared_host_closed(audit, baselines, {'et'})
        progress['aCloseBeforeBStop'] = True
    else:
        require_shared_host_closed(audit, baselines, {'et', 'ts'},
                                   timeout=10.0 if stage == 'shared_b_released' else 0)
        if stage == 'shared_b_released':
            progress['bothClosedBeforeExplicitNodeStop'] = True
        elif stage == 'shared_node_stopped':
            progress['bothClosedAfterExplicitNodeStop'] = True


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
                            'ts-authorized.txt', 'et-audit.txt', 'ts-audit.txt', 'stopped-audit.txt', 'final-audit.txt', 'both-stopped-audit.txt',
                            'shared-ready.txt', 'shared-a-released.txt', 'shared-b-released.txt', 'shared-node-stopped.txt'})


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
    # Shell v2 carries the remote exit status; exec-out's raw service does not.
    # The allowlisted name is the only variable interpolated into this script.
    directory = 'files/dual-overlay-exchange'
    path = directory + '/' + name
    script = (f'if [ ! -d {directory} ] || [ ! -r {directory} ] || '
              f'[ ! -x {directory} ]; then exit 73; fi; '
              f'if [ -e {path} ]; then printf "PRESENT\\n"; cat {path} || exit 74; '
              'else printf "MISSING\\n"; fi')
    command = [str(adb), '-s', serial, 'shell', '-T', 'run-as',
               'dev.herdr.herdr_flutter_probe', 'sh', '-c', shlex.quote(script)]
    try:
        result = run(command, stdout=-1, stderr=-1, timeout=20, check=False)
    except OSError:
        raise PrivateExchangeReadFailure(name, 'adb_unavailable') from None
    except subprocess.TimeoutExpired:
        raise PrivateExchangeReadFailure(name, 'adb_timeout') from None
    if not isinstance(result.stdout, bytes) or len(result.stdout) > 65544:
        raise PrivateExchangeReadFailure(name, 'output_invalid')
    if result.returncode:
        from flutter_android_gui import ADB_TRANSIENT_STDERR
        stderr = getattr(result, 'stderr', b'').strip()
        reason = 'command_failed'
        if not result.stdout:
            if stderr in {line.encode() for line in ADB_TRANSIENT_STDERR}:
                reason = stderr.removeprefix(b'error: ').replace(b' ', b'_').decode('ascii')
            elif stderr == b'run-as: unknown package: dev.herdr.herdr_flutter_probe':
                reason = 'package_missing'
            elif result.returncode == 73 and not stderr:
                reason = 'directory_unavailable'
        elif result.returncode == 74 and result.stdout.startswith(b'PRESENT\n'):
            reason = 'file_unreadable'
        raise PrivateExchangeReadFailure(name, reason)
    if result.stdout == b'MISSING\n':
        return None
    if result.stdout.startswith(b'PRESENT\n'):
        return result.stdout[len(b'PRESENT\n'):]
    raise PrivateExchangeReadFailure(name, 'output_invalid')



def handle_stage(stage, *, session, adb, serial, run, first_stop, baselines, audit_records=None, audit_progress=None, shared=False, ensure_app_running=None):
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
        if ensure_app_running is not None:
            ensure_app_running()
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
                           or (shared and item.get('peerClose') not in PEER_CLOSE_KINDS)
                           for item in sessions)):
                raise DualOverlayDeviceFailure('host_audit_role_invalid')
            audit_records.append({'checkpoint': stage, 'role': ({'et': 'a', 'ts': 'b'}[role] if shared else role),
                'acceptedSessions': event.get('acceptedSessions'), 'newSessions': event.get('newSessions'),
                'capturedBytes': event.get('capturedBytes'), 'newInputBytes': event.get('newInputBytes'),
                'exactBytes': event.get('exactBytes'), 'authorizationActive': event.get('authorizationActive'),
                'sessions': [{key: item.get(key) for key in
                              ('ordinal', 'approvedDevice', 'active', 'peerClose') if shared or key != 'peerClose'}
                             for item in sessions]})
        if ensure_app_running is not None:
            ensure_app_running()
        return event

    if shared and stage in SHARED_CHECKPOINTS[2:]:
        progress = audit_progress if audit_progress is not None else {}
        shared_checkpoint(stage, audit, baselines, progress)
        if stage == 'shared_ready':
            progress['liveProviderRelays'] = shared_relay_state(session.relay, ensure_app_running, active=True)
        elif stage == 'shared_node_stopped':
            progress['providerRelaysAfterNodeStop'] = shared_relay_state(session.relay, ensure_app_running, active=False)
        write_exchange(adb, serial, stage.replace('_', '-') + '.txt', b'accepted', run=run)
        return True

    if stage in ('et_baseline', 'ts_baseline'):
        role = stage[:2]
        expected = b'E' if role == 'et' else b'T'
        baselines[role] = audit_baseline(audit(role, expected), len(expected))
        write_exchange(adb, serial, role + '-audit.txt', b'accepted', run=run)
        return True
    if audit_progress is None:
        audit_progress = {}
    if stage == 'both_stopped_audit':
        wait_for_both_stopped(audit, baselines, first_stop, initially_closed=(first_stop,) if audit_progress.get('stoppedCloseConfirmed') is True else ())
        write_exchange(adb, serial, 'both-stopped-audit.txt', b'accepted', run=run)
        return True
    if stage == 'stopped_audit':
        if set(baselines) != {'et', 'ts'} or first_stop not in ('et', 'ts'):
            raise DualOverlayDeviceFailure('host_audit_baseline_missing')
        survivor = 'ts' if first_stop == 'et' else 'et'
        single = {'et': b'E', 'ts': b'T'}
        # This token only permits the survivor-input test; it does not certify closure.
        pending = stopped_session_pending(audit(first_stop, single[first_stop]), baselines[first_stop], 1,
                                          already_closed=audit_progress.get('stoppedCloseConfirmed') is True)
        audit_unchanged_session(audit(survivor, single[survivor]), baselines[survivor], 1, active=True)
        audit_progress['interimClosePending'] = pending
        audit_progress['stoppedCloseConfirmed'] = not pending
        write_exchange(adb, serial, 'stopped-audit.txt', b'accepted', run=run)
        return True
    if stage == 'final_audit':
        wait_for_stopped_with_survivor(audit, baselines, first_stop, audit_progress)
        write_exchange(adb, serial, 'final-audit.txt', b'accepted', run=run)
        return True
    return False


UI_STAGES = frozenset({'host_board', 'et_network_create', 'ts_network_create', 'ts_login_open',
    'ts_wait_authorization', 'et_pair_profile', 'ts_pair_profile', 'et_pair_review', 'ts_pair_review',
    'et_remote_review', 'ts_remote_review', 'et_remote_connect', 'ts_remote_connect',
    'et_remote_pane', 'ts_remote_pane', 'et_remote_first_frame', 'ts_remote_first_frame',
    'et_remote_marker', 'ts_remote_marker', 'et_remote_tab', 'ts_remote_tab',
    'et_open_host', 'ts_open_host', 'et_input', 'ts_input', 'et_baseline', 'ts_baseline',
    'et_resume', 'ts_resume', 'et_stop_network', 'ts_stop_network', 'stopped_audit', 'final_audit', 'both_stopped_audit',
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
    'et_node_wait', 'ts_node_wait', 'ts_node_ready_refresh', *SHARED_CHECKPOINTS, 'shared_close_a', 'shared_close_b'})


def safe_ui_failure(raw):
    import json
    try:
        detail = json.loads(raw)
        basic = {'stage', 'kind'}
        diagnostic = {'nodeState', 'statusPresent', 'editPresent', 'editEnabled', 'addPresent', 'addEnabled', 'notice'}
        optional = {'responseReceived', 'stackFrames', 'responseCheck', 'bindingCheck', 'bindingSelectionMatches', 'remoteCheck'}
        if (isinstance(detail, dict) and set(detail) - optional in (basic, basic | diagnostic)
                and isinstance(detail['stage'], str) and detail['stage'] in UI_STAGES
                and isinstance(detail['kind'], str)
                and detail['kind'] in {'test_failure', 'flutter_error', 'state_error', 'assertion_error', 'other'}):
            if 'responseReceived' in detail and type(detail['responseReceived']) is not bool:
                return None
            if 'remoteCheck' in detail:
                remote = detail['remoteCheck']
                bools = {'pagePresent', 'reviewPresent', 'reviewChecked', 'connectPresent', 'connectEnabled', 'busy', 'live', 'dashboardPresent', 'snapshotReceived',
                         'boardSelectable', 'paneEnabled', 'paneHit', 'selectionAttempted', 'selected',
                         'selectedMatches', 'terminalPresent', 'sequencePresent', 'markerObserved'}
                phases = {'network', 'hostKey', 'authentication', 'dashboard', 'firstFrame'}
                if (not isinstance(remote, dict) or set(remote) != bools | phases | {'paneCount', 'paneControlCount', 'statusClass', 'adapterPhase', 'adapterError', 'adapterKind', 'channelOpenCode'}
                        or any(type(remote[key]) is not bool for key in bools)
                        or any(type(remote[key]) is not int or not 0 <= remote[key] <= 64 for key in ('paneCount', 'paneControlCount'))
                        or any(remote[key] not in {'waiting', 'active', 'passed', 'failed', 'unknown'} for key in phases)
                        or remote['adapterPhase'] not in {'unavailable', 'before_auth', 'authenticated', 'snapshot_forward_open',
                            'snapshot_write', 'snapshot_read', 'snapshot_decode', 'snapshot_retire', 'capabilities_forward_open',
                            'capabilities_read', 'capabilities_decode', 'dashboard_ready'}
                        or remote['adapterKind'] not in {'none', 'ssh_channel_open', 'ssh_socket', 'timeout', 'remote_failure', 'state_error', 'format_error', 'other'}
                        or remote['adapterError'] not in {'none', 'other', 'host_key_mismatch', 'authentication_failed', 'authentication_aborted', 'timeout',
                            'connection_failed', 'snapshot_rejected', 'session_mismatch', 'pane_missing', 'invalid_response', 'invalid_snapshot',
                            'truncated_response', 'output_limit', 'channel_cleanup_timeout', 'channel_capacity', 'channel_identity',
                            'invalid_terminal_id', 'unsupported_protocol', 'network_binding_changed', 'snapshot_forward_denied'}
                        or type(remote['channelOpenCode']) is not int or not 0 <= remote['channelOpenCode'] <= 4
                        or remote['statusClass'] not in {'unavailable', 'provider_unavailable', 'network_node_not_started',
                            'network_identity_unavailable', 'network_runtime_unavailable', 'network_binding_changed',
                            'device_key_unavailable', 'host_key_mismatch', 'authentication_failed', 'session_or_target_mismatch', 'snapshot_forward_denied',
                            'timeout', 'connection_failed', 'connecting', 'empty', 'other'}):
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
                core = {'inputMatches', 'fieldPresent', 'pagePresent', 'foreground', 'category', 'futureSeconds'}
                controls = {'recheckPresent', 'recheckEnabled', 'previewPresent', 'sourceChecked'}
                if (not isinstance(check, dict) or set(check) not in (core, core | controls)
                        or any(type(check[k]) is not bool for k in set(check) - {'category', 'futureSeconds'})
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


def drive_checkpoints(session, process, adb, serial, first_stop, *, run, timeout=900, report_stage=None, report_failure=None, audit_records=None, audit_progress=None, shared=False):
    """Drive bounded, ordered UI checkpoints; the host facts gate each reply."""
    import json
    import time

    if first_stop not in (('',) if shared else ('et', 'ts')) or timeout <= 0 or timeout > 1200:
        raise DualOverlayDeviceFailure('device_run_invalid')
    checkpoints = ('ts_wait_authorization', 'et_pair_review', 'ts_pair_review',
                   'et_baseline', 'ts_baseline', 'stopped_audit', 'final_audit', 'both_stopped_audit')
    if shared:
        checkpoints = SHARED_CHECKPOINTS

    def require_running():
        if process.poll() is not None:
            raise DualOverlayDeviceFailure('shared_device_exited_during_host_audit')

    deadline = time.monotonic() + timeout
    index = 0
    baselines = {}
    exit_seen = False
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
                                first_stop=first_stop, baselines=baselines, audit_records=audit_records, audit_progress=audit_progress,
                                shared=shared, ensure_app_running=require_running if shared else None):
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
                if shared:
                    expected = SHARED_UI_RESULT
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
            # A result may be atomically published between the read and exit.
            if index == len(checkpoints) and not exit_seen:
                exit_seen = True
                continue
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


def sample_failed_host_audits(session):
    """Read bounded host counters only after UI failure, before session teardown."""
    result = {}
    for role in ('et', 'ts'):
        try:
            event = session.control.call({'op': 'audit', 'role': role, 'expectedBase64': ''})
            keys = ('acceptedSessions', 'newSessions', 'capturedBytes', 'newInputBytes')
            sessions = event.get('sessions')
            if (event.get('event') != 'host_audit' or event.get('role') != role
                    or any(type(event.get(key)) is not int or not 0 <= event[key] <= 1000000 for key in keys)
                    or not isinstance(sessions, list) or len(sessions) > 64
                    or any(not isinstance(item, dict) or type(item.get('active')) is not bool
                           or type(item.get('approvedDevice')) is not bool for item in sessions)):
                raise ValueError('invalid host audit')
            result[role] = {'available': True, **{key: event[key] for key in keys},
                            'activeSessions': sum(item['active'] for item in sessions),
                            'approvedSessions': sum(item['approvedDevice'] for item in sessions)}
        except Exception:
            result[role] = {'available': False}
    return result


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


def flutter_process_state(process):
    if process is None:
        return 'not_started'
    code = process.poll()
    return ('running' if code is None else 'success' if code == 0 else 'signal' if code < 0 else 'nonzero')


def stop_flutter_process(process):
    import os
    import signal

    if process is None or process.poll() is not None:
        return True
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except OSError:
            return False
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            continue
        except OSError:
            return False
        return True
    return process.poll() is not None


def classify_apk_build_failure(log):
    """Classify known markers in the last build attempt without exporting log text."""
    limit = 256 * 1024
    try:
        start = max(0, log.seek(0, 2) - limit)
        log.seek(start)
        tail = log.read(limit)
    except OSError:
        return 'unknown'
    tail = re.sub(rb'\x1b\[[0-9;]*m', b'', tail).replace(b'\r', b'\n')
    if start:
        tail = tail.partition(b'\n')[2]
    # Flutter can retry Gradle. A previous attempt is not evidence about the final failure.
    tail = re.split(rb'^Retrying Gradle Build: #[0-9]+, wait time: [0-9]+ms$', tail, flags=re.M)[-1]
    causes = {
        'disk_space': rb'(?:^|: )(?:No space left on device|Disk quota exceeded)(?:[ \t]*$|, errno = \d+|\))',
        'dependency_download': rb"^[ \t>]*Could not (?:GET|HEAD|get resource) ['\"]?https?://|"
                               rb'^[ \t>]*Could not download \S',
        'android_sdk': rb'No Android SDK found\.|SDK location not found\.|'
                       rb'You have not accepted the license agreements of the following SDK components|'
                       rb'Failed to (?:find|install) the following Android SDK packages',
        'jdk': rb'Android Gradle plugin requires Java \d+(?:\.\d+)? to run|'
               rb'Unsupported class file major version \d+|Could not create the Java Virtual Machine\.',
    }
    failed_steps = {
        'gradle': rb'Gradle build daemon disappeared unexpectedly|Minimum supported Gradle version is \d',
        'dart_compile': rb'^[^\n]+\.dart:\d+:\d+: Error:|^Target kernel_snapshot_program failed:',
        'native_packaging': rb"Execution failed for task ':app:(?:mergeDebugNativeLibs|stripDebugDebugSymbols)'\.",
        'apk_packaging': rb"Execution failed for task ':app:packageDebug'\.|Gradle build failed to produce an \.apk file\.",
    }
    for patterns in (causes, failed_steps):
        matched = [category for category, pattern in patterns.items() if re.search(pattern, tail, re.M)]
        if matched:
            return matched[0] if len(matched) == 1 else 'unknown'
    return 'unknown'


def run_device(args, env):
    """Run the explicitly selected fresh owned-device cases."""
    import json
    from pathlib import Path
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
    shared = getattr(args, 'scenario', 'dual-providers') == SHARED_SCENARIO
    if shared:
        report['scenario'] = SHARED_SCENARIO
        report['sharedTargets'] = {'a': 'easytier', 'b': 'easytier'}
    case_names = (SHARED_SCENARIO,) if shared else ('et', 'ts')
    before_forwards = device.forward_set()
    with tempfile.TemporaryDirectory(prefix='flutter-dual-private-', dir=env['RUNNER_TEMP']) as private:
        private = Path(private)
        for case_name in case_names:
            first_stop = '' if shared else case_name
            case = {'status': 'failed', 'stage': 'build'}
            case.update({'scenario': SHARED_SCENARIO} if shared else {'firstStop': first_stop})
            report['cases'].append(case)
            process = None
            session = None
            session_cleanup_failed = False
            try:
                flags = ['--dart-define=HERDR_ANDROID_DUAL_OVERLAY=true',
                         '--dart-define=HERDR_ANDROID_DUAL_RUN_ID=' + env['GITHUB_RUN_ID'],
                         ('--dart-define=HERDR_ANDROID_SHARED_EASYTIER=true' if shared else
                          '--dart-define=HERDR_ANDROID_DUAL_FIRST_STOP=' + first_stop)]
                try:
                    with (private / (case_name + '-build.log')).open('w+b') as log:
                        command = ['flutter', 'build', 'apk', '--debug', '--target-platform', 'android-x64',
                                   '-t', 'integration_test/android_dual_overlay_test.dart', *flags]
                        result = subprocess.run(command, cwd=app, stdout=log, stderr=subprocess.STDOUT,
                                                timeout=600, check=False)
                        if result.returncode != 0:
                            case['apkBuildFailure'] = classify_apk_build_failure(log)
                            raise DualOverlayDeviceFailure('device_apk_build_failed')
                except subprocess.TimeoutExpired:
                    case['apkBuildFailure'] = 'timeout'
                    raise
                except OSError as error:
                    case['apkBuildFailure'] = 'disk_space' if error.errno in (errno.ENOSPC, errno.EDQUOT) else 'unknown'
                    raise
                built = app / 'build/app/outputs/flutter-apk/app-debug.apk'
                case['stage'] = 'apk_verification'
                apk_evidence = dual_overlay_apk.verify(args.qa_bundle, built)
                case['instrumentationApkSha256'] = apk_evidence['apkSha256']
                case['stage'] = 'install'
                device.adb('install', '-r', str(built))
                with tempfile.TemporaryDirectory(prefix=case_name + '-', dir=private) as work:
                    case['stage'] = 'host_start'
                    session = AndroidDualOverlaySession(args.host_bundle, work, host_source=args.host_source,
                        source_checkout=args.host_checkout, device='emulator-5554', lifetime=900, shared_easytier=shared)
                    with session:
                        case['stage'] = 'private_setup'
                        if not shared:
                            case['tsControlBefore'] = sample_ts_control(session)
                            prepare_private_ca('adb', 'emulator-5554', session.read_ca(), run=subprocess.run)
                        material = session.materials
                        network = material['etNetwork']
                        config = {'runId': env['GITHUB_RUN_ID'],
                                  'etProfile': json.dumps(session.read_host_profile('et')),
                                  'tsProfile': json.dumps(session.read_host_profile('ts')),
                                  'networkName': network['networkName'],
                                  'networkSecret': network['networkSecret'], 'peerUrl': network['peerUrl']}
                        config.update({'scenario': SHARED_SCENARIO} if shared else
                                      {'firstStop': first_stop, 'controlUrl': material['controlUrl']})
                        write_exchange('adb', 'emulator-5554', 'config.json', json.dumps(config).encode(), run=subprocess.run)
                        case['stage'] = 'device_ui'
                        case['hostAudits'] = []
                        case['auditProgress'] = {} if shared else {'interimClosePending': None, 'stoppedCloseConfirmed': None,
                                                 'survivorSecondInputConfirmed': None}
                        with (private / (case_name + '-flutter.log')).open('wb') as log:
                            try:
                                process = subprocess.Popen(['flutter', 'test', '--no-pub', '--no-uninstall',
                                    '--reporter', 'expanded', '-d', 'emulator-5554',
                                    'integration_test/android_dual_overlay_test.dart', *flags], cwd=app,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                                case['ui'] = drive_checkpoints(session, process, 'adb', 'emulator-5554',
                                                               first_stop, run=subprocess.run,
                                                               report_stage=lambda stage: case.update(uiStage=stage),
                                                               report_failure=lambda failure: case.update(uiFailure=failure),
                                                               audit_records=case['hostAudits'],
                                                               audit_progress=case['auditProgress'], shared=shared)
                            except Exception as error:
                                case['flutterAtUiFailure'] = flutter_process_state(process)
                                if isinstance(error, PrivateExchangeReadFailure):
                                    case['exchangeFailure'] = error.diagnostic
                                hosts = sample_failed_host_audits(session)
                                case['failureHostAudits'] = ({'a': hosts['et'], 'b': hosts['ts']} if shared else hosts)
                                raise
                            finally:
                                case['flutterStopped'] = stop_flutter_process(process)
                                if not shared:
                                    case['tsControlAfter'] = sample_ts_control(session)
                        case['stage'] = 'installed_apk'
                        installed = private / (case_name + '-installed.apk')
                        installed_evidence = installed_apk_evidence(device, args.qa_bundle, installed, dual_overlay_apk.verify)
                        case['installedApkSha256'] = installed_evidence['apkSha256']
                        case['stage'] = 'host_cleanup'
                    cleanup = session.report.get('cleanup', {})
                    if not cleanup or any(value is not True for value in cleanup.values()):
                        raise DualOverlayDeviceFailure('host_cleanup_incomplete')
                    case['hostCleanup'] = True
                    if shared:
                        case['stage'] = 'host_verification'
                        peer_counts = {'acceptedOverlayStreams': 1, 'loopbackTcpConnections': 1}
                        if session.report.get('sharedPeerStreams') != {'a': peer_counts, 'b': peer_counts}:
                            raise DualOverlayDeviceFailure('shared_fixture_peer_dial_count_mismatch')
                case.update(status='passed', stage='device_cleanup')
            except Exception as error:
                session_cleanup_failed = (getattr(error, 'cleanup_code', None) == 'shared_overlay_session_cleanup_incomplete'
                                          or case['stage'] == 'host_cleanup')
                if isinstance(error, DualOverlayDeviceFailure):
                    case['errorCode'] = str(error)
                else:
                    case['errorCode'] = ('host_cleanup_incomplete' if case['stage'] == 'host_cleanup'
                                         else 'device_runner_failed')
            finally:
                cleanup_errors = []
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
                    if shared and 'sharedPeerStreams' in session_report:
                        case['sharedPeerStreams'] = session_report['sharedPeerStreams']
                    if 'reverseCleanup' in session_report:
                        case['reverseCleanup'] = session_report['reverseCleanup']
                    cleanup_report = session_report.get('cleanup', {})
                    case['sharedCleanup'] = {key: value for key, value in cleanup_report.items()
                        if key in {'reverseRemoved', 'relayStopped', 'controllerStopped', 'namespaceRemoved',
                                   'hostPrivateDirectoryRemoved', 'controlReaderStopped', 'privateFilesRemoved'}
                        and type(value) is bool}
                    case['hostCleanup'] = (not session_cleanup_failed and bool(cleanup_report)
                                           and all(value is True for value in cleanup_report.values()))
                    if not case['hostCleanup']:
                        cleanup_errors.append('host_cleanup_incomplete')
                if case.get('flutterStopped') is False:
                    cleanup_errors.append('flutter_cleanup_incomplete')
                try:
                    if device.package_present():
                        device.adb('shell', 'am', 'force-stop', device.PACKAGE)
                        device.adb('uninstall', device.PACKAGE)
                    case['packageRemoved'] = not device.package_present()
                except Exception:
                    case['packageRemoved'] = False
                try:
                    for line in device.forward_set() - before_forwards:
                        parts = line.split()
                        if len(parts) == 3 and parts[0] == 'emulator-5554' and re.fullmatch(r'tcp:\d+', parts[1]):
                            device.adb('forward', '--remove', parts[1])
                    case['forwardsRestored'] = device.forward_set() == before_forwards
                except Exception:
                    case['forwardsRestored'] = False
                if not case.get('packageRemoved') or not case.get('forwardsRestored'):
                    cleanup_errors.append('device_cleanup_incomplete')
                if cleanup_errors:
                    case['status'] = 'failed'
                    case.setdefault('errorCode', cleanup_errors[0])
                    case['cleanupErrorCodes'] = cleanup_errors
                elif case['status'] == 'passed':
                    case['stage'] = 'complete'
    if all(case['status'] == 'passed' for case in report['cases']) and len(report['cases']) == len(case_names):
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
    parser.add_argument('--scenario', choices=('dual-providers', SHARED_SCENARIO), default='dual-providers')
    args = parser.parse_args()
    try:
        validate_source_pins(args.native_source,args.host_source)
        result = run_device(args, os.environ)
    except Exception as error:
        code = str(error) if isinstance(error, DualOverlayDeviceFailure) else 'device_precondition_failed'
        safe = {'schemaVersion': 1, 'kind': 'flutter-android-dual-overlay',
                'status': 'failed', 'errorCode': code}
        if args.scenario == SHARED_SCENARIO:
            safe['scenario'] = SHARED_SCENARIO
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
