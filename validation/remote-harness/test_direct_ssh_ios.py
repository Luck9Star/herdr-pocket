"""Fail-closed checks for the opt-in iOS Simulator SSH evidence runner."""
import tempfile
import unittest
import importlib.util
import json
import os
import subprocess
import sys
from unittest.mock import patch
from pathlib import Path

import flutter_direct_ssh_ios as runner


class IosDirectSshTests(unittest.TestCase):
    def test_protocol_dependency_is_present_when_required(self):
        if os.environ.get('HERDR_REQUIRE_PARAMIKO') == '1':
            self.assertIsNotNone(importlib.util.find_spec('paramiko'), 'Paramiko is required for direct SSH acceptance')

    def test_pure_guards_import_without_optional_site_packages(self):
        result = subprocess.run([sys.executable, '-S', '-c', 'import flutter_direct_ssh_ios'],
                                cwd=Path(__file__).resolve().parent, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_only_explicit_feature_branch_may_start(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/main',
                   'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'RUNNER_TEMP': temp}
            with self.assertRaisesRegex(runner.Failure, 'ios_isolated_ci_required'):
                runner.run(Path(temp) / 'app', Path(temp) / 'out', env)

    def test_result_requires_every_check_and_does_not_accept_identity_fields(self):
        value = {key: True for key in runner.FIELDS}
        value.update(schemaVersion=1, platform='ios-simulator', physicalImeVerified=False)
        self.assertEqual(runner.check_result(value), value)
        for changed in ({**value, 'remoteEchoVisible': False}, {**value, 'password': 'secret'},
                        {**value, 'platform': 'android-api35-emulator'}, {**value, 'physicalImeVerified': True}):
            with self.assertRaises(runner.Failure):
                runner.check_result(changed)

    def test_oversize_exchange_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'result.json'
            path.write_text('x' * 4097)
            with self.assertRaisesRegex(runner.Failure, 'ios_result_oversize'):
                runner.read_json(path)

    def test_flutter_log_diagnostics_export_only_fixed_boolean_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'private.log'
            path.write_text('secret-value\nXcode build done.\nFailed to build iOS app\n')
            result = runner.log_diagnostics(path)
            self.assertEqual(set(result), set(runner.LOG_MARKERS))
            self.assertTrue(result['xcodeBuildCompleted'])
            self.assertTrue(result['buildError'])
            self.assertNotIn('secret-value', str(result))

    def test_container_timeout_is_pending_and_later_success_is_usable(self):
        responses = [subprocess.TimeoutExpired('simctl', 15),
                     subprocess.CompletedProcess([], 0, b'/private/app\n', b'')]
        with patch.object(runner.subprocess, 'run', side_effect=responses):
            self.assertEqual(runner.app_container('fixture-id', 15), (None, True))
            self.assertEqual(runner.app_container('fixture-id', 15), (Path('/private/app'), False))

    def test_cleanup_lookup_only_returns_exact_run_owned_name(self):
        owned = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        listing = {'devices': {'runtime': [{'name': 'herdr-direct-unique', 'udid': owned},
                                          {'name': 'herdr-direct-other', 'udid': 'b' * 36}]}}
        with patch.object(runner, 'command', return_value=json.dumps(listing)):
            self.assertEqual(runner.owned_devices('herdr-direct-unique'), [owned])
            self.assertEqual(runner.owned_devices('herdr-direct-missing'), [])


if __name__ == '__main__':
    unittest.main()
