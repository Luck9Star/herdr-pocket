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
import ios_xctest_scaffold


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

    def test_ui_diagnostic_drops_raw_status_credentials_and_untrusted_fields(self):
        actual = runner.ui_diagnostic({'connectExists': True, 'connectEnabled': False,
            'connectHitTestable': True, 'exceptionClass': 'TestFailure', 'sourceLine': 73,
            'statusCode': 'fingerprint_confirmed', 'password': 'secret', 'status': 'secret target'})
        self.assertEqual(actual, {'connectExists': True, 'connectEnabled': False, 'connectHitTestable': True,
            'exceptionClass': 'TestFailure', 'sourceLine': 73, 'statusCode': 'fingerprint_confirmed'})
        self.assertNotIn('secret', str(actual))
        self.assertNotIn('sourceLine', runner.ui_diagnostic({'sourceLine': True}))

    def test_screenshot_requires_explicit_masked_password_stage(self):
        stage = {'stage': 'screenshot_wait'}
        valid = {'passwordMasked': True, 'passwordAuth': True}
        self.assertTrue(runner.safe_screenshot_request(valid, stage))
        for value, current in [({'passwordMasked': 1, 'passwordAuth': True}, stage),
                               ({**valid, 'extra': True}, stage),
                               (valid, {'stage': 'connect_tap'}), (None, stage)]:
            self.assertFalse(runner.safe_screenshot_request(value, current))

    def test_xctest_result_exports_only_bounded_counts_and_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            result_path = Path(temp) / 'fixture.xcresult'
            result_path.mkdir()
            raw = json.dumps({'totalTestCount': 0, 'failedTests': 0,
                              'issues': ['Failed to launch', 'secret fixture text']}).encode()
            with patch.object(runner.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, raw, b'')):
                result = runner.xctest_result_markers(result_path)
            self.assertEqual(result['totalTestCount'], 0)
            self.assertTrue(result['launchFailed'])
            self.assertNotIn('secret', str(result))

    def test_generated_xctest_scaffold_is_exact_and_one_shot(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp)
            project = app / 'ios/Runner.xcodeproj/project.pbxproj'
            project.parent.mkdir(parents=True)
            project.write_text('lastKnownFileType = sourcecode.swift; path = RunnerTests.swift;\n' +
                               'RunnerTests.swift\n' * 5)
            swift = app / 'ios/RunnerTests/RunnerTests.swift'
            swift.parent.mkdir(parents=True)
            swift.write_text('placeholder')
            debug = app / 'ios/Flutter/Debug.xcconfig'
            debug.parent.mkdir(parents=True)
            debug.write_text('#include "Generated.xcconfig"\n')
            ios_xctest_scaffold.prepare(app)
            self.assertFalse(swift.exists())
            self.assertIn('INTEGRATION_TEST_IOS_RUNNER(RunnerTests)',
                          (swift.parent / 'RunnerTests.m').read_text())
            self.assertIn('sourcecode.c.objc; path = RunnerTests.m;', project.read_text())
            self.assertIn("target 'RunnerTests'", (app / 'ios/Podfile').read_text())
            self.assertIn('Pods-Runner.debug.xcconfig', debug.read_text())
            with self.assertRaisesRegex(ValueError, 'ios_xctest_scaffold_unexpected'):
                ios_xctest_scaffold.prepare(app)

    def test_existing_generated_podfile_and_debug_include_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp)
            project = app / 'ios/Runner.xcodeproj/project.pbxproj'
            project.parent.mkdir(parents=True)
            project.write_text('lastKnownFileType = sourcecode.swift; path = RunnerTests.swift;\n' +
                               'RunnerTests.swift\n' * 5)
            swift = app / 'ios/RunnerTests/RunnerTests.swift'
            swift.parent.mkdir(parents=True)
            swift.write_text('placeholder')
            debug = app / 'ios/Flutter/Debug.xcconfig'
            debug.parent.mkdir(parents=True)
            original = '#include? "Pods/Target Support Files/Pods-Runner/Pods-Runner.debug.xcconfig"\n#include "Generated.xcconfig"\n'
            debug.write_text(original)
            podfile = app / 'ios/Podfile'
            podfile.write_text(ios_xctest_scaffold.PODFILE)
            ios_xctest_scaffold.prepare(app)
            self.assertEqual(debug.read_text(), original)
            self.assertEqual(podfile.read_text(), ios_xctest_scaffold.PODFILE)


if __name__ == '__main__':
    unittest.main()
