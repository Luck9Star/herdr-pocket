import importlib.util
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('flutter_ci', Path(__file__).with_name('ci.py'))
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)

import android_device_test


class AndroidNoticeTests(unittest.TestCase):
    def test_exact_native_notice_is_required_inside_apk(self):
        source = ci.ROOT / 'validation/pairing/native/android/notices/BOUNCY-CASTLE-LICENSE.md'
        with tempfile.TemporaryDirectory() as temp:
            apk = Path(temp) / 'synthetic.apk'
            for contents in [None, b'incorrect notice', source.read_bytes()]:
                with zipfile.ZipFile(apk, 'w') as bundle:
                    notices = ci.ROOT / 'validation/pairing/native/camera/android/notices'
                    for notice in notices.iterdir():
                        bundle.write(notice, 'assets/' + notice.name)
                    if contents is not None:
                        bundle.writestr('assets/BOUNCY-CASTLE-LICENSE.md', contents)
                if contents == source.read_bytes():
                    proof = ci.verify_android_notice(apk)
                    self.assertTrue(proof['matched'])
                    self.assertEqual(proof['assetSha256'], proof['sharedSource']['sha256'])
                else:
                    with self.assertRaises(SystemExit):
                        ci.verify_android_notice(apk)

    def test_missing_camera_notice_prevents_packaging(self):
        with tempfile.TemporaryDirectory() as temp:
            apk = Path(temp) / 'synthetic.apk'
            source = ci.ROOT / 'validation/pairing/native/android/notices/BOUNCY-CASTLE-LICENSE.md'
            with zipfile.ZipFile(apk, 'w') as bundle:
                bundle.write(source, 'assets/' + source.name)
            with self.assertRaisesRegex(SystemExit, 'QR-NOTICE'):
                ci.verify_android_notice(apk)

    def test_manifest_separates_native_sources_runtime_and_manual_identity(self):
        metadata = ci.pairing_provenance('macos', None)
        self.assertEqual(len(metadata['androidSources']), 5)
        self.assertEqual(len(metadata['appleSources']), 2)
        self.assertFalse(metadata['privateKeyExport'])
        self.assertIn('NOT RUN', metadata['systemStoreRuntime'])
        for entry in metadata['androidSources'] + metadata['appleSources']:
            self.assertEqual(len(entry['sha256']), 64)


class SharedDiagnosticAssetsTests(unittest.TestCase):
    diagnostic = 'terminal-font-diagnostics-v1.json'
    theme_prompts = 'theme-prompt-samples-v1.json'

    def test_linux_pairing_sources_are_staged_without_invoking_cargo(self):
        app = self.flutter_scaffold()
        runner = app / 'linux/runner'
        registration = (runner / 'my_application.cc').read_text()
        self.assertEqual(registration.count('RegisterHerdrLinuxPairingChannels('), 1)
        self.assertIn('fl_engine_get_binary_messenger(fl_view_get_engine(view))', registration)
        self.assertIn('herdr_pairing.cmake', (runner / 'CMakeLists.txt').read_text())
        self.assertIn('+1.96.0 build --locked', (runner / 'herdr_pairing.cmake').read_text())
        self.assertEqual(ci.pairing_provenance('macos', None)['linuxSources'], [])

    def test_secure_appkit_factory_is_included_only_in_generated_macos_runner(self):
        app = self.flutter_scaffold()
        mac = (app / 'macos/Runner/MainFlutterWindow.swift').read_text()
        ios = (app / 'ios/Runner/AppDelegate.swift').read_text()
        source = (ci.ROOT / 'validation/flutter/native/apple/SecureCredentialView.swift').read_text()
        self.assertIn(source, mac)
        self.assertIn('registerHerdrSecureCredentialFields(registrar:', mac)
        self.assertIn('registrar(forPlugin: "HerdrSecureCredentialFields")', mac)
        self.assertIn('registerHerdrSecureAccessibilityWindow(self)', mac)
        self.assertIn('herdrSecureAccessibilityChildren(window: self, preserving: super.accessibilityChildren())', mac)
        self.assertNotIn('flutterView.accessibilityChildren', mac)
        self.assertNotIn('HerdrSecureCredential', ios)
        self.assertNotIn('herdrSecureAccessibilityChildren', ios)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='herdr-shared-diagnostic-assets-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.shared = ci.ROOT / 'validation/shared'

    def flutter_scaffold(self):
        app = self.root / 'flutter-app'
        def create(args, cwd=None):
            # Only the platform templates are synthetic. The real prepare()
            # copies the repository's pubspec/shared files without an SDK.
            self.assertEqual(args[1], 'create')
            self.assertEqual(Path(args[-1]), app)
            files = {
                'macos/Runner/DebugProfile.entitlements': '<plist><dict></dict></plist>',
                'macos/Runner/Release.entitlements': '<plist><dict></dict></plist>',
                'macos/Runner/MainFlutterWindow.swift': 'class MainFlutterWindow: NSWindow {\n  override func awakeFromNib() {\n    RegisterGeneratedPlugins(registry: flutterViewController)\n  }\n}\n',
                'ios/Runner/AppDelegate.swift': 'GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)',
                'android/app/src/main/AndroidManifest.xml': '<manifest><application /></manifest>',
                'android/app/build.gradle.kts': 'namespace = "dev.herdr.herdr_flutter_probe"\napplicationId = "dev.herdr.herdr_flutter_probe"\n',
                'linux/runner/my_application.cc': '#include "my_application.h"\n  fl_register_plugins(FL_PLUGIN_REGISTRY(view));\n',
                'linux/runner/CMakeLists.txt': 'target_link_libraries(herdr_flutter_probe PRIVATE flutter)\n',
            }
            for name, text in files.items():
                target = app / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
            (app / 'ios/Runner/Info.plist').write_bytes(plistlib.dumps({}))
            (app / 'android/app/src/main/kotlin/dev/herdr/herdr_flutter_probe').mkdir(parents=True)
        with patch.object(ci, 'run', side_effect=create) as command, \
                patch.object(ci.terminal_view_ime, 'prepare_reference'):
            ci.prepare(app)
        command.assert_called_once()
        return app

    def tauri_source(self):
        repo = self.root / 'tauri-source'
        root = repo / 'validation/tauri'
        (root / 'scripts').mkdir(parents=True)
        shutil.copy2(ci.ROOT / 'validation/tauri/scripts/prepare-fixtures.mjs', root / 'scripts/prepare-fixtures.mjs')
        shutil.copytree(self.shared, repo / 'validation/shared', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        vendor = repo / 'validation/vendor'; vendor.mkdir()
        for name in ('RUSSH-NOTICE.md', 'russh-0.65.0-source.json', 'russh-0.65.0-local-close.patch', 'russh-0.65.0-LICENSE-APACHE'):
            shutil.copy2(ci.ROOT / 'validation/vendor' / name, vendor / name)
        for name in ('@xterm/xterm', '@xterm/addon-unicode-graphemes'):
            license = root / 'node_modules' / name / 'LICENSE'
            license.parent.mkdir(parents=True)
            license.write_text('Synthetic license fixture; no dependency is installed or executed.\n')
        return root

    def test_android_connect_diagnostic_is_only_staged_in_device_scaffold(self):
        source = 'a' * 40
        with patch.dict(os.environ, {'GITHUB_SHA': source}):
            app = self.flutter_scaffold()
        staged = app / android_device_test.CONNECT_DIAGNOSTIC_TEST
        self.assertFalse(staged.exists())
        self.assertFalse((app / 'device_test').exists())
        self.assertFalse((app / 'integration_test').exists())
        self.assertNotIn('integration_test:', (app / 'pubspec.yaml').read_text())

        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '123',
               'GITHUB_REF': 'refs/heads/codex/device-preparation-test', 'GITHUB_SHA': source,
               'RUNNER_TEMP': str(self.root)}
        (app / 'candidate/terminal_view').mkdir(parents=True)
        (app / 'pubspec_overrides.yaml').write_text(
            'dependency_overrides:\n  terminal_view:\n    path: candidate/terminal_view\n')
        lock = app / 'pubspec.lock'
        lock.write_text(lock.read_text().replace('candidate/reference_terminal_view', 'candidate/terminal_view'))
        (app / 'candidate-manifest.json').write_text(json.dumps({
            'sourceCommit': source, 'variant': 'experimental-patched',
            'candidateLockSha256': android_device_test.digest(lock)}))

        proof = android_device_test.prepare(app, env)
        original = android_device_test.SOURCE / 'device_test' / staged.name
        self.assertEqual(staged.read_bytes(), original.read_bytes())
        self.assertEqual(proof['connectDiagnosticTestSha256'], android_device_test.digest(staged))
        staged.write_text('changed')
        with self.assertRaisesRegex(android_device_test.DevicePreparationFailure, 'android_device_preparation_changed'):
            android_device_test.verify_lock(app, env)

    @unittest.skipUnless(shutil.which('node'), 'real Tauri resource copier requires an existing Node executable')
    def test_real_copy_paths_include_identical_diagnostic_and_locked_font_bytes(self):
        checksums = dict(line.split('  ', 1)[::-1] for line in (self.shared / 'SHA256SUMS').read_text().splitlines())
        app = self.flutter_scaffold()
        pubspec = (app / 'pubspec.yaml').read_text()
        self.assertIn('  terminal_view:\n    path: candidate/reference_terminal_view\n', pubspec)
        lock = (app / 'pubspec.lock').read_text()
        self.assertIn('      path: "candidate/reference_terminal_view"', lock)
        self.assertEqual(lock.count('      path: "candidate/reference_terminal_view"'), 1)
        root = self.tauri_source()
        subprocess.run([shutil.which('node'), root / 'scripts/prepare-fixtures.mjs'], cwd=root,
                       check=True, capture_output=True, text=True)
        for name in (self.diagnostic, self.theme_prompts):
            with self.subTest(asset=name):
                source = (self.shared / name).read_bytes()
                self.assertEqual(hashlib.sha256(source).hexdigest(), checksums[name])
                self.assertEqual(pubspec.count('    - assets/shared/' + name + '\n'), 1)
                self.assertEqual((app / 'assets/shared' / name).read_bytes(), source)
                self.assertEqual((root / 'public/shared' / name).read_bytes(), source)
        font = json.loads((self.shared / 'fixture.json').read_text())['font']
        expected = (self.shared / font['file']).read_bytes()
        self.assertEqual(hashlib.sha256(expected).hexdigest(), font['sha256'])
        self.assertEqual((app / 'assets/shared' / font['file']).read_bytes(), expected)
        self.assertEqual((root / 'public/shared' / font['file']).read_bytes(), expected)

    @unittest.skipUnless(shutil.which('node'), 'real Tauri resource copier requires an existing Node executable')
    def test_tampered_diagnostic_cannot_reach_tauri_public_assets(self):
        root = self.tauri_source()
        (root.parent / 'shared' / self.diagnostic).write_bytes(b'{"tampered":true}\n')
        result = subprocess.run([shutil.which('node'), root / 'scripts/prepare-fixtures.mjs'], cwd=root,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Shared fixture hash mismatch: ' + self.diagnostic, result.stderr)
        self.assertFalse((root / 'public/shared' / self.diagnostic).exists())

    @unittest.skipUnless(shutil.which('git'), 'candidate patching requires an existing Git executable')
    def test_candidate_apply_keeps_pubspec_registration_and_shared_diagnostic_bytes(self):
        app = self.flutter_scaffold()
        asset = app / 'assets/shared' / self.diagnostic
        expected, pubspec = asset.read_bytes(), (app / 'pubspec.yaml').read_bytes()
        spec = importlib.util.spec_from_file_location('shared_asset_candidate', Path(__file__).with_name('candidate.py'))
        candidate = importlib.util.module_from_spec(spec); spec.loader.exec_module(candidate)
        source = self.root / 'candidate-source'; (source / 'patches').mkdir(parents=True)
        before, after = b'base\n', b'fixed\n'
        patch_bytes = b'--- a/source.txt\n+++ b/source.txt\n@@ -1 +1 @@\n-base\n+fixed\n'
        (source / 'patches/probe.patch').write_bytes(patch_bytes)
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as bundle:
            entry = tarfile.TarInfo('source.txt'); entry.size = len(before)
            bundle.addfile(entry, io.BytesIO(before))
        blob = archive.getvalue()
        (source / 'pubspec.lock').write_bytes((app / 'pubspec.lock').read_bytes())
        (source / 'patches/manifest.json').write_text(json.dumps({
            'patch': 'probe.patch', 'patchSha256': candidate.digest(patch_bytes),
            'archiveUrl': 'https://invalid.example/offline-fixture', 'archiveSha256': candidate.digest(blob),
            'files': {'source.txt': {'beforeSha256': candidate.digest(before), 'afterSha256': candidate.digest(after)}}}))
        with patch.object(candidate, 'SOURCE', source), \
                patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_TEMP': str(self.root), 'GITHUB_SHA': 'a' * 40}), \
                patch.object(candidate.urllib.request, 'urlopen', return_value=io.BytesIO(blob)), \
                patch.object(candidate.terminal_view_ime, 'apply_shim', return_value={'fixture': True}), \
                redirect_stdout(io.StringIO()):
            candidate.apply(app)
        self.assertEqual((app / 'candidate/terminal_view/source.txt').read_bytes(), after)
        self.assertEqual((app / 'pubspec.yaml').read_bytes(), pubspec)
        self.assertEqual(asset.read_bytes(), expected)


if __name__ == '__main__':
    unittest.main()
