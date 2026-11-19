"""Standard-library guards plus an actual loopback SSH protocol/cleanup test."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
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
                def checkpoint(request, screens, *unused):
                    screens.update({tag: {**value, 'private': 'secret'} for tag, value in observed.items()})
                    screens['unknown'] = {'attempt': 1, 'accepted': False, 'expectedTarget': 'secret'}
                    raise runner.Failure('simulated_device_failure')
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
                    with self.assertRaisesRegex(runner.Failure, 'simulated_device_failure'):
                        runner.run(args, env)
                report = json.loads((output / 'result.json').read_text())
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['screenProof'], observed)
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
            for name in ('rotation-stage.json', 'rotation-result.json', 'ordinary-mobile-stage.json'):
                self.assertIsNone(runner.read_public_json('cache/herdr-direct-ssh-123/' + name))
            for name in ('../defines.json', 'rotation-rejected-confirmed.json', 'rotation-secret.json',
                         'ordinary-mobile-keyboard_shown-confirmed.json', 'ordinary-mobile-result.json'):
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
        with DirectSshFixture(screen_proof=True, channel_deadline=deadline) as fixture:
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
                completed = {}
                for phase in runner.ORDINARY_MOBILE_PHASES:
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


if __name__ == '__main__':
    unittest.main()
