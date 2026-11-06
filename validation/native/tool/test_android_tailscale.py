"""Offline provenance/packaging counterexamples. No compiler, library load or network."""
import hashlib
import io
import tarfile
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile

import android_bundle as bundle
import android_tailscale as ts
import tailscale_candidate as candidate


class AndroidTailscaleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='android-ts-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ndk = self.root / ts.NDK_VERSION
        tools = self.ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
        tools.mkdir(parents=True)
        for name in ('aarch64-linux-android35-clang', 'aarch64-linux-android35-clang++', 'llvm-ar'):
            (tools / name).write_bytes(b'synthetic; never executed')

    def test_pinned_ndk_api35_and_environment_excludes_ambient_credentials(self):
        hostile = {'TS_AUTHKEY': 'synthetic-do-not-print', 'AWS_SECRET_ACCESS_KEY': 'synthetic',
                   'HOME': '/not-used', 'GOFLAGS': '-overlay=bad', 'GOPROXY': 'https://bad.invalid',
                   'GOENV': '/bad', 'PATH': '/untrusted'}
        with mock.patch.dict(os.environ, hostile, clear=True), mock.patch.object(candidate.shutil, 'which', return_value='/synthetic/go'):
            go, env = ts.cross_environment(self.root / 'cache', self.ndk)
        self.assertEqual(go, '/synthetic/go')
        self.assertEqual((env['GOOS'], env['GOARCH'], env['CGO_ENABLED']), ('android', 'arm64', '1'))
        self.assertTrue(env['CC'].endswith('/aarch64-linux-android35-clang'))
        self.assertTrue(env['CXX'].endswith('/aarch64-linux-android35-clang++'))
        self.assertTrue(env['AR'].endswith('/llvm-ar'))
        for name in ('TS_AUTHKEY', 'AWS_SECRET_ACCESS_KEY', 'HOME'):
            self.assertNotIn(name, env)
        self.assertEqual(env['GOENV'], 'off')
        self.assertEqual(env['GOFLAGS'], '-mod=readonly')
        self.assertNotIn('bad.invalid', env['GOPROXY'])
        with self.assertRaisesRegex(ValueError, 'pinned'):
            ts.cross_environment(self.root / 'cache', self.root / 'wrong-version')
        (self.ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang').unlink()
        with self.assertRaisesRegex(ValueError, 'toolchain'):
            ts.cross_environment(self.root / 'cache', self.ndk)

    def test_build_ci_guard_precedes_toolchain_and_mutation(self):
        for setting in (None, 'false', 'TRUE', '1'):
            env = {} if setting is None else {'GITHUB_ACTIONS': setting}
            with self.subTest(setting=setting), mock.patch.dict(os.environ, env, clear=True), mock.patch.object(ts, 'cross_environment') as cross:
                with self.assertRaisesRegex(ValueError, 'CI-only'):
                    ts.build(self.root / 'bundle', self.root / 'work', self.root / 'cache', self.ndk)
                cross.assert_not_called()
            self.assertFalse((self.root / 'bundle').exists())

    def make_source_record(self):
        source = candidate.verify_sources()
        modules = candidate.module_files()
        def write(name, data):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        write('tailscale/candidate-source.json', json.dumps(source).encode())
        write('tailscale/module-sources.json', json.dumps(modules).encode())
        for item in modules:
            write('tailscale/module/' + item['path'], (candidate.MODULE / item['path']).read_bytes())
        write('tailscale/explicit-auth.patch', (candidate.NATIVE / source['patch']['path']).read_bytes())
        write('tailscale/explicit-auth-test.go', (candidate.NATIVE / source['patchTests']['path']).read_bytes())
        for name in (ts.LIBRARY, 'libhp_tailscale.h', 'tailscale/upstream-source.zip', 'tailscale/upstream-source.tar.gz',
                     'tailscale/logs/android-go-version.log', 'tailscale/logs/android-build.log',
                     'tailscale/logs/runtime-tests.log', 'tailscale/logs/explicit-auth-test.log'):
            write(name, b'synthetic fixture')
        files = {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob('*') if p.is_file() and not p.is_relative_to(self.ndk)}
        record = {'library': ts.LIBRARY, 'go': ts.GO_VERSION, 'ndk': ts.NDK_VERSION,
                  'sourceManifestSha256': candidate.digest(candidate.MANIFEST), 'moduleSources': modules}
        return source, modules, files, record

    def test_source_records_reject_missing_forged_and_metadata_drift(self):
        source, modules, files, record = self.make_source_record()
        with mock.patch.object(ts.candidate, 'verify_sources', return_value=source), mock.patch.object(ts, 'verify_archives'):
            inspect = mock.Mock()
            ts.verify(self.root, record, files, 'synthetic-readelf', inspect)
            inspect.assert_called_once_with(self.root / ts.LIBRARY, 'synthetic-readelf', ts.SYMBOLS)
            targets = ['tailscale/explicit-auth.patch', 'tailscale/explicit-auth-test.go']
            targets += ['tailscale/module/' + x['path'] for x in modules]
            for name in targets:
                for replacement in (None, '0' * 64):
                    bad = dict(files)
                    if replacement is None:
                        del bad[name]
                    else:
                        bad[name] = replacement
                    with self.subTest(material=name, replacement=replacement), self.assertRaises(ValueError):
                        ts.verify(self.root, record, bad, 'synthetic-readelf', mock.Mock())
            for key in ('go', 'ndk', 'sourceManifestSha256', 'moduleSources'):
                bad = dict(record); bad[key] = [] if key == 'moduleSources' else 'forged'
                with self.subTest(metadata=key), self.assertRaises(ValueError):
                    ts.verify(self.root, bad, files, 'synthetic-readelf', mock.Mock())
            for name in ('tailscale/candidate-source.json', 'tailscale/module-sources.json'):
                path = self.root / name; original = path.read_bytes()
                try:
                    path.write_text('{}')
                    with self.subTest(record=name), self.assertRaisesRegex(ValueError, 'record mismatch'):
                        ts.verify(self.root, record, files, 'synthetic-readelf', mock.Mock())
                finally: path.write_bytes(original)
            for name in ('tailscale/upstream-source.zip', 'tailscale/upstream-source.tar.gz'):
                bad = dict(files); del bad[name]
                with self.subTest(archive=name), self.assertRaisesRegex(ValueError, 'material missing'):
                    ts.verify(self.root, record, bad, 'synthetic-readelf', mock.Mock())

    def test_build_copies_only_prepared_fixed_module_zip_without_execution(self):
        cache = self.root / 'cache'
        zip_path = cache / 'modules/cache/download/tailscale.com/@v/v1.104.1.zip'
        zip_path.parent.mkdir(parents=True); zip_path.write_bytes(b'original module zip fixture')
        native = self.root / 'native'; native.mkdir()
        (native / 'patch').write_bytes(b'patch'); (native / 'test.go').write_bytes(b'test')
        manifest = self.root / 'manifest'; manifest.write_text('{}')
        source = {'tailscaleVersion':'v1.104.1', 'patch':{'path':'patch'}, 'patchTests':{'path':'test.go'}}
        work = self.root / 'work'; output = self.root / 'bundle'; output.mkdir()
        def prepare(path, _cache):
            path.mkdir(); (path / 'logs').mkdir(); (path / 'upstream/tailscale').mkdir(parents=True)
            (path / 'upstream/tailscale/LICENSE').write_bytes(b'fixture')
            (path / 'candidate-source.json').write_text('{}'); (path / 'module-sources.json').write_text('[]')
            (path / 'logs/module-download.json').write_text(json.dumps({'Path':'tailscale.com', 'Version':'v1.104.1', 'Zip':str(zip_path)}))
        def run(args, _cwd, _env, log, _timeout=1200):
            Path(log).write_text('go version go1.27.3 synthetic\n' if args[1] == 'version' else 'synthetic build')
        with mock.patch.dict(os.environ, {'GITHUB_ACTIONS':'true'}, clear=True), \
             mock.patch.object(ts, 'cross_environment', return_value=('/synthetic/go', {})), \
             mock.patch.object(candidate, 'prepare', side_effect=prepare), \
             mock.patch.object(candidate, 'check_or_build'), \
             mock.patch.object(candidate, 'verify_sources', return_value=source), \
             mock.patch.object(candidate, 'verify_candidate'), \
             mock.patch.object(candidate, 'run', side_effect=run), \
             mock.patch.object(candidate, 'module_files', return_value=[]), \
             mock.patch.object(candidate, 'NATIVE', native), mock.patch.object(candidate, 'MANIFEST', manifest):
            result = ts.build(output, work, cache, self.ndk)
        self.assertEqual((output / 'tailscale/upstream-source.zip').read_bytes(), zip_path.read_bytes())
        self.assertEqual(result['library'], ts.LIBRARY)
        self.assertEqual(result['node'], 'not run')

    def test_authenticated_zip_and_patched_tar_reject_all_source_drift(self):
        import warnings
        original = {'LICENSE': b'license', 'tsnet/tsnet.go': b'upstream'}
        patched = {'LICENSE': b'license', 'tsnet/tsnet.go': b'patched',
                   'tsnet/herdr_explicit_auth_test.go': b'test-patch'}
        digest = lambda value: hashlib.sha256(value).hexdigest()
        source = {'tailscaleVersion': 'v1.104.1',
                  'source': {'path': 'tsnet/tsnet.go', 'sha256': digest(b'upstream'), 'patchedSha256': digest(b'patched')},
                  'patchTests': {'sha256': digest(b'test-patch')}}
        sums = self.root / 'go.sum'
        sums.write_text('tailscale.com v1.104.1 h1:FSpDPqFJkqB1md3PsjAgO403gq8jLFY5mKbLPKNRfh0=\n')
        zip_path, tar_path = self.root / 'source.zip', self.root / 'source.tar.gz'
        def write_zip(entries, extra=None):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(zip_path, 'w') as out:
                    for name, value in entries: out.writestr('tailscale.com@v1.104.1/' + name, value)
                    if extra is not None: out.writestr(extra[0], extra[1])
        def write_tar(entries, extra=None):
            with tarfile.open(tar_path, 'w:gz') as out:
                for name, value in entries:
                    info = tarfile.TarInfo('tailscale/' + name); info.size = len(value)
                    out.addfile(info, io.BytesIO(value))
                if extra is not None:
                    info = tarfile.TarInfo(extra[0]); info.type = extra[1]; info.linkname = extra[2]
                    out.addfile(info)
        write_zip(original.items()); write_tar(patched.items())
        ts.verify_archives(zip_path, tar_path, source, sums)
        for name in patched:
            with self.subTest(kind='missing', path=name):
                write_tar([(k,v) for k,v in patched.items() if k != name])
                with self.assertRaises(ValueError): ts.verify_archives(zip_path, tar_path, source, sums)
            with self.subTest(kind='forged', path=name):
                write_tar([(k, b'forged' if k == name else v) for k,v in patched.items()])
                with self.assertRaises(ValueError): ts.verify_archives(zip_path, tar_path, source, sums)
        for extra in [('tailscale/unexpected', tarfile.REGTYPE, ''), ('tailscale/unexpected', tarfile.DIRTYPE, ''),
                      ('tailscale/link', tarfile.SYMTYPE, '../../outside'), ('tailscale/link', tarfile.LNKTYPE, 'tailscale/LICENSE'),
                      ('tailscale/../outside', tarfile.REGTYPE, '')]:
            write_tar(patched.items(), extra)
            with self.subTest(kind='tar-extra', path=extra[0], type=extra[1]), self.assertRaises(ValueError):
                ts.verify_archives(zip_path, tar_path, source, sums)
        write_tar(list(patched.items()) + [('LICENSE', b'license')])
        with self.assertRaises(ValueError):
            ts.verify_archives(zip_path, tar_path, source, sums)
        write_tar(patched.items())
        write_zip([('LICENSE',b'altered'),('tsnet/tsnet.go',b'upstream')])
        with self.assertRaisesRegex(ValueError, 'h1 mismatch'):
            ts.verify_archives(zip_path, tar_path, source, sums)
        write_zip(list(original.items()) + [('LICENSE',b'license')])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            ts.verify_archives(zip_path, tar_path, source, sums)
        write_zip(original.items(), ('tailscale.com@v1.104.1/../outside', b'bad'))
        with self.assertRaisesRegex(ValueError, 'path'):
            ts.verify_archives(zip_path, tar_path, source, sums)
        with zipfile.ZipFile(zip_path, 'w') as out:
            for name, value in original.items():
                info = zipfile.ZipInfo('tailscale.com@v1.104.1/' + name)
                if name == 'LICENSE': info.create_system = 3; info.external_attr = 0o120777 << 16
                out.writestr(info, value)
        with self.assertRaisesRegex(ValueError, 'zip entry'):
            ts.verify_archives(zip_path, tar_path, source, sums)
        write_zip(original.items())
        sums.write_text('tailscale.com v1.104.1 h1:forged\n')
        with self.assertRaisesRegex(ValueError, 'h1 mismatch'):
            ts.verify_archives(zip_path, tar_path, source, sums)
        sums.write_text('tailscale.com v1.104.1 h1:x\ntailscale.com v1.104.1 h1:y\n')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            ts.verify_archives(zip_path, tar_path, source, sums)

    def test_dual_provider_apk_requires_exact_both_libraries_symbols_and_dependencies(self):
        elf = b'\x7fELF\x02\x01' + bytes(10) + struct.pack('<HH', 3, 183)
        (self.root / 'libheeler_easytier.so').write_bytes(elf + b'et')
        (self.root / ts.LIBRARY).write_bytes(elf + b'ts')
        for app, app_lib, required in (
            ('flutter', 'libherdr_flutter_network_runtime.so', bundle.FLUTTER_JNI),
            ('tauri', 'libherdr_pocket_tauri_probe_lib.so', [bundle.BIND_NATIVE]),
        ):
            apk = self.root / (app + '.apk')
            dependencies = {'libheeler_easytier.so', ts.LIBRARY}
            symbols = set(required) | {ts.JNI_BIND}
            def create(et=None, tailscale=None, include_et=True, include_ts=True):
                with zipfile.ZipFile(apk, 'w') as archive:
                    if include_et: archive.writestr('lib/arm64-v8a/libheeler_easytier.so', et if et is not None else (self.root / 'libheeler_easytier.so').read_bytes())
                    if include_ts: archive.writestr('lib/arm64-v8a/' + ts.LIBRARY, tailscale if tailscale is not None else (self.root / ts.LIBRARY).read_bytes())
                    archive.writestr('lib/arm64-v8a/' + app_lib, elf + b'app')
            def readelf(command, **_kwargs):
                if '-d' in command:
                    return ''.join(' (NEEDED) Shared library: [' + dep + ']\n' for dep in dependencies) if command[-1].endswith(app_lib) else ''
                return ''.join(f' {i}: 0000000000000100 16 FUNC GLOBAL DEFAULT 12 {symbol}\n' for i, symbol in enumerate(sorted(symbols)))
            with self.subTest(app=app), mock.patch.object(bundle, 'verify', return_value={'tailscale': {}}), mock.patch.object(bundle.subprocess, 'check_output', side_effect=readelf):
                create(); bundle.apk(apk, self.root, 'a' * 40, 'synthetic-readelf', app)
                for missing in ('et', 'ts'):
                    create(include_et=missing != 'et', include_ts=missing != 'ts')
                    with self.assertRaisesRegex(ValueError, 'missing or duplicate'):
                        bundle.apk(apk, self.root, 'a' * 40, 'synthetic-readelf', app)
                for field in ('et', 'tailscale'):
                    create(**{field: b'changed'})
                    with self.assertRaisesRegex(ValueError, 'differs'):
                        bundle.apk(apk, self.root, 'a' * 40, 'synthetic-readelf', app)
                create(); symbols.remove(ts.JNI_BIND)
                with self.assertRaisesRegex(ValueError, 'exported symbols'):
                    bundle.apk(apk, self.root, 'a' * 40, 'synthetic-readelf', app)
                symbols.add(ts.JNI_BIND)
                for missing in tuple(dependencies):
                    dependencies.remove(missing)
                    with self.subTest(missing_needed=missing), self.assertRaisesRegex(ValueError, 'DT_NEEDED'):
                        bundle.apk(apk, self.root, 'a' * 40, 'synthetic-readelf', app)
                    dependencies.add(missing)

if __name__ == '__main__':
    unittest.main()
