import json
import hashlib
from pathlib import Path
import struct
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock
import android_bundle as bundle
import js_notices

class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.lib = self.path / 'libheeler_easytier.so'
        self.lib.write_bytes(b'\x7fELF\x02\x01' + bytes(10) + struct.pack('<HH', 3, 183))

    def test_report_preserves_failed_source_checks_without_claiming_android_runtime(self):
        # This exercises report assembly only, not APK or native validation.
        (self.path / 'app.apk').write_bytes(b'synthetic report fixture')
        (self.path / 'native-manifest.json').write_text('{}\n')
        candidate = self.path / 'candidate-manifest.json'
        candidate.write_text('{"variant":"experimental-patched"}\n')
        with mock.patch('sys.argv', ['android_bundle.py', 'report', str(self.path),
                                   '--commit', 'a' * 40, '--app', 'flutter', '--checks', 'failure']):
            bundle.main()
        report = json.loads((self.path / 'report.json').read_text())
        self.assertEqual(report['sourceChecks'], 'failure')
        self.assertEqual(report['transportChecks'], 'not_run')
        self.assertEqual(report['terminalCandidateManifestSha256'], bundle.sha(candidate))
        for field in ['androidLoad', 'installation', 'node']:
            self.assertEqual(report[field], 'not run')

    def test_tauri_report_copies_and_records_notices_only_after_apk_match(self):
        (self.path / 'native-manifest.json').write_text('{}\n')
        notice_records = {
            filename: {
                'package': package, 'version': version, 'license': 'MIT',
                'resolved': 'https://registry.npmjs.org/fixture.tgz',
                'integrity': 'sha512-test-fixture', 'packageLockSha256': 'a' * 64,
                'sourceLicenseSha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'data': data,
            }
            for filename, package, version, data in [
                ('xterm-LICENSE', '@xterm/xterm', '6.0.0', b'xterm MIT source'),
                ('xterm-addon-unicode-graphemes-LICENSE', '@xterm/addon-unicode-graphemes', '0.4.0', b'graphemes MIT source'),
            ]
        }
        apk = self.path / 'app.apk'
        with zipfile.ZipFile(apk, 'w') as archive:
            for filename, record in notice_records.items():
                archive.writestr('assets/' + filename, record['data'])
        args = ['android_bundle.py', 'report', str(self.path), '--commit', 'b' * 40, '--app', 'tauri']
        with mock.patch.object(bundle, 'collect_js_notices', return_value=notice_records), mock.patch('sys.argv', args):
            bundle.main()
        report = json.loads((self.path / 'report.json').read_text())
        self.assertEqual(set(report['tauriJavaScriptNotices']), {
            'assets/xterm-LICENSE', 'assets/xterm-addon-unicode-graphemes-LICENSE'})
        self.assertEqual((self.path / 'xterm-LICENSE').read_bytes(), notice_records['xterm-LICENSE']['data'])
        self.assertEqual((self.path / 'xterm-addon-unicode-graphemes-LICENSE').read_bytes(),
                         notice_records['xterm-addon-unicode-graphemes-LICENSE']['data'])
        provenance = json.loads((self.path / 'js-notices.json').read_text())
        self.assertEqual(provenance['xterm-LICENSE']['integrity'], 'sha512-test-fixture')
        self.assertNotIn('data', provenance['xterm-LICENSE'])
        self.assertIn('xterm-LICENSE', (self.path / 'SHA256SUMS').read_text())

        with zipfile.ZipFile(apk, 'w') as archive:
            archive.writestr('assets/xterm-LICENSE', b'tampered')
        (self.path / 'report.json').unlink()
        with mock.patch.object(bundle, 'collect_js_notices', return_value=notice_records), mock.patch('sys.argv', args):
            with self.assertRaisesRegex(ValueError, 'differs'):
                bundle.main()
        self.assertFalse((self.path / 'report.json').exists())

    def test_elf_arch_and_dependencies_fail_closed(self):
        with mock.patch.object(bundle.subprocess, 'check_output', return_value='  (NEEDED) Shared library: [libc.so]\n'):
            self.assertEqual(bundle.elf(self.lib, 'readelf'), ['libc.so'])
            with self.assertRaises(ValueError): bundle.elf(self.lib, 'readelf', needed=['libheeler_easytier.so'])
        self.lib.write_bytes(self.lib.read_bytes()[:18] + struct.pack('<H', 62))
        with self.assertRaises(ValueError): bundle.elf(self.lib, 'readelf')

    def test_reject_forged_or_incomplete_manifest(self):
        manifest = {'sourceCommit': 'a' * 40, 'abi': 'arm64-v8a', 'api': 35,
                    'sourcesSha256': bundle.sha(bundle.ROOT / 'validation/native/sources.json'),
                    'patchManifestSha256': bundle.sha(bundle.ROOT / 'validation/native/patches/portable-manifest.json'),
                    'files': {'libheeler_easytier.so': bundle.sha(self.lib)}}
        (self.path / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError): bundle.verify(self.path, 'b' * 40, 'readelf')
        with self.assertRaises(ValueError): bundle.verify(self.path, 'a' * 40, 'readelf')

    def test_public_native_window_does_not_admit_private_or_missing_dependencies(self):
        dynamic = '  (NEEDED) Shared library: [libnativewindow.so]\n'
        with mock.patch.object(bundle.subprocess, 'check_output', return_value=dynamic):
            self.assertEqual(bundle.elf(self.lib, 'readelf'), ['libnativewindow.so'])
            with self.assertRaisesRegex(ValueError, 'DT_NEEDED in libheeler_easytier.so'):
                bundle.elf(self.lib, 'readelf', needed=['libheeler_easytier.so'])
        with mock.patch.object(bundle.subprocess, 'check_output', return_value=dynamic + '  (NEEDED) Shared library: [libprivate-fixture.so]\n'):
            with self.assertRaisesRegex(ValueError, 'libprivate-fixture.so'):
                bundle.elf(self.lib, 'readelf')

    def prepare_bundle(self):
        native = bundle.ROOT / 'validation/native'
        names = ['upstream-sources.lock', 'Heeler-Cargo.lock', 'reference-source.tar',
                 'easytier-source.tar', 'build-details.json']
        for name in names:
            (self.path / name).write_bytes(b'fixture')
        shutil.copy2(native / 'sources.json', self.path / 'sources.json')
        shutil.copy2(native / 'patches/portable-manifest.json', self.path / 'candidate-provenance.json')
        shutil.copytree(native / 'patches', self.path / 'patches')
        shutil.copytree(native / 'portable-stream', self.path / 'portable-stream')
        self.rehash_bundle()

    def rehash_bundle(self):
        native = bundle.ROOT / 'validation/native'
        files = {p.relative_to(self.path).as_posix(): bundle.sha(p)
                 for p in self.path.rglob('*') if p.is_file() and p.name != 'manifest.json'}
        manifest = {'sourceCommit': 'a' * 40, 'abi': 'arm64-v8a', 'api': 35,
                    'sourcesSha256': bundle.sha(native / 'sources.json'),
                    'patchManifestSha256': bundle.sha(native / 'patches/portable-manifest.json'),
                    'files': files}
        (self.path / 'manifest.json').write_text(json.dumps(manifest))

    def test_manifest_rejects_tampering_after_valid_verification(self):
        self.prepare_bundle()
        with mock.patch.object(bundle, 'elf'):
            self.assertEqual(bundle.verify(self.path, 'a' * 40, 'readelf')['abi'], 'arm64-v8a')
            self.lib.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                bundle.verify(self.path, 'a' * 40, 'readelf')

    def test_source_material_cannot_be_forged_or_omitted_with_self_consistent_hashes(self):
        native = bundle.ROOT / 'validation/native'
        portable = json.loads((native / 'patches/portable-manifest.json').read_text())
        materials = ['sources.json', 'candidate-provenance.json', 'patches/portable-manifest.json',
                     'patches/' + portable['patch']]
        materials += ['portable-stream/' + name for group in ('copiedModules', 'sourceTemplates')
                      for name in portable[group]]
        self.prepare_bundle()
        with mock.patch.object(bundle, 'elf'):
            for name in materials:
                path = self.path / name
                original = path.read_bytes()
                with self.subTest(material=name, mode='forged'):
                    path.write_bytes(b'{}' if name.endswith('.json') else b'forged')
                    self.rehash_bundle()
                    with self.assertRaises(ValueError):
                        bundle.verify(self.path, 'a' * 40, 'readelf')
                with self.subTest(material=name, mode='missing'):
                    path.unlink()
                    self.rehash_bundle()
                    with self.assertRaises(ValueError):
                        bundle.verify(self.path, 'a' * 40, 'readelf')
                path.write_bytes(original)
                self.rehash_bundle()

    def test_apk_rejects_wrong_native_bytes_and_other_abi(self):
        apk = self.path / 'app.apk'
        with mock.patch.object(bundle, 'verify'):
            with zipfile.ZipFile(apk, 'w') as z:
                z.writestr('lib/arm64-v8a/libheeler_easytier.so', b'wrong')
                z.writestr('lib/arm64-v8a/libherdr_flutter_network_runtime.so', b'bridge')
            with self.assertRaisesRegex(ValueError, 'differs'):
                bundle.apk(apk, self.path, 'a' * 40, 'readelf', 'flutter')
            with zipfile.ZipFile(apk, 'a') as z:
                z.writestr('lib/x86_64/libforeign.so', b'foreign')
            with self.assertRaisesRegex(ValueError, 'another ABI'):
                bundle.apk(apk, self.path, 'a' * 40, 'readelf', 'flutter')

    def test_readelf_export_binding_visibility_and_defined(self):
        symbol = 'required_symbol'
        for binding, visibility, section in [('GLOBAL', 'DEFAULT', '12'), ('WEAK', 'PROTECTED', '12')]:
            row = f'  10: 0000000000000100 16 FUNC {binding} {visibility} {section} {symbol}\n'
            with self.subTest(binding=binding, visibility=visibility, section=section):
                with mock.patch.object(bundle.subprocess, 'check_output', side_effect=['', row]):
                    bundle.elf(self.lib, 'readelf', [symbol])
        for binding, visibility, section in [('LOCAL', 'DEFAULT', '12'), ('GLOBAL', 'HIDDEN', '12'),
                                             ('GLOBAL', 'INTERNAL', '12'), ('GLOBAL', 'DEFAULT', 'UND')]:
            row = f'  10: 0000000000000100 16 FUNC {binding} {visibility} {section} {symbol}\n'
            with self.subTest(binding=binding, visibility=visibility, section=section):
                with mock.patch.object(bundle.subprocess, 'check_output', side_effect=['', row]):
                    with self.assertRaisesRegex(ValueError, 'exported symbols'):
                        bundle.elf(self.lib, 'readelf', [symbol])

    def test_apk_checks_expected_jni_exports(self):
        notice_records = {
            filename: {'data': data, 'sourceLicenseSha256': hashlib.sha256(data).hexdigest()}
            for filename, data in [('xterm-LICENSE', b'xterm MIT fixture'),
                                   ('xterm-addon-unicode-graphemes-LICENSE', b'graphemes MIT fixture')]
        }
        for app, app_lib, exports in [
            ('flutter', 'libherdr_flutter_network_runtime.so', list(bundle.FLUTTER_JNI)),
            ('tauri', 'libherdr_pocket_tauri_probe_lib.so', [bundle.BIND_NATIVE]),
        ]:
            apk = self.path / (app + '.apk')
            with zipfile.ZipFile(apk, 'w') as archive:
                archive.writestr('lib/arm64-v8a/libheeler_easytier.so', self.lib.read_bytes())
                archive.writestr('lib/arm64-v8a/' + app_lib, self.lib.read_bytes())
                if app == 'tauri':
                    for filename, record in notice_records.items():
                        archive.writestr('assets/' + filename, record['data'])
            def readelf(command, **kwargs):
                if '-d' in command:
                    return ' (NEEDED) Shared library: [libheeler_easytier.so]\n' if command[-1].endswith(app_lib) else ''
                return ''.join(f' {i}: 0000000000000100 16 FUNC GLOBAL DEFAULT 12 {name}\n'
                               for i, name in enumerate(exports))
            with self.subTest(app=app), mock.patch.object(bundle, 'verify'), mock.patch.object(bundle.subprocess, 'check_output', side_effect=readelf), mock.patch.object(bundle, 'collect_js_notices', return_value=notice_records):
                bundle.apk(apk, self.path, 'a' * 40, 'readelf', app)
                exports.pop()
                try:
                    with self.assertRaisesRegex(ValueError, 'exported symbols'):
                        bundle.apk(apk, self.path, 'a' * 40, 'readelf', app)
                finally:
                    exports.append('Java_dev_herdr_pocket_NetworkRuntimeChannel_nativeCloseScope' if app == 'flutter' else bundle.BIND_NATIVE)

    def test_js_notice_source_lock_and_android_assets(self):
        package_root = self.path / 'tauri'
        package_root.mkdir()
        dependencies = {name: version for name, (version, _) in js_notices.PACKAGES.items()}
        (package_root / 'package.json').write_text(json.dumps({'dependencies': dependencies}))
        lock_entries = {}
        expected_data = {}
        for name, (version, filename) in js_notices.PACKAGES.items():
            package_dir = package_root / 'node_modules' / name
            package_dir.mkdir(parents=True)
            data = ('MIT notice for ' + name).encode()
            expected_data[filename] = data
            (package_dir / 'package.json').write_text(json.dumps({'name': name, 'version': version, 'license': 'MIT'}))
            (package_dir / 'LICENSE').write_bytes(data)
            lock_entries['node_modules/' + name] = {
                'version': version, 'license': 'MIT',
                'resolved': 'https://registry.npmjs.org/test.tgz', 'integrity': 'sha512-test-fixture',
            }
        (package_root / 'package-lock.json').write_text(json.dumps({'packages': lock_entries}))
        records = js_notices.collect(package_root)
        assets = self.path / 'assets'
        js_notices.copy_android_assets(package_root, assets)
        for filename, data in expected_data.items():
            self.assertEqual((assets / filename).read_bytes(), data)
            self.assertEqual(records[filename]['data'], data)

    def test_js_notice_zip_verifier_positive_and_negative_cases(self):
        records = {
            filename: {'data': data, 'sourceLicenseSha256': hashlib.sha256(data).hexdigest()}
            for filename, data in [('xterm-LICENSE', b'xterm MIT fixture'),
                                   ('xterm-addon-unicode-graphemes-LICENSE', b'graphemes MIT fixture')]
        }
        archive_path = self.path / 'notices.zip'
        with zipfile.ZipFile(archive_path, 'w') as archive:
            for filename, record in records.items():
                archive.writestr('assets/' + filename, record['data'])
        self.assertEqual(set(js_notices.verify_zip(archive_path, records, 'assets/')),
                         {'assets/xterm-LICENSE', 'assets/xterm-addon-unicode-graphemes-LICENSE'})
        with zipfile.ZipFile(archive_path, 'w') as archive:
            archive.writestr('assets/xterm-LICENSE', records['xterm-LICENSE']['data'])
            archive.writestr('assets/xterm-addon-unicode-graphemes-LICENSE', b'tampered')
        with self.assertRaisesRegex(ValueError, 'differs'):
            js_notices.verify_zip(archive_path, records, 'assets/')
        with zipfile.ZipFile(archive_path, 'w') as archive:
            archive.writestr('assets/xterm-LICENSE', records['xterm-LICENSE']['data'])
        with self.assertRaisesRegex(ValueError, 'missing, duplicate'):
            js_notices.verify_zip(archive_path, records, 'assets/')

    def test_reject_missing_export(self):
        with mock.patch.object(bundle.subprocess, 'check_output', side_effect=['', '']):
            with self.assertRaises(ValueError): bundle.elf(self.lib, 'readelf', ['required_symbol'])

if __name__ == '__main__': unittest.main()
