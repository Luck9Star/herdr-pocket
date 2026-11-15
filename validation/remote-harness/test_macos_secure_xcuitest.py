"""Safety and scaffold contract; actual XCUITest requires macOS and Xcode."""
import json
from pathlib import Path
import tempfile
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

    def test_fixture_path_is_escaped_and_forwarded_to_test_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.scaffold(root)
            # Fixture name contains XML metacharacters; no credential is in the scheme.
            fixture=root / 'fixture&config.json';fixture.write_text('{}')
            runner.prepare(root,fixture)
            scheme=ET.parse(root / 'macos/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme')
            env=scheme.find('.//EnvironmentVariable')
            self.assertEqual(env.get('key'),'HP_MAC_AX_FIXTURE')
            self.assertEqual(env.get('value'),str(fixture.resolve()))

    def test_unknown_project_or_missing_marker_is_not_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(ValueError):runner.prepare(root)
            self.scaffold(root)
            project=root / 'macos/Runner.xcodeproj/project.pbxproj';project.write_text('unrecognized')
            with self.assertRaises(ValueError):runner.prepare(root)
            self.assertEqual(project.read_text(),'unrecognized')

if __name__ == '__main__':
    unittest.main()
