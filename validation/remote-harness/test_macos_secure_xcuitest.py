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
        (root / '.herdr-generated-probe.json').write_text(json.dumps({'kind':'herdr-flutter-validation'}))
        (root / 'macos/Runner.xcodeproj/project.pbxproj').write_text(PROJECT)
        (root / 'macos/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme').write_text('<Scheme><TestAction><Testables><Testable parallelizable = "YES"/></Testables></TestAction></Scheme>')
        (root / 'macos/RunnerTests/RunnerTests.swift').write_text('unit test')

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
            fixture=root / 'fixture&config.json';fixture.write_text(json.dumps({'port':2222,'username':'fixture','password':'a'*32,'fingerprint':'SHA256:'+'B'*43}))
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
            allowed=['fixtureReadable','appLaunched','homepage','ordinaryInputReadable','passwordSecureField','passwordHiddenFocused','passwordHiddenBlurred',
                     'fingerprintVerified','sshConnected','disconnectedAndCleared','passphraseSecureField',
                     'passphraseHiddenAfterFocusChanges','modeSwitchCleared','returnAndReopenCleared']
            (fixture/'facts.json').write_text(json.dumps({k:True for k in ('authAccepted','ptyRequested','shellRequested','sessionClosed','connectionsClosed')}))
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
            del progress['returnAndReopenCleared'];log.write_text('Test Case testPasswordAndPrivateKeyPassphraseAreSecure passed\n'+''.join('HP_XCUI_STAGE='+k+'\n' for k in progress))
            self.assertNotEqual(execute().returncode,0);self.assertEqual(json.loads(output.read_text())['status'],'failed')
            log.write_text(good_log)
            (fixture/'facts.json').write_text(json.dumps({'authAccepted':False}))
            self.assertNotEqual(execute().returncode,0);self.assertFalse(json.loads(output.read_text())['peerAuthenticationPtyShellAndClose'])

if __name__ == '__main__':
    unittest.main()
