"""Fixed-source Android ZeroTier artifact. Never loads a library or starts a node.

The pinned libzt fork, ZeroTierOne, lwIP and lwip-contrib sources are prepared
by zerotier_candidate.py and compiled for arm64-v8a with the pinned Android NDK.
The upstream CMake source groups and their compile definitions are mirrored
explicitly, so no CMake, no ambient SDK discovery and no Rust toolchain are
used: the ZeroTier runtime is C++ only. The Rust host binds the exported C ABI
and is built elsewhere.
"""
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import re
import shutil
import subprocess

import zerotier_candidate
import zerotier_macos

NDK_VERSION = '28.2.13676358'
API = 35
ABI = 'arm64-v8a'
LIBRARY = 'libhp_zerotier.so'
# The fixed upstream CMakeLists.txt of the pinned libzt fork.
CMAKE_SHA256 = 'bf7b5801d4a715689a75014f92f317a2ec27d955e801bd856e3d2fde12306602'
# The C ABI the Rust host binds: android-network-source owns the identity and
# device entry points, overlay-runtime owns the manager and stream entry points.
SYMBOLS = [
    'hp_zt_identity_create', 'hp_zt_identity_validate',
    'hp_zt_device_new', 'hp_zt_device_start', 'hp_zt_device_stop', 'hp_zt_device_release',
    'hp_zt_manager_abi_version', 'hp_zt_stream_abi_version',
    'hp_zt_network_join', 'hp_zt_network_status', 'hp_zt_network_leave',
    'hp_zt_stream_new', 'hp_zt_stream_open', 'hp_zt_stream_read', 'hp_zt_stream_write',
    'hp_zt_stream_shutdown_write', 'hp_zt_stream_cancel', 'hp_zt_stream_close',
    'hp_zt_stream_release',
]
REQUIRED_MATERIALS = ('zerotier/source-manifest.json', 'zerotier/prepared-source.json',
                      'zerotier/candidate-source.json', 'zerotier/candidate-manifest.json',
                      'zerotier/materials/sources.lock')
MAX_JOBS = 4


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_blob_sha1(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def toolchain(ndk):
    """Return the pinned NDK C, C++ and readelf binaries for arm64-v8a."""
    ndk = Path(ndk).resolve()
    if ndk.name != NDK_VERSION:
        raise ValueError('wrong pinned Android NDK')
    tools = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
    paths = {'cc': tools / 'aarch64-linux-android35-clang',
             'cxx': tools / 'aarch64-linux-android35-clang++',
             'readelf': tools / 'llvm-readelf'}
    if any(not path.is_file() for path in paths.values()):
        raise ValueError('existing pinned Linux Android toolchain required')
    return paths


def common_flags(kind, include_dirs):
    flags = ['-fPIC', '-fstack-protector']
    for path in include_dirs:
        flags += ['-I', str(path)]
    # Upstream ZT_FLAGS, applied to every source group, plus the C API only
    # build the host links against: the central API would require CURL.
    flags += ['-DZT_SDK=1', '-DZT_USE_MINIUPNPC=1', '-D_USING_LWIP_DEFINITIONS_=0',
              '-DOMIT_JSON_SUPPORT=1', '-Wno-unused-parameter']
    if kind == 'cxx':
        flags += ['-std=c++11', '-Wall', '-Wextra', '-DZTS_DISABLE_CENTRAL_API=1',
                  '-DZTS_C_API_ONLY=1']
    return flags


def group_flags(group):
    if group == 'ztcore':
        # Upstream adds the ARMv8 crypto extensions to the ZeroTierOne core for
        # the arm64-v8a Android ABI.
        return ['-march=armv8-a+crypto']
    if group == 'libzt':
        return []
    if group == 'natpmp':
        return ['-DNATPMP_EXPORTS']
    if group == 'lwip':
        return ['-DLWIP_DBG_TYPES_ON=0',
                '-Wno-tautological-constant-out-of-range-compare',
                '-Wno-parentheses-equality']
    if group == 'miniupnpc':
        # Upstream defines these unconditionally for the position independent
        # miniupnpc target, including on Android. MACOSX and _DARWIN_C_SOURCE
        # are upstream quirks of that target, not a Darwin platform claim.
        return ['-DMACOSX', '-DZT_USE_MINIUPNPC', '-DMINIUPNP_STATICLIB',
                '-D_DARWIN_C_SOURCE', '-DMINIUPNPC_SET_SOCKET_TIMEOUT',
                '-DMINIUPNPC_GET_SRC_ADDR', '-D_BSD_SOURCE', '-D_DEFAULT_SOURCE',
                '-DMINIUPNPC_VERSION_STRING="2.0"',
                '-DUPNP_VERSION_STRING="UPnP/1.1"',
                '-DENABLE_STRNATPMPERR', '-DOS_STRING="Darwin/15.0.0"']
    raise ValueError('unknown CMake source group: ' + group)


def environment(output):
    # Deliberately do not inherit HOME, proxy settings, signing variables or
    # other ambient environment state.
    path = os.environ.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin')
    return {'PATH': path, 'TMPDIR': str(output / 'tmp')}


def upstream_version(source):
    """Read the pinned ZeroTierOne version from the prepared upstream source."""
    text = (Path(source) / 'ext/ZeroTierOne/version.h').read_text()
    values = dict(re.findall(r'#define\s+ZEROTIER_ONE_VERSION_(MAJOR|MINOR|REVISION)\s+(\d+)', text))
    if set(values) != {'MAJOR', 'MINOR', 'REVISION'}:
        raise ValueError('pinned ZeroTierOne version is unreadable')
    return '.'.join(values[key] for key in ('MAJOR', 'MINOR', 'REVISION'))


def compile_one(source, group, output, include_dirs, cc, cxx, env):
    kind = 'cxx' if source.suffix == '.cpp' else 'c'
    compiler = cxx if kind == 'cxx' else cc
    label = group + '-' + hashlib.sha256(str(source).encode()).hexdigest()[:16]
    obj = output / 'objects' / (label + '.o')
    obj.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(compiler)] + common_flags(kind, include_dirs) + group_flags(group)
    argv += ['-c', str(source), '-o', str(obj)]
    log = output / 'logs' / (label + '.log')
    result = subprocess.run(argv, cwd=output, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, check=False)
    log.write_text(result.stdout, encoding='utf-8')
    record = {'source': str(source), 'group': group, 'compiler': str(compiler),
              'argv': argv, 'exitCode': result.returncode, 'log': str(log)}
    return record, (None if result.returncode else obj)


def compile_all(groups, output, source, cc, cxx, env):
    include_dirs = zerotier_macos.includes(source)
    jobs = [(group, path) for group, paths in groups.items() for path in paths]
    records, objects = [], []
    with ThreadPoolExecutor(max_workers=MAX_JOBS) as executor:
        futures = [executor.submit(compile_one, path, group, output, include_dirs, cc, cxx, env)
                   for group, path in jobs]
        for future in as_completed(futures):
            record, obj = future.result()
            records.append(record)
            if obj is not None:
                objects.append(obj)
    records.sort(key=lambda item: (item['group'], item['source']))
    failures = [record for record in records if record['exitCode']]
    return objects, records, failures


def build(out, work, cache, ndk):
    """Build the pinned ZeroTier provider for arm64-v8a into the bundle."""
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Android native candidate build is CI-only')
    tools = toolchain(ndk)
    work = Path(work)
    prepared = work / 'prepared'
    zerotier_candidate.fetch(cache)
    zerotier_candidate.prepare(prepared, cache)
    zerotier_candidate.apply_candidate(prepared)
    zerotier_candidate.verify_candidate(prepared)
    source = prepared / 'libzt'
    if sha(source / 'CMakeLists.txt') != CMAKE_SHA256:
        raise ValueError('fixed CMakeLists.txt SHA-256 mismatch')
    output = work / 'build'
    for name in ('objects', 'logs', 'tmp'):
        (output / name).mkdir(parents=True, exist_ok=True)
    env = environment(output)
    groups = zerotier_macos.gather_sources(source)
    objects, records, failures = compile_all(groups, output, source,
                                              tools['cc'], tools['cxx'], env)
    if failures:
        raise ValueError('translation-unit compilation failed; inspect per-TU logs')
    library = output / LIBRARY
    link_argv = [str(tools['cxx']), '-shared', '-fPIC', '-static-libstdc++',
                 '-Wl,-soname,' + LIBRARY, '-Wl,-z,max-page-size=16384',
                 '-pthread', '-llog', '-landroid',
                 '-o', str(library)] + [str(obj) for obj in objects]
    link = subprocess.run(link_argv, cwd=output, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, check=False)
    (output / 'logs/link.log').write_text(link.stdout, encoding='utf-8')
    if link.returncode:
        raise ValueError('shared library link failed; inspect logs/link.log')
    bundle = Path(out)
    bundle.mkdir(parents=True, exist_ok=True)
    shutil.copy2(library, bundle / LIBRARY)
    materials = bundle / 'zerotier' / 'materials'
    candidate = bundle / 'zerotier' / 'candidate'
    materials.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)
    for path in sorted((prepared / 'materials').iterdir()):
        shutil.copy2(path, materials / path.name)
    shutil.copy2(prepared / 'source-manifest.json', bundle / 'zerotier' / 'source-manifest.json')
    shutil.copy2(prepared / 'prepared-source.json', bundle / 'zerotier' / 'prepared-source.json')
    shutil.copy2(prepared / 'candidate-source.json', bundle / 'zerotier' / 'candidate-source.json')
    shutil.copy2(zerotier_candidate.CANDIDATE, bundle / 'zerotier' / 'candidate-manifest.json')
    for entry in json.loads(zerotier_candidate.CANDIDATE.read_text())['patches']:
        shutil.copy2(zerotier_candidate.NATIVE / entry['path'], candidate / Path(entry['path']).name)
    shutil.copytree(output / 'logs', bundle / 'zerotier' / 'logs', dirs_exist_ok=True)
    return {'library': LIBRARY, 'abi': ABI, 'api': API, 'ndk': NDK_VERSION,
            'zerotierVersion': upstream_version(source),
            'sourceManifestSha256': sha(zerotier_candidate.MANIFEST),
            'candidateManifestSha256': sha(zerotier_candidate.CANDIDATE),
            'cmakeSha256': CMAKE_SHA256,
            'translationUnits': len(records),
            'sourceGroups': {group: len(paths) for group, paths in groups.items()},
            'androidBuild': 'passed', 'androidLoad': 'not run', 'node': 'not run'}


def verify(bundle, record, files, readelf, inspect):
    """Re-derive the pinned provenance and inspect the exported C ABI."""
    if (record.get('library') != LIBRARY or record.get('abi') != ABI
            or record.get('api') != API or record.get('ndk') != NDK_VERSION
            or record.get('cmakeSha256') != CMAKE_SHA256
            or record.get('sourceManifestSha256') != sha(zerotier_candidate.MANIFEST)
            or record.get('candidateManifestSha256') != sha(zerotier_candidate.CANDIDATE)):
        raise ValueError('ZeroTier source/toolchain provenance mismatch')
    source = json.loads(zerotier_candidate.MANIFEST.read_text())
    candidate = json.loads(zerotier_candidate.CANDIDATE.read_text())
    expected = {'zerotier/source-manifest.json': sha(zerotier_candidate.MANIFEST),
                'zerotier/candidate-manifest.json': sha(zerotier_candidate.CANDIDATE)}
    for entry in source['sources']:
        expected['zerotier/materials/' + entry['name'] + '.tar.gz'] = entry['sha256']
    for entry in source['upstreamPatches']:
        expected['zerotier/materials/' + Path(entry['path']).name] = entry['sha256']
    for entry in candidate['patches']:
        expected['zerotier/candidate/' + Path(entry['path']).name] = entry['sha256']
    for name, digest in expected.items():
        if files.get(name) != digest:
            raise ValueError('ZeroTier source material mismatch: ' + name)
    for name in REQUIRED_MATERIALS:
        if name not in files:
            raise ValueError('ZeroTier build material missing: ' + name)
    if expected['zerotier/source-manifest.json'] != candidate['baseManifestSha256']:
        raise ValueError('ZeroTier candidate base manifest mismatch')
    lock = bundle / 'zerotier' / 'materials' / 'sources.lock'
    if not lock.is_file() or git_blob_sha1(lock) != source['reference']['lockGitBlob']:
        raise ValueError('ZeroTier reference sources.lock mismatch')
    inspect(bundle / LIBRARY, readelf, SYMBOLS)
