"""Real delayed-auth comparisons; never connects to a host account."""
import importlib.util
import time
import unittest


@unittest.skipUnless(importlib.util.find_spec('paramiko'), 'Paramiko is required')
class FixtureDeadlineTests(unittest.TestCase):
    def peer(self, fixture):
        import paramiko
        peer = paramiko.Transport(('127.0.0.1', fixture.port))
        self.addCleanup(peer.close)
        peer.start_client(timeout=5)
        return peer

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
            reply = b''
            while b'POCKET-ANDROID-READY' not in reply:
                reply += channel.recv(4096)
            channel.sendall(b'hp-check\r')
            while b'POCKET-ANDROID-SSH-OK' not in reply:
                data = channel.recv(4096)
                self.assertTrue(data)
                reply += data
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
            self.assertIn(event['closeReason'], {'peer_eof', 'transport_closed'})
            self.assertEqual(event['authAttempts'], 0)
            self.assertFalse(event['sessionClosed'])

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
