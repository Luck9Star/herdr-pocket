"""Standard-library guards plus an actual loopback SSH protocol/cleanup test."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from threading import Event
import time
import sys
import types
import struct
from subprocess import CompletedProcess
from unittest.mock import MagicMock, Mock, patch
import unittest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('ordinary_android_runner', HERE / 'flutter_direct_ssh_android.py')
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


class GuardTests(unittest.TestCase):
    def test_status_zero_offline_screenshot_gets_a_transport_diagnostic(self):
        request = {'tag': 'key-rotation', 'attempt': 1, 'bounds': [0, 20, 400, 500],
                   'viewSize': [400, 600], 'observedTarget': 'fixture@127.0.0.1:40002'}
        reply = CompletedProcess([], 0, b'error: device offline\n', b'')
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(runner, 'adb', return_value=reply) as adb, \
             patch.object(runner, 'encrypted_device_state', return_value='offline'):
            completed = {}
            with self.assertRaisesRegex(runner.Failure, 'direct_android_screenshot_offline') as failure:
                runner.screen_checkpoint(request, completed, Mock(), Mock(username='fixture', port=40002),
                                         'cache/herdr-direct-ssh-123', Path(temp))
            self.assertEqual(completed, {})
            self.assertEqual(list(Path(temp).iterdir()), [])
            self.assertEqual(adb.call_count, 1)
            diagnostic = failure.exception.diagnostic
            self.assertEqual(diagnostic['deviceState'], 'offline')
            self.assertEqual(diagnostic['source'], 'integration')
            self.assertEqual((diagnostic['tag'], diagnostic['attempt']), ('key-rotation', 1))
            self.assertNotIn('error: device offline', json.dumps(diagnostic))

    def test_frozen_screenshot_requires_fixed_path_one_body_read_and_exact_size(self):
        relative = 'cache/herdr-direct-ssh-123'
        path = relative + '/rotation-connected.png'
        png = b'\x89PNG\r\n\x1a\n' + b'body'
        size = CompletedProcess([], 0, str(len(png)).encode() + b'\n', b'')
        body = CompletedProcess([], 0, png, b'')
        with patch.object(runner, 'adb', side_effect=[size, body]) as adb:
            self.assertEqual(runner.read_screen_png('integration', relative=relative, name='rotation-connected'), png)
            self.assertEqual([call.args for call in adb.call_args_list], [
                ('shell', '-T', 'run-as', runner.PACKAGE, 'stat', '-c', '%s', path),
                ('exec-out', 'run-as', runner.PACKAGE, 'cat', path),
            ])
        for wrong_relative, wrong_name in ((relative + '/..', 'rotation-connected'),
                                           (relative, 'private-key'), ('cache/foreign-123', 'connected')):
            with patch.object(runner, 'adb') as adb, self.assertRaisesRegex(runner.Failure, 'path_invalid'):
                runner.read_screen_png('integration', relative=wrong_relative, name=wrong_name)
            adb.assert_not_called()

        negatives = (
            ('missing', [CompletedProcess([], 1, b'', f"stat: '{path}': No such file or directory\n".encode())]),
            ('missing', [size, CompletedProcess([], 0, f'cat: {path}: No such file or directory\n'.encode(), b'')]),
            ('stat_failed', [CompletedProcess([], 0, b'private text\n', b'')]),
            ('oversize', [CompletedProcess([], 0, str(runner.SCREENSHOT_MAX_BYTES + 1).encode(), b'')]),
            ('empty', [CompletedProcess([], 0, b'0\n', b'')]),
            ('empty', [size, CompletedProcess([], 0, b'', b'')]),
            ('short_read', [size, CompletedProcess([], 0, png[:-1], b'')]),
            ('short_read', [size, CompletedProcess([], 0, png[:5], b'')]),
            ('size_mismatch', [size, CompletedProcess([], 0, png + b'a', b'')]),
            ('signature_invalid', [size, CompletedProcess([], 0, b'invalid text', b'')]),
            ('read_failed', [size, CompletedProcess([], 0, png, b'private stderr')]),
            ('read_timeout', [size, __import__('subprocess').TimeoutExpired('private command', 30)]),
        )
        for outcome, replies in negatives:
            with self.subTest(outcome=outcome), patch.object(runner, 'adb', side_effect=replies) as adb, \
                 patch.object(runner, 'encrypted_device_state', return_value='offline'), \
                 self.assertRaisesRegex(runner.Failure, '^direct_android_screenshot_' + outcome + '$') as failure:
                runner.read_screen_png('integration', relative=relative, name='rotation-connected')
            self.assertEqual(adb.call_count, len(replies))
            diagnostic = failure.exception.diagnostic
            self.assertEqual(diagnostic['outcome'], outcome)
            self.assertEqual(diagnostic['deviceState'], 'offline')
            self.assertNotIn('private', json.dumps(diagnostic))
            self.assertNotIn(path, json.dumps(diagnostic))

    def test_system_screenshot_classifies_channel_failure_before_ocr(self):
        reply = CompletedProcess([], 1, b'', b'error: device offline\n')
        with patch.object(runner, 'adb', return_value=reply) as adb, \
             self.assertRaisesRegex(runner.Failure, '^direct_android_screenshot_offline$') as failure:
            runner.read_screen_png('device')
        adb.assert_called_once_with('exec-out', 'screencap', '-p', check=False)
        self.assertEqual(failure.exception.diagnostic['source'], 'device')

    def test_screen_checkpoint_compares_actual_device_pixels_and_keeps_failure_evidence(self):
        class GateError(RuntimeError):
            def __init__(self):
                super().__init__('terminal_screenshot_echo_not_visible')
                self.evidence = {'markerVisible': False, 'tokenVisible': False}

        calls = []
        def gate(png, *, expected_token, bounds):
            calls.append((png, expected_token, bounds))
            if png.endswith(b'old'):
                raise GateError()
            return {'markerVisible': True, 'tokenVisible': True}

        gate_module = types.SimpleNamespace(ScreenshotGateError=GateError, verify_terminal_screenshot=gate)
        fixture = Mock(screen_token='ACDEFHJKMNPQ', username='fixture', port=40001)
        rotation_fixture = Mock(screen_token='RTUVWXY34679', username='fixture', port=40002)
        header = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR' + struct.pack('>II', 400, 600)
        png_old = header + b'old'
        png_new = header + b'new'
        replies = []
        def adb(*args, **kwargs):
            if args[0] == 'exec-out':
                return CompletedProcess([], 0, png_old if args[1] == 'run-as' else replies.pop(0), b'')
            if args[4:5] == ('stat',):
                return CompletedProcess([], 0, str(len(png_old)).encode(), b'')
            return CompletedProcess([], 0, b'', b'')
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {'terminal_screenshot_gate': gate_module}), patch.object(runner, 'adb', side_effect=adb):
            output = Path(temp)
            completed = {}
            request = {'tag': 'key-rotation', 'attempt': 1, 'bounds': [0, 20, 400, 500], 'viewSize': [400, 600], 'observedTarget': 'fixture@127.0.0.1:40002'}
            replies.append(png_old)
            runner.screen_checkpoint(request, completed, fixture, rotation_fixture, 'cache/herdr-direct-ssh-123', output)
            self.assertFalse(completed['key-rotation']['accepted'])
            failure = json.loads((output / 'key-rotation-first-failed.json').read_text())
            self.assertFalse(failure['checks']['device']['evidence']['markerVisible'])
            self.assertEqual((output / 'key-rotation-first-failed-device.png').read_bytes(), png_old)
            runner.screen_checkpoint(request, completed, fixture, rotation_fixture, 'cache/herdr-direct-ssh-123', output)
            self.assertEqual(len(calls), 2)
            replies.append(png_new)
            runner.screen_checkpoint({**request, 'attempt': 2}, completed, fixture, rotation_fixture, 'cache/herdr-direct-ssh-123', output)
            self.assertTrue(completed['key-rotation']['accepted'])
            self.assertEqual(completed['key-rotation']['expectedTarget'], 'fixture@127.0.0.1:40002')
            proof = json.loads((output / 'key-rotation-screen-proof.json').read_text())
            self.assertEqual(proof['expectedTarget'], 'fixture@127.0.0.1:40002')
            self.assertEqual(proof['checks']['integration']['status'], 'failed')
            self.assertEqual(proof['checks']['device']['status'], 'passed')
            self.assertEqual((output / 'rotation-connected-device.png').read_bytes(), png_new)
            self.assertTrue(all(call[1:] == ('RTUVWXY34679', (0, 20, 400, 500)) for call in calls))
            replies.append(png_new)
            runner.screen_checkpoint({**request, 'tag': 'ordinary', 'attempt': 1,
                'observedTarget': 'fixture@127.0.0.1:40001'}, completed, fixture, rotation_fixture,
                'cache/herdr-direct-ssh-123', output)
            ordinary = json.loads((output / 'ordinary-screen-proof.json').read_text())
            self.assertEqual(ordinary['expectedTarget'], 'fixture@127.0.0.1:40001')
            self.assertEqual(completed['ordinary']['expectedTarget'], 'fixture@127.0.0.1:40001')
            self.assertEqual(calls[-1][1], 'ACDEFHJKMNPQ')
            with self.assertRaises(runner.Failure):
                runner.screen_checkpoint({**request, 'attempt': 4}, completed, fixture, rotation_fixture, 'cache/herdr-direct-ssh-123', output)
            with self.assertRaises(runner.Failure):
                runner.screen_checkpoint({**request, 'tag': 'ordinary', 'attempt': True}, completed, fixture, rotation_fixture, 'cache/herdr-direct-ssh-123', output)

    def test_screen_rejects_target_mismatch_independently_for_each_peer(self):
        fixture = Mock(username='fixture', port=40001)
        rotation_fixture = Mock(username='fixture', port=40002)
        request = {'tag': 'ordinary', 'attempt': 1, 'bounds': [0, 20, 400, 500],
                   'viewSize': [400, 600], 'observedTarget': 'fixture@127.0.0.1:40002'}
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, 'adb') as adb:
            for tag, observed in (('ordinary', 'fixture@127.0.0.1:40002'),
                                  ('key-rotation', 'fixture@127.0.0.1:40001'),
                                  ('ordinary', None)):
                with self.subTest(tag=tag, observed=observed), self.assertRaisesRegex(
                        runner.Failure, 'active_target_mismatch'):
                    runner.screen_checkpoint({**request, 'tag': tag, 'observedTarget': observed},
                        {}, fixture, rotation_fixture, 'cache/herdr-direct-ssh-123', Path(temp))
            adb.assert_not_called()

    def test_screen_geometry_mismatch_saves_both_originals_and_sizes(self):
        header = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR'
        integration = header + struct.pack('>II', 400, 600)
        device = header + struct.pack('>II', 400, 650)
        def adb(*args, **kwargs):
            if args[4:5] == ('stat',):
                return CompletedProcess([], 0, str(len(integration)).encode(), b'')
            return CompletedProcess([], 0, integration if args[1] == 'run-as' else device, b'')
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, 'adb', side_effect=adb):
            output = Path(temp)
            screens = {}
            with self.assertRaisesRegex(runner.Failure, 'geometry_mismatch'):
                runner.screen_checkpoint({'tag': 'key-rotation', 'attempt': 1,
                    'bounds': [0, 20, 400, 500], 'viewSize': [400, 600], 'observedTarget': 'fixture@127.0.0.1:40002'}, screens, Mock(), Mock(username='fixture', port=40002),
                    'cache/herdr-direct-ssh-123', output)
            self.assertEqual(screens, {})
            self.assertEqual((output / 'key-rotation-geometry-device.png').read_bytes(), device)
            self.assertEqual((output / 'key-rotation-geometry-integration.png').read_bytes(), integration)
            sizes = json.loads((output / 'key-rotation-geometry.json').read_text())['imageSizes']
            self.assertEqual(sizes, {'integration': [400, 600], 'device': [400, 650]})

    def test_screen_adb_failure_keeps_last_completed_observation(self):
        rotation = {'attempt': 1, 'accepted': True, 'expectedTarget': 'fixture@127.0.0.1:40002'}
        ordinary = {'attempt': 3, 'accepted': False, 'expectedTarget': 'fixture@127.0.0.1:40001'}
        completed = {'key-rotation': rotation, 'ordinary': ordinary}
        request = {'tag': 'ordinary', 'attempt': 4, 'bounds': [0, 20, 400, 500],
                   'viewSize': [400, 600], 'observedTarget': 'fixture@127.0.0.1:40001'}
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, 'adb', side_effect=runner.Failure('adb_failed')):
            with self.assertRaisesRegex(runner.Failure, 'adb_failed'):
                runner.screen_checkpoint(request, completed, Mock(username='fixture', port=40001),
                    Mock(username='fixture', port=40002), 'cache/herdr-direct-ssh-123', Path(temp))
        self.assertEqual(completed, {'key-rotation': rotation, 'ordinary': ordinary})

    def test_failed_run_exports_only_observed_screenshot_checkpoints(self):
        rotation = {'attempt': 1, 'accepted': True, 'expectedTarget': 'fixture@127.0.0.1:40002'}
        ordinary = {'attempt': 12, 'accepted': False, 'expectedTarget': 'fixture@127.0.0.1:40001'}
        partial = {**ordinary, 'attempt': 3}
        for observed in ({}, {'key-rotation': rotation},
                         {'key-rotation': rotation, 'ordinary': partial},
                         {'key-rotation': rotation, 'ordinary': ordinary}):
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                app = root / 'app'
                app.mkdir()
                output = root / 'public'
                peers = []
                for port in (40001, 40002):
                    peer = MagicMock(port=port, username='fixture', password='secret',
                                     fingerprint='SHA256:private', rotated_fingerprint='SHA256:private2')
                    peer.__enter__.return_value = peer
                    peer.snapshot.return_value = {'connectionsClosed': True}
                    peers.append(peer)
                fixture_module = types.SimpleNamespace(DirectSshFixture=Mock(side_effect=peers))
                process = Mock()
                process.poll.side_effect = [None, 1, 1]
                read_diagnostic = {'source': 'integration', 'operation': 'read', 'outcome': 'short_read',
                                   'deviceState': 'device', 'expectedBytes': 24, 'stdoutBytes': 8, 'stderrBytes': 0}
                def checkpoint(request, screens, *unused):
                    screens.update({tag: {**value, 'private': 'secret'} for tag, value in observed.items()})
                    screens['unknown'] = {'attempt': 1, 'accepted': False, 'expectedTarget': 'secret'}
                    raise runner.ScreenshotReadFailure(read_diagnostic)
                def device_text(*args):
                    if args == ('devices',):
                        return 'List of devices attached\nemulator-5554 device'
                    if args == ('shell', 'getprop', 'ro.kernel.qemu'):
                        return '1'
                    if args == ('shell', 'getprop', 'ro.build.version.sdk'):
                        return '35'
                    if args == ('shell', 'am', 'get-current-user'):
                        return '0'
                    if args == ('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard'):
                        return '1'
                    return ''
                env = {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'RUNNER_TEMP': temp}
                args = types.SimpleNamespace(project=app, output=output)
                with patch.dict(sys.modules, {'direct_ssh_fixture': fixture_module}), \
                     patch.object(runner, 'checked_paths', return_value=(app, output)), \
                     patch.object(runner, 'verify_prepared'), \
                     patch.object(runner, 'text', side_effect=device_text), \
                     patch.object(runner, 'package_present', return_value=False), \
                     patch.object(runner, 'forward_set', return_value=set()), \
                     patch.object(runner, 'adb'), \
                     patch.object(runner, 'read_public_json', return_value={'request': True}), \
                     patch.object(runner, 'screen_checkpoint', side_effect=checkpoint), \
                     patch.object(runner.subprocess, 'Popen', return_value=process):
                    with self.assertRaisesRegex(runner.Failure, 'direct_android_screenshot_short_read'):
                        runner.run(args, env)
                report = json.loads((output / 'result.json').read_text())
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['screenProof'], observed)
                self.assertEqual(report['screenshotReadDiagnostic'], read_diagnostic)
                self.assertNotIn('secret', json.dumps(report))

    def test_protocol_dependency_is_present_when_required(self):
        if os.environ.get('HERDR_REQUIRE_PARAMIKO') == '1':
            self.assertIsNotNone(importlib.util.find_spec('paramiko'), 'Paramiko is required for direct SSH acceptance')

    def test_runner_rejects_local_non_ci_real_devices_and_paths_outside_owned_temp(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'app'
            app.mkdir()
            output = root / 'public'
            env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/codex/acceptance/direct-ssh-android-test',
                   'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'ANDROID_SERIAL': 'emulator-5554', 'RUNNER_TEMP': temp}
            self.assertEqual(runner.checked_paths(app, output, env), (app.resolve(), output.resolve()))
            for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_REF', 'refs/heads/main'), ('ANDROID_SERIAL', 'real-phone')]:
                bad = {**env, key: value}
                with self.subTest(key=key), self.assertRaises(runner.Failure):
                    runner.checked_paths(app, output, bad)
            with self.assertRaises(runner.Failure):
                runner.checked_paths(app, Path(temp).parent / 'public', env)
            output.mkdir()
            with self.assertRaises(runner.Failure):
                runner.checked_paths(app, output, env)

    def test_only_exact_complete_boolean_evidence_can_be_exported(self):
        result = {key: True for key in runner.PUBLIC_FIELDS}
        result.update(schemaVersion=1, platform='android-api35-emulator', physicalImeVerified=False)
        self.assertEqual(runner.safe_result(json.dumps(result)), result)
        for change in ({'remoteEchoVisible': False}, {'physicalImeVerified': True}, {'password': 'must-not-export'},
                       {'platformKeyboardOpenedAndClosed': 1}, {'boardNetworkSettingsReturnedToSameTerminal': False},
                       {'schemaVersion': True}):
            with self.subTest(change=tuple(change)), self.assertRaises(runner.Failure):
                runner.safe_result(json.dumps({**result, **change}))
        del result['platformKeyboardOpenedAndClosed']
        with self.assertRaises(runner.Failure):
            runner.safe_result(json.dumps(result))

    def test_mobile_checkpoints_reject_missing_alien_skipped_and_replayed_phases(self):
        fixture = Mock()
        for value in ([], {'phase': 'board_visible'}, {'phase': 'keyboard_shown', 'password': 'secret'},
                      {'phase': ['keyboard_shown']}, {'phase': 'unrecognized'}):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(runner.Failure):
                runner.ordinary_mobile_checkpoint(fixture, value, {})
        for completed in ({}, {'keyboard_shown': {}}, {phase: {} for phase in reversed(runner.ORDINARY_MOBILE_PHASES)}):
            with self.assertRaisesRegex(runner.Failure, '^direct_ssh_mobile_checkpoints_incomplete$'):
                runner.require_ordinary_mobile_checkpoints(completed)
        with self.assertRaisesRegex(runner.Failure, '^direct_ssh_mobile_stage_out_of_order$'):
            runner.ordinary_mobile_checkpoint(fixture, {'phase': 'keyboard_shown'},
                                              {'keyboard_shown': {}, 'keyboard_hidden': {}})
        self.assertIsNone(runner.ordinary_mobile_checkpoint(fixture, {'phase': 'keyboard_hidden'},
                          {'keyboard_shown': {}, 'keyboard_hidden': {}}))
        fixture.snapshot.assert_not_called()

    def test_mobile_waits_only_for_first_valid_peer_output_publication(self):
        probe = dict(id=1, hostKey='A', authAttempts=0, authSuccesses=0, ptyRequests=0, shellRequests=0,
                     inputBytes=0, outputBytes=0, authAccepted=False, markerReceived=False, sessionClosed=False)
        shell = dict(id=2, hostKey='A', authAttempts=1, authSuccesses=1, ptyRequests=1, shellRequests=1,
                     inputBytes=0, outputBytes=0, authAccepted=True, markerReceived=False, sessionClosed=False,
                     closed=False)

        def facts(**session):
            return dict(connections=2, connectionsClosed=False, connectionEvents=[probe, dict(shell, **session)])

        failure = '^direct_ssh_ordinary_session_evidence_invalid$'
        first = {'phase': 'keyboard_shown'}
        for change in (dict(inputBytes=1), dict(authAttempts=2), dict(ptyRequests=2), dict(shellRequests=2),
                       dict(closed=True), dict(id=3), dict(outputBytes=-1), dict(outputBytes=True)):
            for sample in (1, 2):
                with self.subTest(change=change, sample=sample), patch.object(runner, 'time') as clock:
                    samples = [facts()] * (sample - 1) + [facts(**change), facts(outputBytes=24)]
                    fixture = Mock(snapshot=Mock(side_effect=samples))
                    clock.monotonic.return_value = 1
                    with self.assertRaisesRegex(runner.Failure, failure):
                        runner.ordinary_mobile_checkpoint(fixture, first, {})
                    self.assertEqual(fixture.snapshot.call_count, sample)
                    self.assertEqual(clock.sleep.call_count, sample - 1)

        with patch.object(runner, 'time') as clock:
            fixture = Mock(snapshot=Mock(side_effect=[facts(), facts(outputBytes=24)]))
            clock.monotonic.side_effect = [0, 0, 5]
            with self.assertRaisesRegex(runner.Failure, failure):
                runner.ordinary_mobile_checkpoint(fixture, first, {})
            fixture.snapshot.assert_called_once()
            clock.sleep.assert_called_once()

        with patch.object(runner, 'time') as clock:
            fixture = Mock(snapshot=Mock(side_effect=[facts(), facts(outputBytes=24)]))
            with self.assertRaisesRegex(runner.Failure, failure):
                runner.ordinary_mobile_checkpoint(fixture, {'phase': 'keyboard_hidden'}, {'keyboard_shown': {}})
            fixture.snapshot.assert_called_once()
            clock.sleep.assert_not_called()

        with patch.object(runner, 'time') as clock:
            closed = facts(inputBytes=9, markerReceived=True, sessionClosed=True, closed=True)
            closed['connectionEvents'][0] = dict(probe, closed=True)
            closed['connectionsClosed'] = True
            fixture = Mock(snapshot=Mock(return_value=closed))
            with self.assertRaisesRegex(runner.Failure, failure):
                runner.ordinary_session_evidence(fixture, closed=True)
            fixture.snapshot.assert_called_once()
            clock.sleep.assert_not_called()

    def test_rotation_public_result_requires_every_boolean_and_rejects_extra_data(self):
        result = {key: True for key in runner.ROTATION_PUBLIC_FIELDS}
        result.update(schemaVersion=1, platform='android-api35-emulator', physicalImeVerified=False)
        self.assertEqual(runner.safe_rotation_result(json.dumps(result)), result)
        for change in ({'schemaVersion': True}, {'cancelKeepsOldTrust': False},
                       {'remoteEchoVisible': 1}, {'physicalImeVerified': True},
                       {'password': 'must-never-be-exported'}):
            with self.subTest(change=tuple(change)), self.assertRaises(runner.Failure):
                runner.safe_rotation_result(json.dumps({**result, **change}))
        for raw in ('[]', '{', json.dumps({key: value for key, value in result.items()
                                         if key != 'freshProbeMatchedIndependentB'})):
            with self.subTest(raw_length=len(raw)), self.assertRaises(runner.Failure):
                runner.safe_rotation_result(raw)

    def test_rotation_stages_are_strict_ordered_and_use_independent_peer_evidence(self):
        completed = {}
        fixture = Mock()
        fixture.wait_for_connections_closed.return_value = True
        for phase, stage in runner.ROTATION_PHASES.items():
            evidence = {'stage': stage, 'serverObserved': True}
            fixture.rotation_evidence.return_value = evidence
            value = {'phase': phase, 'stage': stage}
            self.assertEqual(runner.rotation_checkpoint(fixture, value, completed), evidence)
            fixture.wait_for_connections_closed.assert_called_with(stage)
            fixture.rotation_evidence.assert_called_with(stage)
            completed[phase] = evidence
            fixture.reset_mock()
            self.assertIsNone(runner.rotation_checkpoint(fixture, value, completed))
            fixture.wait_for_connections_closed.assert_not_called()
            fixture.rotation_evidence.assert_not_called()
        for value in ({'phase': 'cancelled', 'stage': 2}, {'phase': 'complete', 'stage': 4},
                      {'phase': 'rejected', 'stage': True}, {'phase': 'rejected', 'stage': 3},
                      {'phase': 'rejected', 'stage': 2, 'password': 'secret'},
                      {'phase': 'unknown', 'stage': 2}, []):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(runner.Failure):
                runner.rotation_checkpoint(fixture, value, {})
        fixture.wait_for_connections_closed.return_value = False
        with self.assertRaisesRegex(runner.Failure, '^direct_android_rotation_connection_not_closed$'):
            runner.rotation_checkpoint(fixture, {'phase': 'rejected', 'stage': 2}, {})
        fixture.wait_for_connections_closed.return_value = True
        fixture.rotation_evidence.side_effect = ValueError('must-never-be-exported')
        with self.assertRaisesRegex(runner.Failure, '^direct_android_rotation_server_evidence_invalid$'):
            runner.rotation_checkpoint(fixture, {'phase': 'rejected', 'stage': 2}, {})

    def test_exchange_allows_only_fixed_public_filenames(self):
        with patch.object(runner, 'package_present', return_value=False):
            for name in ('rotation-stage.json', 'rotation-result.json', 'ordinary-mobile-stage.json',
                         'encrypted-stage.json', 'encrypted-result.json', 'encrypted-diagnostic.json'):
                self.assertIsNone(runner.read_public_json('cache/herdr-direct-ssh-123/' + name))
            for name in ('../defines.json', 'rotation-rejected-confirmed.json', 'rotation-secret.json',
                         'ordinary-mobile-keyboard_shown-confirmed.json', 'ordinary-mobile-result.json',
                         'encrypted-secret.json', 'encrypted-review-confirmed.json', '../herdr-key-123.json'):
                with self.subTest(name=name), self.assertRaises(runner.Failure):
                    runner.read_public_json('cache/herdr-direct-ssh-123/' + name)

    def test_package_query_retries_only_known_transient_and_fails_closed(self):
        runner.PACKAGE_QUERY_RETRIES.clear()
        offline=CompletedProcess([],1,b'',b'error: device offline')
        present=CompletedProcess([],0,('package:'+runner.PACKAGE+'\n').encode(),b'')
        with patch.object(runner,'adb',side_effect=[offline,present]) as adb, patch.object(runner.time,'sleep'):
            self.assertTrue(runner.package_present()); self.assertEqual(adb.call_count,2)
            self.assertTrue(all(call.kwargs == {'check':False} for call in adb.call_args_list))
        self.assertEqual(runner.PACKAGE_QUERY_RETRIES[-1]['attempts'],2)
        self.assertTrue(runner.PACKAGE_QUERY_RETRIES[-1]['recovered'])
        for failure in (CompletedProcess([],255,b'partial',b''), CompletedProcess([],1,b'',b'unknown'), CompletedProcess([],0,b'broken output',b'')):
            with self.subTest(code=failure.returncode), patch.object(runner,'adb',return_value=failure) as adb, patch.object(runner.time,'sleep'):
                with self.assertRaises(runner.Failure): runner.package_present()
                self.assertEqual(adb.call_count,1)
        with patch.object(runner,'adb',return_value=offline) as adb, patch.object(runner.time,'sleep'):
            with self.assertRaises(runner.Failure): runner.package_present()
            self.assertEqual(adb.call_count,3)
            self.assertFalse(runner.PACKAGE_QUERY_RETRIES[-1]['recovered'])
        runner.PACKAGE_QUERY_RETRIES.clear()

    def test_pending_diagnostics_and_non_json_never_become_device_success(self):
        relative = 'cache/herdr-direct-ssh-123/result.json'
        for status, stdout, stderr in [
            (0, b'run-as: unknown package: ' + runner.PACKAGE.encode(), b''),
            (1, b'', ('head: ' + relative + ': No such file or directory').encode()),
        ]:
            with self.subTest(status=status):
                self.assertIsNone(runner.checked_public_reply(CompletedProcess([], status, stdout, stderr), relative, 4096))
        for stdout in (b'not JSON', b'', b'[]', b'{' + b'x' * 4097):
            with self.subTest(size=len(stdout)), self.assertRaises(runner.Failure):
                runner.checked_public_reply(CompletedProcess([], 0, stdout, b''), relative, 4096)
        with self.assertRaisesRegex(runner.Failure, 'not_json'):
            runner.safe_result(b'run-as: unknown package')

    def test_file_poll_uses_shell_exit_status_before_reading_and_limits_diagnostics(self):
        relative = 'cache/herdr-direct-ssh-123/result.json'
        with patch.object(runner, 'package_present', return_value=False), patch.object(runner, 'adb') as adb:
            self.assertIsNone(runner.read_public_json(relative))
            adb.assert_not_called()
        missing = CompletedProcess([], 1, b'', b'')
        with patch.object(runner, 'package_present', return_value=True), patch.object(runner, 'adb', return_value=missing) as adb:
            self.assertIsNone(runner.read_public_json(relative))
            self.assertEqual(adb.call_args.args[:5], ('shell', '-T', 'run-as', runner.PACKAGE, 'test'))
        with patch.object(runner, 'package_present', return_value=True), patch.object(runner, 'adb', side_effect=[
            CompletedProcess([], 0, b'', b''), CompletedProcess([], 0, b'{"ready":true}', b'')]) as adb:
            self.assertEqual(runner.read_public_json(relative), {'ready': True})
            self.assertEqual(adb.call_args.args[:5], ('shell', '-T', 'run-as', runner.PACKAGE, 'head'))
        secret = 'must-never-be-exported'
        evidence = runner.safe_failure(ValueError(secret), 'await_device_result')
        self.assertEqual(evidence['exceptionClass'], 'ValueError')
        self.assertNotIn(secret, json.dumps(evidence))


@unittest.skipUnless(importlib.util.find_spec('paramiko') is not None, 'Paramiko is unavailable; loopback protocol test is optional in this environment')
class LoopbackTests(unittest.TestCase):
    def test_shared_peer_stays_on_one_session_for_mobile_checkpoints_then_receives_one_marker_and_closes(self):
        for deadline in (None, time.monotonic() + 60):
            with self.subTest(shared_deadline=deadline is not None):
                self.assert_ordinary_mobile_session(deadline)

    def assert_ordinary_mobile_session(self, deadline):
        import paramiko
        from direct_ssh_fixture import DirectSshFixture
        first_output_sent, publish_ready = Event(), Event()

        class DelayedReadyPublication(DirectSshFixture):
            def _connection_increment(self, transport, field, amount=1):
                if field == 'outputBytes' and not first_output_sent.is_set():
                    first_output_sent.set()
                    publish_ready.wait(5)
                super()._connection_increment(transport, field, amount)

        with DelayedReadyPublication(screen_proof=True, channel_deadline=deadline) as fixture:
            probe = paramiko.Transport(('127.0.0.1', fixture.port))
            try:
                probe.start_client(timeout=5)
                self.assertEqual(probe.get_remote_server_key().get_base64(), fixture.public_key.split()[1])
            finally:
                probe.close()
            self.assertTrue(fixture.wait_for_connections_closed(1))
            transport = paramiko.Transport(('127.0.0.1', fixture.port))
            try:
                transport.start_client(timeout=5)
                self.assertEqual(transport.get_remote_server_key().get_base64(), fixture.public_key.split()[1])
                transport.auth_password(fixture.username, fixture.password)
                channel = transport.open_session(timeout=5)
                channel.get_pty(term='xterm-256color', width=80, height=24)
                channel.invoke_shell()
                channel.settimeout(5)
                self.assertIn(b'POCKET-ANDROID-READY', channel.recv(4096))
                self.assertTrue(first_output_sent.wait(5))
                snapshot = fixture.snapshot

                def release_after_first_snapshot():
                    facts = snapshot()
                    if not publish_ready.is_set():
                        self.assertEqual(facts['connectionEvents'][1]['outputBytes'], 0)
                        publish_ready.set()
                    return facts

                completed = {}
                for phase in runner.ORDINARY_MOBILE_PHASES:
                    with patch.object(fixture, 'snapshot', side_effect=release_after_first_snapshot):
                        name, evidence = runner.ordinary_mobile_checkpoint(fixture, {'phase': phase}, completed)
                    self.assertEqual(name, phase)
                    self.assertEqual(evidence, {'id': 2, 'authAttempts': 1, 'authSuccesses': 1, 'ptyRequests': 1,
                                                'shellRequests': 1, 'inputBytes': 0, 'markerReceived': False, 'closed': False})
                    completed[name] = evidence
                runner.require_ordinary_mobile_checkpoints(completed)
                pending_probe_cleanup = fixture.snapshot()
                pending_probe_cleanup['connectionEvents'][0]['closed'] = False
                with patch.object(fixture, 'snapshot', return_value=pending_probe_cleanup):
                    self.assertEqual(runner.ordinary_session_evidence(fixture, closed=False), evidence)
                for index, field, value in ((0, 'authAttempts', 1), (1, 'id', 3), (1, 'authAttempts', 2),
                                            (1, 'ptyRequests', 2), (1, 'shellRequests', 2), (1, 'inputBytes', 1),
                                            (1, 'closed', True)):
                    drift = fixture.snapshot()
                    drift['connectionEvents'][index][field] = value
                    with patch.object(fixture, 'snapshot', return_value=drift), self.assertRaisesRegex(
                            runner.Failure, '^direct_ssh_ordinary_session_evidence_invalid$'):
                        runner.ordinary_session_evidence(fixture, closed=False)
                channel.sendall((fixture.marker + '\r').encode())
                received = b''
                while fixture.echo_marker.encode() not in received:
                    received += channel.recv(4096)
                self.assertIn(b'\x1b[32m' + fixture.echo_marker.encode(), received)
                channel.close()
            finally:
                publish_ready.set()
                transport.close()
            self.assertTrue(fixture.wait_for_connections_closed(2))
            evidence = runner.ordinary_session_evidence(fixture, closed=True)
            self.assertEqual(evidence['inputBytes'], 9)
            self.assertTrue(evidence['closed'])
            self.assertTrue(evidence['markerReceived'])
            pending_probe_cleanup = fixture.snapshot()
            pending_probe_cleanup['connectionEvents'][0]['closed'] = False
            with patch.object(fixture, 'snapshot', return_value=pending_probe_cleanup), self.assertRaisesRegex(
                    runner.Failure, '^direct_ssh_ordinary_session_evidence_invalid$'):
                runner.ordinary_session_evidence(fixture, closed=True)
            facts = fixture.snapshot()
            self.assertTrue(all(facts[k] for k in ('authAccepted', 'ptyRequested', 'shellRequested', 'markerReceived')))
            self.assertIn([80, 24], facts['ptySizes'])
            self.assertFalse(any(secret in json.dumps(facts) for secret in (fixture.password, fixture.public_key)))
        self.assertTrue(fixture.snapshot()['connectionsClosed'])
        self.assertEqual(fixture.password, '')


    def test_helper_sequence_requires_exact_order_and_is_opt_in(self):
        import paramiko
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(observe_helper_keys=True) as fixture:
            transport = paramiko.Transport(('127.0.0.1', fixture.port))
            try:
                transport.start_client(timeout=5)
                transport.auth_password(fixture.username, fixture.password)
                channel = transport.open_session(timeout=5)
                channel.get_pty(); channel.invoke_shell(); channel.settimeout(5)
                channel.sendall((fixture.marker + '\r').encode())
                self.assertTrue(fixture.wait_for('markerReceived'))
                channel.sendall(b'\x1b\t\x1b[D')
                self.assertFalse(fixture.snapshot()['helperKeysExact'])
                channel.sendall(b'\x03')
                self.assertTrue(fixture.wait_for('helperKeysExact'))
                channel.sendall(b'x')
                import time
                deadline = time.monotonic() + 3
                while fixture.snapshot()['helperKeysExact'] and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertFalse(fixture.snapshot()['helperKeysExact'])
                channel.close()
            finally:
                transport.close()
        with DirectSshFixture(observe_helper_keys=True) as fixture:
            transport = paramiko.Transport(('127.0.0.1', fixture.port))
            try:
                transport.start_client(timeout=5); transport.auth_password(fixture.username, fixture.password)
                channel = transport.open_session(timeout=5); channel.get_pty(); channel.invoke_shell()
                channel.sendall((fixture.marker + '\r').encode()); self.assertTrue(fixture.wait_for('markerReceived'))
                channel.sendall(b'\t\x1b\x1b[D\x03')
                import time
                time.sleep(.1)
                self.assertFalse(fixture.snapshot()['helperKeysExact'])
                channel.close()
            finally:
                transport.close()
        with DirectSshFixture() as fixture:
            self.assertNotIn('helperKeysExact', fixture.snapshot())



class EncryptedKeyAcceptanceTests(unittest.TestCase):
    def test_workflow_explicit_case_keeps_standard_default_and_push_scope(self):
        workflow = (HERE.parents[1] / '.github/workflows/direct-ssh-android.yml').read_text()
        self.assertIn("'codex/acceptance/direct-ssh-android-*'", workflow)
        self.assertIn('options: [standard, encrypted-key, encrypted-key-rotation]', workflow)
        self.assertIn('default: standard', workflow)
        self.assertIn("if: ${{ inputs.auth_case == 'encrypted-key' || inputs.auth_case == 'encrypted-key-rotation' }}", workflow)
        self.assertIn('flutter build apk --debug --target-platform android-x64 --no-pub -t integration_test/android_direct_ssh_test.dart', workflow)
        self.assertIn('AUTH_CASE: ${{ inputs.auth_case }}', workflow)
        self.assertIn('case "${AUTH_CASE:-}" in', workflow)
        self.assertIn("''|standard) set -- ;;", workflow)
        self.assertIn('encrypted-key) set -- --encrypted-key ;;', workflow)
        self.assertIn("*) echo 'unsupported SSH acceptance case' >&2; exit 1 ;;", workflow)
        self.assertIn('--output "$RUNNER_TEMP/direct-ssh-public" "$@"', workflow)

    def test_workflow_case_shell_rejects_unexpected_values_without_expansion(self):
        import subprocess
        workflow = (HERE.parents[1] / '.github/workflows/direct-ssh-android.yml').read_text()
        start = workflow.index('          case "${AUTH_CASE:-}" in')
        end = workflow.index('          esac', start) + len('          esac')
        program = workflow[start:end] + '\nprintf "<%s>" "$@"'
        for value, expected in [('', '<>'), ('standard', '<>'), ('encrypted-key', '<--encrypted-key>'),
                                ('encrypted-key-rotation', '<--encrypted-key-rotation>')]:
            result = subprocess.run(['bash', '-c', program], env={**os.environ, 'AUTH_CASE': value},
                                    capture_output=True, text=True, check=False)
            self.assertEqual((result.returncode, result.stdout), (0, expected))
        for value in ('bogus', 'encrypted-key; echo leaked'):
            result = subprocess.run(['bash', '-c', program], env={**os.environ, 'AUTH_CASE': value},
                                    capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertNotIn(value, result.stderr)

    def test_encrypted_rotation_rejects_push_before_opening_a_fixture(self):
        with patch.object(runner, 'checked_paths') as paths, self.assertRaisesRegex(
                runner.Failure, 'direct_android_encrypted_rotation_requires_manual_dispatch'):
            runner.run_encrypted(None, {'GITHUB_EVENT_NAME': 'push'}, rotating=True)
        paths.assert_not_called()

    def test_startup_observation_does_not_probe_app_before_install(self):
        path = 'cache/herdr-direct-ssh-123'
        with patch.object(runner, 'package_present', return_value=False), \
             patch.object(runner, 'read_public_json') as read:
            self.assertEqual(runner.encrypted_app_observation(path), (False, None, None))
            read.assert_not_called()
        with patch.object(runner, 'package_present', return_value=True), \
             patch.object(runner, 'read_public_json', side_effect=[None, None]) as read:
            self.assertEqual(runner.encrypted_app_observation(path), (True, None, None))
            self.assertEqual(read.call_count, 2)
            self.assertTrue(all(call.kwargs == {'package_known': True} for call in read.call_args_list))
        with patch.object(runner, 'package_present', return_value=True), \
             patch.object(runner, 'read_public_json', side_effect=[{'stage': 'encrypted_waiting_private'}, None]):
            self.assertEqual(runner.encrypted_app_observation(path), (True, 'encrypted_waiting_private', None))
        with patch.object(runner, 'package_present', return_value=True), \
             patch.object(runner, 'read_public_json', return_value={'stage': 'private-key-content'}):
            with self.assertRaises(runner.Failure): runner.encrypted_app_observation(path)
        failure = {'stage': 'fixture_validation', 'code': 'direct_ssh_android_ui_failed',
                   'exceptionClass': 'StateError', 'sourceLocations': []}
        with patch.object(runner, 'package_present', return_value=True), \
             patch.object(runner, 'read_public_json', side_effect=[{'stage': 'encrypted_waiting_private'}, failure]):
            self.assertEqual(runner.encrypted_app_observation(path),
                             (True, 'encrypted_waiting_private', failure))

    def test_connect_diagnostic_accepts_only_fixed_token_free_state(self):
        value = dict.fromkeys(runner.ENCRYPTED_CONNECT_BOOLEAN_FIELDS, False)
        value.update(status='disabled', rectPt=[16, 500, 358, 48],
                     viewSizePx=[1080, 2400], viewSizePt=[360, 800], insetBottomPx=0)
        self.assertEqual(runner.safe_encrypted_connect_diagnostic(value), value)
        for status in ('checking', 'missing', 'multiple', 'disabled', 'not_hit', 'unstable', 'replaced', 'ready'):
            self.assertEqual(runner.safe_encrypted_connect_diagnostic({**value, 'status': status})['status'], status)
        for bad in ({**value, 'status': 'sensitive-test-key'},
                    {**value, 'privateKeyEmpty': 'sensitive-test-key'},
                    {**value, 'rectPt': [16, 500, 358, True]},
                    {**value, 'extra': 'sensitive-test-key'}):
            with self.subTest(bad=bad), self.assertRaises(runner.Failure):
                runner.safe_encrypted_connect_diagnostic(bad)

    def test_tool_progress_discards_untrusted_output_and_detects_split_markers(self):
        import io
        class Chunks:
            def __init__(self):
                self.parts = iter([b"running gradle task 'asse", b"mbledebug'\r\n", b'sensitive-test-key ',
                    b'installing build/app/outputs/', b' loading /x/android_direct_ssh_test.dart', b''])
            def read1(self, unused): return next(self.parts)
        progress = runner.SanitizedToolProgress(Chunks())
        result = progress.finish()
        self.assertEqual(result['streamState'], 'eof')
        self.assertTrue(result['markers']['gradleStarted'])
        self.assertTrue(result['markers']['installationStarted'])
        self.assertTrue(result['markers']['testLoading'])
        self.assertNotIn('sensitive-test-key', json.dumps(result))
        self.assertEqual(set(result['markers']), set(runner.TOOL_MARKERS))

    def test_device_state_uses_fixed_values_without_echoing_adb_output(self):
        for reply, expected in [(CompletedProcess([], 0, b'device\n', b''), 'device'),
                                (CompletedProcess([], 1, b'', b'error: device offline'), 'offline'),
                                (CompletedProcess([], 1, b'', b'error: device unauthorized'), 'unauthorized'),
                                (CompletedProcess([], 1, b'sensitive-test-key', b''), 'unavailable')]:
            with self.subTest(expected=expected), patch.object(runner, 'adb', return_value=reply):
                self.assertEqual(runner.encrypted_device_state(), expected)
        with patch.object(runner, 'adb', side_effect=__import__('subprocess').TimeoutExpired('adb', 30)):
            self.assertEqual(runner.encrypted_device_state(), 'timeout')

    def test_cleanup_checks_remain_independent_when_reverse_removal_fails(self):
        calls = []
        def fake_adb(*args, **unused):
            calls.append(args)
            if args[:2] == ('reverse', '--remove'):
                raise __import__('subprocess').TimeoutExpired('adb', 30)
            return CompletedProcess([], 0, b'', b'')
        with patch.object(runner, 'adb', side_effect=fake_adb), \
             patch.object(runner, 'package_present', side_effect=[True, False]), \
             patch.object(runner, 'forward_set', return_value=set()):
            cleanup, checks = runner.cleanup_encrypted_device('tcp:40001', set())
        self.assertEqual(cleanup, {'reverseRemoved': False, 'packageRemoved': True, 'ownedForwardsRemoved': True})
        self.assertEqual(checks, {'reverse': 'unproven', 'package': 'verified', 'forwards': 'verified'})
        self.assertEqual(sum(call[:2] == ('reverse', '--remove') for call in calls), 1)
        self.assertIn(('uninstall', runner.PACKAGE), calls)

    def test_app_stage_and_failure_details_are_strictly_allowlisted(self):
        self.assertEqual(runner.safe_encrypted_app_stage({'stage': 'encrypted_waiting_private'}),
                         'encrypted_waiting_private')
        self.assertEqual(runner.safe_encrypted_app_stage({'stage': 'encrypted_prepare_rejection'}),
                         'encrypted_prepare_rejection')
        self.assertEqual(runner.safe_encrypted_app_stage({'stage': 'encrypted_prepare_connect'}),
                         'encrypted_prepare_connect')
        for value in ({'stage': 'sensitive-test-key'}, {'stage': 'encrypted_home', 'secret': 'x'}):
            with self.subTest(value=value), self.assertRaises(runner.Failure):
                runner.safe_encrypted_app_stage(value)

        frame = {'file': 'direct_ssh_ui_steps.dart', 'line': 717}
        failure = {'stage': 'encrypted_review', 'code': 'direct_ssh_android_ui_failed',
                   'exceptionClass': 'TestFailure', 'sourceLocations': [frame]}
        self.assertEqual(runner.safe_encrypted_app_failure(failure), failure)
        for extra in ({'stage': 'sensitive-test-key'}, {'code': 'sensitive-test-key'},
                      {'message': 'sensitive-test-key'}, {'exceptionClass': 'sensitive-test-key'},
                      {'sourceLocations': [frame] * 5}, {'sourceLocations': 'raw stack'},
                      {'sourceLocations': [{'file': '/private/direct_ssh_ui_steps.dart', 'line': 717}]},
                      {'sourceLocations': [{**frame, 'line': True}]},
                      {'sourceLocations': [{**frame, 'line': 0}]},
                      {'sourceLocations': [{**frame, 'line': 100000}]},
                      {'sourceLocations': [{**frame, 'column': 10}]}):
            with self.subTest(extra=extra), self.assertRaisesRegex(
                    runner.Failure, 'direct_android_encrypted_app_failure_invalid'):
                runner.safe_encrypted_app_failure({**failure, **extra})

    def test_result_is_exact_and_never_exports_credentials(self):
        value = {field: True for field in runner.ENCRYPTED_PUBLIC_FIELDS}
        value.update(schemaVersion=1, platform='android-api35-emulator', physicalImeVerified=False)
        self.assertEqual(runner.safe_encrypted_result(json.dumps(value)), value)
        for extra in ({'privateKey': 'secret'}, {'passphrase': 'secret'},
                      {'wrongPassphraseRejectedLocally': False}, {'physicalImeVerified': True},
                      {'schemaVersion': True}, {'credentialsCleared': 1}):
            with self.subTest(extra=tuple(extra)), self.assertRaises(runner.Failure):
                runner.safe_encrypted_result(json.dumps({**value, **extra}))
        with self.assertRaises(runner.Failure):
            runner.safe_encrypted_result('{')

    def test_encrypted_cases_require_each_pem_edit_observation(self):
        for rotating in (False, True):
            fields = runner.ENCRYPTED_ROTATION_PUBLIC_FIELDS if rotating else runner.ENCRYPTED_PUBLIC_FIELDS
            value = dict.fromkeys(fields, True)
            value.update(schemaVersion=1, platform='android-api35-emulator', physicalImeVerified=False)
            for field in ('pemCollapsedBeforeReopen', 'pemReopenedFocusedAndExact', 'pemRecollapsedAfterBlur'):
                for bad in ({key: item for key, item in value.items() if key != field},
                            {**value, field: False}, {**value, field: 1}):
                    with self.subTest(rotating=rotating, field=field), self.assertRaises(runner.Failure):
                        runner.safe_encrypted_result(json.dumps(bad), rotating=rotating)

    def test_review_and_wrong_passphrase_require_one_closed_unauthenticated_probe(self):
        probe = dict(id=1, hostKey='A', authAttempts=0, authSuccesses=0,
            ptyRequests=0, shellRequests=0, inputBytes=0, outputBytes=0,
            authAccepted=False, markerReceived=False, sessionClosed=False, closed=True)
        fixture = Mock()
        fixture.wait_for_connections_closed.return_value = True
        fixture.snapshot.return_value = dict(connections=1, connectionsClosed=True, connectionEvents=[probe])
        self.assertEqual(runner.encrypted_probe_evidence(fixture), probe)
        for field, bad in [('authAttempts', 1), ('authSuccesses', 1), ('ptyRequests', 1),
                           ('shellRequests', 1), ('inputBytes', 1), ('outputBytes', 1),
                           ('closed', False), ('authAttempts', False)]:
            fixture.snapshot.return_value = dict(connections=1, connectionsClosed=True,
                connectionEvents=[{**probe, field: bad}])
            with self.subTest(field=field, value=bad), self.assertRaises(runner.Failure):
                runner.encrypted_probe_evidence(fixture)
        fixture.snapshot.return_value = dict(connections=2, connectionsClosed=True, connectionEvents=[probe, probe])
        with self.assertRaises(runner.Failure):
            runner.encrypted_probe_evidence(fixture)

    def test_encrypted_rotation_result_requires_both_evidence_families_without_wrong_passphrase(self):
        value = dict.fromkeys(runner.ENCRYPTED_ROTATION_PUBLIC_FIELDS, True)
        value.update(schemaVersion=1, platform='android-api35-emulator', physicalImeVerified=False)
        self.assertEqual(runner.safe_encrypted_result(json.dumps(value), rotating=True), value)
        standard = {key: value.get(key, True) for key in runner.ENCRYPTED_PUBLIC_FIELDS}
        with self.assertRaises(runner.Failure):
            runner.safe_encrypted_result(json.dumps(value))
        for bad in (standard, {**value, 'wrongPassphraseRejectedLocally': True},
                    {**value, 'cancelKeepsOldTrust': False}, {**value, 'privateKeyPasted': False},
                    {k: v for k, v in value.items() if k != 'freshProbeMatchedIndependentB'}):
            with self.subTest(value=bad), self.assertRaises(runner.Failure):
                runner.safe_encrypted_result(json.dumps(bad), rotating=True)

    def test_encrypted_stages_are_ordered_and_only_accept_public_phase(self):
        self.assertEqual(runner.checked_encrypted_stage({'phase': 'review'}, {}), 'review')
        self.assertIsNone(runner.checked_encrypted_stage({'phase': 'review'}, {'review': {}}))
        self.assertEqual(runner.checked_encrypted_stage({'phase': 'rejected'}, {'review': {}}), 'rejected')
        for value, completed in [({'phase': 'rejected'}, {}), ({'phase': 'review', 'secret': 'x'}, {}),
                                 ({'phase': False}, {}), ({'phase': 'connected'}, {}), ([], {})]:
            with self.subTest(value=value), self.assertRaises(runner.Failure):
                runner.checked_encrypted_stage(value, completed)

    def test_encrypted_rotation_stages_require_order_and_reject_a_replayed_review(self):
        completed = {}
        for phase in ('review', 'rejected', 'cancelled', 'reprobed'):
            value = {'phase': phase}
            self.assertEqual(runner.checked_encrypted_stage(value, completed, rotating=True), phase)
            completed[phase] = {}
            self.assertIsNone(runner.checked_encrypted_stage(value, completed, rotating=True))
        for phases in (completed, {'review': {}}, {'review': {}, 'rejected': {}}):
            invalid = 'review' if 'reprobed' in phases else 'reprobed'
            with self.assertRaises(runner.Failure):
                runner.checked_encrypted_stage({'phase': invalid}, phases, rotating=True)
        with self.assertRaises(runner.Failure):
            runner.checked_encrypted_stage({'phase': 'cancelled'}, {'review': {}, 'rejected': {}})

    def test_encrypted_rotation_rejects_repeated_auth_and_extra_terminal_input(self):
        fixture = Mock()
        value = {'authAttempts': 1, 'inputBytes': 9}
        fixture.public_key_auth_evidence.return_value = value
        self.assertEqual(runner.encrypted_rotation_final_evidence(fixture), value)
        for correction in ({'authAttempts': 2}, {'authAttempts': True}, {'inputBytes': 18}, {'inputBytes': 8}):
            fixture.public_key_auth_evidence.return_value = {**value, **correction}
            with self.subTest(correction=correction), self.assertRaises(runner.Failure):
                runner.encrypted_rotation_final_evidence(fixture)
        fixture.public_key_auth_evidence.side_effect = ValueError('raw private data')
        with self.assertRaisesRegex(runner.Failure, '^direct_android_encrypted_rotation_evidence_invalid$'):
            runner.encrypted_rotation_final_evidence(fixture)

    def test_encrypted_diagnostic_only_exports_fixed_token_free_metrics(self):
        data = {'phase': 'encrypted_wait_idle_ime', 'terminalCount': 1,
            'terminalHit': True, 'disconnectHit': True, 'toggleHit': True, 'enterHit': False, 'headerHit': True,
            'toggleState': 'close', 'insetBottomPx': 400, 'viewSizePx': [1080, 2400],
            'terminalRectPt': [16, 144, 320, 300], 'enterRectPt': [300, 400, 54, 44], 'columns': 12, 'rows': 10,
            'terminalFocused': False, 'testInputRegistered': True, 'testClientSet': True,
            'welcomeVisible': True, 'echoVisible': False}
        self.assertEqual(runner.safe_encrypted_diagnostic(data), data)
        for mutation in ({'privateKey': 'sensitive-test-key'}, {'phase': 'other'},
                         {'toggleState': 'sensitive-test-phrase'}, {'terminalHit': 1},
                         {'insetBottomPx': -1}, {'columns': True}, {'viewSizePx': [0, 1]},
                         {'terminalRectPt': [0, 0, -1, 10]}, {'terminalRectPt': 'secret'}):
            with self.subTest(mutation=mutation), self.assertRaises(runner.Failure):
                runner.safe_encrypted_diagnostic({**data, **mutation})
        with self.assertRaises(runner.Failure):
            runner.safe_encrypted_diagnostic({key: value for key, value in data.items() if key != 'phase'})

    def test_private_ipc_is_single_write_and_never_appears_in_arguments(self):
        fixture = Mock(private_key='sensitive-test-key', passphrase='sensitive-test-phrase')
        with patch.object(runner, 'adb') as adb:
            runner.deliver_encrypted_credentials(fixture, '123')
        self.assertEqual(adb.call_count, 4)
        calls = adb.call_args_list
        self.assertEqual(json.loads(calls[1].kwargs['data']),
                         {'privateKey': fixture.private_key, 'passphrase': fixture.passphrase})
        self.assertEqual(calls[2].args[-2:], ('600', 'cache/herdr-key-123.pending'))
        self.assertEqual(calls[3].args[-2:], ('cache/herdr-key-123.pending', 'cache/herdr-key-123.json'))
        self.assertNotIn('sensitive-test-key', repr([c.args for c in calls]))
        self.assertNotIn('sensitive-test-phrase', repr([c.args for c in calls]))
        with patch.object(runner, 'adb') as adb, self.assertRaises(runner.Failure):
            runner.deliver_encrypted_credentials(fixture, '../123')
        adb.assert_not_called()
        with patch.object(runner, 'adb', side_effect=runner.Failure('failed')) as adb, self.assertRaises(runner.Failure):
            runner.deliver_encrypted_credentials(fixture, '123')
        self.assertEqual(adb.call_count, 1)

    def test_encrypted_screenshot_uses_normal_ocr_without_rotation_bypass(self):
        header = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR' + struct.pack('>II', 400, 600)
        fixture = Mock(username='fixture', port=40001, screen_token='ARCH BARN CAVE DECK DUSK EAST FACT FADE')
        request = {'tag': 'ordinary', 'attempt': 1, 'bounds': [0, 20, 400, 500],
                   'viewSize': [400, 600], 'observedTarget': 'fixture@127.0.0.1:40001'}
        gate = Mock(return_value={'markerVisible': True, 'tokenVisible': True})
        gate_module = types.SimpleNamespace(ScreenshotGateError=type('GateError', (ValueError,), {}),
                                            verify_terminal_screenshot=gate)
        def adb(*args, **unused):
            data = str(len(header)).encode() if args[4:5] == ('stat',) else header
            return CompletedProcess([], 0, data, b'')
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {'terminal_screenshot_gate': gate_module}), \
             patch.object(runner, 'adb', side_effect=adb):
            completed = {}
            runner.screen_checkpoint(request, completed, fixture, None, 'cache/herdr-direct-ssh-123', Path(temp), require_rotation=False)
            self.assertTrue(completed['ordinary']['accepted'])
            self.assertEqual(gate.call_count, 2)
            self.assertTrue(all(call.kwargs['expected_token'] == fixture.screen_token for call in gate.call_args_list))
            with self.assertRaises(runner.Failure):
                runner.screen_checkpoint({**request, 'tag': 'key-rotation'}, {}, fixture, None,
                                         'cache/herdr-direct-ssh-123', Path(temp), require_rotation=False)

    def test_failure_does_not_publish_secret_or_embed_it_in_build_defines(self):
        import shutil
        from screen_proof_token import SCREEN_WORDS
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app = root / 'app'; app.mkdir(); output = root / 'public'
            key_temp = tempfile.TemporaryDirectory(dir=temp)
            fixture = MagicMock(port=40001, username='fixture', private_key='sensitive-test-key',
                passphrase='sensitive-test-phrase', fingerprint='SHA256:public',
                screen_token=' '.join(SCREEN_WORDS[:8]), echo_marker='POCKET-ANDROID-SSH-OK')
            fixture._temp = key_temp
            fixture.__enter__.return_value = fixture
            fixture.snapshot.return_value = {'connectionsClosed': True}
            def exit_fixture(*unused):
                fixture.private_key = fixture.passphrase = ''
                key_temp.cleanup()
            fixture.__exit__.side_effect = exit_fixture
            fake_module = types.SimpleNamespace(EncryptedKeyFixture=Mock(return_value=fixture))
            def fake_text(*args):
                values = {('devices',): 'List of devices attached\nemulator-5554 device',
                    ('shell', 'getprop', 'ro.kernel.qemu'): '1',
                    ('shell', 'getprop', 'ro.build.version.sdk'): '35',
                    ('shell', 'am', 'get-current-user'): '0',
                    ('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard'): '1'}
                return values.get(args, '')
            def fail_start(command, **options):
                self.assertEqual(options['stdout'], runner.subprocess.PIPE)
                self.assertEqual(options['stderr'], runner.subprocess.STDOUT)
                define = next(x.split('=', 1)[1] for x in command if x.startswith('--dart-define-from-file='))
                content = Path(define).read_text()
                self.assertNotIn('sensitive-test-key', content)
                self.assertNotIn('sensitive-test-phrase', content)
                raise RuntimeError('sensitive-test-key sensitive-test-phrase')
            env = {'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '123', 'RUNNER_TEMP': temp}
            args = types.SimpleNamespace(project=app, output=output)
            with patch.dict(sys.modules, {'tauri_encrypted_key_fixture': fake_module}), \
                 patch.object(runner, 'checked_paths', return_value=(app, output)), \
                 patch.object(runner, 'verify_prepared'), patch.object(runner, 'text', side_effect=fake_text), \
                 patch.object(runner, 'package_present', return_value=False), \
                 patch.object(runner, 'forward_set', return_value=set()), patch.object(runner, 'adb'), \
                 patch.object(runner.subprocess, 'Popen', side_effect=fail_start):
                with self.assertRaises(runner.Failure): runner.run_encrypted(args, env)
            published = ''.join(f.read_text() for f in output.iterdir() if f.is_file())
            self.assertNotIn('sensitive-test-key', published)
            self.assertNotIn('sensitive-test-phrase', published)
            self.assertFalse(Path(key_temp.name).exists())
            self.assertFalse(any(root.glob('herdr-direct-android-key-*')))

    def test_reverse_conflict_and_failed_creation_never_remove_unowned_mapping(self):
        from screen_proof_token import SCREEN_WORDS
        for scenario in ('existing', 'creation_failed'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); app = root / 'app'; app.mkdir(); output = root / 'public'
                key_temp = tempfile.TemporaryDirectory(dir=temp)
                fixture = MagicMock(port=40001, username='fixture', private_key='sensitive-test-key',
                    passphrase='sensitive-test-phrase', fingerprint='SHA256:public',
                    screen_token=' '.join(SCREEN_WORDS[:8]), echo_marker='POCKET-ANDROID-SSH-OK')
                fixture._temp = key_temp; fixture.__enter__.return_value = fixture
                fixture.snapshot.return_value = {'connectionsClosed': True}
                def exit_fixture(*unused):
                    fixture.private_key = fixture.passphrase = ''
                    key_temp.cleanup()
                fixture.__exit__.side_effect = exit_fixture
                fake_module = types.SimpleNamespace(EncryptedKeyFixture=Mock(return_value=fixture))
                mappings = {'tcp:40001'} if scenario == 'existing' else set()
                calls = []
                def fake_text(*args):
                    if args == ('reverse', '--list'):
                        return '\n'.join('emulator-5554 '+m+' '+m for m in sorted(mappings))
                    values = {('devices',): 'List of devices attached\nemulator-5554 device',
                        ('shell', 'getprop', 'ro.kernel.qemu'): '1',
                        ('shell', 'getprop', 'ro.build.version.sdk'): '35',
                        ('shell', 'am', 'get-current-user'): '0',
                        ('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard'): '1'}
                    return values.get(args, '')
                def fake_adb(*args, **unused):
                    calls.append(args)
                    if args[:2] == ('reverse', '--no-rebind'):
                        # Another actor acquired the mapping after the read.
                        mappings.add('tcp:40001')
                        raise runner.Failure('direct_android_adb_failed')
                    if args[:2] == ('reverse', '--remove'):
                        mappings.discard(args[2])
                    return CompletedProcess([], 0, b'', b'')
                env = {'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '123', 'RUNNER_TEMP': temp}
                args = types.SimpleNamespace(project=app, output=output)
                with patch.dict(sys.modules, {'tauri_encrypted_key_fixture': fake_module}), \
                     patch.object(runner, 'checked_paths', return_value=(app, output)), \
                     patch.object(runner, 'verify_prepared'), patch.object(runner, 'text', side_effect=fake_text), \
                     patch.object(runner, 'package_present', return_value=False), \
                     patch.object(runner, 'forward_set', return_value=set()), patch.object(runner, 'adb', side_effect=fake_adb):
                    with self.assertRaises(runner.Failure): runner.run_encrypted(args, env)
                self.assertEqual(mappings, {'tcp:40001'})
                self.assertFalse(any(call[:2] == ('reverse', '--remove') for call in calls))
                creations = [call for call in calls if call[:2] == ('reverse', '--no-rebind')]
                self.assertEqual(len(creations), 0 if scenario == 'existing' else 1)
                self.assertFalse(Path(key_temp.name).exists())

    def test_device_failure_preserves_only_whitelisted_stage_and_metrics(self):
        from screen_proof_token import SCREEN_WORDS
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app = root / 'app'; app.mkdir(); output = root / 'public'
            key_temp = tempfile.TemporaryDirectory(dir=temp)
            fixture = MagicMock(port=40001, username='fixture', private_key='sensitive-test-key',
                passphrase='sensitive-test-phrase', fingerprint='SHA256:public',
                screen_token=' '.join(SCREEN_WORDS[:8]), echo_marker='POCKET-ANDROID-SSH-OK')
            fixture._temp = key_temp; fixture.__enter__.return_value = fixture
            def exit_fixture(*unused):
                fixture.private_key = fixture.passphrase = ''
                key_temp.cleanup()
            fixture.__exit__.side_effect = exit_fixture
            probe = dict(id=1, hostKey='A', authAttempts=0, authSuccesses=0,
                ptyRequests=0, shellRequests=0, inputBytes=0, outputBytes=0,
                authAccepted=False, markerReceived=False, sessionClosed=False, closed=True)
            fixture.snapshot.return_value = dict(connections=1, connectionsClosed=True, connectionEvents=[probe])
            fixture.wait_for_connections_closed.return_value = True
            diagnostic = {'phase': 'encrypted_keyboard_show', 'terminalCount': 1,
                'terminalHit': True, 'disconnectHit': True, 'toggleHit': True, 'enterHit': False, 'headerHit': True,
                'toggleState': 'close', 'insetBottomPx': 400, 'viewSizePx': [1080, 2400],
                'terminalRectPt': [16, 144, 320, 300], 'enterRectPt': [300, 400, 54, 44],
                'columns': 12, 'rows': 10, 'terminalFocused': False, 'testInputRegistered': True,
                'testClientSet': True, 'welcomeVisible': True, 'echoVisible': False}
            connect_diagnostic = dict.fromkeys(runner.ENCRYPTED_CONNECT_BOOLEAN_FIELDS, False)
            connect_diagnostic.update(status='disabled', rectPt=[16, 500, 358, 48], viewSizePx=[1080, 2400], viewSizePt=[360, 800], insetBottomPx=0)
            fake_module = types.SimpleNamespace(EncryptedKeyFixture=Mock(return_value=fixture))
            process = Mock(pid=12345); process.stdout = __import__('io').BytesIO(b'')
            process.poll.side_effect = [None, None, 1, 1, 1, 1]
            failure = {'stage': 'encrypted_review', 'code': 'direct_ssh_android_ui_failed',
                       'exceptionClass': 'TestFailure',
                       'sourceLocations': [{'file': 'direct_ssh_ui_steps.dart', 'line': 717}]}
            finished = {'value': False}
            def wait(**unused): finished['value'] = True; return 1
            process.wait.side_effect = wait
            def fake_text(*args):
                values = {('devices',): 'List of devices attached\nemulator-5554 device',
                    ('shell', 'getprop', 'ro.kernel.qemu'): '1',
                    ('shell', 'getprop', 'ro.build.version.sdk'): '35',
                    ('shell', 'am', 'get-current-user'): '0',
                    ('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard'): '1'}
                return values.get(args, '')
            def read_json(path, *unused, **kwargs):
                if path.endswith('/stage.json'): return {'stage': 'encrypted_waiting_private'}
                if path.endswith('encrypted-diagnostic.json'): return diagnostic
                if path.endswith('encrypted-connect-diagnostic.json'): return connect_diagnostic
                if path.endswith('encrypted-stage.json'): return {'phase': 'review'}
                if path.endswith('failure.json') and finished['value']: return failure
                return None
            env = {'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '123', 'RUNNER_TEMP': temp}
            args = types.SimpleNamespace(project=app, output=output)
            with patch.dict(sys.modules, {'tauri_encrypted_key_fixture': fake_module}), \
                 patch.object(runner, 'checked_paths', return_value=(app, output)), \
                 patch.object(runner, 'verify_prepared'), patch.object(runner, 'text', side_effect=fake_text), \
                 patch.object(runner, 'encrypted_device_state', return_value='device'), \
                 patch.object(runner, 'package_present', side_effect=[False, True, False, False]), \
                 patch.object(runner, 'forward_set', return_value=set()), \
                 patch.object(runner, 'adb', return_value=CompletedProcess([], 0, b'', b'')), \
                 patch.object(runner, 'read_public_json', side_effect=read_json), \
                 patch.object(runner.time, 'sleep'), patch.object(runner.subprocess, 'Popen', return_value=process):
                with self.assertRaisesRegex(runner.Failure, 'direct_android_device_test_failed'):
                    runner.run_encrypted(args, env)
            result = json.loads((output/'result.json').read_text())
            self.assertEqual(result['failureStage'], 'encrypted_review')
            self.assertEqual(result['deviceFailure'], failure)
            self.assertEqual(result['checkpoints'], {'review': probe})
            self.assertEqual(result['uiDiagnostic'], diagnostic)
            self.assertEqual(result['connectDiagnostic'], connect_diagnostic)
            self.assertNotIn('sensitive-test-key', json.dumps(result))
            self.assertNotIn('sensitive-test-phrase', json.dumps(result))
            self.assertFalse(Path(key_temp.name).exists())

    def test_complete_case_requires_review_rejection_ocr_and_live_peer_confirmation(self):
        self.assert_complete_encrypted_case(rotating=False)

    def test_complete_rotation_case_requires_the_single_rotating_peer_for_ocr_and_auth(self):
        self.assert_complete_encrypted_case(rotating=True)

    def assert_complete_encrypted_case(self, *, rotating):
        from screen_proof_token import SCREEN_WORDS
        phases = ('review', 'rejected', 'cancelled', 'reprobed') if rotating else ('review', 'rejected')
        screen_tag = 'key-rotation' if rotating else 'ordinary'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app = root / 'app'; app.mkdir(); output = root / 'public'
            key_temp = tempfile.TemporaryDirectory(dir=temp)
            fixture = MagicMock(port=40001, username='fixture', private_key='sensitive-test-key',
                passphrase='sensitive-test-phrase', fingerprint='SHA256:public', rotated_fingerprint='SHA256:rotated',
                screen_token=' '.join(SCREEN_WORDS[:8]), echo_marker='POCKET-ANDROID-SSH-OK')
            fixture._temp = key_temp; fixture.__enter__.return_value = fixture
            def exit_fixture(*unused):
                fixture.private_key = fixture.passphrase = ''
                key_temp.cleanup()
            fixture.__exit__.side_effect = exit_fixture
            probe = dict(id=1, hostKey='A', authAttempts=0, authSuccesses=0,
                ptyRequests=0, shellRequests=0, inputBytes=0, outputBytes=0,
                authAccepted=False, markerReceived=False, sessionClosed=False, closed=True)
            session = dict(id=2, hostKey='A', authAttempts=1, authSuccesses=1,
                ptyRequests=1, shellRequests=1, inputBytes=9, outputBytes=99,
                authAccepted=True, markerReceived=True, sessionClosed=True, closed=True)
            before = dict(connections=1, connectionsClosed=True, connectionEvents=[probe])
            closed = dict(connections=2, connectionsClosed=True, connectionEvents=[probe, session])
            if rotating:
                events = [probe, {**probe, 'id': 2, 'hostKey': 'B'}, {**probe, 'id': 3, 'hostKey': 'B'},
                          {**session, 'id': 4, 'hostKey': 'B', 'publicKeyAccepted': True}]
                closed = dict(connections=4, connectionsClosed=True, connectionEvents=events)
                fixture.rotation_evidence.side_effect = [{'stage': 2}, {'stage': 2}, {'stage': 3}]
                fixture.public_key_auth_evidence.return_value = {'authAttempts': 1, 'inputBytes': 9}
            fixture.snapshot.side_effect = ([before] if rotating else [before, before]) + [closed] * 4
            fixture.wait_for_connections_closed.return_value = True
            fixture.wait_for.return_value = True
            fake_module = types.SimpleNamespace(EncryptedKeyFixture=Mock(return_value=fixture),
                                                RotatingEncryptedKeyFixture=Mock(return_value=fixture))
            process = Mock(pid=12345); process.stdout = __import__('io').BytesIO(b'')
            process.poll.return_value = None
            def wait(**unused): process.poll.return_value = 0; return 0
            process.wait.side_effect = wait
            def fake_text(*args):
                values = {('devices',): 'List of devices attached\nemulator-5554 device',
                    ('shell', 'getprop', 'ro.kernel.qemu'): '1',
                    ('shell', 'getprop', 'ro.build.version.sdk'): '35',
                    ('shell', 'am', 'get-current-user'): '0',
                    ('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard'): '1'}
                return values.get(args, '')
            current = {'round': 0}
            fields = runner.ENCRYPTED_ROTATION_PUBLIC_FIELDS if rotating else runner.ENCRYPTED_PUBLIC_FIELDS
            device = dict.fromkeys(fields, True)
            device.update(schemaVersion=1, platform='android-api35-emulator', physicalImeVerified=False)
            diagnostic = {'phase': 'encrypted_capture', 'terminalCount': 1,
                'terminalHit': True, 'disconnectHit': True, 'toggleHit': True, 'enterHit': False, 'headerHit': True,
                'toggleState': 'open', 'insetBottomPx': 0, 'viewSizePx': [1080, 2400],
                'terminalRectPt': [16, 144, 320, 300], 'enterRectPt': [300, 400, 54, 44], 'columns': 22, 'rows': 10,
                'terminalFocused': False, 'testInputRegistered': True, 'testClientSet': True,
                'welcomeVisible': True, 'echoVisible': True}
            def read_json(path, *unused, **kwargs):
                if path.endswith('/stage.json'): return {'stage': 'encrypted_waiting_private'}
                if path.endswith('encrypted-diagnostic.json'): return diagnostic
                if path.endswith('screen-request.json'):
                    return {'tag': screen_tag} if current['round'] == len(phases) else None
                if path.endswith('encrypted-stage.json'):
                    return {'phase': phases[min(current['round'], len(phases) - 1)]}
                if path.endswith('encrypted-result.json'):
                    result = device if current['round'] == len(phases) else None
                    current['round'] += 1
                    return result
                return None
            def screenshot(request, screens, ordinary_peer, rotation_peer, *unused, require_rotation):
                self.assertIs(require_rotation, rotating)
                self.assertIs(ordinary_peer, fixture)
                self.assertIs(rotation_peer, fixture if rotating else None)
                screens[request['tag']] = {'attempt': 1, 'accepted': True, 'expectedTarget': 'fixture@127.0.0.1:40001'}
            def start_tool(command, **unused):
                defines_path = next(item.split('=', 1)[1] for item in command if item.startswith('--dart-define-from-file='))
                defines = json.loads(Path(defines_path).read_text())
                self.assertEqual(defines['HERDR_ANDROID_ENCRYPTED_KEY_CASE'], 'rotation' if rotating else '1')
                target = json.loads(defines['HERDR_ANDROID_ENCRYPTED_KEY_TARGET'])
                self.assertEqual(target['fingerprint'], fixture.fingerprint)
                self.assertEqual(target.get('rotatedFingerprint'), fixture.rotated_fingerprint if rotating else None)
                self.assertNotIn('sensitive-test-key', json.dumps(defines))
                return process
            png = b'\x89PNG\r\n\x1a\n' + b'test'
            env = {'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '123', 'RUNNER_TEMP': temp,
                   'GITHUB_EVENT_NAME': 'workflow_dispatch'}
            args = types.SimpleNamespace(project=app, output=output)
            with patch.dict(sys.modules, {'tauri_encrypted_key_fixture': fake_module}), \
                 patch.object(runner, 'checked_paths', return_value=(app, output)), \
                 patch.object(runner, 'verify_prepared'), patch.object(runner, 'text', side_effect=fake_text), \
                 patch.object(runner, 'encrypted_device_state', return_value='device'), \
                 patch.object(runner, 'package_present', side_effect=[False] + [True] * (len(phases) + 2) + [False]), \
                 patch.object(runner, 'forward_set', return_value=set()), \
                 patch.object(runner, 'adb', return_value=CompletedProcess([], 0, png, b'')) as adb, \
                 patch.object(runner, 'read_public_json', side_effect=read_json), \
                 patch.object(runner, 'screen_checkpoint', side_effect=screenshot), \
                 patch.object(runner.time, 'sleep'), patch.object(runner.subprocess, 'Popen', side_effect=start_tool):
                report = runner.run_encrypted(args, env, rotating=rotating)
            self.assertEqual(report['status'], 'passed')
            self.assertTrue(report['startup']['packageObserved'])
            self.assertTrue(report['startup']['appStageObserved'])
            self.assertTrue(report['startup']['privateInputDelivered'])
            self.assertEqual(report['startup']['tool']['streamState'], 'eof')
            self.assertEqual(report['uiDiagnostic'], diagnostic)
            self.assertEqual(tuple(report['checkpoints']), phases)
            self.assertEqual(tuple(report['screenProof']), (screen_tag,))
            self.assertEqual(report['authenticationMethod'], 'publickey')
            if rotating:
                self.assertEqual(report['kind'], 'flutter-android-encrypted-ed25519-rotation')
                self.assertEqual(report['rotatedSessionEvidence'], {'authAttempts': 1, 'inputBytes': 9})
                self.assertEqual([call.args[0] for call in fixture.rotation_evidence.call_args_list], [2, 2, 3])
                fake_module.RotatingEncryptedKeyFixture.assert_called_once_with()
                fake_module.EncryptedKeyFixture.assert_not_called()
            else:
                fake_module.RotatingEncryptedKeyFixture.assert_not_called()
            self.assertTrue(report['peerClosedBeforeDriverExit'])
            self.assertTrue(report['cleanup']['temporaryKeyRemoved'])
            self.assertFalse(report['cleanup']['rawLogsUploaded'])
            calls = adb.call_args_list
            self.assertTrue(any(call.args == ('reverse', '--no-rebind', 'tcp:40001', 'tcp:40001') for call in calls))
            self.assertTrue(any(call.args == ('reverse', '--remove', 'tcp:40001') for call in calls))
            secret_writes = [call for call in calls if call.kwargs.get('data') and b'sensitive-test-key' in call.kwargs['data']]
            self.assertEqual(len(secret_writes), 1)
            self.assertNotIn('sensitive-test-key', (output/'result.json').read_text())
            self.assertNotIn('sensitive-test-phrase', (output/'result.json').read_text())
            self.assertFalse(Path(key_temp.name).exists())

    @unittest.skipUnless(importlib.util.find_spec('paramiko') and __import__('shutil').which('ssh-keygen'),
                         'Paramiko and ssh-keygen required')
    def test_real_encrypted_peer_authenticates_once_echoes_proof_and_closes(self):
        import io
        import paramiko
        from tauri_encrypted_key_fixture import EncryptedKeyFixture
        from screen_proof_token import token_lines
        with EncryptedKeyFixture(screen_proof=True) as fixture:
            private_dir = fixture._temp.name
            fixture.echo_marker += '\r\n' + '\r\n'.join(token_lines(fixture.screen_token))
            with paramiko.Transport(('127.0.0.1', fixture.port)) as probe:
                probe.start_client(timeout=5)
                self.assertEqual(probe.get_remote_server_key(), fixture._key)
            runner.encrypted_probe_evidence(fixture)
            key = paramiko.Ed25519Key.from_private_key(io.StringIO(fixture.private_key), password=fixture.passphrase)
            transport = paramiko.Transport(('127.0.0.1', fixture.port))
            try:
                transport.start_client(timeout=5)
                transport.auth_publickey(fixture.username, key)
                channel = transport.open_session(timeout=5)
                channel.get_pty(); channel.invoke_shell(); channel.settimeout(5)
                channel.sendall(b'hp-check\r')
                self.assertTrue(fixture.wait_for('markerReceived'))
                output = b''
                while token_lines(fixture.screen_token)[-1].encode() not in output and len(output) < 8192:
                    output += channel.recv(8192)
                self.assertIn(b'POCKET-ANDROID-SSH-OK', output)
                for token in token_lines(fixture.screen_token): self.assertIn(token.encode(), output)
                channel.close()
                self.assertTrue(fixture.wait_for('sessionClosed'))
            finally:
                transport.close()
            self.assertTrue(fixture.wait_for_connections_closed(2))
            runner.ordinary_session_evidence(fixture, closed=True)
        self.assertFalse(Path(private_dir).exists())
        self.assertEqual((fixture.private_key, fixture.passphrase), ('', ''))

    @unittest.skipUnless(importlib.util.find_spec('paramiko') and __import__('shutil').which('ssh-keygen'),
                         'Paramiko and ssh-keygen required')
    def test_real_encrypted_rotation_peer_rejects_b_before_one_public_key_session(self):
        import io
        import paramiko
        from tauri_encrypted_key_fixture import RotatingEncryptedKeyFixture
        from screen_proof_token import token_lines
        with RotatingEncryptedKeyFixture() as fixture:
            private_dir = Path(fixture._temp.name)
            key = paramiko.Ed25519Key.from_private_key(io.StringIO(fixture.private_key), fixture.passphrase)
            with paramiko.Transport(('127.0.0.1', fixture.port)) as probe:
                probe.start_client(timeout=5)
                self.assertEqual(probe.get_remote_server_key(), fixture._key)
            runner.encrypted_probe_evidence(fixture)
            for stage in (2, 3):
                with paramiko.Transport(('127.0.0.1', fixture.port)) as probe:
                    probe.start_client(timeout=5)
                    self.assertEqual(probe.get_remote_server_key(), fixture._rotated_key)
                    self.assertNotEqual(probe.get_remote_server_key(), fixture._key)
                checkpoints = runner.closed_rotation_evidence(fixture, stage)
                self.assertEqual(checkpoints['connections'], stage)
                self.assertEqual(checkpoints['rejectedTransport']['authAttempts'], 0)
                if stage == 2:
                    self.assertEqual(runner.closed_rotation_evidence(fixture, 2), checkpoints)
            with paramiko.Transport(('127.0.0.1', fixture.port)) as session:
                session.start_client(timeout=5)
                self.assertEqual(session.get_remote_server_key(), fixture._rotated_key)
                session.auth_publickey(fixture.username, key)
                channel = session.open_session(timeout=5)
                channel.get_pty(); channel.invoke_shell(); channel.settimeout(5)
                channel.sendall(b'hp-check\r')
                last_token = token_lines(fixture.screen_token)[-1].encode()
                output = b''
                while last_token not in output and len(output) < 8192:
                    data = channel.recv(8192)
                    if not data:
                        break
                    output += data
                self.assertIn(b'POCKET-ANDROID-SSH-OK', output)
                for token in token_lines(fixture.screen_token):
                    self.assertIn(token.encode(), output)
                channel.close()
                self.assertTrue(fixture.wait_for('sessionClosed'))
            self.assertTrue(fixture.wait_for_connections_closed(4))
            evidence = runner.encrypted_rotation_final_evidence(fixture)
            self.assertEqual((evidence['authAttempts'], evidence['ptyRequests'], evidence['shellRequests']), (1, 1, 1))
            self.assertTrue(evidence['publicKeyAccepted'])
        self.assertFalse(private_dir.exists())
        self.assertEqual((fixture.private_key, fixture.passphrase), ('', ''))

if __name__ == '__main__':
    unittest.main()
