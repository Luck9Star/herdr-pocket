#!/usr/bin/env python3
"""Collect genuine provider compilation failures without skipping other probes."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[3]
CONFIG = json.loads((ROOT / 'validation/native/sources.json').read_text())
OUT = Path(os.environ.get('NATIVE_PROBE_OUTPUT', str(ROOT / 'validation/native/artifacts'))).resolve()
WORK = Path(os.environ.get('RUNNER_TEMP', '/tmp')) / ('herdr-native-' + os.environ.get('GITHUB_RUN_ID', 'local'))
REPORT = {'schemaVersion': 1, 'sourceCommit': os.environ.get('GITHUB_SHA', 'local'),
          'runUrl': 'https://github.com/' + os.environ.get('GITHUB_REPOSITORY', '') + '/actions/runs/' + os.environ.get('GITHUB_RUN_ID', ''),
          'platform': platform.system(), 'architecture': platform.machine(),
          'runnerImage': os.environ.get('ImageVersion'), 'scope': CONFIG['scope'],
          'providers': {name: {'provider': name, 'status': 'not run', 'networkValidation': 'not run', 'deviceValidation': 'not run', 'commands': []} for name in ['tailscale', 'easytier', 'zerotier']}}
CURRENT = None


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(label, argv, cwd=None, timeout=1200, env=None):
    entry = {'label': label, 'argv': [str(x) for x in argv], 'exitCode': None}
    CURRENT['commands'].append(entry)
    logfile = OUT / (CURRENT['provider'] + '-' + str(len(CURRENT['commands'])).zfill(2) + '-' + label + '.log')
    entry['log'] = logfile.name
    started = time.monotonic()
    try:
        with logfile.open('w') as f:
            options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
            process = subprocess.Popen(entry['argv'], cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, **options)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=f, stderr=subprocess.STDOUT, check=False)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
        entry['exitCode'] = code
        if code != 0:
            raise RuntimeError(label + ' exited ' + str(code))
    except subprocess.TimeoutExpired:
        entry['exitCode'] = 124
        raise RuntimeError(label + ' exceeded ' + str(timeout) + ' seconds')
    finally:
        entry['seconds'] = round(time.monotonic() - started, 3)


def checkout(url, commit, destination, label):
    run(label + '-init', ['git', 'init', destination], timeout=60)
    run(label + '-line-endings', ['git', 'config', 'core.autocrlf', 'false'], cwd=destination, timeout=60)
    run(label + '-remote', ['git', 'remote', 'add', 'origin', url], cwd=destination, timeout=60)
    run(label + '-fetch', ['git', 'fetch', '--depth=1', 'origin', commit], cwd=destination, timeout=300)
    run(label + '-checkout', ['git', 'checkout', '--detach', 'FETCH_HEAD'], cwd=destination, timeout=60)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=destination, text=True).strip()
    if actual != commit:
        raise RuntimeError(label + ' commit mismatch')
    CURRENT.setdefault('sources', []).append({'repository': url, 'commit': actual})


def lock_values(reference):
    # Data only: never source an upstream shell file in the runner environment.
    values = dict(re.findall(r'^([A-Z0-9_]+)="([^"]*)"$', (reference / 'sources.lock').read_text(), re.M))
    if values['TAILSCALE_MODULE_VERSION'] != 'v1.104.1' or values['EASYTIER_RUST_TOOLCHAIN'] != '1.95.0':
        raise RuntimeError('Reference lock changed unexpectedly')
    return values


def patches(reference, family, entries, target):
    for spec in entries.split():
        name, digest = spec.split(':')
        path = reference / 'patches' / family / name
        if sha(path) != digest:
            raise RuntimeError('Patch digest mismatch: ' + name)
        run('patch-check', ['git', 'apply', '--check', path], cwd=target, timeout=60)
        run('patch-apply', ['git', 'apply', path], cwd=target, timeout=60)
        CURRENT.setdefault('patches', []).append({'file': name, 'sha256': digest})


def licenses(label, tree):
    dest = OUT / 'licenses' / label
    dest.mkdir(parents=True, exist_ok=True)
    for name in ['LICENSE', 'LICENSE.txt', 'LICENSE-MIT', 'LICENSE-APACHE', 'COPYING', 'AUTHORS.md', 'NOTICE']:
        path = tree / name
        if path.is_file():
            shutil.copy2(path, dest / name)


def tsnet(reference, lock):
    probe = WORK / 'tsnet'; probe.mkdir()
    for name, key in [('go.mod', 'LIBTAILSCALE_GO_MOD_SHA256'), ('go.sum', 'LIBTAILSCALE_GO_SUM_SHA256')]:
        source = reference / 'native/tailscale' / name
        if sha(source) != lock[key]: raise RuntimeError(name + ' lock checksum mismatch')
        shutil.copy2(source, probe / name)
        shutil.copy2(source, OUT / ('tsnet-' + name))
    shutil.copy2(ROOT / 'validation/native/tsnet/main.go', probe / 'main.go')
    ext = {'Windows': '.dll', 'Darwin': '.dylib', 'Linux': '.so'}[platform.system()]
    library = probe / ('libtsnet-probe' + ext)
    env = dict(os.environ, CGO_ENABLED='1', GOTOOLCHAIN='local')
    run('go-version', ['go', 'version'], cwd=probe, env=env)
    run('compile-c-abi', ['go', 'build', '-mod=readonly', '-buildmode=c-shared', '-o', library, '.'], cwd=probe, env=env)
    run('load-c-abi', [sys.executable, '-c', 'import ctypes,sys; library=ctypes.CDLL(sys.argv[1]); version=library.hp_probe_abi_version; version.restype=ctypes.c_int; assert version()==1; print("probe ABI v1 loaded; node never started")', library], timeout=30)
    CURRENT['library'] = {'sha256': sha(library), 'bytes': library.stat().st_size, 'load': 'passed', 'nodeStarted': False}
    CURRENT['tested'] = 'tsnet import + Dial(context)/Close type check + c-shared ABI build/load; no tsnet dial executed'


def easytier(reference, lock, check=True):
    target = reference / 'native/easytier/vendor/easytier'
    target.parent.mkdir(parents=True)
    checkout(lock['EASYTIER_REPO'], lock['EASYTIER_COMMIT'], target, 'easytier-source')
    patches(reference, 'easytier', lock['EASYTIER_PATCHES'], target)
    licenses('easytier', target)
    licenses('heeler-easytier', reference / 'native/easytier')
    protoc = CONFIG['protoc'][platform.system()]
    archive = WORK / protoc['file']
    with urllib.request.urlopen('https://github.com/protocolbuffers/protobuf/releases/download/v36.2/' + protoc['file'], timeout=60) as response:
        content = response.read(32 * 1024 * 1024 + 1)
    if len(content) > 32 * 1024 * 1024: raise RuntimeError('protoc archive exceeds 32 MiB budget')
    archive.write_bytes(content)
    if sha(archive) != protoc['sha256']: raise RuntimeError('protoc checksum mismatch')
    tools = WORK / 'protoc'
    with zipfile.ZipFile(archive) as z: z.extractall(tools)
    compiler = tools / 'bin' / ('protoc.exe' if os.name == 'nt' else 'protoc')
    compiler.chmod(0o755)
    env = dict(os.environ, PROTOC=str(compiler), CARGO_BUILD_JOBS='2')
    run('protoc-version', [compiler, '--version'], env=env)
    run('rust-version', ['rustc', '+1.95.0', '--version'], env=env)
    if check:
        run('check-c-abi-library', ['cargo', '+1.95.0', 'check', '--locked', '--lib'], cwd=reference / 'native/easytier', env=env, timeout=1800)
        CURRENT['tested'] = 'Real patched heeler-easytier library cargo check only; no linking, network node or TCP dial'
    return env


def zerotier(reference, lock):
    target = WORK / 'libzt'
    checkout(lock['LIBZT_REPO'], lock['LIBZT_COMMIT'], target, 'libzt-source')
    for path, prefix in [('ext/ZeroTierOne', 'ZEROTIERONE'), ('ext/lwip', 'LWIP'), ('ext/lwip-contrib', 'LWIP_CONTRIB')]:
        expected = lock[prefix + '_COMMIT']
        link = subprocess.check_output(['git', 'ls-tree', 'HEAD', '--', path], cwd=target, text=True)
        if expected not in link: raise RuntimeError('libzt gitlink mismatch: ' + path)
        destination = target / path
        # gitlinks are empty directories in a new checkout; no user work exists here.
        checkout(lock[prefix + '_REPO'], expected, destination, prefix.lower())
        licenses(prefix.lower(), destination)
    patches(reference, 'libzt', lock['ZEROTIER_PATCHES'], target)
    licenses('libzt', target)
    build = WORK / 'libzt-build'
    run('cmake-version', ['cmake', '--version'], timeout=30)
    run('cmake-configure', ['cmake', '-S', target, '-B', build, '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
                          '-DBUILD_STATIC_LIB=OFF', '-DBUILD_SHARED_LIB=ON', '-DBUILD_HOST_SELFTEST=OFF',
                          '-DBUILD_HOST_EXAMPLES=OFF', '-DALLOW_INSTALL_TARGET=OFF', '-DZTS_DISABLE_CENTRAL_API=ON'], timeout=300)
    run('build-shared', ['cmake', '--build', build, '--config', 'Release', '--target', 'zt-shared', '--parallel', '2'], timeout=1200)
    suffix = {'Windows': '.dll', 'Darwin': '.dylib', 'Linux': '.so'}[platform.system()]
    libraries = [p for p in build.rglob('*') if p.is_file() and p.suffix == suffix and 'zt' in p.name]
    if len(libraries) != 1: raise RuntimeError('Expected one libzt shared library, found ' + str(len(libraries)))
    library = libraries[0]
    run('load-and-resolve', [sys.executable, '-c', 'import ctypes,sys; library=ctypes.CDLL(sys.argv[1]); [getattr(library,s) for s in ["zts_node_start","zts_bsd_socket","zts_bsd_connect","zts_bsd_close"]]; print("four symbols resolved; node never started")', library], timeout=30)
    CURRENT['library'] = {'sha256': sha(library), 'bytes': library.stat().st_size, 'load': 'passed', 'nodeStarted': False}
    CURRENT['tested'] = 'Patched libzt shared library compiled/loaded; four symbols resolved, never invoked'


if __name__ == '__main__':
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Native toolchain/build execution is CI-only; no local SDK installation or identity access')
    OUT.mkdir(parents=True, exist_ok=True)
    if WORK.exists(): raise SystemExit('Refusing to overwrite previous probe workspace')
    WORK.mkdir(parents=True)
    CURRENT = {'provider': 'source', 'commands': []}
    REPORT['providers']['source'] = CURRENT
    reference = WORK / 'reference'
    try:
        checkout(CONFIG['reference']['repository'], CONFIG['reference']['commit'], reference, 'reference')
        lock = lock_values(reference)
        shutil.copy2(reference / 'sources.lock', OUT / 'upstream-sources.lock')
        licenses('reference', reference)
        CURRENT['status'] = 'passed'
        for name, probe in [('tailscale', tsnet), ('easytier', easytier), ('zerotier', zerotier)]:
            CURRENT = {'provider': name, 'commands': [], 'networkValidation': 'not run', 'deviceValidation': 'not run'}
            REPORT['providers'][name] = CURRENT
            try:
                probe(reference, lock)
                CURRENT['status'] = 'passed'
            except Exception as exc:
                CURRENT['status'] = 'failed'
                CURRENT['error'] = str(exc)
            (OUT / 'results.json').write_text(json.dumps(REPORT, indent=2) + '\n')
    except Exception as exc:
        CURRENT['status'] = 'failed'; CURRENT['error'] = str(exc)
    finally:
        (OUT / 'results.json').write_text(json.dumps(REPORT, indent=2) + '\n')
        (OUT / 'SHA256SUMS').write_text(''.join(sha(p) + '  ' + str(p.relative_to(OUT)) + '\n' for p in sorted(OUT.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))
    print(json.dumps({name: {'status': row.get('status'), 'error': row.get('error')} for name, row in REPORT['providers'].items()}))
    sys.exit(1 if any(row.get('status') != 'passed' for row in REPORT['providers'].values()) else 0)
