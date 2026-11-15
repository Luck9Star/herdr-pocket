import unittest
from unittest.mock import patch

from flutter_android_dual_overlay import (
    DualOverlayDeviceFailure, audit_baseline, audit_unchanged_session, prepare_private_ca, write_exchange, read_exchange, handle_stage, drive_checkpoints, installed_apk_evidence, safe_ui_failure,
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
    def test_fixed_name_and_no_output_leak(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            return type('Result', (), {'returncode': 0, 'stdout': b'private'})()
        self.assertEqual(read_exchange('adb', 'emulator-5554', 'stage', run=run), b'private')
        self.assertNotIn('private', repr(calls))
        with self.assertRaises(DualOverlayDeviceFailure):
            read_exchange('adb', 'emulator-5554', '../bad', run=run)


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


class SafeUiFailureTest(unittest.TestCase):
    def test_only_fixed_stage_and_class_are_published(self):
        self.assertEqual(safe_ui_failure(b'{"stage":"et_identity_create","kind":"test_failure"}'),
                         {'stage': 'et_identity_create', 'kind': 'test_failure'})
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

    def test_all_checkpoint_replies_and_test_process_are_required(self):
        import json
        stages = iter([b'ts_wait_authorization', b'et_pair_review', b'ts_pair_review',
                       b'et_baseline', b'ts_baseline', b'stopped_audit', b'final_audit'])
        result = {'status': 'passed', 'firstStop': 'et', 'twoReviewedTargets': True,
                  'observedBothUpdates': True, 'responseMarkersMatched': True,
                  'explicitTsAuthorization': True, 'newFullAfterResume': True,
                  'stoppedTabRetired': True, 'initialInputsAccepted': True, 'survivorInputAccepted': True}
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


if __name__ == '__main__':
    unittest.main()
