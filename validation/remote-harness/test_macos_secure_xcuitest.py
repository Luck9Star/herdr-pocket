"""Safety and scaffold contract; actual XCUITest requires macOS and Xcode."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
import xml.etree.ElementTree as ET

import macos_secure_xcuitest as runner

PROJECT = '''productType = "com.apple.product-type.bundle.unit-test";
''' + ('''\t\t\t\tBUNDLE_LOADER = "$(TEST_HOST)";
\t\t\t\tTEST_HOST = "$(BUILT_PRODUCTS_DIR)/herdr_flutter_probe.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/herdr_flutter_probe";
''' * 3)

class ScaffoldTests(unittest.TestCase):
    def scaffold(self, root):
        (root / 'macos/Runner.xcodeproj/xcshareddata/xcschemes').mkdir(parents=True)
        (root / 'macos/RunnerTests').mkdir(parents=True)
        (root / 'macos/Runner').mkdir(parents=True)
        (root / '.herdr-generated-probe.json').write_text(json.dumps({'kind':'herdr-flutter-validation'}))
        (root / 'macos/Runner.xcodeproj/project.pbxproj').write_text(PROJECT)
        (root / 'macos/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme').write_text('<Scheme><TestAction><Testables><Testable parallelizable = "YES"/></Testables></TestAction></Scheme>')
        (root / 'macos/RunnerTests/RunnerTests.swift').write_text('unit test')
        (root / 'macos/Runner/MainFlutterWindow.swift').write_text('class Window {\n    super.awakeFromNib()\n}\n')

    def test_embedder_notification_hook_is_disposable_and_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.scaffold(root);runner.install_test_semantics_hook(root)
            text=(root/'macos/Runner/MainFlutterWindow.swift').read_text()
            self.assertIn('CommandLine.arguments.contains("--herdr-xcui-embedder-semantics")',text)
            self.assertIn('NSApplicationDidChangeAccessibilityEnhancedUserInterfaceNotification',text)
            self.assertIn('"AXEnhancedUserInterface": true',text)
            with self.assertRaises(ValueError):runner.install_test_semantics_hook(root)

    def test_only_expected_disposable_scaffold_is_converted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.scaffold(root);runner.prepare(root)
            project=(root / 'macos/Runner.xcodeproj/project.pbxproj').read_text()
            self.assertIn('com.apple.product-type.bundle.ui-testing',project)
            self.assertEqual(project.count('TEST_TARGET_NAME = Runner;'),3)
            self.assertNotIn('TEST_HOST',project)
            self.assertIn('secureTextFields', (root / 'macos/RunnerTests/RunnerTests.swift').read_text())
            with self.assertRaises(ValueError):runner.prepare(root)

    def test_fixture_embedded_only_in_disposable_test_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.scaffold(root)
            fixture=root / 'fixture&config.json';fixture.write_text(json.dumps({'port':2222,'username':'fixture','password':'a'*32,'fingerprint':'SHA256:'+'B'*43,'keyPort':2223,'keyFingerprint':'SHA256:'+'C'*43,'privateKey':'-----BEGIN OPENSSH PRIVATE KEY-----\nYWJj\n-----END OPENSSH PRIVATE KEY-----\n','passphrase':'b'*32}))
            runner.prepare(root,fixture)
            scheme=ET.parse(root / 'macos/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme')
            self.assertIsNone(scheme.find('.//EnvironmentVariable'))
            source=(root / 'macos/RunnerTests/RunnerTests.swift').read_text()
            self.assertNotIn('__HP_FIXTURE_BASE64__',source)
            self.assertNotIn('a'*32,source)

    def test_unknown_project_or_missing_marker_is_not_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(ValueError):runner.prepare(root)
            self.scaffold(root)
            project=root / 'macos/Runner.xcodeproj/project.pbxproj';project.write_text('unrecognized')
            with self.assertRaises(ValueError):runner.prepare(root)
            self.assertEqual(project.read_text(),'unrecognized')

    def test_workflow_report_requires_case_progress_and_peer(self):
        workflow=(Path(__file__).resolve().parents[2] / '.github/workflows/flutter-macos-secure-xcui.yml').read_text()
        start=workflow.index("          python3 - \"$RUNNER_TEMP/macos-secure-evidence/result.json\" \"$result\" <<'PY'\n")
        body=workflow[start:].split("\n          PY\n",1)[0].split("<<'PY'\n",1)[1]
        script=textwrap.dedent(body)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture=root/'macos-secure-fixture';fixture.mkdir()
            allowed=['fixtureReadable','appLaunched','homepage','addressTyped','portTyped','usernameTyped','ordinaryInputReadable','ordinarySentinelObserved','passwordSecureField','passwordHiddenFocused','passwordHiddenBlurred','maskingScanCompleted','passwordValuePresent','passphraseValuePresent',
                     'passwordProbeTapped','passwordFingerprintDialog','fingerprintVerified','sshConnected','disconnectedAndCleared','passphraseSecureField','encryptedKeyProbeTapped','encryptedKeyFingerprintDialog','encryptedKeyFingerprintVerified','encryptedKeyConnected','encryptedKeyDisconnectedAndCleared',
                     'passphraseHiddenAfterFocusChanges','modeSwitchCleared','returnAndReopenCleared']
            good_peer={k:True for k in ('authAccepted','ptyRequested','shellRequested','sessionClosed','connectionsClosed')}
            (fixture/'facts.json').write_text(json.dumps({'password':good_peer,'encryptedKey':good_peer}))
            progress={k:True for k in allowed}
            good_log='Test Case testPasswordAndPrivateKeyPassphraseAreSecure passed\n'+''.join('HP_XCUI_STAGE='+k+'\n' for k in progress)
            log=root/'macos-secure-private.log';log.write_text(good_log)
            output=root/'result.json';env={**os.environ,'RUNNER_TEMP':temp,'GITHUB_SHA':'a'*40}
            def execute():
                return subprocess.run([sys.executable,'-',str(output),'0'],input=script,text=True,env=env,capture_output=True)
            self.assertEqual(execute().returncode,0);self.assertEqual(json.loads(output.read_text())['status'],'passed')
            log.write_text('Executed 0 tests')
            self.assertNotEqual(execute().returncode,0);self.assertFalse(json.loads(output.read_text())['testExecuted'])
            log.write_text('Test Case testPasswordAndPrivateKeyPassphraseAreSecure failed')
            self.assertNotEqual(execute().returncode,0);self.assertTrue(json.loads(output.read_text())['testExecuted']);self.assertFalse(json.loads(output.read_text())['testPassed'])
            mask=['fixtureReadable','appLaunched','homepage','passwordSecureField',
                  'passwordHiddenFocused','passwordHiddenBlurred','passphraseSecureField',
                  'passphraseHiddenAfterFocusChanges','modeSwitchCleared','maskingScanCompleted','passwordValuePresent','passphraseValuePresent']
            log.write_text('Test Case testPasswordAndPrivateKeyPassphraseAreSecure failed\n'+''.join('HP_XCUI_STAGE='+k+'\n' for k in mask))
            self.assertNotEqual(execute().returncode,0);self.assertTrue(json.loads(output.read_text())['systemTreeAndSecureFieldsVerified'])
            log.write_text('Test Case testPasswordAndPrivateKeyPassphraseAreSecure failed\nHP_XCUI_METRIC=windows:1,nodes:10,buttons:2,exact:1,label:1\nprivate fixture material')
            self.assertNotEqual(execute().returncode,0)
            report=json.loads(output.read_text());self.assertEqual(report['homeMetrics']['nodes'],10)
            self.assertNotIn('private fixture material',output.read_text())
            log.write_text('Test Case testPasswordAndPrivateKeyPassphraseAreSecure failed\nHP_XCUI_FINGERPRINT=phase:password,nodes:12,prefix:1,exact:0\nprivate fingerprint material')
            self.assertNotEqual(execute().returncode,0)
            report=json.loads(output.read_text());self.assertEqual(report['fingerprintMetrics'][0]['expectedExactCount'],0)
            self.assertNotIn('private fingerprint material',output.read_text())
            (root/'macos-secure-private-details.json').write_text(json.dumps({'message':'test timed out','private':'synthetic credential'}))
            self.assertNotEqual(execute().returncode,0)
            report=json.loads(output.read_text());self.assertIn('timeout',report['failureCategories']);self.assertTrue(report['xcresultDetailsAvailable'])
            self.assertNotIn('synthetic credential',output.read_text())
            del progress['returnAndReopenCleared'];log.write_text('Test Case testPasswordAndPrivateKeyPassphraseAreSecure passed\n'+''.join('HP_XCUI_STAGE='+k+'\n' for k in progress))
            self.assertNotEqual(execute().returncode,0);self.assertEqual(json.loads(output.read_text())['status'],'failed')
            log.write_text(good_log)
            (fixture/'facts.json').write_text(json.dumps({'password':{'authAccepted':False},'encryptedKey':good_peer}))
            self.assertNotEqual(execute().returncode,0);self.assertFalse(json.loads(output.read_text())['peerAuthenticationPtyShellAndClose'])
            (fixture/'facts.json').write_text(json.dumps({'password':good_peer,'encryptedKey':{'authAccepted':False}}))
            log.write_text(good_log.replace('HP_XCUI_STAGE=passphraseValuePresent','HP_XCUI_STAGE=passphraseValueUnavailable'))
            self.assertNotEqual(execute().returncode,0)
            result=json.loads(output.read_text());self.assertFalse(result['systemTreeAndSecureFieldsVerified']);self.assertEqual(result['errorCode'],'secure_input_unproven')
            (fixture/'facts.json').write_text(json.dumps({'password':good_peer,'encryptedKey':good_peer}))
            self.assertEqual(execute().returncode,0)

    def test_clean_package_precedes_fixture_and_test_hook_and_is_success_gated(self):
        workflow=(Path(__file__).resolve().parents[2] / '.github/workflows/flutter-macos-secure-xcui.yml').read_text()
        self.assertLess(workflow.index('candidate.py" verify-lock'),workflow.index('flutter build macos --debug'))
        self.assertLess(workflow.index('flutter build macos --debug'),workflow.index('ci.py" package'))
        self.assertLess(workflow.index('ci.py" package'),workflow.index('--install-hook'))
        self.assertIn("if: success() && github.ref == 'refs/heads/codex/acceptance/macos-secure-design-parity'",workflow)

    def test_secure_queries_scroll_with_bounded_real_hits_and_dual_peer_guards(self):
        swift=(Path(__file__).parent/'macos_secure_xcuitest.swift').read_text()
        self.assertIn('target.scroll(byDeltaX: 0, deltaY: amount)',swift)
        self.assertIn('first == element.frame && element.isHittable',swift)
        self.assertIn('element.coordinate(withNormalizedOffset:',swift)
        self.assertIn('passwordValueUnavailable',swift)
        self.assertIn('passphraseValueUnavailable',swift)
        self.assertIn('encryptedKeyConnected',swift)
        scanner=swift[swift.index('private func snapshotNodes'):swift.index('private func stableHit')]
        self.assertIn('try app.snapshot()',scanner)
        self.assertIn('pending.append(contentsOf: node.children)',scanner)
        self.assertNotIn('allElementsBoundByIndex',scanner)

if __name__ == '__main__':
    unittest.main()
