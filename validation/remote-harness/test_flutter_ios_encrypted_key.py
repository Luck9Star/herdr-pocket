"""Flutter iOS encrypted SSH: loopback protocol facts, not simulator or OCR evidence."""
import io
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import paramiko

import flutter_direct_ssh_android as android
import flutter_direct_ssh_ios as ios
from ios_direct_ssh_batch import encrypted_key_case_valid, publish_evidence
from ios_encrypted_key_fixture import EncryptedKeyFixture
from terminal_screenshot_gate import ScreenshotGateError


class FlutterIosEncryptedKeyTests(unittest.TestCase):
    def test_shared_device_result_exports_pem_observations_to_both_hosts(self):
        source = Path(ios.__file__).resolve().parents[1] / 'flutter/integration_test/direct_ssh_ui_steps.dart'
        run = source.read_text().split('Future<void> runEncryptedDirectSshUi(', 1)[1]
        report = run.split('  final report = {\n', 1)[1].split('\n  };', 1)[0]
        pem_fields = {'pemCollapsedBeforeReopen', 'pemReopenedFocusedAndExact', 'pemRecollapsedAfterBlur'}
        shared_observations = dict.fromkeys(re.findall(r"^    '([^']+)': true,$", report, re.MULTILINE), True)
        self.assertEqual(pem_fields & shared_observations.keys(), pem_fields)
        for rotating in (False, True):
            fields = ios.ENCRYPTED_ROTATION_PUBLIC_FIELDS if rotating else ios.ENCRYPTED_PUBLIC_FIELDS
            for platform in ('ios-simulator', 'android-api35-emulator'):
                with self.subTest(rotating=rotating, platform=platform):
                    device = dict.fromkeys(fields - pem_fields, True)
                    device.update({field: shared_observations[field] for field in pem_fields})
                    device.update(schemaVersion=1, platform=platform, physicalImeVerified=False)
                    if platform == 'ios-simulator':
                        check, failure = lambda value: ios.check_result(value, fields), ios.Failure
                    else:
                        check = lambda value: android.safe_encrypted_result(json.dumps(value), rotating=rotating)
                        failure = android.Failure
                    self.assertEqual(check(device), device)
                    for field in pem_fields:
                        absent = {key: value for key, value in device.items() if key != field}
                        for bad in (absent, {**device, field: False}, {**device, field: 1},
                                    {**device, 'unknownPemObservation': True}):
                            with self.subTest(field=field, keys=bad.keys()), self.assertRaises(failure):
                                check(bad)

    def test_rotation_only_runner_drives_four_ordered_checkpoints_and_publishes_one_case(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app, output = root / 'app', root / 'output'
            exchange = root / 'container/tmp/herdr-direct-ssh-123'
            exchange.mkdir(parents=True)
            source = Path(ios.__file__).resolve().parents[1] / 'flutter'
            for name in (ios.TARGET, 'integration_test/direct_ssh_ui_steps.dart',
                         'integration_test/ios_exchange.dart', 'test/ios_layout_diagnostics.dart'):
                destination = app / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((source / name).read_bytes())

            def write(name, value):
                (exchange / name).write_text(json.dumps(value))

            write('stage.json', {'stage': 'encrypted_waiting_private'})
            fixture = MagicMock(port=2323, username='fixture', fingerprint='SHA256:A', rotated_fingerprint='SHA256:B',
                                private_key='isolated-key', passphrase='isolated-passphrase', wrong_passphrase='local-only')
            fixture.__enter__.return_value = fixture
            def finish_fixture():
                fixture.private_key = fixture.passphrase = fixture.wrong_passphrase = ''
            fixture.close.side_effect = finish_fixture
            fixture.__exit__.side_effect = lambda *_: finish_fixture()
            zero = dict.fromkeys(('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes'), 0)
            probe = dict(id=1, hostKey='A', closed=True, authAccepted=False, markerReceived=False, sessionClosed=False, **zero)
            session = {**probe, 'id': 4, 'hostKey': 'B', 'authAccepted': True, 'authAttempts': 1, 'authSuccesses': 1,
                       'ptyRequests': 1, 'shellRequests': 1, 'inputBytes': 9, 'outputBytes': 102, 'markerReceived': True,
                       'sessionClosed': True, 'singleMarkerLineExact': True}
            final_facts = {'connections': 4, 'connectionsClosed': True,
                'connectionEvents': [probe, {**probe, 'id': 2, 'hostKey': 'B'}, {**probe, 'id': 3, 'hostKey': 'B'}, session]}
            fixture.snapshot.return_value = {'connections': 0, 'connectionsClosed': True, 'connectionEvents': []}
            fixture.wait_for_connections_closed.return_value = True
            fixture.rotation_evidence.side_effect = lambda count: {'stage': count, 'connections': count, 'connectionsClosed': True}
            phases = iter(('review', 'rejected', 'cancelled', 'reprobed', 'screen', 'result'))
            def advance(_):
                phase = next(phases)
                if phase == 'review':
                    (exchange / 'encrypted-credentials.json').unlink()
                    fixture.snapshot.return_value = final_facts
                if phase == 'rejected':
                    write('stage.json', {'stage': 'rotation_rejected'})
                    write('review-request.json', {'tag': 'encrypted-rotation', 'formAbsent': True, 'secretAbsent': True})
                if phase in ios.ENCRYPTED_ROTATION_CHECKPOINTS:
                    write('encrypted-rotation-stage.json', {'phase': phase})
                if phase == 'screen':
                    write('stage.json', {'stage': 'encrypted_capture'})
                    write('screen-request.json', {'tag': 'encrypted-rotation', 'attempt': 1,
                        'observedTarget': 'fixture@127.0.0.1:2323', 'bounds': [0, 30, 300, 570],
                        'targetBounds': [0, 10, 200, 20], 'viewSize': [300, 600]})
                if phase == 'result':
                    value = dict.fromkeys(ios.ENCRYPTED_ROTATION_PUBLIC_FIELDS, True)
                    value.update(schemaVersion=1, platform='ios-simulator', physicalImeVerified=False)
                    write('encrypted-rotation-result.json', value)
                    write('encrypted-rotation-mode-switch.json', dict.fromkeys(
                        ('passwordToKeyCleared', 'keyToPasswordCleared', 'sameTrust'), True))

            def capture(device, path):
                encoded = io.BytesIO()
                Image.new('RGB', (300, 600), 'white' if 'review' in path.name else 'black').save(encoded, format='PNG')
                return encoded.getvalue()

            device = '12345678-1234-1234-1234-123456789ABC'
            def command(*args, **unused):
                if 'runtimes' in args:
                    return json.dumps({'runtimes': [{'isAvailable': True, 'version': '26.2',
                        'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-26-2'}]})
                if 'devicetypes' in args:
                    return json.dumps({'devicetypes': [{'name': 'iPhone 11', 'identifier': 'fixture-phone'}]})
                return ''

            def run(command, **unused):
                if command[0] == 'flutter':
                    argument = next(item for item in command if item.startswith('--dart-define-from-file='))
                    defines = json.loads(Path(argument.split('=', 1)[1]).read_text())
                    self.assertEqual(defines['HERDR_IOS_ENCRYPTED_KEY_CASE'], 'rotation')
                    self.assertEqual(json.loads(defines['HERDR_IOS_ENCRYPTED_KEY_TARGET'])['rotatedFingerprint'], 'SHA256:B')
                    self.assertNotIn('HERDR_IOS_DIRECT_TARGET', defines)
                    self.assertNotIn('HERDR_IOS_ROTATION_TARGET', defines)
                    self.assertNotIn('isolated-passphrase', json.dumps(defines))
                return subprocess.CompletedProcess(command, 0, device.encode(), b'')

            tool = MagicMock(pid=12345)
            tool.poll.return_value = None
            def wait(**unused):
                if not (exchange / 'encrypted-rotation-peer-confirmed.json').is_file():
                    tool.poll.return_value = 1
                    return 1
                tool.poll.return_value = 0
                write('stage.json', {'stage': 'encrypted_returned_home'})
                return 0
            tool.wait.side_effect = wait
            live = {**session, 'closed': False, 'sessionClosed': False}
            def validate_terminal(peer, *, closed):
                self.assertIs(peer, fixture)
                return session if closed else live
            def ocr(png, **unused):
                return {'imageSha256': hashlib.sha256(png).hexdigest(), 'markerVisible': True, 'tokenVisible': True,
                        'proofSequenceVisible': True}

            env = {'GITHUB_ACTIONS': 'true', 'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'RUNNER_TEMP': str(root),
                   'GITHUB_REF': ios.ENCRYPTED_ROTATION_REF + 'test', 'GITHUB_EVENT_NAME': 'workflow_dispatch'}
            with patch.object(ios, 'verify_prepared'), patch('ios_xctest_scaffold.prepare'), \
                 patch.object(ios, 'command', side_effect=command), patch.object(ios.subprocess, 'run', side_effect=run), \
                 patch.object(ios.subprocess, 'Popen', return_value=tool), patch.object(ios.os, 'killpg'), \
                 patch.object(ios, 'ContainerLocator', return_value=SimpleNamespace(get=lambda _: exchange.parents[1], timeouts=0, attempts=1)), \
                 patch('direct_ssh_fixture.DirectSshFixture') as old_peer, \
                 patch('ios_encrypted_key_fixture.EncryptedKeyFixture', return_value=fixture) as new_peer, \
                 patch.object(ios, 'owned_devices', side_effect=[[device], []]), patch.object(ios.time, 'sleep', side_effect=advance), \
                 patch.object(ios, 'encrypted_probe_evidence', return_value=probe), \
                 patch.object(ios, 'encrypted_rotation_session', side_effect=validate_terminal), \
                 patch.object(ios, 'capture_system_screen', side_effect=capture), \
                 patch.object(ios, 'target_pixel_proof', return_value={'targetVisible': True}), \
                 patch('terminal_screenshot_gate.verify_terminal_screenshot', side_effect=ocr):
                report = ios.run(app, output, env, encrypted_rotation=True)

            old_peer.assert_not_called()
            new_peer.assert_called_once()
            self.assertIs(new_peer.call_args.kwargs['rotate_after_probe'], True)
            self.assertEqual(report['status'], 'passed')
            self.assertEqual(set(report['cases']), {'encryptedKeyRotation'})
            self.assertTrue(report['cleanup']['encryptedSecretsCleared'])
            self.assertNotIn('isolated-key', (output / 'result.json').read_text())
            names = publish_evidence(output, root / 'published', shell='flutter', source_sha='a' * 40, encrypted_rotation=True)
            self.assertEqual(names, {'result.json', 'encrypted-rotation-review.png', 'encrypted-rotation-terminal.png',
                                     'encrypted-rotation-terminal-ocr.json'})

    @staticmethod
    def _wait_handshake(peer):
        deadline = time.monotonic() + 2
        while not peer.snapshot()['connectionEvents'][0]['handshakeCompleted'] and time.monotonic() < deadline:
            time.sleep(.01)

    def test_single_rotating_encrypted_peer_and_exact_command_guard(self):
        for command, exact in ((b'hp-check\r', True), (b'\nhp-check\r', False)):
            with self.subTest(exact=exact), tempfile.TemporaryDirectory() as directory, EncryptedKeyFixture(
                    rotate_after_probe=True, screen_proof=True, channel_deadline=time.monotonic() + 60) as peer:
                exchange = Path(directory)
                checkpoints = {}
                for count, fingerprint in enumerate((peer.fingerprint, peer.rotated_fingerprint, peer.rotated_fingerprint), 1):
                    with paramiko.Transport(('127.0.0.1', peer.port)) as probe:
                        probe.start_client(timeout=5)
                        self.assertEqual(probe.get_remote_server_key().fingerprint, fingerprint)
                        if count == 1:
                            self._wait_handshake(peer)
                    if count == 1:
                        checkpoints['review'] = ios.encrypted_probe_evidence(peer)
                    elif count == 2:
                        checkpoints['rejected'] = ios.closed_rotation_evidence(peer, count)
                        checkpoints['cancelled'] = ios.closed_rotation_evidence(peer, count)
                    else:
                        checkpoints['reprobed'] = ios.closed_rotation_evidence(peer, count)
                key = paramiko.Ed25519Key.from_private_key(io.StringIO(peer.private_key), peer.passphrase)
                with paramiko.Transport(('127.0.0.1', peer.port)) as session:
                    session.start_client(timeout=5)
                    self.assertEqual(session.get_remote_server_key().fingerprint, peer.rotated_fingerprint)
                    session.auth_publickey(peer.username, key)
                    with session.open_session(timeout=5) as channel:
                        channel.get_pty()
                        channel.invoke_shell()
                        channel.sendall(command)
                        self.assertTrue(peer.wait_for('markerReceived'))
                        if exact:
                            self.assertTrue(ios.encrypted_rotation_session(peer, closed=False)['singleMarkerLineExact'])
                self.assertTrue(peer.wait_for_connections_closed(4))
                self.assertEqual(peer.rotation_evidence(4)['acceptedSession']['markerReceived'], True)
                report = dict.fromkeys(ios.ENCRYPTED_ROTATION_PUBLIC_FIELDS, True)
                report.update(schemaVersion=1, platform='ios-simulator', physicalImeVerified=False)
                (exchange / 'encrypted-rotation-result.json').write_text(json.dumps(report))
                modes = dict.fromkeys(('passwordToKeyCleared', 'keyToPasswordCleared', 'sameTrust'), True)
                (exchange / 'encrypted-rotation-mode-switch.json').write_text(json.dumps(modes))
                if exact:
                    case = ios.encrypted_case_evidence(exchange, peer, checkpoints, rotating=True)
                    self.assertEqual(case['checkpoints']['rejected'], case['checkpoints']['cancelled'])
                    self.assertEqual(case['acceptedSession']['id'], 4)
                    self.assertEqual(case['acceptedSession']['authAttempts'], 1)
                    self.assertEqual(case['acceptedSession']['hostKey'], 'B')
                    self.assertTrue(case['acceptedSession']['singleMarkerLineExact'])
                    self.assertNotIn('wrongPassphrase', case)
                    with self.assertRaisesRegex(ios.Failure, 'checkpoints_incomplete'):
                        ios.encrypted_case_evidence(exchange, peer, {'review': checkpoints['review']}, rotating=True)
                else:
                    with self.assertRaisesRegex(ios.Failure, 'encrypted_rotation_session_invalid'):
                        ios.encrypted_case_evidence(exchange, peer, checkpoints, rotating=True)
            self.assertFalse(any((peer.private_key, peer.passphrase, peer.wrong_passphrase)))

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
                self._wait_handshake(peer)
            review = ios.encrypted_probe_evidence(peer)
            with self.assertRaises(paramiko.SSHException):
                paramiko.Ed25519Key.from_private_key(io.StringIO(values['privateKey']), password='wrong')
            rejected = ios.encrypted_probe_evidence(peer)
            self.assertEqual(review, rejected)
            self.assertIs(rejected['handshakeCompleted'], True)
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
                                                      'peerClosedBeforeDriverExit': True}))
            facts = json.dumps([case, peer.snapshot()])
            self.assertTrue(all(secret not in facts for secret in values.values()), 'credential in public evidence')
            with self.assertRaisesRegex(ios.Failure, 'checkpoints_incomplete'):
                ios.encrypted_case_evidence(exchange, peer, {'review': review})
            credentials.touch()
            with self.assertRaisesRegex(ios.Failure, 'checkpoints_incomplete'):
                ios.encrypted_case_evidence(exchange, peer, checkpoints)
        self.assertFalse(any((peer.private_key, peer.passphrase, peer.wrong_passphrase)))

    def test_encrypted_probe_evidence_requires_completed_handshake(self):
        zero = dict.fromkeys(('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes'), 0)
        event = {'id': 1, 'hostKey': 'A', 'closed': True, 'authAccepted': False,
                 'markerReceived': False, 'sessionClosed': False, **zero}
        for bad_event in ({**event, 'handshakeCompleted': False}, dict(event)):
            with self.subTest(bad_event=bad_event):
                peer = SimpleNamespace(
                    wait_for_connections_closed=lambda count: count == 1,
                    snapshot=lambda: {'connections': 1, 'connectionsClosed': True, 'connectionEvents': [bad_event]},
                )
                with self.assertRaisesRegex(ios.Failure, 'ios_encrypted_probe_incomplete'):
                    ios.encrypted_probe_evidence(peer)
        good_peer = SimpleNamespace(
            wait_for_connections_closed=lambda count: count == 1,
            snapshot=lambda: {'connections': 1, 'connectionsClosed': True,
                              'connectionEvents': [{**event, 'handshakeCompleted': True}]},
        )
        self.assertEqual(ios.encrypted_probe_evidence(good_peer), {**event, 'handshakeCompleted': True})

    def test_public_key_only_fixture_rejects_its_password_and_an_unrelated_key(self):
        with EncryptedKeyFixture(channel_deadline=time.monotonic() + 60) as peer:
            with paramiko.Transport(('127.0.0.1', peer.port)) as session:
                session.start_client(timeout=5)
                with self.assertRaises(paramiko.BadAuthenticationType) as rejected:
                    session.auth_password(peer.username, peer.password, fallback=False)
                self.assertEqual(rejected.exception.allowed_types, ['publickey'])
            with paramiko.Transport(('127.0.0.1', peer.port)) as session:
                session.start_client(timeout=5)
                with self.assertRaises(paramiko.AuthenticationException):
                    session.auth_publickey(peer.username, paramiko.RSAKey.generate(2048))
            self.assertTrue(peer.wait_for_connections_closed(2))
            for event in peer.snapshot()['connectionEvents']:
                self.assertEqual(event['authAttempts'], 1)
                self.assertTrue(all(event[key] == 0 for key in ('authSuccesses', 'ptyRequests', 'shellRequests',
                                                               'inputBytes', 'outputBytes')))

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

    def test_rotation_flag_is_manual_and_requires_its_own_ref(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '1', 'RUNNER_TEMP': '/tmp'}
        for ref, event, enabled in ((ios.ENCRYPTED_ROTATION_REF + 'r1', 'push', True),
                                    (ios.ENCRYPTED_ROTATION_REF + 'r1', 'workflow_dispatch', False),
                                    ('refs/heads/codex/acceptance/direct-ssh-ios-flutter-only-r1', 'workflow_dispatch', True)):
            with self.subTest(ref=ref, event=event), self.assertRaisesRegex(
                    ios.Failure, 'encrypted_rotation_ref_or_dispatch_mismatch'):
                ios.run('unused', 'unused', dict(env, GITHUB_REF=ref, GITHUB_EVENT_NAME=event), encrypted_rotation=enabled)
