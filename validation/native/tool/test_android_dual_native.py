"""Offline counterexamples; no Android runtime, compiler or network claim."""
import copy
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import android_bundle as bundle
import android_tailscale as ts
import android_targets as targets


class DualNativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_x86_uses_android_amd64_compiler_without_arm_fallback(self):
        ndk = self.root / targets.NDK
        directory = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
        directory.mkdir(parents=True)
        for name in ('x86_64-linux-android35-clang', 'x86_64-linux-android35-clang++', 'llvm-ar'):
            (directory / name).touch()
        _, env = ts.cross_environment(self.root / 'cache', ndk, 'x86_64')
        self.assertEqual((env['GOOS'], env['GOARCH']), ('android', 'amd64'))
        self.assertEqual(env['CC'], str((directory / 'x86_64-linux-android35-clang').resolve()))
        rust = targets.rust_environment(ndk, 'x86_64')
        self.assertEqual(rust['CARGO_TARGET_X86_64_LINUX_ANDROID_LINKER'], env['CC'])
        with self.assertRaisesRegex(ValueError, 'toolchain'):
            ts.cross_environment(self.root / 'cache', ndk)
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            targets.target('host')

    def test_explicit_elf_arch_exports_and_android_dependencies(self):
        library = self.root / 'lib.so'
        library.write_bytes(b'\x7fELF\x02\x01' + bytes(10) + struct.pack('<HH', 3, 62))
        dynamic = ' (NEEDED) Shared library: [libc.so]\n'
        symbols = ' 1: 000000000001 12 FUNC GLOBAL DEFAULT 12 hp_ts_abi_version\n'
        with mock.patch.object(bundle.subprocess, 'check_output', side_effect=[dynamic, symbols]):
            self.assertEqual(bundle.elf(library, 'readelf', ['hp_ts_abi_version'], abi='x86_64'), ['libc.so'])
        with self.assertRaisesRegex(ValueError, 'arm64'):
            bundle.elf(library, 'readelf')
        with mock.patch.object(bundle.subprocess, 'check_output', return_value=dynamic + ' (NEEDED) Shared library: [libc.so.6]\n'):
            with self.assertRaisesRegex(ValueError, 'DT_NEEDED'):
                bundle.elf(library, 'readelf', abi='x86_64')
        with mock.patch.object(bundle.subprocess, 'check_output', side_effect=[dynamic, symbols.replace('DEFAULT 12', 'DEFAULT UND')]):
            with self.assertRaisesRegex(ValueError, 'symbols missing'):
                bundle.elf(library, 'readelf', ['hp_ts_abi_version'], abi='x86_64')

    def test_manifest_does_not_select_abi_implicitly(self):
        (self.root / 'manifest.json').write_text(json.dumps({'sourceCommit': 'a' * 40, 'abi': 'x86_64', 'api': 35}))
        with self.assertRaisesRegex(ValueError, 'ABI/API'):
            bundle.verify(self.root, 'a' * 40, 'readelf')

    def test_unvalidated_zerotier_and_incomplete_bridge_fail_before_mutation(self):
        for options in ({'abi': 'x86_64', 'zerotier': True}, {'abi': 'x86_64', 'bridge': True}):
            out = self.root / 'unused'
            with mock.patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}), self.assertRaises(ValueError):
                bundle.build(out, **options)
            self.assertFalse(out.exists())

    def test_bridge_requires_both_real_provider_libraries_and_current_sources(self):
        sources = bundle.bridge_sources()
        files = {'bridge-source/' + name: digest for name, digest in sources.items()}
        files[bundle.BRIDGE] = 'a' * 64
        record = {'library': bundle.BRIDGE, 'rust': '1.96.0', 'abi': 'x86_64',
                  'features': bundle.BRIDGE_FEATURES, 'sources': sources}
        with mock.patch.object(bundle, 'elf') as inspect:
            bundle.verify_bridge(self.root, record, files, 'readelf', 'x86_64')
            self.assertEqual(inspect.call_args.kwargs['needed'], ['libheeler_easytier.so', 'libhp_tailscale.so'])
            self.assertEqual(inspect.call_args.kwargs['abi'], 'x86_64')
        for key, value in [('abi', 'arm64-v8a'), ('features', ['native-fixture']), ('sources', {})]:
            bad = copy.deepcopy(record); bad[key] = value
            with self.assertRaisesRegex(ValueError, 'provenance'):
                bundle.verify_bridge(self.root, bad, files, 'readelf', 'x86_64')
        files.pop(next(name for name in files if name.startswith('bridge-source/')))
        with self.assertRaisesRegex(ValueError, 'source material'):
            bundle.verify_bridge(self.root, record, files, 'readelf', 'x86_64')

    def test_workflow_is_separate_opt_in_and_builds_no_app(self):
        text = (bundle.ROOT / '.github/workflows/android-dual-overlay-native.yml').read_text()
        self.assertIn("branches: ['codex/acceptance-android-dual-native/**']", text)
        self.assertIn('--abi x86_64 --tailscale --bridge --release', text)
        for forbidden in ('acceptance-dual-overlay/**', 'flutter build', 'tauri --', 'emulator -avd', 'adb install'):
            self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main()
