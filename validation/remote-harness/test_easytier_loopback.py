"""Evidence and isolation negative controls; no node, credentials or network."""
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import easytier_loopback as probe


def result(case):
    positive = case == 'positive'
    return {'schemaVersion': 1, 'case': case, 'passed': True, 'errorCode': None,
            'transportErrorCode': (None if positive else 'host_key_mismatch'
                                   if case == 'wrong-pin' else 'overlay_transport_failed'),
            'nodeStarted': True, 'candidateAbi': True, 'sshBannerViaOverlay': True,
            'bannerConnections': 1, 'peerStoppedBeforeAttempt': case == 'peer-gone',
            'frameMarkerPresent': positive, 'frameColumns': 80 if positive else 0,
            'frameRows': 24 if positive else 0, 'nativeStopCompleted': True,
            'reservedNodesAfterCleanup': 0, 'reservedStreamsAfterCleanup': 0,
            'audit': {'hostKeyChecked': positive or case == 'wrong-pin',
                      'hostKeyMatched': positive, 'authStarted': positive,
                      'snapshotReceived': positive, 'fullFrameReceived': positive}}


class EvidenceTests(unittest.TestCase):
    def test_cleanup_paths_require_owned_runner_directory_and_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            bundle, output = root / 'hp-easytier-bundle-123', root / 'easytier-evidence'
            probe.checked_paths(bundle, output, root, '123')
            with self.assertRaises(probe.Failure):
                probe.checked_paths(root, output, root, '123')
            target = root / 'unrelated'; target.mkdir(); bundle.symlink_to(target, target_is_directory=True)
            with self.assertRaises(probe.Failure):
                probe.checked_paths(bundle, output, root, '123')
    def test_build_diagnostics_keep_codes_and_source_locations_without_raw_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build.log').write_text('temporary-secret\nerror[E0599]: private arbitrary message\n'
                ' --> /home/runner/private/pocket_easytier_peer.rs:12:3\n')
            diagnostics = probe.build_diagnostics(root)
            self.assertEqual(diagnostics, {'rustErrorCodes': ['E0599'],
                'locations': [{'file': 'pocket_easytier_peer.rs', 'line': 12, 'column': 3}]})
            self.assertNotIn('temporary-secret', json.dumps(diagnostics))
            self.assertNotIn('/home/runner', json.dumps(diagnostics))

    def test_finalizer_refuses_foreign_namespace_before_running_any_command(self):
        with patch.dict(probe.os.environ, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1'):
            with patch.object(probe, 'command') as command:
                with self.assertRaises(probe.Failure):
                    probe.finalize(Path('/unused'), {}, 'personal-network')
                command.assert_not_called()

    def test_all_four_expected_cases_pass_the_same_strict_validator(self):
        for case in probe.CASES:
            safe = probe.safe_client_result(result(case), case)
            probe.validate_case(safe, 2 if case in ('positive', 'wrong-pin') else 1,
                                2 if case == 'positive' else 0, 1 if case == 'positive' else 0)

    def test_unknown_payloads_and_credentials_are_never_copied(self):
        raw = result('positive')
        raw.update(privateKeyPem='temporary-secret', stdout='arbitrary remote response')
        raw['audit']['privateKey'] = 'temporary-secret'
        self.assertNotIn('temporary-secret', json.dumps(probe.safe_client_result(raw, 'positive')))
        for field in ('errorCode', 'transportErrorCode'):
            raw = result('positive'); raw[field] = 'temporary_secret'
            with self.assertRaises(probe.Failure): probe.safe_client_result(raw, 'positive')

    def test_non_json_wrong_case_and_numeric_booleans_are_rejected(self):
        for raw in ('run-as: unknown package', None, [], {'case': 'positive'}):
            with self.assertRaises(probe.Failure): probe.safe_client_result(raw, 'positive')
        raw = result('positive'); raw['passed'] = 1
        with self.assertRaises(probe.Failure): probe.safe_client_result(raw, 'positive')
        with self.assertRaises(probe.Failure): probe.safe_client_result(result('wrong-pin'), 'positive')
        raw = result('positive'); raw['bannerConnections'] = True
        with self.assertRaises(probe.Failure): probe.safe_client_result(raw, 'positive')

    def test_wrong_pin_requires_server_side_zero_authentication(self):
        with self.assertRaises(probe.Failure):
            probe.validate_case(result('wrong-pin'), 2, 1, 0)
        raw = result('wrong-pin'); raw['audit']['authStarted'] = True
        with self.assertRaises(probe.Failure): probe.validate_case(raw, 2, 0, 0)

    def test_real_frame_and_complete_native_cleanup_are_mandatory(self):
        for field, value in [('frameMarkerPresent', False), ('nativeStopCompleted', False),
                             ('reservedNodesAfterCleanup', 1), ('reservedStreamsAfterCleanup', 1)]:
            raw = result('positive'); raw[field] = value
            with self.subTest(field=field), self.assertRaises(probe.Failure):
                probe.validate_case(raw, 2, 2, 1)

    def test_plain_tcp_attempt_or_unconfirmed_peer_stop_fails(self):
        for case in ('no-route', 'peer-gone'):
            with self.assertRaises(probe.Failure): probe.validate_case(result(case), 2, 0, 0)
        raw = result('peer-gone'); raw['peerStoppedBeforeAttempt'] = False
        with self.assertRaises(probe.Failure): probe.validate_case(raw, 1, 0, 0)

    def test_only_loopback_up_is_accepted(self):
        loopback = {'ifname': 'lo', 'flags': ['LOOPBACK', 'UP', 'LOWER_UP']}
        probe.checked_namespace([loopback])
        for links in ([], [dict(loopback, flags=[])],
                      [loopback, {'ifname': 'eth0', 'flags': ['UP']}], 'lo'):
            with self.assertRaises(probe.Failure): probe.checked_namespace(links)

    def test_both_configs_disable_discovery_and_only_server_exposes_loopback(self):
        for server in (False, True):
            config = tomllib.loads(probe.native_config('temporary-network', 'temporary-secret', 12345, server))
            for key in ('stun_servers', 'tcp_stun_servers', 'stun_servers_v6'):
                self.assertEqual(config[key], [])
            self.assertTrue(config['flags']['no_tun'])
            self.assertFalse(config['flags']['enable_ipv6'])
            self.assertTrue(config['flags']['disable_upnp'])
            if server:
                self.assertEqual(config['listeners'], ['tcp://127.0.0.1:12345'])
                self.assertEqual(config['ipv4'], probe.OVERLAY_HOST + '/24')
                self.assertNotIn('proxy_network', config)
            else:
                self.assertEqual(config['listeners'], [])
                self.assertEqual(config['peer'], [{'uri': 'tcp://127.0.0.1:12345'}])
                self.assertNotIn('proxy_network', config)


if __name__ == '__main__':
    unittest.main()
