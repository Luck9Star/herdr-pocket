"""Real delayed-auth comparisons; never connects to a host account."""
import importlib.util
import errno
import socket
import struct
import threading
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('paramiko'), 'Paramiko is required')
class FixtureDeadlineTests(unittest.TestCase):
    def peer(self, fixture):
        import paramiko
        peer = paramiko.Transport(('127.0.0.1', fixture.port))
        self.addCleanup(peer.close)
        peer.start_client(timeout=5)
        return peer

    def read_until(self, channel, marker, reply=b''):
        while marker not in reply:
            data = channel.recv(4096)
            self.assertTrue(data, 'unexpected_fixture_eof')
            reply += data
        return reply

    def test_legacy_wait_closes_an_active_unauthenticated_second_a_at_ten_seconds(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture() as fixture:
            self.peer(fixture).close()
            self.assertTrue(fixture.wait_for_connections_closed(1))
            peer = self.peer(fixture)
            started = time.monotonic()
            while peer.is_active() and time.monotonic() - started < 12:
                time.sleep(.02)
            self.assertTrue(fixture.wait_for_connections_closed(2, timeout=2))
            event = fixture.snapshot()['connectionEvents'][1]
            self.assertGreaterEqual(time.monotonic() - started, 9)
            self.assertTrue(event['handshakeCompleted'])
            self.assertEqual(event['hostKey'], 'A')
            self.assertEqual([event[name] for name in ('authAttempts', 'ptyRequests', 'inputBytes', 'outputBytes')], [0] * 4)
            self.assertNotIn('closeReason', event, 'Android public schema remains unchanged')

    def test_batch_wait_survives_same_delay_then_authenticates_and_receives_one_input(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(channel_deadline=time.monotonic() + 30, screen_proof=True) as fixture:
            self.peer(fixture).close()
            self.assertTrue(fixture.wait_for_connections_closed(1))
            peer = self.peer(fixture)
            time.sleep(11)
            self.assertTrue(peer.is_active())
            self.assertEqual(fixture.snapshot()['connectionEvents'][1]['authAttempts'], 0)
            peer.auth_password(fixture.username, fixture.password)
            channel = peer.open_session(timeout=5)
            channel.get_pty(width=80, height=24)
            channel.invoke_shell()
            channel.settimeout(5)
            reply = self.read_until(channel, b'POCKET-ANDROID-READY')
            channel.sendall(b'hp-check\r')
            self.read_until(channel, b'POCKET-ANDROID-SSH-OK', reply)
            channel.close(); peer.close()
            self.assertTrue(fixture.wait_for_connections_closed(2))
            event = fixture.snapshot()['connectionEvents'][1]
            self.assertEqual(event['authAttempts'], 1)
            self.assertEqual(event['authSuccesses'], 1)
            self.assertEqual(event['ptyRequests'], 1)
            self.assertEqual(event['shellRequests'], 1)
            self.assertEqual(event['inputBytes'], 9)
            self.assertTrue(event['markerReceived'])
            self.assertTrue(event['sessionClosed'])
            self.assertIn(event['closeReason'], {'peer_eof', 'transport_closed'})
            self.assertGreaterEqual(event['firstAuthMs'], 10000)
            self.assertGreaterEqual(event['closedMs'], event['firstAuthMs'])
            self.assertIn(event['hostKeyAlgorithm'], {'rsa-sha2-256', 'rsa-sha2-512', 'ssh-rsa'})

    def test_deadline_close_never_counts_as_ui_session_close(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(channel_deadline=time.monotonic() + 1) as fixture:
            self.peer(fixture)
            self.assertTrue(fixture.wait_for_connections_closed(1, timeout=3))
            event = fixture.snapshot()['connectionEvents'][0]
            self.assertEqual(event['closeReason'], 'batch_deadline')
            self.assertEqual(event['authAttempts'], 0)
            self.assertFalse(event['sessionClosed'])

    def test_peer_cancel_closes_before_deadline_without_authentication(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(channel_deadline=time.monotonic() + 30) as fixture:
            peer = self.peer(fixture)
            peer.close()
            self.assertTrue(fixture.wait_for_connections_closed(1, timeout=3))
            event = fixture.snapshot()['connectionEvents'][0]
            self.assertIn(event['closeReason'], {'peer_eof', 'transport_closed', 'preauth_peer_reset',
                                                 'preauth_peer_abort', 'preauth_peer_broken_pipe'})
            self.assertEqual([event[name] for name in ('authAttempts', 'authSuccesses', 'ptyRequests',
                             'shellRequests', 'inputBytes', 'outputBytes')], [0] * 6)
            self.assertFalse(event['sessionClosed'])
            if event['closeReason'].startswith('preauth_peer_'):
                self.assertIn(event['socketErrno'], {errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE})

    def abort_peer(self, peer):
        # Kernel-generated RST, without an SSH channel EOF/close. Linger's
        # native int pair is the POSIX layout on the Darwin/Linux test hosts.
        peer.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
        peer.close()
        self.assertFalse(peer.is_active())

    def test_only_known_posix_errno_and_strict_zero_auth_admit_pre_auth_close(self):
        from direct_ssh_fixture import DirectSshFixture
        fixture = DirectSshFixture(channel_deadline=time.monotonic() + 10)
        transport = object()
        event = {name: 0 for name in ('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes')}
        event.update(authAccepted=False, markerReceived=False, sessionClosed=False)
        fixture._events_by_transport[transport] = event
        for code, reason in ((errno.ECONNRESET, 'preauth_peer_reset'), (errno.ECONNABORTED, 'preauth_peer_abort'),
                             (errno.EPIPE, 'preauth_peer_broken_pipe'), (errno.EIO, 'socket_error')):
            self.assertEqual(fixture._socket_close_reason(transport, OSError(code, 'private-text')), reason)
        self.assertEqual(fixture._socket_close_reason(transport, OSError('private-text')), 'socket_error')
        event['authAttempts'] = 1
        self.assertEqual(fixture._socket_close_reason(transport, OSError(errno.ECONNRESET, 'private-text')),
                         'authentication_socket_error')
        event['authAccepted'] = True
        self.assertEqual(fixture._socket_close_reason(transport, OSError(errno.ECONNRESET, 'private-text')),
                         'session_socket_error')
        self.assertNotIn('private-text', str(event))

    def test_controlled_pre_auth_reset_has_errno_and_never_becomes_session_close(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(channel_deadline=time.monotonic() + 10) as fixture:
            peer = self.peer(fixture)
            deadline = time.monotonic() + 2
            while not fixture.snapshot()['connectionEvents'][0]['handshakeCompleted'] and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(fixture.snapshot()['connectionEvents'][0]['handshakeCompleted'])
            self.abort_peer(peer)
            self.assertTrue(fixture.wait_for_connections_closed(1, timeout=3))
            event = fixture.snapshot()['connectionEvents'][0]
            self.assertEqual(event['closeReason'], 'preauth_peer_reset')
            self.assertEqual(event['socketErrorKind'], 'connection_reset')
            self.assertEqual(event['socketErrno'], errno.ECONNRESET)
            self.assertEqual([event[name] for name in ('authAttempts', 'authSuccesses', 'ptyRequests',
                             'shellRequests', 'inputBytes', 'outputBytes')], [0] * 6)
            self.assertFalse(event['sessionClosed'])

    def test_unrelated_socket_errno_is_not_cancel_even_with_zero_authentication(self):
        import paramiko
        from direct_ssh_fixture import DirectSshFixture
        release = threading.Event()
        def unrelated_error(transport, timeout=None):
            self.assertTrue(release.wait(10))
            raise OSError(errno.EIO, 'synthetic-unrelated-io-error')
        with patch.object(paramiko.Transport, 'accept', unrelated_error):
            with DirectSshFixture(channel_deadline=time.monotonic() + 10) as fixture:
                self.peer(fixture)
                release.set()
                self.assertTrue(fixture.wait_for_connections_closed(1, timeout=3))
                event = fixture.snapshot()['connectionEvents'][0]
                self.assertEqual(event['closeReason'], 'socket_error')
                self.assertEqual(event['socketErrorKind'], 'other')
                self.assertEqual(event['socketErrno'], errno.EIO)
                self.assertEqual(event['authAttempts'], 0)
                self.assertFalse(event['sessionClosed'])
                self.assertNotIn('synthetic-unrelated', str(event))

    def test_authenticated_shell_reset_does_not_count_as_normal_disconnect(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(channel_deadline=time.monotonic() + 10) as fixture:
            peer = self.peer(fixture)
            peer.auth_password(fixture.username, fixture.password)
            channel = peer.open_session(timeout=2)
            channel.get_pty(); channel.invoke_shell(); channel.settimeout(2)
            reply = self.read_until(channel, b'POCKET-ANDROID-READY')
            channel.sendall(b'hp-check\r')
            self.read_until(channel, b'POCKET-ANDROID-SSH-OK', reply)
            self.abort_peer(peer)
            self.assertTrue(fixture.wait_for_connections_closed(1, timeout=3))
            event = fixture.snapshot()['connectionEvents'][0]
            self.assertEqual(event['closeReason'], 'session_socket_error')
            self.assertEqual(event['socketErrno'], errno.ECONNRESET)
            self.assertTrue(event['authAccepted'])
            self.assertTrue(event['markerReceived'])
            self.assertEqual(event['inputBytes'], 9)
            self.assertFalse(event['sessionClosed'])
            self.assertFalse(fixture.wait_for('sessionClosed', timeout=.05))

    def test_clean_authenticated_channel_close_remains_successful(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(channel_deadline=time.monotonic() + 10) as fixture:
            peer = self.peer(fixture)
            peer.auth_password(fixture.username, fixture.password)
            channel = peer.open_session(timeout=2)
            channel.get_pty(); channel.invoke_shell(); channel.settimeout(2)
            reply = self.read_until(channel, b'POCKET-ANDROID-READY')
            channel.sendall(b'hp-check\r')
            self.read_until(channel, b'POCKET-ANDROID-SSH-OK', reply)
            channel.close()
            self.assertTrue(fixture.wait_for_connections_closed(1, timeout=3))
            event = fixture.snapshot()['connectionEvents'][0]
            self.assertIn(event['closeReason'], {'peer_eof', 'transport_closed'})
            self.assertTrue(event['sessionClosed'])
            self.assertTrue(event['markerReceived'])
            self.assertEqual(event['authAttempts'], 1)
            self.assertEqual(event['inputBytes'], 9)

    def test_batch_deadline_in_an_authenticated_shell_is_not_a_peer_disconnect(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(channel_deadline=time.monotonic() + 2) as fixture:
            peer = self.peer(fixture)
            peer.auth_password(fixture.username, fixture.password)
            channel = peer.open_session(timeout=1)
            channel.get_pty(); channel.invoke_shell()
            self.assertTrue(fixture.wait_for_connections_closed(1, timeout=4))
            event = fixture.snapshot()['connectionEvents'][0]
            self.assertTrue(event['authAccepted'])
            self.assertEqual(event['closeReason'], 'batch_deadline')
            self.assertFalse(event['sessionClosed'])
            self.assertFalse(event['markerReceived'])

    def test_cleanup_interrupts_a_waiting_transport_and_joins_workers(self):
        from direct_ssh_fixture import DirectSshFixture
        fixture = DirectSshFixture(channel_deadline=time.monotonic() + 30).__enter__()
        self.addCleanup(fixture.close)
        self.peer(fixture)
        started = time.monotonic()
        fixture.close()
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(fixture.snapshot()['connectionsClosed'])
        self.assertTrue(all(not thread.is_alive() for thread in fixture._threads))
        self.assertEqual(fixture.snapshot()['connectionEvents'][0]['closeReason'], 'fixture_stopped')

    def test_deadline_rejects_unbounded_and_non_numeric_values(self):
        from direct_ssh_fixture import DirectSshFixture
        for value in (True, '30', float('inf'), float('nan'), -1, 10 ** 1000, time.monotonic() + 1801):
            with self.assertRaisesRegex(ValueError, 'invalid_fixture_channel_deadline'):
                DirectSshFixture(channel_deadline=value)
