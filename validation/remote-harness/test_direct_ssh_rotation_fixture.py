"""Real loopback protocol checks for the opt-in ordinary-SSH rotating peer."""
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))


@unittest.skipUnless(importlib.util.find_spec('paramiko') is not None,
                     'Paramiko is required for loopback SSH protocol checks')
class RotationFixtureTests(unittest.TestCase):
    def transport(self, fixture):
        import paramiko
        peer = paramiko.Transport(('127.0.0.1', fixture.port))
        self.addCleanup(peer.close)
        peer.start_client(timeout=5)
        return peer

    def probe(self, fixture, expected_key, count):
        peer = self.transport(fixture)
        self.assertEqual(peer.get_remote_server_key().get_base64(), expected_key.split()[1])
        peer.close()
        self.assertTrue(fixture.wait_for_connections_closed(count, timeout=5))

    def assert_no_session(self, event):
        # A client can close just after reading the host key, before the server
        # finishes start_server. The server must report that boundary honestly.
        self.assertIs(type(event['handshakeCompleted']), bool)
        self.assertTrue(event['closed'])
        self.assertFalse(event['authAccepted'])
        self.assertFalse(event['sessionClosed'])
        self.assertFalse(event['markerReceived'])
        self.assertEqual([event[name] for name in (
            'authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests',
            'inputBytes', 'outputBytes')], [0] * 6)

    def test_one_probe_a_then_persistent_b_with_independent_zero_auth_checkpoints(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(rotate_after_probe=True, observe_helper_keys=True) as fixture:
            port = fixture.port
            for key, fingerprint in ((fixture.public_key, fixture.fingerprint),
                                     (fixture.rotated_public_key, fixture.rotated_fingerprint)):
                raw_key = base64.b64decode(key.split()[1])
                independently_computed = 'SHA256:' + base64.b64encode(
                    hashlib.sha256(raw_key).digest()).decode().rstrip('=')
                self.assertEqual(fingerprint, independently_computed)
                self.assertEqual(len(fingerprint.removeprefix('SHA256:')), 43)
            self.assertNotEqual(fixture.public_key, fixture.rotated_public_key)
            self.assertNotEqual(fixture.fingerprint, fixture.rotated_fingerprint)

            # Connection 1 is the initial A probe. A stale-A client rejects 2;
            # after cancelling, a fresh explicit probe observes B on 3.
            for count, key in enumerate((fixture.public_key, fixture.rotated_public_key,
                                         fixture.rotated_public_key), start=1):
                self.probe(fixture, key, count)
                snapshot = fixture.snapshot()
                self.assertEqual(snapshot['connections'], count)
                for event in snapshot['connectionEvents']:
                    self.assert_no_session(event)
                self.assertFalse(any(snapshot[name] for name in (
                    'authAccepted', 'ptyRequested', 'shellRequested', 'markerReceived')))
                if count in (2, 3):
                    evidence = fixture.rotation_evidence(count)
                    self.assertEqual(evidence['stage'], count)
                    self.assertEqual(evidence['rejectedTransport']['hostKey'], 'B')
                    self.assertNotIn('acceptedSession', evidence)
                    self.assertEqual('freshProbe' in evidence, count == 3)

            peer = self.transport(fixture)
            self.assertEqual(peer.get_remote_server_key().get_base64(),
                             fixture.rotated_public_key.split()[1])
            peer.auth_password(fixture.username, fixture.password)
            channel = peer.open_session(timeout=5)
            channel.get_pty(term='xterm-256color', width=80, height=24)
            channel.invoke_shell()
            channel.settimeout(5)
            marker = (fixture.marker + '\r').encode()
            channel.sendall(marker)
            received = b''
            while (fixture.echo_marker.encode() not in received
                   or not received.endswith(b'\r\n$ ')):
                chunk = channel.recv(4096)
                self.assertTrue(chunk, 'fixture closed before sending marker')
                received += chunk
            helpers = b'\x1b\t\x1b[D\x03'
            channel.sendall(helpers)
            self.assertTrue(fixture.wait_for('helperKeysExact', timeout=5))
            channel.close()
            peer.close()
            self.assertTrue(fixture.wait_for_connections_closed(4, timeout=5))
            facts = fixture.snapshot()
            self.assertEqual(fixture.port, port)
            self.assertEqual(facts['connections'], 4)
            self.assertEqual([event['hostKey'] for event in facts['connectionEvents']],
                             ['A', 'B', 'B', 'B'])
            for event in facts['connectionEvents'][:3]:
                self.assert_no_session(event)
            session = facts['connectionEvents'][3]
            self.assertEqual([session[name] for name in (
                'authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests')], [1] * 4)
            self.assertTrue(all(session[name] for name in (
                'authAccepted', 'markerReceived', 'sessionClosed', 'closed')))
            self.assertEqual(session['inputBytes'], len(marker) + len(helpers))
            self.assertEqual(session['outputBytes'], len(received))
            self.assertIn([80, 24], facts['ptySizes'])
            evidence = fixture.rotation_evidence(4)
            self.assertEqual(evidence['acceptedSession']['authSuccesses'], 1)
            self.assertEqual(evidence['freshProbe']['authAttempts'], 0)
            self.assertNotIn('handshakeCompleted', evidence['initialProbe'])
            self.assertEqual(json.loads(json.dumps(evidence)), evidence)
            evidence['initialProbe']['authAttempts'] = 99
            self.assertEqual(fixture.rotation_evidence(4)['initialProbe']['authAttempts'], 0)
            self.assertEqual(fixture.snapshot(), facts)
            encoded = json.dumps(facts)
            for secret in (fixture.password, fixture.public_key, fixture.rotated_public_key):
                self.assertNotIn(secret, encoded)
            # Returned snapshots cannot rewrite the peer's evidence.
            facts['connectionEvents'][0]['authAttempts'] = 99
            self.assertEqual(fixture.snapshot()['connectionEvents'][0]['authAttempts'], 0)
        self.assertEqual(fixture.password, '')
        self.assertTrue(fixture.snapshot()['connectionsClosed'])

    def test_rotation_is_opt_in_and_default_connections_keep_a(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture() as fixture:
            self.assertIsNone(fixture.rotated_public_key)
            self.assertIsNone(fixture.rotated_fingerprint)
            self.assertNotIn('helperKeysExact', fixture.snapshot())
            for count in (1, 2):
                self.probe(fixture, fixture.public_key, count)
            self.assertEqual([event['hostKey'] for event in fixture.snapshot()['connectionEvents']],
                             ['A', 'A'])

    def test_rejected_authentication_attempts_cannot_look_like_zero_auth_probe(self):
        import paramiko
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(rotate_after_probe=True) as fixture:
            peer = self.transport(fixture)
            attempts = (
                lambda: peer.auth_none(fixture.username),
                lambda: peer.auth_password(fixture.username, 'wrong-password'),
                lambda: peer.auth_publickey(fixture.username, paramiko.RSAKey.generate(1024)),
                lambda: peer.auth_interactive(fixture.username, lambda *args: []),
            )
            for authenticate in attempts:
                with self.assertRaises(paramiko.AuthenticationException):
                    authenticate()
            peer.close()
            self.assertTrue(fixture.wait_for_connections_closed(1, timeout=5))
            event = fixture.snapshot()['connectionEvents'][0]
            self.assertEqual(event['authAttempts'], 4)
            self.assertEqual(event['authSuccesses'], 0)
            self.assertFalse(event['authAccepted'])
            self.assertEqual(event['ptyRequests'], 0)
            self.assertEqual(event['inputBytes'], 0)
            self.assertEqual(event['outputBytes'], 0)

    def test_checkpoint_rejects_invalid_minimum_and_does_not_pass_before_connection(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture() as fixture:
            for minimum in (0, -1, True, '1'):
                with self.subTest(minimum=minimum), self.assertRaises(ValueError):
                    fixture.wait_for_connections_closed(minimum, timeout=.01)
            self.assertFalse(fixture.wait_for_connections_closed(1, timeout=.03))

    def test_rotation_evidence_rejects_phase_count_identity_and_activity_counterexamples(self):
        from direct_ssh_fixture import DirectSshFixture
        fixture = DirectSshFixture(rotate_after_probe=True)
        silent = {'id': 1, 'hostKey': 'A', 'authAttempts': 0, 'authSuccesses': 0,
                  'ptyRequests': 0, 'shellRequests': 0, 'inputBytes': 0, 'outputBytes': 0,
                  'authAccepted': False, 'markerReceived': False, 'sessionClosed': False,
                  'closed': True}
        events = [{**silent, 'id': index + 1, 'hostKey': 'A' if index == 0 else 'B'}
                  for index in range(4)]
        events[3].update(authAttempts=2, authSuccesses=1, ptyRequests=1, shellRequests=1,
                         inputBytes=9, outputBytes=50, authAccepted=True,
                         markerReceived=True, sessionClosed=True)
        valid = {'connections': 4, 'connectionsClosed': True, 'connectionEvents': events}
        with patch.object(fixture, 'snapshot', return_value=valid):
            self.assertEqual(fixture.rotation_evidence(4)['acceptedSession']['authAttempts'], 2)
            for stage in (True, 1, 2, 3, 5, '4'):
                with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, '^invalid_rotation_evidence$'):
                    fixture.rotation_evidence(stage)
        mutations = [('connections', 3), ('connectionsClosed', False)]
        for field, value in mutations:
            damaged = copy.deepcopy(valid)
            damaged[field] = value
            with self.subTest(field=field), patch.object(fixture, 'snapshot', return_value=damaged):
                with self.assertRaisesRegex(ValueError, '^invalid_rotation_evidence$'):
                    fixture.rotation_evidence(4)
        changes = [(index, field, value) for index in range(3) for field, value in (
            ('authAttempts', 1), ('authSuccesses', 1), ('ptyRequests', 1),
            ('shellRequests', 1), ('inputBytes', 1), ('outputBytes', 1),
            ('authAccepted', True), ('markerReceived', True), ('sessionClosed', True))]
        changes += [(0, 'hostKey', 'B'), (1, 'hostKey', 'A'), (2, 'closed', False),
                    (2, 'id', 2), (1, 'authAttempts', False), (0, 'closed', 1),
                    (3, 'authAttempts', 0), (3, 'authSuccesses', 0),
                    (3, 'ptyRequests', 2), (3, 'shellRequests', 0),
                    (3, 'inputBytes', 0), (3, 'outputBytes', 0),
                    (3, 'authAccepted', False), (3, 'markerReceived', False),
                    (3, 'sessionClosed', False), (3, 'closed', False)]
        for index, field, value in changes:
            damaged = copy.deepcopy(valid)
            damaged['connectionEvents'][index][field] = value
            with self.subTest(index=index, field=field), patch.object(fixture, 'snapshot', return_value=damaged):
                with self.assertRaisesRegex(ValueError, '^invalid_rotation_evidence$'):
                    fixture.rotation_evidence(4)
        for event_count in (3, 5):
            damaged = {**valid, 'connectionEvents': events[:3] if event_count == 3 else events + [events[-1]]}
            with self.subTest(event_count=event_count), patch.object(fixture, 'snapshot', return_value=damaged):
                with self.assertRaisesRegex(ValueError, '^invalid_rotation_evidence$'):
                    fixture.rotation_evidence(4)
        nonrotating = DirectSshFixture()
        with patch.object(nonrotating, 'snapshot', return_value=valid):
            # A non-rotating peer cannot claim a rotating protocol result.
            with self.assertRaisesRegex(ValueError, '^invalid_rotation_evidence$'):
                nonrotating.rotation_evidence(4)


if __name__ == '__main__':
    unittest.main()
