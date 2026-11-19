"""Disposable public-key-only loopback peer for Tauri device acceptance."""
import re
import secrets
import socket
import subprocess
import tempfile
from pathlib import Path

import paramiko
from direct_ssh_fixture import DirectSshFixture, _base


class EncryptedKeyFixture(DirectSshFixture):
    def __enter__(self):
        self._temp = tempfile.TemporaryDirectory(prefix='tauri-key-fixture-')
        path = Path(self._temp.name) / 'identity'
        self.passphrase = secrets.token_hex(16)
        try:
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N',self.passphrase,'-f',str(path)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            self.private_key = path.read_text(encoding='utf-8')
            self._expected = path.with_suffix('.pub').read_text(encoding='utf-8').split()[1]
            return super().__enter__()
        except BaseException:
            self._temp.cleanup()
            self.private_key = self.passphrase = ''
            raise

    def _handle(self, transport):
        owner = self
        class Server(_base.Server):
            def check_auth_none(self, username):
                owner._connection_increment(transport, 'authAttempts')
                return paramiko.AUTH_FAILED
            def check_auth_password(self, username, password):
                owner._connection_increment(transport, 'authAttempts')
                return paramiko.AUTH_FAILED
            def check_auth_interactive(self, username, submethods):
                owner._connection_increment(transport, 'authAttempts')
                return paramiko.AUTH_FAILED
            def check_auth_publickey(self, username, offered):
                owner._connection_increment(transport, 'authAttempts')
                accepted = username == owner.username and secrets.compare_digest(offered.get_base64(), owner._expected)
                if accepted:
                    owner._record('authAccepted')
                    owner._connection_record(transport, 'authAccepted')
                    owner._connection_increment(transport, 'authSuccesses')
                return paramiko.AUTH_SUCCESSFUL if accepted else paramiko.AUTH_FAILED
            def get_allowed_auths(self, username):
                return 'publickey'
            def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
                owner._record('ptyRequested')
                owner._connection_increment(transport, 'ptyRequests')
                return True
            def check_channel_shell_request(self, channel):
                owner._record('shellRequested')
                owner._connection_increment(transport, 'shellRequests')
                self.shell.set()
                return True
        server = Server()
        opened = False
        try:
            transport.start_server(server=server)
            self._connection_record(transport, 'handshakeCompleted')
            channel = transport.accept(10)
            if channel is None or not server.shell.wait(10):
                return
            opened = True
            channel.settimeout(.2)
            ready = b'POCKET-ANDROID-READY\r\n$ '
            channel.sendall(ready)
            self._connection_increment(transport, 'outputBytes', len(ready))
            pending = b''
            while not self._stop.is_set() and transport.is_active():
                try:
                    data = channel.recv(1024)
                except socket.timeout:
                    continue
                if not data:
                    break
                self._connection_increment(transport, 'inputBytes', len(data))
                pending += data
                if len(pending) > 4096:
                    break
                if re.search(rb'(?:^|[\r\n])hp-check[\r\n]', pending):
                    self._record('markerReceived')
                    self._connection_record(transport, 'markerReceived')
                    reply = ('\r\n\x1b[32m' + self.echo_marker + '\x1b[0m\r\n$ ').encode()
                    channel.sendall(reply)
                    self._connection_increment(transport, 'outputBytes', len(reply))
                    pending = b''
        except (EOFError, OSError, paramiko.SSHException):
            pass
        finally:
            if opened and not self._stop.is_set():
                self._record('sessionClosed')
                self._connection_record(transport, 'sessionClosed')
            transport.close()
            with self._lock:
                self._transports.discard(transport)

    def __exit__(self, *_):
        try:
            self.close()
        finally:
            self.private_key = self.passphrase = self._expected = ''
            self._temp.cleanup()
