"""Optional protocol check; dedicated device workflow requires Paramiko."""
import importlib.util
import io
import os
import shutil
import unittest
from unittest.mock import Mock


@unittest.skipUnless(importlib.util.find_spec('paramiko') and shutil.which('ssh-keygen'), 'Paramiko and ssh-keygen required')
class EncryptedKeyFixtureTests(unittest.TestCase):
    def test_key_selection_cannot_record_success_before_authenticated_channel(self):
        import paramiko
        from tauri_encrypted_key_fixture import EncryptedKeyFixture

        peer = EncryptedKeyFixture()
        peer._expected = 'fixture-public-key-id'
        peer._facts['publicKeyAccepted'] = False
        transport = Mock(spec=paramiko.Transport)
        transport.accept.return_value = None
        transport.is_authenticated.return_value = False
        event = {'authAttempts': 0, 'authSuccesses': 0, 'authAccepted': False}
        peer._events_by_transport[transport] = event
        peer._connection_events.append(event)
        offered = Mock(spec=paramiko.PKey)
        offered.get_base64.return_value = peer._expected

        def assert_observation(attempts, authenticated):
            facts = peer.snapshot()
            row = facts['connectionEvents'][0]
            self.assertEqual(row['authAttempts'], attempts)
            self.assertEqual(row['authSuccesses'], int(authenticated))
            for name in ('authAccepted', 'publicKeyAccepted'):
                self.assertIs(facts[name], authenticated)
                self.assertIs(row.get(name, False), authenticated)

        def simulate_callbacks(*, server):
            # A permitted key lookup says only that the server would verify its signature.
            self.assertEqual(server.check_auth_publickey(peer.username, offered), paramiko.AUTH_SUCCESSFUL)
            assert_observation(1, False)
            self.assertEqual(server.check_channel_request('session', 0), paramiko.OPEN_SUCCEEDED)
            assert_observation(1, False)
            self.assertEqual(server.check_auth_publickey(peer.username, offered), paramiko.AUTH_SUCCESSFUL)
            assert_observation(2, False)
            transport.is_authenticated.return_value = True
            self.assertEqual(server.check_channel_request('unknown', 1), paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED)
            assert_observation(2, False)
            for channel in (2, 3):
                self.assertEqual(server.check_channel_request('session', channel), paramiko.OPEN_SUCCEEDED)
                assert_observation(2, True)

        transport.start_server.side_effect = simulate_callbacks
        peer._handle(transport)

    def test_observes_probe_and_rejected_authentication_as_distinct_connections(self):
        import paramiko
        from tauri_encrypted_key_fixture import EncryptedKeyFixture
        with EncryptedKeyFixture() as peer:
            with paramiko.Transport(('127.0.0.1', peer.port)) as probe:
                probe.start_client(timeout=5)
                self.assertEqual(probe.get_remote_server_key(), peer._key)
            self.assertTrue(peer.wait_for_connections_closed(1, timeout=5))
            with paramiko.Transport(('127.0.0.1', peer.port)) as attempt:
                attempt.start_client(timeout=5)
                with self.assertRaises(paramiko.AuthenticationException):
                    attempt.auth_password(peer.username, peer.password, fallback=False)
            self.assertTrue(peer.wait_for_connections_closed(2, timeout=5))
            first, second = peer.snapshot()['connectionEvents']
            self.assertEqual((first['authAttempts'], second['authAttempts']), (0, 1))
            for event in (first, second):
                self.assertTrue(event['closed'])
                self.assertEqual([event[name] for name in ('authSuccesses', 'ptyRequests', 'shellRequests',
                                                         'inputBytes', 'outputBytes')], [0] * 5)

    def test_encrypted_key_reaches_owned_pty_and_closes(self):
        import paramiko
        from tauri_encrypted_key_fixture import EncryptedKeyFixture
        with EncryptedKeyFixture() as peer:
            path = peer._temp.name
            with self.assertRaises(paramiko.PasswordRequiredException):
                paramiko.Ed25519Key.from_private_key(io.StringIO(peer.private_key))
            with self.assertRaises(paramiko.SSHException):
                paramiko.Ed25519Key.from_private_key(io.StringIO(peer.private_key),password='incorrect')
            key = paramiko.Ed25519Key.from_private_key(io.StringIO(peer.private_key),password=peer.passphrase)
            client = paramiko.SSHClient()
            client.get_host_keys().add('['+'127.0.0.1'+']:'+str(peer.port),'ssh-rsa',peer._key)
            try:
                with self.assertRaises(paramiko.AuthenticationException):
                    client.connect('127.0.0.1',port=peer.port,username=peer.username,password=peer.password,
                                   allow_agent=False,look_for_keys=False,timeout=10)
                self.assertFalse(peer.snapshot()['authAccepted'])
                client.connect('127.0.0.1',port=peer.port,username=peer.username,pkey=key,
                               allow_agent=False,look_for_keys=False,timeout=10)
                channel=client.invoke_shell();channel.settimeout(5);channel.sendall(b'hp-check\n')
                self.assertTrue(peer.wait_for('markerReceived'))
                output=b''
                while peer.echo_marker.encode() not in output and len(output)<4096:
                    output+=channel.recv(4096)
                self.assertIn(peer.echo_marker.encode(),output)
                with client.get_transport().open_session(timeout=5):
                    event = peer.snapshot()['connectionEvents'][-1]
                    self.assertEqual(event['authAttempts'], 1)
                    self.assertEqual(event['authSuccesses'], 1)
                    self.assertIs(event['publicKeyAccepted'], True)
                channel.close();self.assertTrue(peer.wait_for('sessionClosed'))
                self.assertTrue(all(peer.snapshot()[k] for k in ('authAccepted','ptyRequested','shellRequested')))
            finally:
                client.close()
        self.assertFalse(os.path.exists(path))
        self.assertEqual(peer.private_key,'');self.assertEqual(peer.passphrase,'')


if __name__=='__main__':
    unittest.main()
