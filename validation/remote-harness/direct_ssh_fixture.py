#!/usr/bin/env python3
"""Shared, disposable ordinary SSH peer. Only binds loopback; never executes input.

The existing Paramiko Server is reused. No host authorization, accounts, user
keys, herdr, sockets, or pairing helpers are accessed. Raw input is not logged.
"""
import base64
import hashlib
import importlib.util
from pathlib import Path
import re
import secrets
import socket
import threading
import time

import paramiko

_SOURCE = Path(__file__).resolve().parents[1] / 'flutter/test/direct_ssh_fixture.py'
_spec = importlib.util.spec_from_file_location('herdr_existing_plain_ssh_fixture', _SOURCE)
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)


class DirectSshFixture:
    marker = 'hp-check'
    echo_marker = 'POCKET-ANDROID-SSH-OK'
    username = 'fixture'

    def __init__(self):
        self.password = secrets.token_hex(16)
        self._key = paramiko.RSAKey.generate(2048)
        self.public_key = f'{self._key.get_name()} {self._key.get_base64()}'
        self.fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(self._key.asbytes()).digest()).decode().rstrip('=')
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._listener = None
        self._threads = []
        self._transports = set()
        self._facts = {name: False for name in ('authAccepted', 'ptyRequested', 'shellRequested', 'markerReceived', 'sessionClosed')}
        self._connections = 0
        self._dimensions = []

    def _record(self, key):
        with self._lock:
            self._facts[key] = True

    def snapshot(self):
        with self._lock:
            return {**self._facts, 'connections': self._connections,
                    'connectionsClosed': not self._transports,
                    'ptySizes': [list(size) for size in self._dimensions]}

    def wait_for(self, field, timeout=10):
        if field not in self._facts and field != 'connectionsClosed':
            raise ValueError('unknown_fixture_field')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.snapshot()[field]:
                return True
            time.sleep(.02)
        return False

    def __enter__(self):
        self._listener = socket.socket()
        self._listener.bind(('127.0.0.1', 0))
        self.port = self._listener.getsockname()[1]
        self._listener.listen(8)
        self._listener.settimeout(.2)
        thread = threading.Thread(target=self._serve, daemon=True)
        self._threads.append(thread)
        thread.start()
        return self

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            transport = paramiko.Transport(conn)
            transport.add_server_key(self._key)
            with self._lock:
                self._connections += 1
                self._transports.add(transport)
            thread = threading.Thread(target=self._handle, args=(transport,), daemon=True)
            self._threads.append(thread)
            thread.start()

    def _handle(self, transport):
        owner = self

        class Server(_base.Server):
            def check_auth_password(self, username, password):
                accepted = username == owner.username and secrets.compare_digest(password, owner.password)
                if accepted:
                    owner._record('authAccepted')
                return paramiko.AUTH_SUCCESSFUL if accepted else paramiko.AUTH_FAILED

            def check_auth_publickey(self, username, offered):
                return paramiko.AUTH_FAILED

            def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
                owner._record('ptyRequested')
                with owner._lock:
                    if len(owner._dimensions) < 16:
                        owner._dimensions.append((width, height))
                return True

            def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
                with owner._lock:
                    if len(owner._dimensions) < 16:
                        owner._dimensions.append((width, height))
                return True

            def check_channel_shell_request(self, channel):
                owner._record('shellRequested')
                return super().check_channel_shell_request(channel)

        server = Server()
        shell_open = False
        try:
            transport.start_server(server=server)
            channel = transport.accept(10)
            if channel is None or not server.shell.wait(10):
                return
            shell_open = True
            channel.settimeout(.2)
            channel.sendall(b'POCKET-ANDROID-READY\r\n$ ')
            pending = b''
            while not self._stop.is_set() and transport.is_active():
                try:
                    data = channel.recv(1024)
                except socket.timeout:
                    continue
                if not data:
                    break
                pending += data
                if len(pending) > 4096:
                    break
                if re.search(rb'(?:^|[\r\n])hp-check[\r\n]', pending):
                    self._record('markerReceived')
                    channel.sendall(('\r\n\x1b[32m' + self.echo_marker + '\x1b[0m\r\n$ ').encode())
                    pending = b''
        except (EOFError, OSError, paramiko.SSHException):
            pass
        finally:
            if shell_open and not self._stop.is_set():
                self._record('sessionClosed')
            transport.close()
            with self._lock:
                self._transports.discard(transport)

    def close(self):
        self._stop.set()
        if self._listener is not None:
            self._listener.close()
        if self._threads:
            self._threads[0].join(timeout=2)
        with self._lock:
            transports = list(self._transports)
        for transport in transports:
            transport.close()
        # The listener exits before reading the final worker list.
        for thread in list(self._threads):
            thread.join(timeout=2)
        self.password = ''

    def __exit__(self, *_):
        self.close()
