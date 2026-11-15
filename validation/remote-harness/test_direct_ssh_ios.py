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

    def test_xctest_execution_disables_clones_and_preserves_the_owned_destination(self):
        command = runner.xctest_execution(['xcodebuild', '-destination', 'id=owned-fixture'], '/private/result')
        self.assertEqual(command.count('-destination'), 1)
        self.assertEqual(command[command.index('-destination') + 1], 'id=owned-fixture')
        self.assertEqual(command[command.index('-parallel-testing-enabled') + 1], 'NO')
        self.assertEqual(command[command.index('-maximum-concurrent-test-simulator-destinations') + 1], '1')
        self.assertNotIn('-parallel-testing-worker-count', command)

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

    def test_xctest_failure_details_are_bounded_and_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            result_path = Path(temp) / 'fixture.xcresult'; result_path.mkdir()
            summary = {'totalTestCount': 1, 'failedTests': 1, 'testFailures': [{
                'testIdentifier': 'RunnerTests/testExample',
                'failureText': 'Expected false but got true; password=secret123 /private/user/path fixture 127.0.0.1'}]}
            detail = {'failureMessages': ['Failed to launch because secret123 was invalid']}
            responses = [subprocess.CompletedProcess([], 0, json.dumps(value).encode(), b'')
                         for value in (summary, detail)]
            with patch.object(runner.subprocess, 'run', side_effect=responses):
                result = runner.xctest_result_markers(result_path, ('secret123', 'fixture', '/private/user'))
            self.assertEqual(len(result['failureReasons']), 2)
            self.assertIn('Expected false', result['failureReasons'][0])
            for secret in ('secret123', 'fixture', '/private/user', '127.0.0.1'):
                self.assertNotIn(secret, str(result))

    def test_multiline_test_failure_extracts_only_sanitized_assertion_and_source_line(self):
        text = ('EXCEPTION CAUGHT BY FLUTTER TEST FRAMEWORK\nThe following assertion was thrown during a test:\n'
                'A timer was still pending for fixture with password=secret123\nExpected: exactly one matching candidate\n'
                '  Actual: password=secret123 /private/user/path\n'
                '#4 package direct_ssh_ui_steps.dart:137:9\n')
        result = runner.failure_facts(text, ('secret123', '/private/user'))
        self.assertEqual(result['expected'], 'Expected: exactly one matching candidate')
        self.assertEqual(len(result['frameworkExcerpt']), 3)
        self.assertEqual(result['sourceLine'], 137)
        self.assertNotIn('secret123', str(result)); self.assertNotIn('/private/user', str(result))

    def test_framework_diagnostic_never_exports_raw_or_extra_fields(self):
        value = {'exceptionClass':'AssertionError', 'sourceLine':123,
                 'excerpt':['Timer pending secret123 /private/user/path'], 'password':'secret123'}
        result = runner.framework_diagnostic(value, ('secret123', '/private/user'))
        self.assertEqual(result['exceptionClass'], 'AssertionError')
        self.assertEqual(result['sourceLine'], 123)
        self.assertNotIn('secret123', str(result)); self.assertNotIn('/private/user', str(result))
        self.assertNotIn('password', result)

    def test_semantics_probe_only_accepts_fixed_boolean_and_bounded_counts(self):
        valid = {'platformEnabled': True, 'realPlatformEnabled': False, 'bindingHandles': 1, 'pipelineHandles': 2}
        self.assertEqual(runner.semantics_probe(valid), valid)
        for value in ({**valid, 'extra':'secret'}, {**valid, 'bindingHandles':True},
                      {**valid, 'pipelineHandles':101}, {**valid, 'platformEnabled':1}):
            self.assertIsNone(runner.semantics_probe(value))

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
            scheme = app / 'ios/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme'
            scheme.parent.mkdir(parents=True)
            scheme.write_text('<TestableReference parallelizable = "YES"/>')
            ios_xctest_scaffold.prepare(app)
            self.assertFalse(swift.exists())
            self.assertIn('INTEGRATION_TEST_IOS_RUNNER(RunnerTests)',
                          (swift.parent / 'RunnerTests.m').read_text())
            self.assertIn('sourcecode.c.objc; path = RunnerTests.m;', project.read_text())
            self.assertIn("target 'RunnerTests'", (app / 'ios/Podfile').read_text())
            self.assertIn('Pods-Runner.debug.xcconfig', debug.read_text())
            self.assertIn('parallelizable = "NO"', scheme.read_text())
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
            scheme = app / 'ios/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme'
            scheme.parent.mkdir(parents=True)
            scheme.write_text('<TestableReference parallelizable = "YES"/>')
            podfile = app / 'ios/Podfile'
            podfile.write_text(ios_xctest_scaffold.PODFILE)
            ios_xctest_scaffold.prepare(app)
            self.assertEqual(debug.read_text(), original)
            self.assertEqual(podfile.read_text(), ios_xctest_scaffold.PODFILE)


if __name__ == '__main__':
    unittest.main()
