"""Fail-closed checks for the opt-in iOS Simulator SSH evidence runner."""
import tempfile
import unittest
import importlib.util
import json
import os
import subprocess
import sys
import struct
import hashlib
import io
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

import flutter_direct_ssh_ios as runner
import ios_xctest_scaffold


class IosDirectSshTests(unittest.TestCase):
    def test_connect_failure_exports_only_fixed_phase_enum_and_boolean_control_facts(self):
        value = {'phase': 'hostKeyVerified', 'failureCode': 'authAborted',
                 'hostKeyMatched': True, 'credentialCaptured': True, 'passwordRequested': False}
        self.assertEqual(runner.connection_diagnostic(value), value)
        for invalid in ({**value, 'message': 'raw-secret'}, {**value, 'failureCode': 'raw-secret'},
                        {**value, 'phase': 'raw-secret'}, {**value, 'credentialCaptured': 1},
                        {**value, 'failureCode': []}, None):
            self.assertEqual(runner.connection_diagnostic(invalid), {})

    def test_overflow_projection_keeps_only_whitelisted_geometry_stage_and_project_location(self):
        event = {'direction': 'bottom', 'pixels': 58.0, 'stage': 'input',
                 'owner': 'DirectSshPage', 'file': 'direct_ssh_page.dart', 'line': 302, 'column': 16,
                 'routeCurrent': True, 'viewSize': [828, 1792], 'viewInsets': [0, 0, 0, 672],
                 'devicePixelRatio': 2.0, 'flexSize': [414, 88]}
        self.assertEqual(runner.layout_diagnostics({'events': [event]}), [event])
        for invalid in ({**event, 'stack': 'private raw text'}, {**event, 'pixels': float('inf')},
                        {**event, 'pixels': True}, {**event, 'direction': 'secret'},
                        {**event, 'stage': 'secret'}, {**event, 'file': '/private/account/main.dart'},
                        {**event, 'routeCurrent': 1}, {**event, 'line': True},
                        {**event, 'viewInsets': [0, 0, 0, float('nan')]}):
            self.assertEqual(runner.layout_diagnostics({'events': [invalid]}), [])
        self.assertEqual(len(runner.layout_diagnostics({'events': [event] * 6})), 4)
        self.assertEqual(runner.layout_diagnostics(None), [])

    def test_preconnect_hash_is_optional_and_requires_the_existing_masked_admission(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            self.assertEqual(runner.public_artifacts(output, masked_preconnect=True)['artifacts'], {})
            png = b'owned-current-run-masked-image'
            (output / 'preconnect.png').write_bytes(png)
            self.assertEqual(runner.public_artifacts(output)['artifacts'], {})
            self.assertEqual(runner.public_artifacts(output, masked_preconnect=True)['artifacts'],
                             {'preconnect.png': hashlib.sha256(png).hexdigest()})
            for name in ('ordinary-terminal', 'key-change-terminal'):
                (output / (name + '.png')).write_bytes(png)
                (output / (name + '-ocr.json')).write_text(json.dumps({'imageSha256': hashlib.sha256(png).hexdigest()}))
            (output / 'key-change-review.png').write_bytes(png)
            artifacts = runner.public_artifacts(output, masked_preconnect=True)['artifacts']
            self.assertEqual(set(artifacts), {'ordinary-terminal.png', 'key-change-review.png',
                                            'key-change-terminal.png', 'preconnect.png'})

    @unittest.skipUnless(importlib.util.find_spec('PIL'), 'Pillow is optional outside screenshot CI')
    def test_target_ocr_requires_full_exact_single_row_and_uses_only_measured_crop(self):
        from PIL import Image
        from terminal_screenshot_gate import ScreenshotGateError
        png = io.BytesIO()
        Image.new('RGB', (300, 600), 'white').save(png, format='PNG')
        target = 'fixture@127.0.0.1:2222'
        for text in ('fixture@127.0.0.1:2223', 'fixture@127.0.0.1:\n2222', 'prefix' + target):
            with patch.object(runner.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, text.encode(), b'')):
                with self.assertRaisesRegex(ScreenshotGateError, 'ios_target_not_visible'):
                    runner.target_pixel_proof(png.getvalue(), target, [0, 10, 200, 20])
        with patch.object(runner.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, (target + '\n').encode(), b'')) as ocr:
            evidence = runner.target_pixel_proof(png.getvalue(), target, [0, 10, 200, 20])
            self.assertTrue(evidence['targetVisible'])
            self.assertEqual(evidence['targetBounds'], [0, 10, 200, 20])
            with Image.open(io.BytesIO(ocr.call_args.kwargs['input'])) as cropped:
                self.assertEqual(cropped.size, (440, 80))

    def test_rotation_result_requires_actual_ios_host_and_all_predicates(self):
        value = {key: True for key in runner.ROTATION_PUBLIC_FIELDS}
        value.update(schemaVersion=1, platform='ios-simulator', physicalImeVerified=False)
        self.assertEqual(runner.check_rotation_result(value), value)
        for changed in (None, {**value, 'platform': 'android-api35-emulator'},
                        {**value, 'cancelKeepsOldTrust': False}, {**value, 'schemaVersion': True},
                        {**value, 'password': 'private'}):
            with self.assertRaises(runner.Failure):
                runner.check_rotation_result(changed)

    def screen_request(self, **changes):
        return dict({'tag': 'key-rotation', 'attempt': 1, 'bounds': [0, 30, 300, 570],
                     'targetBounds': [0, 10, 200, 20], 'viewSize': [300, 600],
                     'observedTarget': 'fixture@127.0.0.1:2222'}, **changes)

    def peer(self, input_bytes=9):
        return SimpleNamespace(username='fixture', port=2222, screen_token='fixture-token',
            snapshot=lambda: {'connectionEvents': [{'markerReceived': True, 'inputBytes': input_bytes}]})

    def test_screen_rejects_unmeasured_geometry_wrong_identity_and_skipped_attempt(self):
        variants = [self.screen_request(bounds=[True, 0, 300, 600]),
                    self.screen_request(bounds=[0, 31, 300, 570]),
                    self.screen_request(targetBounds=[0, 10, 301, 20]),
                    self.screen_request(observedTarget='another@127.0.0.1:2222'),
                    self.screen_request(attempt=2), self.screen_request(tag='ordinary')]
        for request in variants:
            with self.subTest(request=request), patch.object(runner, 'capture_system_screen') as capture:
                with self.assertRaises(runner.Failure):
                    runner.screen_checkpoint(request, {}, self.peer(), self.peer(), 'device', None, None, None)
                capture.assert_not_called()

    def test_screen_requires_single_real_peer_input_before_any_capture(self):
        for amount in (0, 8, 18):
            with patch.object(runner, 'capture_system_screen') as capture:
                with self.assertRaisesRegex(runner.Failure, 'ios_screen_peer_input_missing'):
                    runner.screen_checkpoint(self.screen_request(), {}, self.peer(amount), self.peer(amount),
                                             'device', None, None, None)
                capture.assert_not_called()

    def test_system_capture_uses_simctl_io_and_preserves_original_bytes(self):
        png = b'\x89PNG\r\n\x1a\n' + b'\0\0\0\rIHDR' + struct.pack('>II', 300, 600)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'capture.png'
            path.write_bytes(png)
            with patch.object(runner, 'command') as command:
                self.assertEqual(runner.capture_system_screen('owned', path), png)
            command.assert_called_once_with('xcrun', 'simctl', 'io', 'owned', 'screenshot', str(path), timeout=45)

    def test_screen_requires_system_dimensions_and_does_not_call_ocr_on_wrong_size(self):
        png = b'\x89PNG\r\n\x1a\n' + b'\0\0\0\rIHDR' + struct.pack('>II', 301, 600)
        with patch.object(runner, 'capture_system_screen', return_value=png), patch.object(runner, 'target_pixel_proof') as ocr:
            with self.assertRaisesRegex(runner.Failure, 'ios_screenshot_geometry_mismatch'):
                runner.screen_checkpoint(self.screen_request(), {}, self.peer(), self.peer(), 'device', None, Path('/private'), None)
            ocr.assert_not_called()

    def test_screen_publishes_original_gate_schema_and_same_image_manifest_hash(self):
        png = b'\x89PNG\r\n\x1a\n' + b'\0\0\0\rIHDR' + struct.pack('>II', 300, 600)
        evidence = {'schemaVersion': 1, 'imageSha256': hashlib.sha256(png).hexdigest(),
                    'markerVisible': True, 'tokenVisible': True, 'proofSequenceVisible': True,
                    'terminalBounds': [0, 30, 300, 570]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp); completed = {}
            with patch.object(runner, 'capture_system_screen', return_value=png) as capture, \
                 patch.object(runner, 'target_pixel_proof', return_value={'targetVisible': True}), \
                 patch('terminal_screenshot_gate.verify_terminal_screenshot', return_value=evidence) as gate:
                runner.screen_checkpoint(self.screen_request(), completed, self.peer(), self.peer(), 'owned', path, path, path)
                runner.screen_checkpoint(self.screen_request(), completed, self.peer(), self.peer(), 'owned', path, path, path)
            capture.assert_called_once(); gate.assert_called_once_with(png, expected_token='fixture-token', bounds=(0, 30, 300, 570))
            self.assertEqual(json.loads((path / 'key-change-terminal-ocr.json').read_text()), evidence)
            self.assertEqual(json.loads((path / 'screen-key-rotation-1.json').read_text())['accepted'], True)
            manifest = runner.public_artifacts(path)
            item = manifest['cases']['keyChange']['terminalScreenshot']
            self.assertEqual(manifest['artifacts'][item['imageFile']], evidence['imageSha256'])
            self.assertEqual(item['imageSha256'], evidence['imageSha256'])
            (path / item['imageFile']).write_bytes(png + b'tampered')
            with self.assertRaisesRegex(runner.Failure, 'ios_artifact_criteria_hash_mismatch'):
                runner.public_artifacts(path)

    def test_target_ocr_failure_never_exports_unapproved_terminal_frame(self):
        from terminal_screenshot_gate import ScreenshotGateError
        png = b'\x89PNG\r\n\x1a\n' + b'\0\0\0\rIHDR' + struct.pack('>II', 300, 600)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp); completed = {}
            with patch.object(runner, 'capture_system_screen', return_value=png), \
                 patch.object(runner, 'target_pixel_proof', side_effect=ScreenshotGateError('ios_target_not_visible')):
                runner.screen_checkpoint(self.screen_request(), completed, self.peer(), self.peer(), 'owned', path, path, path)
            self.assertFalse(completed['key-rotation']['accepted'])
            self.assertEqual(runner.public_artifacts(path)['artifacts'], {})
            self.assertFalse((path / 'key-change-terminal.png').exists())

    def test_review_requires_closed_rejected_transport_and_never_uses_terminal_ocr(self):
        peer = SimpleNamespace(wait_for_connections_closed=lambda count: True,
                               rotation_evidence=lambda count: {'stage': count})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            with patch.object(runner, 'capture_system_screen', return_value=b'original-system-image'), \
                 patch('terminal_screenshot_gate.verify_terminal_screenshot') as gate:
                runner.review_checkpoint({'tag': 'key-rotation', 'formAbsent': True, 'secretAbsent': True},
                                         peer, 'owned', path, path, path)
                gate.assert_not_called()
            self.assertEqual((path / 'key-change-review.png').read_bytes(), b'original-system-image')
            self.assertEqual(json.loads((path / 'review-done.json').read_text()), {'captured': True})
            self.assertIn('key-change-review.png', runner.public_artifacts(path)['artifacts'])
        for bad in (None, {'tag': 'key-rotation', 'formAbsent': 1, 'secretAbsent': True}):
            with self.assertRaises(runner.Failure):
                runner.review_checkpoint(bad, peer, 'owned', None, None, None)

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

    def test_container_lookup_is_throttled_and_success_is_cached(self):
        now = [0.0]
        calls = []

        def lookup(device, timeout):
            calls.append((device, timeout))
            return (None, True) if len(calls) == 1 else (Path('/private/app'), False)

        locator = runner.ContainerLocator('fixture-id', clock=lambda: now[0], lookup=lookup, interval=10)
        self.assertIsNone(locator.get(5))
        now[0] = 9.9
        self.assertIsNone(locator.get(5))
        self.assertEqual(len(calls), 1)
        now[0] = 10
        self.assertEqual(locator.get(5), Path('/private/app'))
        now[0] = 100
        self.assertEqual(locator.get(5), Path('/private/app'))
        self.assertEqual((locator.attempts, locator.timeouts, len(calls)), (2, 1, 2))

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
        self.assertEqual(runner.ui_diagnostic({'statusCode': 'probe_failed', 'appLifecycle': 'resumed',
            'probeEnabled': True, 'trustDialogVisible': False, 'raw': 'secret'}),
            {'statusCode': 'probe_failed', 'appLifecycle': 'resumed',
             'probeEnabled': True, 'trustDialogVisible': False})
        self.assertEqual(runner.ui_diagnostic({'statusCode': 'secret', 'appLifecycle': 'secret'}), {})

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
