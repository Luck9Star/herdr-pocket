"""Standard-library guards plus an actual loopback SSH protocol/cleanup test."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from subprocess import CompletedProcess
from unittest.mock import patch
import unittest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('ordinary_android_runner', HERE / 'flutter_direct_ssh_android.py')
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


class GuardTests(unittest.TestCase):
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
        for change in ({'remoteEchoVisible': False}, {'physicalImeVerified': True}, {'password': 'must-not-export'}):
            with self.subTest(change=tuple(change)), self.assertRaises(runner.Failure):
                runner.safe_result(json.dumps({**result, **change}))

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
    def test_shared_peer_requires_auth_pty_shell_marker_and_peer_close_then_cleans(self):
        import paramiko
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture() as fixture:
            transport = paramiko.Transport(('127.0.0.1', fixture.port))
            try:
                transport.start_client(timeout=5)
                self.assertEqual(transport.get_remote_server_key().get_base64(), fixture.public_key.split()[1])
                transport.auth_password(fixture.username, fixture.password)
                channel = transport.open_session(timeout=5)
                channel.get_pty(term='xterm-256color', width=80, height=24)
                channel.invoke_shell()
                channel.settimeout(5)
                channel.sendall((fixture.marker + '\r').encode())
                received = b''
                while fixture.echo_marker.encode() not in received:
                    received += channel.recv(4096)
                self.assertIn(b'\x1b[32m' + fixture.echo_marker.encode(), received)
                channel.close()
            finally:
                transport.close()
            self.assertTrue(fixture.wait_for('sessionClosed'))
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
