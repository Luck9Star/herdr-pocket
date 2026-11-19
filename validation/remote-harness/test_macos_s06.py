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
    from herdr_pocket_helper.profile import encode_profile
    from herdr_pocket_helper.wire import fingerprint
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
        report = {'checks': dict.fromkeys(runner.CHECKS, True), 'widths': [1440, 700, 1440],
                  'autoResumeTicks': [280, 310, 318]}
        self.assertEqual(runner.checked_ui_result(report), report)
        for key in runner.CHECKS:
            changed = copy.deepcopy(report)
            changed['checks'][key] = False
            with self.assertRaisesRegex(GuiFailure, 'checks_incomplete'):
                runner.checked_ui_result(changed)
        for widths in ([1440, 1440, 1440], [1440, 700], [1440, 700.0, 1440]):
            with self.assertRaisesRegex(GuiFailure, 'widths_invalid'):
                runner.checked_ui_result({**report, 'widths': widths})
        self.assertIn('reviewedPublicProfiles', report['checks'])
        self.assertIn('localProfilesAbsentFromBoard', report['checks'])
        self.assertNotIn('localIdentitiesRemoved', report['checks'])

    def test_native_report_requires_auto_resumed_original_observation_and_advancing_ticks(self):
        report = {'checks': dict.fromkeys(runner.CHECKS, True), 'widths': [1440, 700, 1440],
                  'autoResumeTicks': [280, 310, 318]}
        self.assertIn('autoResumedOriginalObservation', report['checks'])
        self.assertEqual(runner.checked_ui_result(report), report)
        previous = copy.deepcopy(report)
        del previous['checks']['autoResumedOriginalObservation']
        previous['checks']['explicitResume'] = True
        with self.assertRaisesRegex(GuiFailure, 'checks_incomplete'):
            runner.checked_ui_result(previous)
        for ticks in (None, [280, 310], [280, 280, 310], [280, 310, 310], [280, 310, 299],
                      [True, 310, 318], [280, 310, 1000000]):
            with self.assertRaisesRegex(GuiFailure, 'auto_resume_ticks_invalid'):
                runner.checked_ui_result({**report, 'autoResumeTicks': ticks})

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

    def test_broker_error_publication_accepts_only_fixed_category(self):
        channel = runner.NativeChannel(Path('/tmp/owned/broker'), '1' * 64)
        for stderr, expected in ((b'topic_occupied\n', 'topic_occupied'),
                                 (b'write_denied\n', 'write_denied'),
                                 (b'read_unavailable\n', 'read_unavailable'),
                                 (b'prepare_denied\n', 'prepare_denied'),
                                 (b'write_denied\nprivate-source', 'rejected')):
            failure = subprocess.CompletedProcess([], 2, b'', stderr)
            with patch('macos_s06.subprocess.run', return_value=failure):
                with self.assertRaises(GuiFailure) as raised:
                    channel.send('release', b'fixture')
            self.assertEqual(str(raised.exception), 's06_native_private_channel_' + expected)

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
        for category in ('topic_occupied', 'prepare_denied', 'write_denied', 'read_unavailable'):
            marker = 'private_channel_' + category
            facts = log_facts(f'HP_S06_NATIVE_FAILURE={marker}\n')
            self.assertEqual(facts['fixedFailure'], marker)

    def test_native_pair_control_diagnostics_publish_only_fixed_counts(self):
        log = ("HP_S06_NATIVE_STAGE=pairA\n"
               "HP_S06_NATIVE_PAIR_CONTROL=entry\n"
               "HP_S06_NATIVE_PAIR_CONTROL=host\n"
               "HP_S06_NATIVE_PAIR_CONTROL=privateValue\n"
               "HP_S06_NATIVE_PAIR_AX=host,2,1,1,1,0,0,0,1,0\n"
               "HP_S06_NATIVE_PAIR_AX=host,2,1,1,1,0,0,0,1,0,private-value\n"
               "HP_S06_NATIVE_PAIR_AX=host,2,1,1,1,0,0,0,1,90000\n"
               "HP_S06_NATIVE_PAIR_AX=port,2,1,1,1,0,0,0,1,0\n"
               "HP_S06_NATIVE_PAIR_AX=host,2,1,1,1,2,0,0,1,0\n"
               "HP_S06_NATIVE_FAILURE=unique_visible_control_missing\n")
        facts = log_facts(log)
        self.assertEqual(facts['lastPairControl'], 'host')
        self.assertEqual(facts['pairControlFailure'], {
            'control': 'host', 'named': 2, 'expectedRole': 1, 'withinRegion': 1,
            'hittable': 1, 'enabled': 0, 'namedTextViews': 0, 'namedEditableChildren': 0,
            'formTitleHittable': 1, 'storageUnavailableHittable': 0,
        })
        self.assertNotIn('private', json.dumps(facts))
        incomplete = log_facts('HP_S06_NATIVE_PAIR_CONTROL=host\nHP_S06_NATIVE_PAIR_AX=port,2,1,1,1,0,0,0,1,0\n')
        self.assertEqual(incomplete['lastPairControl'], 'host')
        self.assertNotIn('pairControlFailure', incomplete)

    def test_pair_readback_facts_are_fixed_and_scoped_to_the_latest_field(self):
        old = ("HP_S06_NATIVE_PAIR_CONTROL=host\n"
               "HP_S06_NATIVE_PAIR_INPUT=host,verified\n"
               "HP_S06_NATIVE_PAIR_READ=host,011111\n")
        current = ("HP_S06_NATIVE_PAIR_CONTROL=host\n"
                   "HP_S06_NATIVE_PAIR_INPUT=host,typing\n"
                   "HP_S06_NATIVE_PAIR_INPUT=host,copiedSecret\n"
                   "HP_S06_NATIVE_PAIR_INPUT=user,verified\n"
                   "HP_S06_NATIVE_PAIR_READ=user,111111\n"
                   "HP_S06_NATIVE_PAIR_READ=host,111111,private-value\n")
        facts = log_facts(old + current)
        self.assertEqual(facts['lastPairInputStep'], 'typing')
        self.assertNotIn('pairReadback', facts)
        after = ("HP_S06_NATIVE_PAIR_INPUT=host,copy\n"
                 "HP_S06_NATIVE_PAIR_READ=host,101110\n"
                 "HP_S06_NATIVE_PAIR_READ=host,000001\n")
        facts = log_facts(old + current + after)
        self.assertEqual(facts['lastPairInputStep'], 'copy')
        self.assertEqual(facts['pairReadback'], {
            'control': 'host', 'ownerAXBeforeExact': True, 'ownerAXAfterExact': False,
            'ownedEditorPresent': True, 'ownedEditorAXExact': True,
            'clipboardChanged': True, 'clipboardExact': False,
        })
        self.assertNotIn('private', json.dumps(facts))
        self.assertNotIn('Secret', json.dumps(facts))

    def test_pair_focus_diagnostics_accept_only_fixed_phase_and_failure(self):
        log = ("HP_S06_NATIVE_PAIR_CONTROL=host\n"
               "HP_S06_NATIVE_PAIR_INPUT=host,focus\n"
               "HP_S06_NATIVE_PAIR_INPUT=host,privateFocus\n"
               "HP_S06_NATIVE_FAILURE=public_pair_focus_unproven\n"
               "HP_S06_NATIVE_FAILURE=private_value\n")
        facts = log_facts(log)
        self.assertEqual(facts['lastPairInputStep'], 'focus')
        self.assertEqual(facts['fixedFailure'], 'public_pair_focus_unproven')
        self.assertNotIn('private', json.dumps(facts))

    def test_target_review_diagnostics_publish_only_fixed_states(self):
        log = ("HP_S06_NATIVE_PAIR_CONTROL=targetReview\n"
               "HP_S06_NATIVE_PAIR_REVIEW=A,before,unchecked,1,0\n"
               "HP_S06_NATIVE_PAIR_REVIEW=A,after,checked,1,1\n"
               "HP_S06_NATIVE_PAIR_REVIEW=B,after,checked,1,1\n"
               "HP_S06_NATIVE_PAIR_REVIEW=B,before,unchecked,1,0\n"
               "HP_S06_NATIVE_PAIR_REVIEW=B,after,unknown,1,1,private-value\n"
               "HP_S06_NATIVE_PAIR_REVIEW=A,after,private,1,0\n"
               "HP_S06_NATIVE_FAILURE=public_pair_review_state_unconfirmed\n")
        facts = log_facts(log)
        before = {'checkbox': 'unchecked', 'buttonAXEnabled': True, 'buttonBrandFilled': False}
        after = {'checkbox': 'checked', 'buttonAXEnabled': True, 'buttonBrandFilled': True}
        self.assertEqual(facts['targetReview'], {'A': {'before': before, 'after': after}, 'B': {'before': before}})
        self.assertEqual(facts['fixedFailure'], 'public_pair_review_state_unconfirmed')
        self.assertNotIn('private', json.dumps(facts))

    def test_generated_native_focus_color_comes_from_app_tokens(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            assets = app / 'assets/shared'
            assets.mkdir(parents=True)
            token = assets / 'design-tokens-v2.json'
            generated = app / 'macos/RunnerTests/RunnerTests.swift'
            generated.parent.mkdir(parents=True)
            nonce = '7' * 64
            with patch.object(runner, 'prepare'), patch.object(runner, 'install_test_semantics_hook'):
                token.write_text(json.dumps({'colors': {'brand': '#123aEf'}}))
                runner.prepare_test(app, nonce)
                source = generated.read_text()
                self.assertIn('UInt32("123aEf", radix: 16)', source)
                self.assertIn('enum MacosS06FocusOutline', source)
                self.assertNotIn('__HP_S06_FOCUS_BRAND__', source)
                token.write_text(json.dumps({'colors': {'brand': 'private-text'}}))
                with self.assertRaisesRegex(GuiFailure, 'focus_token_invalid'):
                    runner.prepare_test(app, nonce)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), 'requires local macOS AppKit')
    def test_focus_outline_requires_both_edges_and_ignores_inner_color(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            driver = root / 'main.swift'
            driver.write_text('''import CoreGraphics
let sRGB = CGColorSpace(name: CGColorSpace.sRGB)!
let context = CGContext(data: nil, width: 144, height: 64, bitsPerComponent: 8, bytesPerRow: 144 * 4,
    space: sRGB, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
context.setFillColor(red: 1, green: 1, blue: 1, alpha: 1)
context.fill(CGRect(x: 0, y: 0, width: 144, height: 64))
context.setFillColor(red: 79.0 / 255, green: 70.0 / 255, blue: 229.0 / 255, alpha: 1)
context.fill(CGRect(x: 72, y: 0, width: 1, height: 64))
func focused() -> Bool { MacosS06FocusOutline.present(in: context.makeImage()!, width: 72, brand: 0x4f46e5) }
precondition(!focused())
context.fill(CGRect(x: 4, y: 0, width: 1, height: 64))
precondition(!focused())
context.fill(CGRect(x: 139, y: 0, width: 1, height: 64))
precondition(focused())
precondition(MacosS06FocusOutline.filledButton(in: context.makeImage()!, brand: 0x4f46e5) == false)
context.fill(CGRect(x: 18, y: 0, width: 18, height: 64))
precondition(MacosS06FocusOutline.filledButton(in: context.makeImage()!, brand: 0x4f46e5) == false)
context.fill(CGRect(x: 108, y: 0, width: 18, height: 64))
precondition(MacosS06FocusOutline.filledButton(in: context.makeImage()!, brand: 0x4f46e5) == true)
''')
            executable = root / 'check-outline'
            subprocess.run(['swiftc', runner.HERE / 'macos_s06_focus.swift', driver, '-o', executable],
                           check=True, timeout=30)
            subprocess.run([executable], check=True, timeout=5)

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
                        self.assertIsNone(channel.receive(f'request{index}'))
                        test.send(f'request{index}', request)
                        host_request = channel.receive(f'request{index}')
                        self.assertEqual(host_request, request)
                        review = target.review(host_request)
                        response = target.approve(host_request, request_id=review['requestId'],
                            device_fingerprint=review['deviceFingerprint'], reviewed=True)
                        self.assertIsNone(test.receive(f'response{index}'))
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
                        move_pattern = rf'\x1b\[{runner.MARKER_ROW};([0-9]+)H(?:\x1b\[[0-9;]+m)*([0-9]+)'
                        move = re.search(move_pattern.encode(), pixels[1])
                        self.assertIsNotNone(move)
                        first_digit = runner.MARKER_COLUMN + len(config['marker']) + 1
                        start = int(move.group(1)) - first_digit
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
        cases = ((host, 'release', b'replay', 'topic_occupied'),
                 (host, 'testReady', b'wrong writer', 'message_rejected'),
                 (host, 'unknown', b'wrong topic', 'message_rejected'),
                 (test, 'request0', b'x' * 2049, 'message_rejected'))
        for sender, topic, data, failure in cases:
            with self.assertRaisesRegex(GuiFailure, 'private_channel_' + failure):
                sender.send(topic, data)
        self.assertIsNotNone(test.receive('release'))
        challenge = str(uuid.uuid4()).encode()
        # The live host polls before XCTest sends. On R3 the empty board's
        # writeObjects returned false in this order, unlike write-then-read.
        self.assertIsNone(host.receive('testReady'))
        test.send('testReady', challenge)
        self.assertEqual(host.receive('testReady'), challenge)
        self.assertIsNone(test.receive('hostReady'))
        host.send('hostReady', challenge)
        self.assertEqual(test.receive('hostReady'), challenge)

    def check_swift_release(self, base, payload):
        compiler = shutil.which('swiftc')
        self.assertIsNotNone(compiler, 'macOS stock fixture verification requires Swift')
        driver = base / 'main.swift'
        driver.write_text('''import Foundation
do {
    let fixture = try JSONDecoder().decode(MacosS06Fixture.self, from: FileHandle.standardInput.readDataToEndOfFile())
    if fixture.hasIndependentTargets {
        for peer in fixture.peers {
            let profile = try JSONEncoder().encode(peer.publicProfile)
            let record = [String(decoding: profile, as: UTF8.self), peer.profilePreview]
            let line = try JSONEncoder().encode(record)
            print(String(decoding: line, as: UTF8.self))
        }
    } else {
        print("binding")
    }
} catch {
    print("decode")
}
''')
        probe = base / 'decode-fixture'
        subprocess.run([compiler, str(runner.HERE / 'macos_s06_fixture.swift'), str(driver), '-o', str(probe)],
                       check=True, capture_output=True, timeout=25)
        rows = subprocess.check_output([probe], input=payload, timeout=5).splitlines()
        release = json.loads(payload)
        self.assertEqual(len(rows), 2)
        fields = ('host', 'port', 'username', 'session', 'socketPath', 'herdrPath', 'expectedHostKey')
        for row, peer in zip(rows, release['peers']):
            profile_wire, preview = json.loads(row)
            profile = json.loads(profile_wire)
            self.assertEqual(profile, {**{key: peer[key] for key in fields}, 'provider': 'direct',
                                       'version': 1, 'type': 'herdr-connection-profile'})
            self.assertEqual(json.loads(encode_profile(profile)), profile)
            self.assertEqual(fingerprint(profile['expectedHostKey']), peer['fingerprint'])
            self.assertEqual(preview.splitlines(), [
                '待预览（尚未信任）', f"主机 {peer['host']}:{peer['port']}", f"账号 {peer['username']}",
                '网络 direct', f"会话 {peer['session']}", f"socket {peer['socketPath']}",
                f"herdr {peer['herdrPath']}", f"主机指纹 {peer['fingerprint']}",
            ])
            for mutation in ({'privateKeyPem': 'forbidden'}, {'port': str(profile['port'])},
                             {'session': 'default'}):
                with self.assertRaises(ValueError):
                    encode_profile({**profile, **mutation})

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
