"""Standard-library guards plus an actual loopback SSH protocol/cleanup test."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('ordinary_android_runner', HERE / 'flutter_direct_ssh_android.py')
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


class GuardTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
