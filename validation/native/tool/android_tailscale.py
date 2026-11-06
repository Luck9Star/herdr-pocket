"""Fixed-source Android tsnet artifact. Never loads a library or starts a node."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import zipfile

import tailscale_candidate as candidate

GO_VERSION = '1.27.3'
NDK_VERSION = '28.2.13676358'
LIBRARY = 'libhp_tailscale.so'
JNI_BIND = 'Java_org_herdr_network_AndroidTailscaleConfig_bindNative'
SYMBOLS = ['hp_ts_' + name for name in (
    'abi_version', 'node_new', 'node_start', 'node_status', 'node_begin_login',
    'node_dial', 'node_cancel', 'node_close', 'node_release', 'stream_read',
    'stream_write', 'stream_shutdown_write', 'stream_cancel', 'stream_close', 'stream_release')]


# Bounded independently authenticated source archives; values exceed the fixed
# v1.104.1 module by a wide margin, never depend on the bundle's manifest.
MAX_ENTRIES = 20000
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


def source_name(name, prefix):
    if not name.startswith(prefix) or '\\' in name or '\x00' in name:
        raise ValueError('unsafe source archive path')
    relative = name[len(prefix):]
    parts = relative.split('/')
    if not relative or any(part in ('', '.', '..') for part in parts):
        raise ValueError('unsafe source archive path')
    return relative


def stream_sha(stream, size):
    if size < 0 or size > MAX_FILE_BYTES:
        raise ValueError('source archive file bound')
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        data = stream.read(min(1024 * 1024, remaining))
        if not data:
            raise ValueError('truncated source archive')
        digest.update(data)
        remaining -= len(data)
    if stream.read(1):
        raise ValueError('source archive size mismatch')
    return digest.hexdigest()


def verify_archives(zip_path, tar_path, source, sum_path):
    """Recompute Go x/mod/dirhash.HashZip(Hash1), then match patched tar files."""
    version = source['tailscaleVersion']
    expected_key = 'tailscale.com ' + version
    sums = [line.split() for line in Path(sum_path).read_text().splitlines()]
    expected = [parts[2] for parts in sums if len(parts) == 3 and ' '.join(parts[:2]) == expected_key]
    if len(expected) != 1 or not expected[0].startswith('h1:'):
        raise ValueError('fixed Go sum missing or ambiguous')
    prefix = 'tailscale.com@' + version + '/'
    original = {}
    zip_names = {}
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > MAX_ENTRIES:
            raise ValueError('source zip entry bound')
        for entry in entries:
            name = source_name(entry.filename, prefix)
            mode = (entry.external_attr >> 16) & 0o170000
            if entry.is_dir() or mode not in (0, 0o100000) or name in original:
                raise ValueError('invalid or duplicate source zip entry')
            total += entry.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError('source zip total bound')
            with archive.open(entry) as data:
                sha = stream_sha(data, entry.file_size)
            original[name] = sha
            zip_names[entry.filename] = sha
    h = hashlib.sha256()
    for name in sorted(zip_names, key=lambda value: value.encode('utf-8')):
        h.update((zip_names[name] + '  ' + name + '\n').encode('utf-8'))
    got = 'h1:' + base64.b64encode(h.digest()).decode('ascii')
    if got != expected[0]:
        raise ValueError('fixed upstream Go module h1 mismatch')
    patch = source['source']['path']
    added = 'tsnet/herdr_explicit_auth_test.go'
    if patch not in original or original[patch] != source['source']['sha256'] or added in original:
        raise ValueError('fixed upstream source mismatch')
    expected_files = dict(original)
    expected_files[patch] = source['source']['patchedSha256']
    expected_files[added] = source['patchTests']['sha256']
    expected_dirs = {'tailscale'}
    for name in expected_files:
        parts = name.split('/')[:-1]
        for index in range(1, len(parts) + 1):
            expected_dirs.add('tailscale/' + '/'.join(parts[:index]))
    found = set()
    dirs = set()
    total = 0
    with tarfile.open(tar_path, 'r:gz') as archive:
        for entry in archive:
            if len(found) + len(dirs) >= MAX_ENTRIES:
                raise ValueError('source tar entry bound')
            if entry.isdir():
                directory = entry.name.rstrip('/')
                if directory not in expected_dirs or directory in dirs:
                    raise ValueError('invalid or duplicate source tar directory')
                dirs.add(directory)
                continue
            name = source_name(entry.name, 'tailscale/')
            if not entry.isfile() or name in found or name not in expected_files:
                raise ValueError('invalid or unexpected source tar entry')
            total += entry.size
            if total > MAX_TOTAL_BYTES:
                raise ValueError('source tar total bound')
            data = archive.extractfile(entry)
            if data is None:
                raise ValueError('unreadable source tar entry')
            with data:
                sha = stream_sha(data, entry.size)
            if sha != expected_files[name]:
                raise ValueError('patched source tar content mismatch: ' + name)
            found.add(name)
    if found != expected_files.keys():
        raise ValueError('patched source tar missing entries')


def cross_environment(cache, ndk):
    ndk = Path(ndk).resolve()
    if ndk.name != NDK_VERSION:
        raise ValueError('wrong pinned Android NDK')
    tools = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
    paths = {name: tools / binary for name, binary in {
        'CC': 'aarch64-linux-android35-clang',
        'CXX': 'aarch64-linux-android35-clang++', 'AR': 'llvm-ar',
    }.items()}
    if any(not path.is_file() for path in paths.values()):
        raise ValueError('existing pinned Linux Android toolchain required')
    go, env = candidate.environment(cache)
    env.update({name: str(path) for name, path in paths.items()})
    env.update(GOOS='android', GOARCH='arm64', CGO_ENABLED='1')
    return go, env


def build(bundle, work, cache, ndk):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Android native candidate build is CI-only')
    go, env = cross_environment(cache, ndk)
    candidate.prepare(work, cache)
    # Run synthetic host tests with the sanitized host environment. Android
    # output below is inspected only, never executed by the Linux runner.
    candidate.check_or_build(work, cache, False)
    source = candidate.verify_sources()
    candidate.verify_candidate(work, source)
    version_log = work / 'logs/android-go-version.log'
    candidate.run([go, 'version'], work, env, version_log, 30)
    if version_log.read_text().split()[2] != 'go' + GO_VERSION:
        raise ValueError('wrong pinned Go compiler')
    candidate.run([go, 'build', '-trimpath', '-buildmode=c-shared',
                   '-ldflags=-linkmode=external -extldflags=-Wl,-soname,libhp_tailscale.so,-z,max-page-size=16384',
                   '-o', bundle / LIBRARY, '.'], work, env, work / 'logs/android-build.log')
    source_dir = bundle / 'tailscale'
    source_dir.mkdir()
    for name in ('candidate-source.json', 'module-sources.json'):
        shutil.copy2(work / name, source_dir / name)
    for item in candidate.module_files():
        target = source_dir / 'module' / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate.MODULE / item['path'], target)
    shutil.copy2(candidate.NATIVE / source['patch']['path'], source_dir / 'explicit-auth.patch')
    shutil.copy2(candidate.NATIVE / source['patchTests']['path'], source_dir / 'explicit-auth-test.go')
    # Include the exact Go-authenticated module archive, not just a mutable
    # extracted tarball or a self-authored manifest digest.
    downloaded = json.loads((work / 'logs/module-download.json').read_text())
    expected_zip = Path(cache).resolve() / 'modules/cache/download/tailscale.com/@v' / (source['tailscaleVersion'] + '.zip')
    if (downloaded.get('Path') != 'tailscale.com' or downloaded.get('Version') != source['tailscaleVersion']
            or Path(downloaded.get('Zip', '')).resolve() != expected_zip or expected_zip.is_symlink() or not expected_zip.is_file()):
        raise ValueError('unexpected fixed Go module zip')
    shutil.copy2(expected_zip, source_dir / 'upstream-source.zip')
    # Fixed upstream, including license files and our explicit-auth patch.
    with tarfile.open(source_dir / 'upstream-source.tar.gz', 'w:gz') as archive:
        archive.add(work / 'upstream/tailscale', arcname='tailscale')
    shutil.copytree(work / 'logs', source_dir / 'logs')
    return {'library': LIBRARY, 'go': GO_VERSION, 'ndk': NDK_VERSION,
            'sourceManifestSha256': candidate.digest(candidate.MANIFEST),
            'moduleSources': candidate.module_files(),
            'hostTests': 'passed', 'androidBuild': 'passed',
            'androidLoad': 'not run', 'node': 'not run'}


def verify(bundle, record, files, readelf, inspect):
    source = candidate.verify_sources()
    if (record.get('library') != LIBRARY or record.get('go') != GO_VERSION
            or record.get('ndk') != NDK_VERSION
            or record.get('sourceManifestSha256') != candidate.digest(candidate.MANIFEST)
            or record.get('moduleSources') != candidate.module_files()):
        raise ValueError('Tailscale source/toolchain provenance mismatch')
    expected = {'tailscale/candidate-source.json': source,
                'tailscale/module-sources.json': candidate.module_files()}
    for path, value in expected.items():
        if path not in files or json.loads((bundle / path).read_text()) != value:
            raise ValueError('Tailscale source record mismatch: ' + path)
    materials = {'tailscale/explicit-auth.patch': source['patch']['sha256'],
                 'tailscale/explicit-auth-test.go': source['patchTests']['sha256']}
    materials.update({'tailscale/module/' + item['path']: item['sha256']
                      for item in candidate.module_files()})
    for name, sha in materials.items():
        if files.get(name) != sha:
            raise ValueError('Tailscale source material mismatch: ' + name)
    for path in (LIBRARY, 'libhp_tailscale.h', 'tailscale/upstream-source.zip', 'tailscale/upstream-source.tar.gz',
                 'tailscale/logs/android-go-version.log', 'tailscale/logs/android-build.log',
                 'tailscale/logs/runtime-tests.log', 'tailscale/logs/explicit-auth-test.log'):
        if path not in files:
            raise ValueError('Tailscale build material missing: ' + path)
    verify_archives(bundle / 'tailscale/upstream-source.zip', bundle / 'tailscale/upstream-source.tar.gz', source, candidate.MODULE / 'go.sum')
    inspect(bundle / LIBRARY, readelf, SYMBOLS)
