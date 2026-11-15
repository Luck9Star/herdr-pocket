import json
import contextlib
import io
import os
import stat
import time
import unittest
from unittest import mock

import android_dual_overlay_hosts as hosts
import test_paired_dual_fixture as fixtures
import paired_dual_demo as provisioning
from pairing import encode


class HostControlTests(unittest.TestCase):
    def setUp(self):
        fixtures.DualPairingTests.setUp(self)
        self.authorized = []
        self.active = {4444}
        self.control = hosts.PairingControl(self.targets,
            lambda url: self.authorized.append(url) or True, 'https://127.0.0.1:4321',
            active_ports=lambda _: self.active)

    def approve(self, role):
        raw = encode(self.pending[role].request).decode()
        review = self.control.dispatch({'op': 'review_pairing', 'role': role, 'request': raw})
        return self.control.dispatch(dict(op='approve_pairing', role=role, request=raw,
            requestId=review['requestId'], deviceFingerprint=review['deviceFingerprint'], reviewed=True))

    def test_real_public_pairing_review_cannot_authorize_another_host(self):
        raw = encode(self.pending['et'].request).decode()
        with self.assertRaises((ValueError, hosts.GuiFailure)):
            self.control.dispatch({'op': 'review_pairing', 'role': 'ts', 'request': raw})
        with self.assertRaises(hosts.GuiFailure):
            self.control.dispatch({'op': 'approve_pairing', 'role': 'et', 'request': raw})
        self.assertEqual((self.targets['et'].root / 'authorized_keys').read_bytes(), b'')
        response = self.approve('et')
        self.pending['et'].accept(response['response'].encode(), now=int(time.time()), source_reviewed=True)
        self.assertEqual(response['event'], 'pairing_approved')

    def test_ts_authorization_requires_explicit_action_and_exact_https_origin(self):
        secret = 'https://127.0.0.1:4321/a/one-time-test-value'
        for authorize, url in [(False, secret), (True, secret.replace('https:', 'http:')),
                               (True, secret.replace(':4321/', ':4322/'))]:
            with self.assertRaises(hosts.HostControlError):
                self.control.dispatch({'op': 'complete_ts_auth', 'authorize': authorize, 'url': url})
        self.assertEqual(self.authorized, [])
        response = self.control.dispatch({'op': 'complete_ts_auth', 'authorize': True, 'url': secret})
        self.assertEqual(self.authorized, [secret])
        self.assertNotIn('one-time-test-value', json.dumps(response))

    def test_session_lifetime_and_input_are_monotonic_and_reconnect_is_ambiguous(self):
        self.approve('et')
        target = self.targets['et']
        log = target.root / 'sshd.log'
        line = ('Accepted publickey for fixture from 127.0.0.1 port {} ssh2: ED25519 '
                + target.approval.fingerprint + '\n')
        log.write_text(line.format(4444))
        capture = target.root / 'received.bin'; capture.write_bytes(b'E1')
        first = self.control.audit('et', b'E1')
        self.assertEqual((first['acceptedSessions'], first['newSessions'], first['newInputBytes']), (1, 1, 2))
        self.assertEqual(first['sessions'], [{'ordinal': 1, 'approvedDevice': True,
                                            'active': True, 'capturedBytes': 2}])
        capture.write_bytes(b'E1E2')
        second = self.control.audit('et', b'E1E2')
        self.assertEqual((second['newSessions'], second['newInputBytes']), (0, 2))
        self.active.clear()
        self.assertFalse(self.control.audit('et', b'E1E2')['sessions'][0]['active'])
        log.write_text(log.read_text() + line.format(5555)); self.active.add(5555)
        reconnected = self.control.audit('et', b'E1E2')
        self.assertTrue(reconnected['inputAttributionAmbiguous'])
        self.assertFalse(reconnected['soleApprovedSession'])
        self.assertTrue(all(row['capturedBytes'] is None for row in reconnected['sessions']))
        log.write_text(log.read_text() + line.format(5555))
        reused = self.control.audit('et', b'E1E2')
        self.assertEqual([row['active'] for row in reused['sessions']], [False, False, True])
        capture.write_bytes(b'')
        with self.assertRaisesRegex(hosts.HostControlError, 'not_monotonic'):
            self.control.audit('et', b'')

    def test_bounded_audit_and_private_materials(self):
        with self.assertRaises(hosts.HostControlError):
            self.control.dispatch({'op': 'audit', 'role': 'et', 'expectedBase64': 'not base64!'})
        path = self.root / 'private.json'
        hosts.write_private(path, {'synthetic': True})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError): hosts.write_private(path, {})

    def test_socket_audit_uses_only_the_corresponding_local_ssh_listener(self):
        text = ('0 0 127.0.0.1:2222 127.0.0.1:4444\n'
                '0 0 127.0.0.1:3333 127.0.0.1:5555\n'
                '0 0 127.0.0.1:2222 192.0.2.1:6666\n')
        with mock.patch.object(hosts.sys, 'platform', 'linux'), \
             mock.patch.object(hosts.subprocess, 'check_output', return_value=text):
            self.assertEqual(hosts.live_ssh_ports(2222), {4444})

    def test_owned_lifetime_is_bounded_without_changing_pairing_rules(self):
        for value in (True, 0, 59, 1801):
            with self.assertRaises(hosts.HostControlError):
                hosts.HostHarness(self.root, self.root, lifetime=value)
        self.assertEqual(hosts.HostHarness(self.root, self.root).lifetime, 900)

    def test_private_control_consumes_multiple_commands_from_one_pipe_read(self):
        harness = mock.MagicMock()
        harness.__enter__.return_value = harness
        harness.children = []
        harness.cleanup = {'ownedProcessesStopped': True}
        harness.control.dispatch.return_value = {'event': 'synthetic_reply'}
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b'{"op":"synthetic"}\n{"op":"stop"}\n'); os.close(write_fd)
        output = io.StringIO()
        with os.fdopen(read_fd) as source, mock.patch.object(hosts.sys, 'stdin', source), \
             mock.patch.object(hosts.sys, 'argv', ['hosts', '--bundle', str(self.root), '--work', str(self.root)]), \
             mock.patch.object(hosts, 'HostHarness', return_value=harness), contextlib.redirect_stdout(output):
            self.assertEqual(hosts.main(), 0)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([row['event'] for row in rows], ['ready', 'synthetic_reply', 'cleanup'])
        self.assertEqual(rows[-1]['stopReason'], 'explicit-stop')
        harness.control.dispatch.assert_called_once_with({'op': 'synthetic'})

    def test_startup_diagnostics_only_emit_fixed_enums(self):
        value = mock.Mock(returncode=1, stdout=b'', stderr=b'Missing privilege separation directory: /run/sshd')
        with mock.patch.object(provisioning.subprocess, 'run', return_value=value):
            with self.assertRaises(RuntimeError) as caught:
                provisioning.command(['/usr/sbin/sshd', '-t'], {})
        self.assertEqual(caught.exception.fixture_code, 'sshd_privsep_directory_missing')
        self.assertNotIn('/run/sshd', str(caught.exception))
        self.assertEqual(hosts.safe_startup_failure({'stage': 'et_sshd_check',
            'errorCode': caught.exception.fixture_code}),
            {'stage': 'et_sshd_check', 'errorCode': 'sshd_privsep_directory_missing'})
        for value in ({'stage': 'https://private.invalid/', 'errorCode': 'one-time-value'},
                      {'stage': [], 'errorCode': {}}):
            self.assertEqual(hosts.safe_startup_failure(value),
                             {'stage': 'unknown', 'errorCode': 'fixture_startup_failed'})


if __name__ == '__main__':
    unittest.main()
