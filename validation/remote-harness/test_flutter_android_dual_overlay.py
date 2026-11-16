import unittest
from unittest.mock import patch

from flutter_android_dual_overlay import (
    DualOverlayDeviceFailure, audit_baseline, audit_unchanged_session, prepare_private_ca, write_exchange, read_exchange, handle_stage, drive_checkpoints, installed_apk_evidence, safe_ui_failure, sample_ts_control, sample_failed_host_audits, wait_for_both_stopped, wait_for_stopped_with_survivor,
)


def evidence():
    return {'acceptedSessions': 2, 'newSessions': 0, 'capturedBytes': 4,
            'exactBytes': True, 'authorizationActive': True,
            'sessions': [{'ordinal': 1, 'approvedDevice': True, 'active': False},
                         {'ordinal': 2, 'approvedDevice': True, 'active': True}]}


class SessionAuditTest(unittest.TestCase):
    def test_previous_closed_session_is_allowed_and_active_ordinal_is_stable(self):
        result = evidence()
        baseline = audit_baseline(result, 4)
        self.assertEqual(baseline, (2, 2))
        audit_unchanged_session(result, baseline, 4)
        result['sessions'][1]['active'] = False
        audit_unchanged_session(result, baseline, 4, active=False)

    def test_reconnect_wrong_bytes_or_wrong_active_session_are_rejected(self):
        for changes in ({'newSessions': 1}, {'capturedBytes': 5}, {'exactBytes': False},
                        {'authorizationActive': False}, {'sessions': [None, None]},
                        {'acceptedSessions': 3, 'newSessions': 0}):
            with self.subTest(changes=changes):
                result = evidence()
                result.update(changes)
                with self.assertRaises(DualOverlayDeviceFailure):
                    audit_unchanged_session(result, (2, 2), 4)

    def test_baseline_requires_single_approved_active_session(self):
        result = evidence()
        result['sessions'][0]['active'] = True
        with self.assertRaises(DualOverlayDeviceFailure):
            audit_baseline(result, 4)
        result = evidence()
        result['sessions'][1]['approvedDevice'] = False
        with self.assertRaises(DualOverlayDeviceFailure):
            audit_baseline(result, 4)


class PrivateCATest(unittest.TestCase):
    def test_real_commands_write_readback_and_marker_in_private_directory(self):
        import subprocess
        import tempfile
        from pathlib import Path
        calls = []
        cert = b'-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----'
        with tempfile.TemporaryDirectory() as tmp:
            def run(command, **kwargs):
                calls.append((command, kwargs))
                self.assertEqual(command[:7], ['adb', '-s', 'emulator-5554', 'shell', '-T',
                                                'run-as', 'dev.herdr.herdr_flutter_probe'])
                return subprocess.run(command[7:], cwd=tmp, **kwargs)
            prepare_private_ca('adb', 'emulator-5554', cert, run=run)
            self.assertEqual(len(calls), 6)
            self.assertEqual(calls[1][1]['input'], cert)
            self.assertNotIn('fixture', repr([call[0] for call in calls]))
            self.assertEqual((Path(tmp) / 'files/dual-overlay-ca.pem').read_bytes(), cert)
            self.assertEqual((Path(tmp) / 'files/dual-overlay-ca.pem').stat().st_mode & 0o777, 0o600)
            self.assertEqual((Path(tmp) / 'files/enable-dual-overlay-private-ca').stat().st_mode & 0o777, 0o600)

    def test_invalid_or_failed_readback_never_creates_marker(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            return type('Result', (), {'returncode': 0, 'stdout': b'wrong'})()
        with self.assertRaises(DualOverlayDeviceFailure):
            prepare_private_ca('adb', 'emulator-5554', b'not a certificate', run=run)
        self.assertEqual(calls, [])
        with self.assertRaisesRegex(DualOverlayDeviceFailure, 'private_ca_readback_failed'):
            prepare_private_ca('adb', 'emulator-5554', b'-----BEGIN CERTIFICATE-----', run=run)
        self.assertEqual(len(calls), 4)
        self.assertFalse(any('enable-dual-overlay-private-ca' in repr(call) for call in calls))


class PrivateExchangeTest(unittest.TestCase):
    def test_only_allowlisted_file_names_and_atomic_private_payload(self):
        import subprocess
        import tempfile
        from pathlib import Path
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            def run(command, **kwargs):
                calls.append((command, kwargs))
                self.assertEqual(command[:7], ['adb', '-s', 'emulator-5554', 'shell', '-T',
                                                'run-as', 'dev.herdr.herdr_flutter_probe'])
                return subprocess.run(command[7:], cwd=tmp, **kwargs)
            write_exchange('adb', 'emulator-5554', 'config.json', b'test secret', run=run)
            self.assertEqual(calls[1][1]['input'], b'test secret')
            self.assertNotIn('test secret', repr([call[0] for call in calls]))
            file = Path(tmp) / 'files/dual-overlay-exchange/config.json'
            self.assertEqual(file.read_bytes(), b'test secret')
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertFalse(file.with_name('config.json.new').exists())
            with self.assertRaises(DualOverlayDeviceFailure):
                write_exchange('adb', 'emulator-5554', '../bad', b'', run=run)
            self.assertEqual(len(calls), 4)


class PrivateExchangeReadTest(unittest.TestCase):
    def test_atomic_read_distinguishes_missing_empty_and_failures(self):
        import subprocess
        import tempfile
        from pathlib import Path
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'files/dual-overlay-exchange'
            directory.mkdir(parents=True)
            def run(command, **kwargs):
                calls.append(command)
                self.assertEqual(command[:7], ['adb', '-s', 'emulator-5554', 'shell', '-T',
                                                'run-as', 'dev.herdr.herdr_flutter_probe'])
                self.assertEqual(command[7:9], ['sh', '-c'])
                return subprocess.run(['sh', '-c', ' '.join(command[7:])], cwd=tmp, **kwargs)
            self.assertIsNone(read_exchange('adb', 'emulator-5554', 'result.json', run=run))
            result = directory / 'result.json'
            result.write_bytes(b'')
            self.assertEqual(read_exchange('adb', 'emulator-5554', 'result.json', run=run), b'')
            result.write_bytes(b'private')
            self.assertEqual(read_exchange('adb', 'emulator-5554', 'result.json', run=run), b'private')
            self.assertNotIn('private', repr(calls))
            result.unlink()
            directory.rmdir()
            with self.assertRaisesRegex(DualOverlayDeviceFailure, 'private_exchange_read_failed'):
                read_exchange('adb', 'emulator-5554', 'result.json', run=run)
            with self.assertRaises(DualOverlayDeviceFailure):
                read_exchange('adb', 'emulator-5554', '../bad', run=run)
        for returncode, stdout in ((1, b'MISSING\n'), (0, b''), (0, b'cat: missing'),
                                   (0, b'PRESENT\n' + b'x' * 65537)):
            def bad_run(*args, **kwargs):
                return type('Result', (), {'returncode': returncode, 'stdout': stdout})()
            with self.assertRaisesRegex(DualOverlayDeviceFailure, 'private_exchange_read_failed'):
                read_exchange('adb', 'emulator-5554', 'result.json', run=bad_run)


class HostStageTest(unittest.TestCase):
    def test_pairing_approval_requires_matching_host_and_device_fingerprints(self):
        import base64
        import json
        from flutter_android_gui import public_host_fingerprint
        key = 'ssh-ed25519 ' + base64.b64encode(
            b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes(range(32))).decode()
        wire = json.dumps({'request_id': '1' * 32, 'public_key': key}).encode()
        class Control:
            def __init__(self): self.calls = []
            def call(self, request):
                self.calls.append(request['op'])
                if request['op'] == 'review_pairing':
                    return {'event': 'pairing_review', 'role': 'et', 'requestId': '1' * 32,
                            'hostFingerprint': public_host_fingerprint(key),
                            'deviceFingerprint': public_host_fingerprint(key)}
                return {'event': 'pairing_approved', 'role': 'et', 'response': '{}'}
        control = Control()
        session = type('Session', (), {'control': control,
            'read_host_profile': lambda self, role: {'expectedHostKey': key}})()
        with patch('flutter_android_dual_overlay.read_exchange', return_value=wire), \
             patch('flutter_android_dual_overlay.write_exchange') as write:
            self.assertTrue(handle_stage('et_pair_review', session=session, adb='adb',
                                        serial='emulator-5554', run=None, first_stop='et', baselines={}))
            self.assertEqual(control.calls, ['review_pairing', 'approve_pairing'])
            write.assert_called_once()
        control.calls.clear()
        other = 'ssh-ed25519 ' + base64.b64encode(
            b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes(reversed(range(32)))).decode()
        session.read_host_profile = lambda role: {'expectedHostKey': other}
        with patch('flutter_android_dual_overlay.read_exchange', return_value=wire), \
             patch('flutter_android_dual_overlay.write_exchange') as write:
            with self.assertRaisesRegex(DualOverlayDeviceFailure, 'pairing_review_mismatch'):
                handle_stage('et_pair_review', session=session, adb='adb',
                             serial='emulator-5554', run=None, first_stop='et', baselines={})
            self.assertNotIn('approve_pairing', control.calls)
            write.assert_not_called()

    def test_stopped_and_final_audits_require_exact_bytes_and_same_session(self):
        class Control:
            def __init__(self): self.calls = []
            def call(self, request):
                self.calls.append(request)
                role = request['role']
                result = evidence()
                result.update(event='host_audit', role=role, capturedBytes=1,
                              sessions=[{'ordinal': 1, 'approvedDevice': True, 'active': False},
                                        {'ordinal': 2, 'approvedDevice': True, 'active': role == 'ts'}])
                return result
        control = Control()
        session = type('Session', (), {'control': control})()
        baselines = {'et': (2, 2), 'ts': (2, 2)}
        with patch('flutter_android_dual_overlay.write_exchange') as write:
            self.assertTrue(handle_stage('stopped_audit', session=session, adb='adb',
                                        serial='emulator-5554', run=None, first_stop='et', baselines=baselines))
        self.assertEqual([event['role'] for event in control.calls], ['et', 'ts'])
        self.assertEqual(write.call_args.args[2:4], ('stopped-audit.txt', b'accepted'))
        baselines['ts'] = (1, 1)
        with patch('flutter_android_dual_overlay.write_exchange') as write:
            with self.assertRaises(DualOverlayDeviceFailure):
                handle_stage('stopped_audit', session=session, adb='adb',
                             serial='emulator-5554', run=None, first_stop='et', baselines=baselines)
            write.assert_not_called()


class InterimAndFinalAuditTests(unittest.TestCase):
    def test_pending_stop_permits_survivor_input_then_confirms_closure(self):
        for first in ('et', 'ts'):
            survivor = 'ts' if first == 'et' else 'et'
            class Control:
                def __init__(self): self.count = {'et': 0, 'ts': 0}; self.expected = []
                def call(self, request):
                    import base64
                    role = request['role']; self.count[role] += 1
                    expected = base64.b64decode(request['expectedBase64']); self.expected.append((role, expected))
                    value = evidence(); value.update(event='host_audit', role=role, capturedBytes=len(expected))
                    value['sessions'][1]['active'] = role == survivor or self.count[role] < 3
                    return value
            control = Control(); session = type('Session', (), {'control': control})()
            progress = {'interimClosePending': None, 'stoppedCloseConfirmed': None, 'survivorSecondInputConfirmed': None}
            baseline = {'et': (2, 2), 'ts': (2, 2)}
            with patch('flutter_android_dual_overlay.write_exchange') as write, patch('time.sleep'):
                self.assertTrue(handle_stage('stopped_audit', session=session, adb='adb', serial='emulator-5554',
                                            run=None, first_stop=first, baselines=baseline, audit_progress=progress))
                self.assertEqual(write.call_args.args[2:4], ('stopped-audit.txt', b'accepted'))
                self.assertEqual(progress, {'interimClosePending': True, 'stoppedCloseConfirmed': False,
                                            'survivorSecondInputConfirmed': None})
                self.assertTrue(handle_stage('final_audit', session=session, adb='adb', serial='emulator-5554',
                                            run=None, first_stop=first, baselines=baseline, audit_progress=progress))
                self.assertEqual(write.call_args.args[2:4], ('final-audit.txt', b'accepted'))
                self.assertEqual(progress, {'interimClosePending': True, 'stoppedCloseConfirmed': True,
                                            'survivorSecondInputConfirmed': True})
                self.assertIn((first, b'E' if first == 'et' else b'T'), control.expected)
                self.assertIn((survivor, b'Ee' if survivor == 'et' else b'Tt'), control.expected)

    def test_never_closed_preserves_input_evidence_but_fails(self):
        current = [0.0]
        progress = {'interimClosePending': True, 'stoppedCloseConfirmed': False, 'survivorSecondInputConfirmed': None}
        def audit(role, expected):
            value = evidence(); value['capturedBytes'] = len(expected)
            return value
        with self.assertRaisesRegex(DualOverlayDeviceFailure, 'host_audit_close_timeout'):
            wait_for_stopped_with_survivor(audit, {'et': (2, 2), 'ts': (2, 2)}, 'et', progress,
                timeout=.5, interval=.25, monotonic=lambda:current[0], sleep=lambda t:current.__setitem__(0,current[0]+t))
        self.assertTrue(progress['survivorSecondInputConfirmed'])
        self.assertFalse(progress['stoppedCloseConfirmed'])

    def test_drift_and_reactivation_never_receive_interim_or_final_token(self):
        for failure in ('reconnect', 'wrong_bytes', 'ordinal', 'reactivated'):
            progress = {'interimClosePending': False, 'stoppedCloseConfirmed': failure == 'reactivated',
                        'survivorSecondInputConfirmed': None}
            class Control:
                def call(self, request):
                    value = evidence(); value.update(event='host_audit', role=request['role'], capturedBytes=1)
                    if failure == 'reconnect': value['newSessions'] = 1
                    if failure == 'wrong_bytes': value['exactBytes'] = False
                    if failure == 'ordinal': value['sessions'][1]['ordinal'] = 3
                    return value
            session = type('Session', (), {'control': Control()})()
            with patch('flutter_android_dual_overlay.write_exchange') as write:
                with self.assertRaisesRegex(DualOverlayDeviceFailure, 'host_audit_session_changed'):
                    handle_stage('stopped_audit', session=session, adb='adb', serial='emulator-5554', run=None,
                                 first_stop='et', baselines={'et': (2, 2), 'ts': (2, 2)}, audit_progress=progress)
                write.assert_not_called()

    def test_final_audit_rejects_survivor_input_drift_before_claiming_proof(self):
        progress = {'interimClosePending': True, 'stoppedCloseConfirmed': False, 'survivorSecondInputConfirmed': None}
        def audit(role, expected):
            value = evidence(); value['capturedBytes'] = len(expected); value['exactBytes'] = False
            return value
        with self.assertRaisesRegex(DualOverlayDeviceFailure, 'host_audit_session_changed'):
            wait_for_stopped_with_survivor(audit, {'et': (2, 2), 'ts': (2, 2)}, 'et', progress)
        self.assertIsNone(progress['survivorSecondInputConfirmed'])


class BothStoppedAuditTests(unittest.TestCase):
    def test_delayed_closure_is_only_waitable_state_and_timeout_is_distinct(self):
        for first in ('et', 'ts'):
            survivor = 'ts' if first == 'et' else 'et'
            current = [0.0]
            calls = {'et': 0, 'ts': 0}
            def now(): return current[0]
            def sleep(delay): current[0] += delay
            def audit(role, expected):
                calls[role] += 1
                value = evidence(); value['capturedBytes'] = len(expected)
                value['sessions'][1]['active'] = role == survivor and calls[role] < 3
                return value
            wait_for_both_stopped(audit, {'et': (2, 2), 'ts': (2, 2)}, first,
                                  timeout=1, interval=.2, monotonic=now, sleep=sleep)
            self.assertEqual(calls, {'et': 3, 'ts': 3})
            def never(role, expected):
                value = evidence(); value['capturedBytes'] = len(expected)
                value['sessions'][1]['active'] = role == survivor
                return value
            with self.assertRaisesRegex(DualOverlayDeviceFailure, 'host_audit_close_timeout'):
                wait_for_both_stopped(never, {'et': (2, 2), 'ts': (2, 2)}, first,
                                      timeout=.5, interval=.25, monotonic=now, sleep=sleep)

    def test_polling_rejects_any_session_or_input_drift_immediately(self):
        for error in ('reconnect', 'bytes', 'ordinal', 'reactivation'):
            current = [0.0]; calls = {'et': 0, 'ts': 0}
            def sleep(delay): current[0] += delay
            def audit(role, expected):
                calls[role] += 1
                value = evidence(); value['capturedBytes'] = len(expected)
                value['sessions'][1]['active'] = role == 'et'
                if error == 'reconnect': value['newSessions'] = 1
                if error == 'bytes': value['exactBytes'] = False
                if error == 'ordinal': value['sessions'][1]['ordinal'] = 3
                if error == 'reactivation':
                    value['sessions'][1]['active'] = (role == 'ts' and calls[role] > 1) or (role == 'et' and calls[role] < 3)
                return value
            with self.assertRaisesRegex(DualOverlayDeviceFailure, 'host_audit_session_changed'):
                wait_for_both_stopped(audit, {'et': (2, 2), 'ts': (2, 2)}, 'ts',
                                      timeout=2, interval=.1, monotonic=lambda:current[0], sleep=sleep)
            if error != 'reactivation': self.assertEqual(current[0], 0)

    def test_final_stage_rejects_previously_closed_session_reappearing(self):
        def audit(role, expected):
            value = evidence(); value['capturedBytes'] = len(expected)
            value['sessions'][1]['active'] = role == 'et'
            return value
        with self.assertRaisesRegex(DualOverlayDeviceFailure, 'host_audit_session_changed'):
            wait_for_both_stopped(audit, {'et': (2, 2), 'ts': (2, 2)}, 'et', initially_closed=('et',))

    def test_final_audit_checks_original_sessions_bytes_and_closure(self):
        import base64
        for first_stop in ('et', 'ts'):
            survivor = 'ts' if first_stop == 'et' else 'et'
            class Control:
                def __init__(self): self.calls = []; self.failure = None
                def call(self, request):
                    self.calls.append(request)
                    role = request['role']
                    expected = (b'E' if role == 'et' else b'T') + ((b'e' if role == 'et' else b't') if role == survivor else b'')
                    self_expected = base64.b64encode(expected).decode('ascii')
                    if request['expectedBase64'] != self_expected: raise AssertionError('wrong audit bytes')
                    value = evidence()
                    value.update(event='host_audit', role=role, capturedBytes=len(expected))
                    value['sessions'][1]['active'] = self.failure == 'active'
                    if self.failure == 'reconnect': value['newSessions'] = 1
                    if self.failure == 'bytes': value['exactBytes'] = False
                    return value
            control = Control()
            session = type('Session', (), {'control': control})()
            baseline = {'et': (2, 2), 'ts': (2, 2)}
            with patch('flutter_android_dual_overlay.write_exchange') as write:
                self.assertTrue(handle_stage('both_stopped_audit', session=session, adb='adb', serial='emulator-5554',
                                             run=None, first_stop=first_stop, baselines=baseline))
                self.assertEqual(write.call_args.args[2:4], ('both-stopped-audit.txt', b'accepted'))
            for failure in ('reconnect', 'bytes'):
                control.failure = failure
                with patch('flutter_android_dual_overlay.write_exchange') as write:
                    with self.assertRaises(DualOverlayDeviceFailure):
                        handle_stage('both_stopped_audit', session=session, adb='adb', serial='emulator-5554',
                                     run=None, first_stop=first_stop, baselines=baseline)
                    write.assert_not_called()


class FailedHostAuditTests(unittest.TestCase):
    def test_failure_snapshot_only_keeps_bounded_counters(self):
        class Control:
            def __init__(self): self.requests = []
            def call(self, request):
                self.requests.append(request)
                return {'event': 'host_audit', 'role': request['role'], 'acceptedSessions': 1,
                        'newSessions': 1, 'capturedBytes': 0, 'newInputBytes': 0,
                        'sessions': [{'active': True, 'approvedDevice': True, 'private': 'secret'}],
                        'extra': 'secret'}
        control = Control(); session = type('Session', (), {'control': control})()
        result = sample_failed_host_audits(session)
        self.assertEqual(result['et'], {'available': True, 'acceptedSessions': 1, 'newSessions': 1,
            'capturedBytes': 0, 'newInputBytes': 0, 'activeSessions': 1, 'approvedSessions': 1})
        self.assertNotIn('secret', repr(result))
        self.assertEqual([req['role'] for req in control.requests], ['et', 'ts'])
        self.assertTrue(all(req['expectedBase64'] == '' for req in control.requests))
        control.call = lambda request: {'event': 'host_audit', 'role': request['role'], 'acceptedSessions': True}
        self.assertEqual(sample_failed_host_audits(session), {'et': {'available': False}, 'ts': {'available': False}})


class SafeTsControlTest(unittest.TestCase):
    def test_only_bounded_fixed_fields_are_retained(self):
        fields = {'event': 'ts_diagnostics', 'secondClientRegistered': False,
                  **{key: 0 for key in ('keyRequests', 'noiseRequests', 'registerRequests', 'mapRequests',
                                       'tlsHandshakeErrors', 'authCompletions')}}
        control = type('Control', (), {'call': lambda self, request: fields})()
        session = type('Session', (), {'control': control})()
        self.assertTrue(sample_ts_control(session)['available'])
        fields['unexpected'] = 'secret'
        self.assertEqual(sample_ts_control(session), {'available': False})
        fields.pop('unexpected'); fields['keyRequests'] = True
        self.assertEqual(sample_ts_control(session), {'available': False})


class SafeUiFailureTest(unittest.TestCase):
    def test_remote_diagnostic_rejects_untrusted_content(self):
        import json
        remote = {**{key: False for key in ('pagePresent', 'reviewPresent', 'reviewChecked', 'connectPresent',
                    'connectEnabled', 'busy', 'live', 'dashboardPresent', 'snapshotReceived',
                    'boardSelectable', 'paneEnabled', 'paneHit', 'selectionAttempted', 'selected',
                    'selectedMatches', 'terminalPresent', 'sequencePresent', 'markerObserved')},
                  **{key: 'unknown' for key in ('network', 'hostKey', 'authentication', 'dashboard', 'firstFrame')},
                  'paneCount': 0, 'paneControlCount': 0, 'statusClass': 'unavailable',
                  'adapterPhase': 'before_auth', 'adapterError': 'none', 'adapterKind': 'none', 'channelOpenCode': 0}
        payload = {'stage': 'et_remote_pane', 'kind': 'test_failure', 'remoteCheck': remote}
        self.assertEqual(safe_ui_failure(json.dumps(payload).encode()), payload)
        denied = {**remote, 'statusClass': 'snapshot_forward_denied', 'adapterPhase': 'snapshot_forward_open',
                  'adapterKind': 'ssh_channel_open', 'adapterError': 'snapshot_forward_denied', 'channelOpenCode': 1}
        self.assertEqual(safe_ui_failure(json.dumps(dict(payload, remoteCheck=denied)).encode())['remoteCheck'], denied)
        for altered in ({**remote, 'raw': 'secret'}, {**remote, 'statusClass': 'secret'},
                        {**remote, 'paneCount': True}, {**remote, 'network': 'secret'}):
            self.assertIsNone(safe_ui_failure(json.dumps(dict(payload, remoteCheck=altered)).encode()))

    def test_binding_diagnostic_contains_only_boolean_fields(self):
        import json
        values = {'hostPresent': True, 'hostEnabled': True, 'bindingMatches': True, 'catalogReady': True,
                  'catalogWriting': False, 'addPresent': False, 'addEnabled': False}
        payload = {'stage': 'et_bind_save', 'kind': 'test_failure', 'bindingCheck': values, 'bindingSelectionMatches': True}
        self.assertEqual(safe_ui_failure(json.dumps(payload).encode()), payload)
        self.assertIsNone(safe_ui_failure(json.dumps(dict(payload, bindingCheck={**values, 'id': 'secret'})).encode()))
        self.assertIsNone(safe_ui_failure(json.dumps(dict(payload, bindingCheck={**values, 'bindingMatches': 'secret'})).encode()))

    def test_response_diagnostic_is_bounded_and_redacted(self):
        import json
        check = {'inputMatches': True, 'fieldPresent': True, 'pagePresent': True,
                 'foreground': True, 'category': 'future', 'futureSeconds': 3, 'recheckPresent': True,
                 'recheckEnabled': True, 'previewPresent': False, 'sourceChecked': False}
        payload = {'stage': 'et_response_preview', 'kind': 'test_failure', 'responseCheck': check}
        self.assertEqual(safe_ui_failure(json.dumps(payload).encode()), payload)
        old = {k:v for k,v in check.items() if k not in {'recheckPresent','recheckEnabled','previewPresent','sourceChecked'}}
        self.assertEqual(safe_ui_failure(json.dumps(dict(payload, responseCheck=old)).encode())['responseCheck'], old)
        for changed in ({**check, 'futureSeconds': 601}, {**check, 'category': 'secret'},
                        {**check, 'raw': 'secret'}, {**check, 'inputMatches': 'secret'},
                        {**check, 'category': 'valid'}):
            self.assertIsNone(safe_ui_failure(json.dumps(dict(payload, responseCheck=changed)).encode()))

    def test_safe_source_frames_reject_paths_and_invalid_values(self):
        import json
        payload = {'stage': 'et_response_preview', 'kind': 'test_failure',
                   'responseReceived': True,
                   'stackFrames': [{'file': 'dual_overlay_ui_steps.dart', 'line': 123}]}
        self.assertEqual(safe_ui_failure(json.dumps(payload).encode()), payload)
        for frame in ({'file': '/private/dual_overlay_ui_steps.dart', 'line': 123},
                      {'file': 'dual_overlay_ui_steps.dart', 'line': True},
                      {'file': 'secret.dart', 'line': 1}):
            self.assertIsNone(safe_ui_failure(json.dumps(dict(payload, stackFrames=[frame])).encode()))
        self.assertIsNone(safe_ui_failure(json.dumps(dict(payload, responseReceived='secret')).encode()))

    def test_new_specific_stages_are_allowlisted_without_accepting_raw_details(self):
        import json
        for stage in ('et_remote_tab', 'ts_remote_tab', 'ts_identity_load', 'ts_pair_page', 'ts_pair_input', 'ts_pair_preview',
                      'ts_pair_fill', 'ts_pair_target_review', 'ts_pair_create', 'ts_pair_request'):
            payload = {'stage': stage, 'kind': 'test_failure'}
            self.assertEqual(safe_ui_failure(json.dumps(payload).encode()), payload)
            payload['raw'] = 'secret'
            self.assertIsNone(safe_ui_failure(json.dumps(payload).encode()))

    def test_only_fixed_stage_and_class_are_published(self):
        self.assertEqual(safe_ui_failure(b'{"stage":"et_identity_create","kind":"test_failure"}'),
                         {'stage': 'et_identity_create', 'kind': 'test_failure'})
        diagnostic = b'{"stage":"ts_node_wait","kind":"state_error","nodeState":"starting","statusPresent":true,"editPresent":true,"editEnabled":false,"addPresent":false,"addEnabled":false,"notice":"not_visible"}'
        self.assertEqual(safe_ui_failure(diagnostic)['nodeState'], 'starting')
        self.assertIsNone(safe_ui_failure(diagnostic.replace(b'"notice":"not_visible"', b'"notice":"secret"')))
        for raw in (b'{"stage":"secret","kind":"test_failure"}',
                    b'{"stage":"et_identity_create","kind":"secret"}',
                    b'{"stage":"et_identity_create","kind":"test_failure","message":"secret"}', b'not-json'):
            self.assertIsNone(safe_ui_failure(raw))


class DeviceCheckpointTest(unittest.TestCase):
    def test_cannot_skip_a_real_checkpoint_or_accept_nonzero_test_exit(self):
        process = type('Process', (), {'poll': lambda self: None, 'wait': lambda self, timeout: 0})()
        with patch('flutter_android_dual_overlay.read_exchange', return_value=b'et_baseline'):
            with self.assertRaisesRegex(DualOverlayDeviceFailure, 'device_stage_out_of_order'):
                drive_checkpoints(None, process, 'adb', 'emulator-5554', 'et', run=None)

    def test_completed_contract_requires_survivor_stop_and_both_host_audits(self):
        import json
        expected = {'status': 'passed', 'firstStop': 'et', 'twoReviewedTargets': True,
                    'observedBothUpdates': True, 'responseMarkersMatched': True,
                    'explicitTsAuthorization': True, 'newFullAfterResume': True,
                    'stoppedTabRetired': True, 'survivorStopped': True,
                    'initialInputsAccepted': True, 'survivorInputAccepted': True}
        for valid in (True, False):
            result = dict(expected)
            if not valid: result.pop('survivorStopped')
            stages = iter([b'ts_wait_authorization', b'et_pair_review', b'ts_pair_review',
                           b'et_baseline', b'ts_baseline', b'stopped_audit', b'final_audit', b'both_stopped_audit'])
            process = type('Process', (), {'poll': lambda self: None, 'wait': lambda self, timeout: 0})()
            def read(_adb, _serial, name, **_kwargs):
                return json.dumps(result).encode() if name == 'result.json' else next(stages)
            with patch('flutter_android_dual_overlay.read_exchange', side_effect=read), \
                 patch('flutter_android_dual_overlay.handle_stage', return_value=True) as checked, \
                 patch('time.sleep'):
                if valid:
                    self.assertEqual(drive_checkpoints(None, process, 'adb', 'emulator-5554', 'et', run=None), expected)
                    self.assertEqual(checked.call_count, 8)
                else:
                    with self.assertRaisesRegex(DualOverlayDeviceFailure, 'device_result_invalid'):
                        drive_checkpoints(None, process, 'adb', 'emulator-5554', 'et', run=None)

    def test_result_published_after_missing_read_is_rechecked_after_exit(self):
        import json
        expected = {'status': 'passed', 'firstStop': 'et', 'twoReviewedTargets': True,
                    'observedBothUpdates': True, 'responseMarkersMatched': True,
                    'explicitTsAuthorization': True, 'newFullAfterResume': True,
                    'stoppedTabRetired': True, 'survivorStopped': True,
                    'initialInputsAccepted': True, 'survivorInputAccepted': True}
        stages = iter([b'ts_wait_authorization', b'et_pair_review', b'ts_pair_review',
                       b'et_baseline', b'ts_baseline', b'stopped_audit', b'final_audit',
                       b'both_stopped_audit', b'both_stopped_audit'])
        reads = iter([None, json.dumps(expected).encode()])
        polls = iter([None] * 7 + [0])
        process = type('Process', (), {'poll': lambda self: next(polls),
                                       'wait': lambda self, timeout: 0})()
        def read(_adb, _serial, name, **_kwargs):
            return next(reads) if name == 'result.json' else next(stages)
        with patch('flutter_android_dual_overlay.read_exchange', side_effect=read), \
             patch('flutter_android_dual_overlay.handle_stage', return_value=True), \
             patch('time.sleep'):
            self.assertEqual(drive_checkpoints(None, process, 'adb', 'emulator-5554', 'et', run=None), expected)

    def test_all_checkpoint_replies_and_test_process_are_required(self):
        import json
        stages = iter([b'ts_wait_authorization', b'et_pair_review', b'ts_pair_review',
                       b'et_baseline', b'ts_baseline', b'stopped_audit', b'final_audit', b'both_stopped_audit'])
        result = {'status': 'passed', 'firstStop': 'et', 'twoReviewedTargets': True,
                  'observedBothUpdates': True, 'responseMarkersMatched': True,
                  'explicitTsAuthorization': True, 'newFullAfterResume': True,
                  'stoppedTabRetired': True, 'survivorStopped': True,
                  'initialInputsAccepted': True, 'survivorInputAccepted': True}
        process = type('Process', (), {'poll': lambda self: None, 'wait': lambda self, timeout: 1})()
        def read(_adb, _serial, name, **_kwargs):
            return json.dumps(result).encode() if name == 'result.json' else next(stages)
        with patch('flutter_android_dual_overlay.read_exchange', side_effect=read), \
             patch('flutter_android_dual_overlay.handle_stage', return_value=True), \
             patch('time.sleep'):
            with self.assertRaisesRegex(DualOverlayDeviceFailure, 'device_test_failed'):
                drive_checkpoints(None, process, 'adb', 'emulator-5554', 'et', run=None)


class InstalledApkTest(unittest.TestCase):
    def test_verify_actual_app_copy_and_reject_non_package_paths(self):
        import tempfile
        from pathlib import Path
        class Device:
            PACKAGE = 'dev.herdr.herdr_flutter_probe'
            path = b'package:/data/app/~~owned/dev.herdr-probe/base.apk\n'
            def adb(self, *args):
                return type('Result', (), {'stdout': self.path if args[:3] == ('shell', 'pm', 'path') else b'APK'})()
        device = Device()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'installed.apk'
            result = installed_apk_evidence(device, 'qa', target,
                lambda bundle, path: {'apkSha256': 'checked' if path.read_bytes() == b'APK' else 'bad'})
            self.assertEqual(result['apkSha256'], 'checked')
            for invalid in (b'package:/data/app/../secret/base.apk', b'package:/etc/passwd', b'multiple\nlines'):
                device.path = invalid
                with self.assertRaisesRegex(DualOverlayDeviceFailure, 'installed_apk_path_invalid'):
                    installed_apk_evidence(device, 'qa', target, lambda *_: {})



class WorkflowFallbackTest(unittest.TestCase):
    def test_missing_report_records_failure_and_existing_report_is_preserved(self):
        import json
        import os
        import subprocess
        import sys
        import tempfile
        import textwrap
        from pathlib import Path
        workflow = Path(__file__).resolve().parents[2] / '.github/workflows/flutter-android-dual-overlay.yml'
        text = workflow.read_text()
        step = text.split('      - name: Preserve a failed report when device evidence is missing\n', 1)[1]
        script = step.split("          python3 - <<'PYCODE'\n", 1)[1].split('          PYCODE\n', 1)[0]
        script = textwrap.dedent(script)
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, RUNNER_TEMP=tmp, DEVICE_OUTCOME='skipped',
                       GITHUB_SHA='a' * 40, NATIVE_SOURCE='b' * 40, HOST_SOURCE='c' * 40)
            result = subprocess.run([sys.executable, '-c', script], env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            path = Path(tmp) / 'dual-evidence/manifest.json'
            report = json.loads(path.read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['errorCode'], 'device_manifest_missing')
            self.assertEqual(report['deviceStepOutcome'], 'skipped')
            self.assertNotIn('cases', report)
            path.unlink()
            env['DEVICE_OUTCOME'] = 'success'
            result = subprocess.run([sys.executable, '-c', script], env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(path.read_text())['deviceStepOutcome'], 'success')
            path.write_text('{"status":"actual-device-result"}')
            subprocess.run([sys.executable, '-c', script], env=env, check=True)
            self.assertEqual(json.loads(path.read_text()), {'status': 'actual-device-result'})


if __name__ == '__main__':
    unittest.main()
