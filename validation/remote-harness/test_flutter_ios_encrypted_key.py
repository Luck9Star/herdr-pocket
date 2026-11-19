"""Flutter iOS encrypted SSH: loopback protocol facts, not simulator or OCR evidence."""
import io
import json
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import paramiko

import flutter_direct_ssh_ios as ios
from ios_direct_ssh_batch import encrypted_key_case_valid
from tauri_ios_direct_ssh import EncryptedKeyFixture
from terminal_screenshot_gate import ScreenshotGateError


class FlutterIosEncryptedKeyTests(unittest.TestCase):
    def test_loopback_probe_local_rejection_and_one_signed_shell(self):
        with tempfile.TemporaryDirectory() as directory, EncryptedKeyFixture(
                screen_proof=True, channel_deadline=time.monotonic() + 60) as peer:
            exchange = Path(directory)
            credentials = exchange / 'encrypted-credentials.json'
            ios.deliver_encrypted_credentials(exchange, peer)
            with self.assertRaisesRegex(ios.Failure, 'already_delivered'):
                ios.deliver_encrypted_credentials(exchange, peer)
            self.assertEqual(stat.S_IMODE(credentials.stat().st_mode), 0o600)
            values = json.loads(credentials.read_bytes())
            credentials.unlink()
            self.assertEqual(set(values), {'privateKey', 'passphrase'})
            with paramiko.Transport(('127.0.0.1', peer.port)) as probe:
                probe.start_client(timeout=5)
                reviewed = probe.get_remote_server_key()
                self.assertEqual(reviewed.fingerprint, peer.fingerprint)
            review = ios.encrypted_probe_evidence(peer)
            with self.assertRaises(paramiko.SSHException):
                paramiko.Ed25519Key.from_private_key(io.StringIO(values['privateKey']), password='wrong')
            rejected = ios.encrypted_probe_evidence(peer)
            self.assertEqual(review, rejected)
            self.assertTrue(all(rejected[k] == 0 for k in ('authAttempts', 'authSuccesses', 'ptyRequests',
                                                          'shellRequests', 'inputBytes', 'outputBytes')))
            key = paramiko.Ed25519Key.from_private_key(io.StringIO(values['privateKey']), password=values['passphrase'])
            with paramiko.Transport(('127.0.0.1', peer.port)) as session:
                session.start_client(timeout=5)
                self.assertEqual(session.get_remote_server_key(), reviewed)
                session.auth_publickey(peer.username, key)
                with session.open_session(timeout=5) as channel:
                    channel.settimeout(5)
                    channel.get_pty()
                    channel.invoke_shell()
                    channel.sendall(b'hp-check\r')
                    received = b''
                    while peer.echo_marker.encode() not in received:
                        chunk = channel.recv(4096)
                        self.assertTrue(bool(chunk) and len(received) < 8192, 'expected fixture echo')
                        received += chunk
            device = {**dict.fromkeys(ios.ENCRYPTED_PUBLIC_FIELDS, True), 'schemaVersion': 1,
                      'platform': 'ios-simulator', 'physicalImeVerified': False}
            (exchange / 'encrypted-result.json').write_text(json.dumps(device))
            modes = dict.fromkeys(('passwordToKeyCleared', 'keyToPasswordCleared', 'sameTrust'), True)
            (exchange / 'encrypted-mode-switch.json').write_text(json.dumps(modes))
            checkpoints = {'review': review, 'rejected': rejected}
            case = ios.encrypted_case_evidence(exchange, peer, checkpoints)
            self.assertTrue(encrypted_key_case_valid({**case, 'status': 'passed', 'returnedHome': True,
                                                      'peerClosedBeforeDriverExit': True}, shell='flutter'))
            facts = json.dumps([case, peer.snapshot()])
            self.assertTrue(all(secret not in facts for secret in values.values()), 'credential in public evidence')
            with self.assertRaisesRegex(ios.Failure, 'checkpoints_incomplete'):
                ios.encrypted_case_evidence(exchange, peer, {'review': review})
            credentials.touch()
            with self.assertRaisesRegex(ios.Failure, 'checkpoints_incomplete'):
                ios.encrypted_case_evidence(exchange, peer, checkpoints)
        self.assertFalse(any((peer.private_key, peer.passphrase, peer.wrong_passphrase)))

    def test_secret_delivery_rejects_aliased_directory_and_existing_target(self):
        peer = SimpleNamespace(private_key='test-only', passphrase='test-only')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'owned').mkdir()
            (root / 'alias').symlink_to(root / 'owned', target_is_directory=True)
            with self.assertRaisesRegex(ios.Failure, 'exchange_invalid'):
                ios.deliver_encrypted_credentials(root / 'alias', peer)
            (root / 'owned/encrypted-credentials.json').symlink_to(root / 'outside')
            with self.assertRaisesRegex(ios.Failure, 'already_delivered'):
                ios.deliver_encrypted_credentials(root / 'owned', peer)
            self.assertFalse((root / 'outside').exists())

    def test_encrypted_screen_requires_current_peer_and_both_pixel_proofs(self):
        request = {'tag': 'encrypted', 'attempt': 1, 'bounds': [0, 30, 300, 570], 'targetBounds': [0, 10, 200, 20],
                   'viewSize': [300, 600], 'observedTarget': 'fixture@127.0.0.1:2323'}
        def peer(port, count):
            return SimpleNamespace(port=port, username='fixture', screen_token='test-only', snapshot=lambda: {
                'connectionEvents': [{'markerReceived': True, 'inputBytes': count}]})
        password, key = peer(2222, 9), peer(2323, 9)
        completed = {'ordinary': {'accepted': True, 'attempt': 1}}
        png = b'\x89PNG\r\n\x1a\n' + b'\0\0\0\rIHDR' + struct.pack('>II', 300, 600)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def capture(value, current):
                ios.screen_checkpoint(value, completed, password, password, 'owned', root, root, root, encrypted=current)
            with patch.object(ios, 'capture_system_screen', return_value=png) as shot:
                for current, value in ((None, request), (peer(2323, 18), request),
                                       (key, {**request, 'observedTarget': 'fixture@127.0.0.1:2222'})):
                    with self.assertRaises(ios.Failure):
                        capture(value, current)
                shot.assert_not_called()
                with patch.object(ios, 'target_pixel_proof', return_value={'targetVisible': True}), patch(
                        'terminal_screenshot_gate.verify_terminal_screenshot', side_effect=ScreenshotGateError('test_missing_token')):
                    capture(request, key)
                self.assertFalse(completed['encrypted']['accepted'])
                self.assertFalse(list(root.glob('encrypted-key-terminal*')))
                self.assertEqual(shot.call_count, 1)

    def test_encrypted_failures_do_not_export_free_text_or_fetch_details(self):
        marker = 'sensitive diagnostic fragment'
        data = {'failedTests': 1, 'testFailures': [{'testIdentifierString': 'RunnerTests/case', 'failureText': marker}]}
        with tempfile.TemporaryDirectory() as directory, patch.object(ios.subprocess, 'run', return_value=
                subprocess.CompletedProcess([], 0, json.dumps(data).encode())) as run:
            result = ios.xctest_result_markers(Path(directory), counts_only=True)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result['failedTests'], 1)
        self.assertNotIn(marker, json.dumps(result))
        self.assertEqual(ios.framework_diagnostic({'exceptionClass': 'TestFailure', 'excerpt': [marker]}, (),
                                                 include_excerpt=False), {'exceptionClass': 'TestFailure'})

    def test_encrypted_flag_must_agree_with_flutter_only_ref_before_any_setup(self):
        prefix = 'refs/heads/codex/acceptance/direct-ssh-ios-'
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '1', 'RUNNER_TEMP': '/tmp'}
        for suffix, flag in (('both-r1', True), ('flutter-only-r1', True), ('tauri-only-encrypted-key-r1', True),
                             ('flutter-only-encrypted-key-r1', False)):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ios.Failure, 'encrypted_ref_mismatch'):
                ios.run('unused', 'unused', dict(env, GITHUB_REF=prefix + suffix), include_encrypted_key=flag)
