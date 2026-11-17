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
    """An opt-in rotating peer with per-transport server observations.

    Rotation selects A for the first accepted connection, then B permanently;
    the runner must reserve connection 1 for its explicit initial key probe.
    authAttempts counts the none/password/publickey/interactive authorization
    checks reached by normal SSH clients, including rejected checks. It does
    not count malformed packets rejected internally by Paramiko. outputBytes
    counts successful shell sendall calls, not client rendering or receipt.
    No credentials, public keys, usernames, or raw input enter the event log.
    """

    marker = 'hp-check'
    echo_marker = 'POCKET-ANDROID-SSH-OK'
    username = 'fixture'

    def __init__(self, *, observe_helper_keys=False, rotate_after_probe=False, screen_proof=False):
        self._observe_helper_keys = observe_helper_keys
        self._rotate_after_probe = rotate_after_probe
        # Public, per-peer freshness proof, emitted only by this SSH server.
        # Keep the default protocol byte-for-byte compatible with other probes.
        self.screen_token = (''.join(secrets.choice('ACDEFHJKMNPQRTUVWXY34679') for _ in range(12))
                             if screen_proof else None)
        self._helper_bytes = b''
        self.password = secrets.token_hex(16)
        self._key = paramiko.RSAKey.generate(2048)
        self.public_key = f'{self._key.get_name()} {self._key.get_base64()}'
        self.fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(self._key.asbytes()).digest()).decode().rstrip('=')
        self._rotated_key = paramiko.RSAKey.generate(2048) if rotate_after_probe else None
        self.rotated_public_key = (f'{self._rotated_key.get_name()} {self._rotated_key.get_base64()}'
                                   if self._rotated_key is not None else None)
        self.rotated_fingerprint = ('SHA256:' + base64.b64encode(hashlib.sha256(
            self._rotated_key.asbytes()).digest()).decode().rstrip('=')
            if self._rotated_key is not None else None)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._listener = None
        self._threads = []
        self._transports = set()
        self._facts = {name: False for name in ('authAccepted', 'ptyRequested', 'shellRequested', 'markerReceived', 'sessionClosed')}
        if observe_helper_keys:
            self._facts['helperKeysExact'] = False
        self._connections = 0
        self._dimensions = []
        self._connection_events = []
        self._events_by_transport = {}

    def _connection_record(self, transport, field, value=True):
        with self._lock:
            self._events_by_transport[transport][field] = value

    def _connection_increment(self, transport, field, amount=1):
        with self._lock:
            self._events_by_transport[transport][field] += amount

    def _record(self, key):
        with self._lock:
            self._facts[key] = True

    def snapshot(self):
        with self._lock:
            return {**self._facts, 'connections': self._connections,
                    'connectionsClosed': not self._transports,
                    'ptySizes': [list(size) for size in self._dimensions],
                    'connectionEvents': [dict(event) for event in self._connection_events]}

    def rotation_evidence(self, stage):
        """Validate a closed 2/3/4-connection checkpoint and return safe facts.

        Intent labels come from the runner's ordered probe/reject/reprobe/session
        protocol, never from a server inference about an unauthenticated peer.
        Stage 4 validates all three earlier transports independently as well.
        """
        def require(condition):
            if not condition:
                raise ValueError('invalid_rotation_evidence')

        require(self._rotate_after_probe and type(stage) is int and stage in (2, 3, 4))
        facts = self.snapshot()
        events = facts['connectionEvents']
        require(type(facts['connections']) is int and facts['connections'] == stage
                and facts['connectionsClosed'] is True and len(events) == stage)
        counters = ('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests',
                    'inputBytes', 'outputBytes')
        booleans = ('authAccepted', 'markerReceived', 'sessionClosed', 'closed')
        labels = ('initialProbe', 'rejectedTransport', 'freshProbe', 'acceptedSession')
        evidence = {'stage': stage, 'connections': stage, 'connectionsClosed': True}
        for index, event in enumerate(events):
            require(type(event['id']) is int and event['id'] == index + 1
                    and event['hostKey'] == ('A' if index == 0 else 'B')
                    and event['closed'] is True)
            require(all(type(event[field]) is int and event[field] >= 0 for field in counters)
                    and all(type(event[field]) is bool for field in booleans))
            if index < 3:
                require(all(event[field] == 0 for field in counters)
                        and not any(event[field] for field in booleans if field != 'closed'))
            else:
                require(event['authAttempts'] >= 1 and event['authSuccesses'] == 1
                        and event['ptyRequests'] == 1 and event['shellRequests'] == 1
                        and event['inputBytes'] > 0 and event['outputBytes'] > 0
                        and all(event[field] for field in booleans))
            evidence[labels[index]] = {field: event[field]
                                      for field in ('id', 'hostKey', *counters, *booleans)}
        return evidence

    def wait_for_connections_closed(self, minimum, timeout=10):
        """Wait for a runner checkpoint; this never labels a connection's intent.

        With rotation enabled, only connection 1 uses A, and all later ones use
        B on the same listener. A runner must identify probe/rejection phases
        from its own actions, then check exact counts and zero auth/PTY/IO.
        """
        if type(minimum) is not int or minimum < 1:
            raise ValueError('invalid_connection_minimum')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            facts = self.snapshot()
            if (facts['connections'] >= minimum and facts['connectionsClosed']
                    and all(event['closed'] for event in facts['connectionEvents'])):
                return True
            time.sleep(.02)
        return False

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
            with self._lock:
                self._connections += 1
                rotated = self._rotate_after_probe and self._connections > 1
                event = {'id': self._connections, 'hostKey': 'B' if rotated else 'A',
                         'handshakeCompleted': False, 'authAttempts': 0,
                         'authAccepted': False, 'authSuccesses': 0,
                         'ptyRequests': 0, 'shellRequests': 0,
                         'inputBytes': 0, 'outputBytes': 0,
                         'markerReceived': False, 'sessionClosed': False,
                         'closed': False}
                self._connection_events.append(event)
                self._events_by_transport[transport] = event
                self._transports.add(transport)
            transport.add_server_key(self._rotated_key if rotated else self._key)
            thread = threading.Thread(target=self._connection_worker, args=(transport,), daemon=True)
            self._threads.append(thread)
            thread.start()

    def _connection_worker(self, transport):
        try:
            self._handle(transport)
        finally:
            transport.close()
            with self._lock:
                self._events_by_transport[transport]['closed'] = True
                self._transports.discard(transport)

    def _handle(self, transport):
        owner = self

        class Server(_base.Server):
            def check_auth_none(self, username):
                owner._connection_increment(transport, 'authAttempts')
                return paramiko.AUTH_FAILED

            def check_auth_password(self, username, password):
                owner._connection_increment(transport, 'authAttempts')
                accepted = username == owner.username and secrets.compare_digest(password, owner.password)
                if accepted:
                    owner._record('authAccepted')
                    owner._connection_record(transport, 'authAccepted')
                    owner._connection_increment(transport, 'authSuccesses')
                return paramiko.AUTH_SUCCESSFUL if accepted else paramiko.AUTH_FAILED

            def check_auth_publickey(self, username, offered):
                owner._connection_increment(transport, 'authAttempts')
                return paramiko.AUTH_FAILED

            def check_auth_interactive(self, username, submethods):
                owner._connection_increment(transport, 'authAttempts')
                return paramiko.AUTH_FAILED

            def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
                owner._record('ptyRequested')
                owner._connection_increment(transport, 'ptyRequests')
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
                owner._connection_increment(transport, 'shellRequests')
                return super().check_channel_shell_request(channel)

        server = Server()
        shell_open = False
        try:
            transport.start_server(server=server)
            self._connection_record(transport, 'handshakeCompleted')
            channel = transport.accept(10)
            if channel is None or not server.shell.wait(10):
                return
            shell_open = True
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
                if self._observe_helper_keys and self.snapshot()['markerReceived']:
                    with self._lock:
                        self._helper_bytes = (self._helper_bytes + data)[:32]
                        self._facts['helperKeysExact'] = self._helper_bytes == b'\x1b\t\x1b[D\x03'
                    continue
                pending += data
                if len(pending) > 4096:
                    break
                if re.search(rb'(?:^|[\r\n])hp-check[\r\n]', pending):
                    self._record('markerReceived')
                    self._connection_record(transport, 'markerReceived')
                    proof = self.screen_token + '\r\n' if self.screen_token is not None else ''
                    reply = ('\r\n\x1b[32m' + self.echo_marker + '\x1b[0m\r\n' + proof + '$ ').encode()
                    channel.sendall(reply)
                    self._connection_increment(transport, 'outputBytes', len(reply))
                    pending = b''
        except (EOFError, OSError, paramiko.SSHException):
            pass
        finally:
            if shell_open and not self._stop.is_set():
                self._record('sessionClosed')
                self._connection_record(transport, 'sessionClosed')
            transport.close()

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
