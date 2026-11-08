import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import android_bundle as bundle
import android_zerotier

ROOT = bundle.ROOT


def git_blob_sha1(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


class ZeroTierSurfaceTests(unittest.TestCase):
    """The required ABI and the JNI exports must match the Rust host sources."""

    def test_required_symbols_match_the_rust_ffi_surface(self):
        names = set()
        for relative in ('validation/android-network-source/src/zerotier.rs',
                         'validation/overlay-runtime/src/zerotier.rs'):
            names |= set(re.findall(r'\bfn\s+(hp_zt_[A-Za-z0-9_]+)',
                                    (ROOT / relative).read_text()))
        self.assertEqual(names, set(android_zerotier.SYMBOLS))
        self.assertEqual(len(android_zerotier.SYMBOLS), 19)

    def test_bound_symbols_match_the_boundary_header(self):
        header = (ROOT / 'validation/native/zerotier-runtime/hp_zt_bound.h').read_text()
        names = set(re.findall(r'\b(hp_zt_bound_[A-Za-z0-9_]+)\(', header))
        self.assertEqual(names, set(android_zerotier.BOUND_SYMBOLS))
        self.assertEqual(len(android_zerotier.BOUND_SYMBOLS), 6)

    def test_link_flags_include_hardening_and_page_alignment(self):
        flags = android_zerotier.link_flags()
        for flag in ('-shared', '-fPIC', '-static-libstdc++',
                     '-Wl,-soname,' + android_zerotier.LIBRARY,
                     '-Wl,-z,max-page-size=16384', '-Wl,--no-undefined',
                     '-pthread', '-llog', '-landroid'):
            self.assertIn(flag, flags)

    def test_jni_exports_match_the_rust_host(self):
        text = (ROOT / 'validation/android-network-source/src/zerotier.rs').read_text()
        names = set(re.findall(
            r'pub extern "system" fn (Java_org_herdr_network_AndroidZeroTierNative_[A-Za-z0-9_]+)',
            text))
        self.assertEqual(names, set(bundle.ZERO_TIER_JNI))

    def test_compile_flags_mirror_the_upstream_android_build(self):
        self.assertEqual(android_zerotier.group_flags('ztcore'), ['-march=armv8-a+crypto'])
        self.assertEqual(android_zerotier.group_flags('natpmp'), ['-DNATPMP_EXPORTS'])
        self.assertEqual(android_zerotier.group_flags('libzt'), [])
        self.assertIn('-DLWIP_DBG_TYPES_ON=0', android_zerotier.group_flags('lwip'))
        self.assertIn('-DMACOSX', android_zerotier.group_flags('miniupnpc'))
        cxx = android_zerotier.common_flags('cxx', [])
        for flag in ('-fPIC', '-fstack-protector', '-DZT_SDK=1', '-DZT_USE_MINIUPNPC=1',
                     '-DOMIT_JSON_SUPPORT=1', '-std=c++11', '-DZTS_DISABLE_CENTRAL_API=1'):
            self.assertIn(flag, cxx)
        self.assertNotIn('-std=c++11', android_zerotier.common_flags('c', []))

    def test_toolchain_requires_the_pinned_ndk(self):
        with self.assertRaisesRegex(ValueError, 'wrong pinned Android NDK'):
            android_zerotier.toolchain(Path('/tmp') / 'ndk' / '27.0.0')


class ZeroTierBundleTests(unittest.TestCase):
    """Offline checks of the standalone ZeroTier provider artifact."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.out = self.path / 'bundle'
        self.out.mkdir()
        self.commit = 'c' * 40
        self.lock = b'LIBZT_COMMIT="fixture"\n'
        self.source = {'schemaVersion': 1,
                       'reference': {'repository': 'fixture/repo', 'commit': 'a' * 40,
                                     'lockGitBlob': git_blob_sha1(self.lock)},
                       'sources': [{'name': 'libzt', 'repository': 'fixture/libzt',
                                    'commit': 'b' * 40, 'destination': '.',
                                    'sha256': hashlib.sha256(b'libzt tarball').hexdigest()}],
                       'upstreamPatches': [{'path': 'patches/libzt/0001-fixture.patch',
                                            'sha256': hashlib.sha256(b'upstream patch').hexdigest()}]}
        self.source_manifest = self.path / 'zerotier-runtime-source.json'
        self.source_manifest.write_text(json.dumps(self.source, indent=2))
        self.candidate = {'schemaVersion': 1,
                          'baseManifestSha256': bundle.sha(self.source_manifest),
                          'patches': [{'path': 'candidates/zerotier/patches/0005-fixture.patch',
                                       'sha256': hashlib.sha256(b'candidate patch').hexdigest()}],
                          'copies': [], 'validationFiles': [], 'beforeFiles': {}, 'afterFiles': {}}
        self.candidate_manifest = self.path / 'zerotier-candidate.json'
        self.candidate_manifest.write_text(json.dumps(self.candidate, indent=2))
        self.library = self.out / android_zerotier.LIBRARY
        self.library.write_bytes(b'\x7fELF\x02\x01' + bytes(10) + struct.pack('<HH', 3, 183))
        materials = self.out / 'zerotier' / 'materials'
        candidate = self.out / 'zerotier' / 'candidate'
        materials.mkdir(parents=True)
        candidate.mkdir(parents=True)
        (materials / 'libzt.tar.gz').write_bytes(b'libzt tarball')
        (materials / '0001-fixture.patch').write_bytes(b'upstream patch')
        (materials / 'sources.lock').write_bytes(self.lock)
        (candidate / '0005-fixture.patch').write_bytes(b'candidate patch')
        shutil.copy2(self.source_manifest, self.out / 'zerotier' / 'source-manifest.json')
        (self.out / 'zerotier' / 'prepared-source.json').write_text('{}')
        (self.out / 'zerotier' / 'candidate-source.json').write_text('{}')
        shutil.copy2(self.candidate_manifest, self.out / 'zerotier' / 'candidate-manifest.json')
        self.record = {'library': android_zerotier.LIBRARY, 'abi': android_zerotier.ABI,
                       'api': android_zerotier.API, 'ndk': android_zerotier.NDK_VERSION,
                       'cmakeSha256': android_zerotier.CMAKE_SHA256,
                       'sourceManifestSha256': bundle.sha(self.source_manifest),
                       'candidateManifestSha256': bundle.sha(self.candidate_manifest),
                       'translationUnits': 1, 'androidBuild': 'passed',
                       'androidLoad': 'not run', 'node': 'not run'}
        self.write_manifest()

    def write_manifest(self):
        files = {p.relative_to(self.out).as_posix(): bundle.sha(p)
                 for p in sorted(self.out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
        manifest = {'schemaVersion': 3, 'provider': 'zerotier', 'sourceCommit': self.commit,
                    'abi': 'arm64-v8a', 'api': 35, 'ndk': android_zerotier.NDK_VERSION,
                    'files': files, 'zerotier': self.record}
        (self.out / 'manifest.json').write_text(json.dumps(manifest, indent=2))

    def pinned(self):
        return mock.patch.object(android_zerotier.zerotier_candidate, 'MANIFEST', self.source_manifest), \
               mock.patch.object(android_zerotier.zerotier_candidate, 'CANDIDATE', self.candidate_manifest)

    def test_standalone_artifact_verifies_and_rejects_tampering(self):
        manifest_patch, candidate_patch = self.pinned()
        with manifest_patch, candidate_patch, mock.patch.object(bundle, 'elf') as inspect:
            self.assertEqual(bundle.verify(self.out, self.commit, 'readelf')['provider'], 'zerotier')
            inspect.assert_called_once_with(
                self.out / android_zerotier.LIBRARY,
                'readelf',
                (*android_zerotier.SYMBOLS, *android_zerotier.BOUND_SYMBOLS),
            )
            inspect.reset_mock()
            with self.assertRaisesRegex(ValueError, 'source commit mismatch'):
                bundle.verify(self.out, 'd' * 40, 'readelf')
            manifest = json.loads((self.out / 'manifest.json').read_text())
            manifest['api'] = 34
            (self.out / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'ABI/API mismatch'):
                bundle.verify(self.out, self.commit, 'readelf')
            manifest['api'] = 35
            (self.out / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'artifact hash mismatch'):
                self.library.write_bytes(b'tampered')
                bundle.verify(self.out, self.commit, 'readelf')
            self.library.write_bytes(b'\x7fELF\x02\x01' + bytes(10) + struct.pack('<HH', 3, 183))
            material = self.out / 'zerotier' / 'materials' / 'libzt.tar.gz'
            material.write_bytes(b'forged tarball')
            self.write_manifest()
            with self.assertRaisesRegex(ValueError, 'source material mismatch'):
                bundle.verify(self.out, self.commit, 'readelf')
            material.write_bytes(b'libzt tarball')
            self.write_manifest()
            (self.out / 'zerotier' / 'prepared-source.json').unlink()
            self.write_manifest()
            with self.assertRaisesRegex(ValueError, 'build material missing'):
                bundle.verify(self.out, self.commit, 'readelf')
            (self.out / 'zerotier' / 'prepared-source.json').write_text('{}')
            self.write_manifest()
            self.record['ndk'] = '27.0.0'
            self.write_manifest()
            with self.assertRaisesRegex(ValueError, 'provenance mismatch'):
                bundle.verify(self.out, self.commit, 'readelf')

    def test_standalone_artifact_is_not_an_apk_provider_bundle(self):
        apk = self.path / 'app.apk'
        with zipfile.ZipFile(apk, 'w') as archive:
            archive.writestr('lib/arm64-v8a/libherdr_flutter_network_runtime.so', b'bridge')
        with mock.patch.object(bundle, 'verify', return_value={'provider': 'zerotier'}):
            with self.assertRaisesRegex(ValueError, 'standalone ZeroTier artifact'):
                bundle.apk(apk, self.out, self.commit, 'readelf', 'flutter')


class NativeBundleSchemaTests(unittest.TestCase):
    """The existing full bundle schema rules must stay intact."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        native = ROOT / 'validation/native'
        for name in ['upstream-sources.lock', 'Heeler-Cargo.lock', 'reference-source.tar',
                     'easytier-source.tar', 'build-details.json']:
            (self.path / name).write_bytes(b'fixture')
        shutil.copy2(native / 'sources.json', self.path / 'sources.json')
        shutil.copy2(native / 'patches/portable-manifest.json', self.path / 'candidate-provenance.json')
        shutil.copytree(native / 'patches', self.path / 'patches')
        shutil.copytree(native / 'portable-stream', self.path / 'portable-stream')
        (self.path / 'libheeler_easytier.so').write_bytes(
            b'\x7fELF\x02\x01' + bytes(10) + struct.pack('<HH', 3, 183))
        self.manifest = {}
        self.write_manifest()

    def write_manifest(self):
        native = ROOT / 'validation/native'
        files = {p.relative_to(self.path).as_posix(): bundle.sha(p)
                 for p in sorted(self.path.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
        manifest = {'sourceCommit': 'a' * 40, 'abi': 'arm64-v8a', 'api': 35,
                    'sourcesSha256': bundle.sha(native / 'sources.json'),
                    'patchManifestSha256': bundle.sha(native / 'patches/portable-manifest.json'),
                    'files': files}
        manifest.update(self.manifest)
        (self.path / 'manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_provider_manifest_and_schema_must_agree(self):
        with mock.patch.object(bundle, 'elf'):
            self.assertEqual(bundle.verify(self.path, 'a' * 40, 'readelf')['abi'], 'arm64-v8a')
            self.manifest = {'schemaVersion': 1, 'tailscale': {}}
            self.write_manifest()
            with self.assertRaisesRegex(ValueError, 'Tailscale manifest/provider mismatch'):
                bundle.verify(self.path, 'a' * 40, 'readelf')
            self.manifest = {'schemaVersion': 2}
            self.write_manifest()
            with self.assertRaisesRegex(ValueError, 'Tailscale manifest/provider mismatch'):
                bundle.verify(self.path, 'a' * 40, 'readelf')
            self.manifest = {'schemaVersion': 2, 'zerotier': {}}
            self.write_manifest()
            with self.assertRaisesRegex(ValueError, 'ZeroTier manifest/provider mismatch'):
                bundle.verify(self.path, 'a' * 40, 'readelf')
            self.manifest = {'schemaVersion': 3}
            self.write_manifest()
            with self.assertRaisesRegex(ValueError, 'ZeroTier manifest/provider mismatch'):
                bundle.verify(self.path, 'a' * 40, 'readelf')
            self.manifest = {'schemaVersion': 4, 'zerotier': {}}
            self.write_manifest()
            with self.assertRaisesRegex(ValueError, 'unsupported native manifest schema'):
                bundle.verify(self.path, 'a' * 40, 'readelf')


if __name__ == '__main__':
    unittest.main()
