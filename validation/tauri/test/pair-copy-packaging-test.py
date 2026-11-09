#!/usr/bin/env python3
"""Exercise disposable Android source wiring; no Gradle, SDK, device or clipboard."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
TAURI = REPO / 'validation/tauri'


class PairCopyPackaging(unittest.TestCase):
    def test_registered_native_command_reuses_packaged_clipboard_plugin(self):
        with tempfile.TemporaryDirectory(prefix='pair-copy-package-') as temporary:
            root = Path(temporary) / 'validation/tauri'
            (root / 'scripts').mkdir(parents=True)
            for name in ('wire-android.py', 'js_notices.py'):
                shutil.copyfile(TAURI / 'scripts' / name, root / 'scripts' / name)
            shutil.copytree(TAURI / 'android', root / 'android')
            for name in ('package.json', 'package-lock.json'):
                shutil.copyfile(TAURI / name, root / name)
            lock = json.loads((TAURI / 'package-lock.json').read_text())
            for package in ('@xterm/xterm', '@xterm/addon-unicode-graphemes'):
                folder = root / 'node_modules' / package
                folder.mkdir(parents=True)
                for name in ('package.json', 'LICENSE'):
                    shutil.copyfile(TAURI / 'node_modules' / package / name, folder / name)
                self.assertEqual(json.loads((folder / 'package.json').read_text())['version'], lock['packages']['node_modules/' + package]['version'])
            app = root / 'src-tauri/gen/android/app'
            app.mkdir(parents=True)
            (app / 'build.gradle.kts').write_text('// isolated generated-project fixture\n')
            subprocess.run([sys.executable, str(root / 'scripts/wire-android.py')], check=True, capture_output=True)
            copied = app / 'src/main/java/org/herdr/pocket/ClipboardPlugin.kt'
            self.assertEqual(copied.read_bytes(), (TAURI / 'android/ClipboardPlugin.kt').read_bytes())
            self.assertIn('fun copyPairingRequest(', copied.read_text())
            self.assertIn('manager.setPrimaryClip(clip)', copied.read_text())
        lib = (TAURI / 'src-tauri/src/lib.rs').read_text()
        self.assertIn('mod pair_copy;', lib)
        self.assertIn('pair_copy::pair_copy_request', lib)
        self.assertIn('.plugin(clipboard::android_plugin())', lib)
        bridge = (TAURI / 'src-tauri/src/clipboard.rs').read_text()
        self.assertIn('"copyPairingRequest"', bridge)

    def test_wire_android_hardens_gradle_wrapper_timeout(self):
        with tempfile.TemporaryDirectory(prefix='wrapper-timeout-') as temporary:
            root = Path(temporary) / 'validation/tauri'
            (root / 'scripts').mkdir(parents=True)
            for name in ('wire-android.py', 'js_notices.py'):
                shutil.copyfile(TAURI / 'scripts' / name, root / 'scripts' / name)
            shutil.copytree(TAURI / 'android', root / 'android')
            for name in ('package.json', 'package-lock.json'):
                shutil.copyfile(TAURI / name, root / name)
            lock = json.loads((TAURI / 'package-lock.json').read_text())
            for package in ('@xterm/xterm', '@xterm/addon-unicode-graphemes'):
                folder = root / 'node_modules' / package
                folder.mkdir(parents=True)
                for name in ('package.json', 'LICENSE'):
                    shutil.copyfile(TAURI / 'node_modules' / package / name, folder / name)
            app = root / 'src-tauri/gen/android/app'
            app.mkdir(parents=True)
            (app / 'build.gradle.kts').write_text('// isolated generated-project fixture\n')
            wrapper_dir = root / 'src-tauri/gen/android/gradle/wrapper'
            wrapper_dir.mkdir(parents=True)
            initial_props = (
                'distributionBase=GRADLE_USER_HOME\n'
                'distributionPath=wrapper/dists\n'
                'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.6.1-bin.zip\n'
                'networkTimeout=10000\n'
                'validateDistributionUrl=true\n'
                'zipStoreBase=GRADLE_USER_HOME\n'
                'zipStorePath=wrapper/dists\n'
            )
            (wrapper_dir / 'gradle-wrapper.properties').write_text(initial_props)
            subprocess.run([sys.executable, str(root / 'scripts/wire-android.py')], check=True, capture_output=True)
            updated = (wrapper_dir / 'gradle-wrapper.properties').read_text()
            self.assertIn('networkTimeout=120000', updated)
            self.assertNotIn('networkTimeout=10000', updated)
            self.assertIn('distributionUrl=https\\://services.gradle.org/distributions/gradle-9.6.1-bin.zip', updated)
            self.assertIn('validateDistributionUrl=true', updated)


if __name__ == '__main__':
    unittest.main()
