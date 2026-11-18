"""Optional protocol check; dedicated device workflow requires Paramiko."""
import importlib.util
import io
import os
import shutil
import unittest


@unittest.skipUnless(importlib.util.find_spec('paramiko') and shutil.which('ssh-keygen'), 'Paramiko and ssh-keygen required')
class EncryptedKeyFixtureTests(unittest.TestCase):
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
                channel.close();self.assertTrue(peer.wait_for('sessionClosed'))
                self.assertTrue(all(peer.snapshot()[k] for k in ('authAccepted','ptyRequested','shellRequested')))
            finally:
                client.close()
        self.assertFalse(os.path.exists(path))
        self.assertEqual(peer.private_key,'');self.assertEqual(peer.passphrase,'')


if __name__=='__main__':
    unittest.main()
