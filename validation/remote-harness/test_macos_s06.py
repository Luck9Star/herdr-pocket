"""Source and owned stock-SSH checks. Native XCUITest runs on its own workflow."""
import base64
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import Mock, patch

try:
    import macos_s06 as runner
    from macos_s06_diagnostics import TEST_SELECTION, checked_summary, diagnostics, log_facts
    from paired_dual_demo import fixture_sshd_config, ssh_args
    from paired_gui import GuiFailure, wait_for
    from pairing import MemoryKeyStore, PendingPairing, encode
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    runner = None

BINARY = os.environ.get('HERDR_MACOS_S06_BINARY')
WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/flutter-macos-s06-xcui.yml'


@unittest.skipIf(runner is None, 'requires validation/pairing/requirements.txt')
class MacosS06Checks(unittest.TestCase):
    def test_scope_rejects_local_native_launch(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(GuiFailure, 'requires_isolated_arm64_runner'):
                runner.isolated_runner(Path('/tmp/ordinary-app'), Path('/tmp/ordinary-output'))

    def test_optional_session_changes_only_the_owned_socket_policy(self):
        root = Path('/tmp/owned')
        default = fixture_sshd_config(root, 2345, 'fixture')
        explicit = fixture_sshd_config(root, 2345, 'fixture', 's06-a')
        self.assertIn('PermitOpen [/tmp/owned/config/herdr/sessions/qa-pair/herdr.sock]:*\n', default)
        self.assertEqual(explicit, default.replace('/qa-pair/', '/s06-a/'))
        for invalid in ('default', '../bad', 'two names', None):
            with self.assertRaisesRegex(GuiFailure, 'fixture_session_name_invalid'):
                fixture_sshd_config(root, 2345, 'fixture', invalid)

    def test_native_report_rejects_missing_checks_and_fake_widths(self):
        report = {'checks': dict.fromkeys(runner.CHECKS, True), 'widths': [1440, 700, 1440]}
        self.assertEqual(runner.checked_ui_result(report), report)
        for key in runner.CHECKS:
            changed = copy.deepcopy(report)
            changed['checks'][key] = False
            with self.assertRaisesRegex(GuiFailure, 'checks_incomplete'):
                runner.checked_ui_result(changed)
        for widths in ([1440, 1440, 1440], [1440, 700], [1440, 700.0, 1440]):
            with self.assertRaisesRegex(GuiFailure, 'widths_invalid'):
                runner.checked_ui_result({**report, 'widths': widths})
        self.assertIn('localProfilesAbsentFromBoard', report['checks'])
        self.assertNotIn('localIdentitiesRemoved', report['checks'])

    def test_workflow_installs_and_verifies_candidate_before_build_and_native_run(self):
        lines = [line.strip() for line in WORKFLOW.read_text().splitlines()]
        app = '"$RUNNER_TEMP/macos-s06-flutter"'
        expected = [
            f'python3 validation/flutter/tool/ci.py prepare --destination {app}',
            f'python3 validation/flutter/tool/candidate.py apply --destination {app}',
            f'cd {app}',
            'flutter pub get',
            f'python3 "$GITHUB_WORKSPACE/validation/flutter/tool/candidate.py" verify-lock --destination {app}',
            'flutter build macos --debug --config-only --no-pub',
        ]
        positions = [lines.index(line) for line in expected]
        self.assertEqual(positions, sorted(positions))
        native_run = '"$RUNNER_TEMP/macos-s06-venv/bin/python" validation/remote-harness/macos_s06.py '
        self.assertLess(positions[-1], next(i for i, line in enumerate(lines) if line.startswith(native_run)))

    def test_runner_rejects_reference_unverified_wrong_source_and_changed_candidate_lock(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            source = '1' * 40
            lock = root / 'pubspec.lock'
            lock.write_bytes(b'verified lock\n')
            manifest = root / 'candidate-manifest.json'
            metadata = {'variant': 'experimental-patched', 'sourceCommit': source,
                        'candidateLockSha256': hashlib.sha256(lock.read_bytes()).hexdigest()}
            with self.assertRaisesRegex(GuiFailure, 'candidate_lock_not_verified'):
                runner.checked_candidate(root, source)
            for change in ({'variant': 'reference'}, {'candidateLockSha256': None}, {'sourceCommit': '2' * 40}):
                manifest.write_text(json.dumps({**metadata, **change}))
                with self.assertRaisesRegex(GuiFailure, 'candidate_lock_not_verified'):
                    runner.checked_candidate(root, source)
            manifest.write_text(json.dumps(metadata))
            self.assertEqual(runner.checked_candidate(root, source)['candidateLockSha256'],
                             metadata['candidateLockSha256'])
            lock.write_bytes(b'changed after verification\n')
            with self.assertRaisesRegex(GuiFailure, 'candidate_lock_not_verified'):
                runner.checked_candidate(root, source)

    def test_xcode_selects_exact_native_case_on_known_test_action(self):
        base = ['xcodebuild', '-scheme', 'Runner']
        bundle = Path('/tmp/owned/private.xcresult')
        self.assertEqual(runner.test_command(base, bundle),
                         base + ['-only-testing:' + TEST_SELECTION, '-resultBundlePath', str(bundle), 'test'])

    def test_harness_does_not_review_public_requests_before_valid_challenge(self):
        process, channel, target = Mock(), Mock(), Mock()
        process.poll.return_value = None
        channel.receive.return_value = b'invalid challenge'
        with self.assertRaisesRegex(GuiFailure, 'channel_challenge_invalid'):
            runner.requests_and_disconnect(process, channel, {'a': target})
        channel.receive.assert_called_once_with('testReady')
        channel.send.assert_not_called()
        target.review.assert_not_called()

    def test_native_startup_diagnostics_whitelist_and_last_known_phase(self):
        log = ("Test Case '-[RunnerTests.MacosS06UITests testTwoPairedPeersInNativeWindow]' started.\n"
               "HP_S06_NATIVE_STAGE=entered\n"
               "HP_S06_NATIVE_STAGE=releaseRead\n"
               "HP_S06_NATIVE_STAGE=secretValue\n"
               "HP_S06_NATIVE_STAGE=pairA\n"
               "HP_S06_NATIVE_STAGE=keyA\n"
               "HP_S06_NATIVE_STAGE=pairA\n"
               "HP_S06_NATIVE_FAILURE=private_release_decode_failed\n"
               "HP_S06_NATIVE_FAILURE=private_token\n"
               "/private/secret-data/RunnerTests.swift:168:12: error: private fixture text\n")
        facts = log_facts(log)
        self.assertEqual(facts['loggedStages'], ['entered', 'releaseRead', 'pairA', 'keyA'])
        self.assertEqual(facts['lastLoggedStage'], 'pairA')
        self.assertIs(facts['testCaseStarted'], True)
        self.assertEqual(facts['fixedFailure'], 'private_release_decode_failed')
        self.assertEqual(facts['testSourceFailureLines'], [168])
        for leak in ('secretValue', 'private_token', '/private', 'private fixture text'):
            self.assertNotIn(leak, json.dumps(facts))
        result = log_facts('No tests were found.\nEarly unexpected exit.\n')
        self.assertEqual(result['startupFlags'], ['noTestsSelected', 'runnerConnectionLost'])
        self.assertIs(result['testCaseStarted'], False)
        self.assertNotIn('lastLoggedStage', result)

    def test_xcresult_counts_are_only_small_numeric_fields(self):
        raw = {'totalTestCount': 1, 'failedTests': 1, 'passedTests': True, 'skippedTests': 9000,
               'configuration': 'secret-data', 'failedDetails': ['secret-path']}
        self.assertEqual(checked_summary(raw), {'totalTestCount': 1, 'failedTests': 1})
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            log = root / 'private-log'
            bundle = root / 'private.xcresult'
            bundle.mkdir()
            log.write_text('HP_S06_NATIVE_STAGE=entered\nprivate raw log\n')
            def summary_command(_args, *, stdout, **_opts):
                stdout.write(json.dumps(raw).encode())
                return subprocess.CompletedProcess(_args, 0)
            with patch('macos_s06_diagnostics.subprocess.run', side_effect=summary_command):
                result = diagnostics(log, bundle, 65)
            self.assertEqual(result['lastLoggedStage'], 'entered')
            self.assertEqual(result['xcresultTestCounts'], {'totalTestCount': 1, 'failedTests': 1})
            self.assertEqual(result['xcodeExitCode'], 65)
            self.assertNotIn('secret', json.dumps(result))
            self.assertNotIn('private raw log', json.dumps(result))

    @unittest.skipUnless(BINARY and sys.platform == 'darwin', 'requires explicit owned-stock macOS opt-in')
    def test_two_real_stock_peers_advance_their_own_terminal_and_close(self):
        keys = MemoryKeyStore()
        with tempfile.TemporaryDirectory(prefix='hps06t-', dir='/tmp') as directory:
            base = Path(directory).resolve()
            with runner.owned_channel(base) as channel, runner.fixtures(Path(BINARY), base) as (
                    targets, owned, metadata, configs):
                self.assertEqual(metadata['herdrSha256'], runner.HERDR_SHA256)
                test = runner.NativeChannel(channel.executable, channel.nonce, party='test')
                release = runner.release_payload(configs)
                channel.send('release', release)
                self.assertEqual(test.receive('release'), release)
                self.check_swift_release(base, release)
                self.check_private_channel(channel, test)
                with ExitStack() as readers:
                    clients = []
                    for index, (target, config) in enumerate(zip(targets.values(), configs)):
                        handle = keys.create()
                        pairing = PendingPairing(keys, handle, account=config['username'],
                            expected_host_key=target.host.pin, device='Owned local test', now=int(time.time()))
                        request = encode(pairing.request)
                        test.send(f'request{index}', request)
                        host_request = channel.receive(f'request{index}')
                        self.assertEqual(host_request, request)
                        review = target.review(host_request)
                        response = target.approve(host_request, request_id=review['requestId'],
                            device_fingerprint=review['deviceFingerprint'], reviewed=True)
                        channel.send(f'response{index}', response)
                        public_response = test.receive(f'response{index}')
                        self.assertEqual(public_response, response)
                        pairing.accept(public_response, now=int(time.time()), source_reviewed=True)
                        private = target.root / 'client'
                        private.write_bytes(keys._keys[handle].private_bytes(
                            Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()))
                        private.chmod(0o600)
                        command = shlex.join([config['herdrPath'], '--session', config['session'],
                                              'terminal', 'session', 'observe', config['terminalId'],
                                              '--cols', '80', '--rows', '24'])
                        ssh = ssh_args(target.root, config['port'], config['username'], private, command)
                        client = readers.enter_context(subprocess.Popen(
                            ssh, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0))
                        readers.callback(self.stop_client, client)
                        clients.append(client)
                    for client, config in zip(clients, configs):
                        first, second = self.frame(client), self.frame(client)
                        self.assertEqual(first['type'], 'terminal.frame')
                        self.assertIs(first['full'], True)
                        self.assertIs(second['full'], False)
                        self.assertEqual((first['width'], first['height']), (80, 24))
                        self.assertEqual(second['seq'], first['seq'] + 1)
                        pattern = re.escape(config['marker'].encode()) + rb' ([0-9]{6})'
                        pixels = [base64.b64decode(frame['bytes'], validate=True) for frame in (first, second)]
                        full = re.search(pattern, pixels[0])
                        self.assertIsNotNone(full)
                        # herdr only writes the changed digits in a delta.
                        move = re.search(rb'\x1b\[12;([0-9]+)H(?:\x1b\[[0-9;]+m)*([0-9]+)', pixels[1])
                        self.assertIsNotNone(move)
                        start = int(move.group(1)) - 8
                        digits, replacement = full.group(1), move.group(2)
                        self.assertTrue(0 <= start < start + len(replacement) <= len(digits))
                        updated = digits[:start] + replacement + digits[start + len(replacement):]
                        self.assertGreater(int(updated), int(digits))
                    self.assertTrue(all(client.poll() is None for client in clients))
                for target in targets.values():
                    wait_for(lambda: runner.peer_connection_evidence(target.approval) ==
                             {'authenticationCount': 1, 'closed': True}, 'owned_stock_peer_not_closed', timeout=5)
                    self.assertEqual(target.audit(b'')['receivedBytes'], 0)
                wait_for(lambda: all(json.loads((target.root / 'pty-size.json').read_text())['elapsedMs'] >= 1000
                                     for target in targets.values()), 'owned_pty_record_too_short', timeout=5)
            for target in targets.values():
                self.assertEqual(runner.final_pty(target.root)['changes'], 0)
                self.assertEqual((target.root / 'authorized_keys').read_bytes(), b'')
                self.assertFalse((target.root / 'capture-running').exists())
                self.assertIsNotNone(target.approval.revocation_response)
            self.assertTrue(all(child.poll() is not None for child in owned))
            self.assertTrue(channel.released)
            try:
                self.assertIsNone(test.receive('release'))
                self.assertIsNone(channel.receive('request0'))
                self.assertIsNone(channel.receive('request1'))
            finally:
                channel.call('releaseAll')
        self.assertFalse(base.exists())

    def check_private_channel(self, host, test):
        other = runner.NativeChannel(host.executable, secrets.token_hex(32), party='test')
        try:
            self.assertIsNone(other.receive('release'))
        finally:
            runner.NativeChannel(host.executable, other.nonce).call('releaseAll')
        for sender, topic, data in ((host, 'release', b'replay'), (host, 'testReady', b'wrong writer'),
                                    (host, 'unknown', b'wrong topic'), (test, 'request0', b'x' * 2049)):
            with self.assertRaisesRegex(GuiFailure, 'private_channel_rejected'):
                sender.send(topic, data)
        challenge = str(uuid.uuid4()).encode()
        test.send('testReady', challenge)
        self.assertEqual(host.receive('testReady'), challenge)
        host.send('hostReady', challenge)
        self.assertEqual(test.receive('hostReady'), challenge)

    def check_swift_release(self, base, payload):
        compiler = shutil.which('swiftc')
        self.assertIsNotNone(compiler, 'macOS stock fixture verification requires Swift')
        driver = base / 'main.swift'
        driver.write_text('''import Foundation
do {
    let fixture = try JSONDecoder().decode(MacosS06Fixture.self, from: FileHandle.standardInput.readDataToEndOfFile())
    print(fixture.hasIndependentTargets ? "valid" : "binding")
} catch {
    print("decode")
}
''')
        probe = base / 'decode-fixture'
        subprocess.run([compiler, str(runner.HERE / 'macos_s06_fixture.swift'), str(driver), '-o', str(probe)],
                       check=True, capture_output=True, timeout=25)
        self.assertEqual(subprocess.check_output([probe], input=payload, timeout=5), b'valid\n')
        release = json.loads(payload)
        wrong_port = copy.deepcopy(release)
        wrong_port['peers'][0]['port'] = str(wrong_port['peers'][0]['port'])
        wrong_key = copy.deepcopy(release)
        wrong_key['peers'][0]['terminal_id'] = wrong_key['peers'][0].pop('terminalId')
        wrong_binding = copy.deepcopy(release)
        wrong_binding['peers'][1]['terminalId'] = wrong_binding['peers'][0]['terminalId']
        for state, expected in ((wrong_port, b'decode\n'), (wrong_key, b'decode\n'), (wrong_binding, b'binding\n')):
            self.assertEqual(subprocess.check_output([probe], input=json.dumps(state).encode(), timeout=5), expected)

    @staticmethod
    def frame(client):
        # First frame contains the controlled few cells. Keep a bounded line
        # and a separate read deadline for each active SSH peer.
        from selectors import DefaultSelector, EVENT_READ
        with DefaultSelector() as selector:
            selector.register(client.stdout, EVENT_READ)
            if not selector.select(10):
                raise RuntimeError('owned_stock_frame_timeout')
            return json.loads(client.stdout.readline(65537))

    @staticmethod
    def stop_client(client):
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
