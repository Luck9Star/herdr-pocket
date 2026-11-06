#!/usr/bin/env python3
"""Build and verify the explicitly requested Android candidate; never load it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
SYMBOLS = ['heeler_et_stream_connect', 'heeler_et_stream_read', 'heeler_et_stream_write',
           'heeler_et_stream_shutdown_write', 'heeler_et_stream_close', 'heeler_et_node_start',
           'heeler_et_node_status', 'heeler_et_node_stop', 'heeler_et_node_stream_connect']
BIND_NATIVE = 'Java_org_herdr_network_AndroidEasyTierConfig_bindNative'
FLUTTER_JNI = [BIND_NATIVE] + [
    'Java_dev_herdr_pocket_NetworkRuntimeChannel_' + name
    for name in ('nativeCreateScope', 'nativeReserveOpen', 'nativeCall', 'nativeCloseScope')
]
SYSTEM = {'libc.so', 'libm.so', 'libdl.so', 'liblog.so', 'libandroid.so', 'libz.so',
          'libjnigraphics.so', 'libEGL.so', 'libGLESv2.so', 'libOpenSLES.so', 'libvulkan.so', 'libstdc++.so'}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def elf(path, readelf, required=(), needed=(), allowed=()):
    header = path.read_bytes()[:20]
    if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', header, 16) != (3, 183):
        raise ValueError('expected little-endian AArch64 ELF shared library')
    dynamic = subprocess.check_output([readelf, '-d', str(path)], text=True)
    dependencies = set(re.findall(r'\(NEEDED\).*?\[([^]]+)\]', dynamic))
    if not set(needed) <= dependencies or dependencies - SYSTEM - set(needed) - set(allowed):
        raise ValueError('unexpected or missing DT_NEEDED: ' + str(sorted(dependencies)))
    if required:
        symbols = subprocess.check_output([readelf, '--dyn-syms', '--wide', str(path)], text=True)
        found = {line.split()[-1].split('@')[0] for line in symbols.splitlines()
                 if len(line.split()) >= 8 and line.split()[4] in ('GLOBAL', 'WEAK')
                 and line.split()[5] in ('DEFAULT', 'PROTECTED') and line.split()[6] != 'UND'}
        if not set(required) <= found:
            raise ValueError('required exported symbols missing')
    return sorted(dependencies)

def verify(bundle, commit, readelf):
    manifest = json.loads((bundle / 'manifest.json').read_text())
    if manifest['sourceCommit'] != commit or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('source commit mismatch')
    if manifest['abi'] != 'arm64-v8a' or manifest['api'] != 35:
        raise ValueError('ABI/API mismatch')
    if manifest['sourcesSha256'] != sha(ROOT / 'validation/native/sources.json') or manifest['patchManifestSha256'] != sha(ROOT / 'validation/native/patches/portable-manifest.json'):
        raise ValueError('native sources or patch manifest mismatch')
    files = manifest['files']
    required_files = {'libheeler_easytier.so', 'upstream-sources.lock', 'Heeler-Cargo.lock',
                      'reference-source.tar', 'easytier-source.tar', 'candidate-provenance.json',
                      'sources.json', 'build-details.json'}
    if not required_files <= files.keys():
        raise ValueError('required library or source materials missing')
    for name, digest in files.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('unsafe manifest path')
        path = bundle / relative
        if path.is_symlink() or not path.is_file() or sha(path) != digest:
            raise ValueError('artifact hash mismatch: ' + name)
    expected_sources = ROOT / 'validation/native/sources.json'
    expected_manifest = ROOT / 'validation/native/patches/portable-manifest.json'
    portable = json.loads(expected_manifest.read_text())
    materials = {
        'sources.json': sha(expected_sources),
        'patches/portable-manifest.json': sha(expected_manifest),
        'patches/' + portable['patch']: portable['patchSha256'],
    }
    for group in ('copiedModules', 'sourceTemplates'):
        for name, digest in portable[group].items():
            materials['portable-stream/' + name] = digest
    for name, digest in materials.items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or files.get(name) != digest:
            raise ValueError('missing or mismatched source material: ' + name)
    if json.loads((bundle / 'candidate-provenance.json').read_text()) != portable:
        raise ValueError('candidate provenance mismatch')
    elf(bundle / 'libheeler_easytier.so', readelf, SYMBOLS)
    return manifest

def build(out):
    import portable_candidate as candidate
    base = candidate.base
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Android native candidate build is CI-only')
    out.mkdir(parents=True, exist_ok=False)
    base.OUT = out.resolve()
    base.WORK = Path(os.environ['RUNNER_TEMP']) / ('herdr-android-candidate-' + os.environ['GITHUB_RUN_ID'])
    base.WORK.mkdir()
    base.CURRENT = {'provider': 'easytier-android', 'commands': []}
    reference = base.WORK / 'reference'
    base.checkout(base.CONFIG['reference']['repository'], base.CONFIG['reference']['commit'], reference, 'reference')
    lock = base.lock_values(reference)
    env = base.easytier(reference, lock, check=False)
    candidate.apply(reference)
    ndk = Path(os.environ['ANDROID_HOME']) / 'ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin'
    cc = ndk / 'aarch64-linux-android35-clang'
    env.update({'CC_aarch64_linux_android': str(cc), 'CXX_aarch64_linux_android': str(cc) + '++',
                'AR_aarch64_linux_android': str(ndk / 'llvm-ar'),
                'CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER': str(cc)})
    source = reference / 'native/easytier'
    base.run('android-arm64-build', ['cargo', '+1.95.0', 'build', '--locked', '--lib', '--target', 'aarch64-linux-android'], cwd=source, env=env, timeout=3600)
    library = source / 'target/aarch64-linux-android/debug/libheeler_easytier.so'
    shutil.copy2(library, out / library.name)
    elf(out / library.name, str(ndk / 'llvm-readelf'), SYMBOLS)
    for tree, name in [(reference, 'reference-source.tar'),
                       (reference / 'native/easytier/vendor/easytier', 'easytier-source.tar')]:
        with (out / name).open('wb') as archive:
            subprocess.run(['git', 'archive', '--format=tar', 'HEAD'], cwd=tree, stdout=archive, check=True)
    shutil.copy2(reference / 'sources.lock', out / 'upstream-sources.lock')
    shutil.copy2(source / 'Cargo.lock', out / 'Heeler-Cargo.lock')
    shutil.copytree(ROOT / 'validation/native/portable-stream', out / 'portable-stream')
    shutil.copytree(ROOT / 'validation/native/patches', out / 'patches')
    shutil.copy2(ROOT / 'validation/native/sources.json', out / 'sources.json')
    (out / 'build-details.json').write_text(json.dumps(base.CURRENT, indent=2) + '\n')
    files = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    manifest = {'schemaVersion': 1, 'sourceCommit': os.environ['GITHUB_SHA'], 'abi': 'arm64-v8a', 'api': 35,
                'ndk': '28.2.13676358', 'rust': '1.95.0', 'sourcesSha256': sha(ROOT / 'validation/native/sources.json'),
                'patchManifestSha256': sha(ROOT / 'validation/native/patches/portable-manifest.json'), 'files': files,
                'staticInspection': 'passed', 'androidLoad': 'not run', 'installation': 'not run', 'node': 'not run'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (out / 'SHA256SUMS').write_text(''.join(f'{v}  {k}\n' for k, v in files.items()))
    verify(out, os.environ['GITHUB_SHA'], str(ndk / 'llvm-readelf'))

def apk(path, bundle, commit, readelf, app):
    verify(bundle, commit, readelf)
    app_lib = {'flutter': 'libherdr_flutter_network_runtime.so', 'tauri': 'libherdr_pocket_tauri_probe_lib.so'}[app]
    with zipfile.ZipFile(path) as archive:
        libs = [x for x in archive.namelist() if x.startswith('lib/') and x.endswith('.so')]
        if any(not x.startswith('lib/arm64-v8a/') for x in libs):
            raise ValueError('APK contains another ABI')
        for name in ['libheeler_easytier.so', app_lib]:
            key = 'lib/arm64-v8a/' + name
            if libs.count(key) != 1:
                raise ValueError('missing or duplicate APK library: ' + name)
        if hashlib.sha256(archive.read('lib/arm64-v8a/libheeler_easytier.so')).hexdigest() != sha(bundle / 'libheeler_easytier.so'):
            raise ValueError('APK native library differs from verified bundle')
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            names = [Path(x).name for x in libs]
            if len(names) != len(set(names)):
                raise ValueError('duplicate APK native library')
            for entry in libs:
                name = Path(entry).name
                extracted = Path(directory) / name
                extracted.write_bytes(archive.read(entry))
                needed = ['libheeler_easytier.so'] if name == app_lib else []
                required = (FLUTTER_JNI if app == 'flutter' else [BIND_NATIVE]) if name == app_lib else []
                elf(extracted, readelf, required=required, needed=needed, allowed=set(names) - {name})

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('build'); p.add_argument('bundle', type=Path)
    p = sub.add_parser('verify'); p.add_argument('bundle', type=Path); p.add_argument('--commit', required=True); p.add_argument('--readelf', required=True)
    p = sub.add_parser('report'); p.add_argument('output', type=Path); p.add_argument('--commit', required=True); p.add_argument('--app', choices=['flutter', 'tauri'], required=True)
    p.add_argument('--checks', choices=['success', 'failure', 'cancelled', 'skipped', 'not_run'], default='not_run')
    p.add_argument('--transport-checks', choices=['success', 'failure', 'cancelled', 'skipped', 'not_run'], default='not_run')
    p = sub.add_parser('apk'); p.add_argument('apk', type=Path); p.add_argument('bundle', type=Path); p.add_argument('--commit', required=True); p.add_argument('--readelf', required=True); p.add_argument('--app', choices=['flutter', 'tauri'], required=True)
    a = parser.parse_args()
    if a.command == 'build': build(a.bundle)
    elif a.command == 'verify': verify(a.bundle, a.commit, a.readelf)
    elif a.command == 'report':
        report = {'sourceCommit': a.commit, 'app': a.app, 'abi': 'arm64-v8a', 'api': 35,
                  'sourceChecks': a.checks,
                  'transportChecks': a.transport_checks,
                  'transportChecksScope': 'shared Rust isolated SSH and unit checks; not Android runtime or real overlay',
                  'sourceChecksScope': 'Flutter analyzer, unit/widget, renderer and isolated SSH GUI checks' if a.app == 'flutter' else 'JavaScript unit tests; Rust target compilation is part of build',
                  'apkSha256': sha(a.output / 'app.apk'), 'nativeManifestSha256': sha(a.output / 'native-manifest.json'),
                  'build': 'passed', 'staticInspection': 'passed', 'androidLoad': 'not run',
                  'installation': 'not run', 'node': 'not run'}
        candidate = a.output / 'candidate-manifest.json'
        if candidate.exists():
            report['terminalCandidateManifestSha256'] = sha(candidate)
        (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (a.output / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(a.output.iterdir()) if p.is_file() and p.name != 'SHA256SUMS'))
    else: apk(a.apk, a.bundle, a.commit, a.readelf, a.app)

if __name__ == '__main__': main()
