#!/usr/bin/env python3
"""Build and inspect an isolated, fixed-source host candidate. Never install it."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid

HERE = Path(__file__).resolve().parent
BASE = '2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01'
PATCH_HASH = '7f89a79677a456f024bd73555130861cd1b0b47e9d4d69f98d4e18ffc7f1ed8a'
PATCH = HERE / 'herdr-0.9.5-pocket-input.patch'
ZIG_ARCHIVE_HASH = '70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00'
NAME = 'herdr-pocket-input-candidate'
SCOPE = 'experimental isolated host candidate; not a production release'
TEMP_PARENT = str(Path('/tmp').resolve())
CAPABILITY = {'type': 'pocket_input_capabilities', 'version': 1, 'protocol': 22,
              'atomic_terminal_guard': True, 'raw_bytes': True, 'max_input_bytes': 4096}


class Refused(Exception):
    """Only fixed public codes are exposed; never forward tool/server output."""


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def new_output(path):
    path = Path(path).absolute()
    # Resolve the existing parent; refuse links and all existing output objects.
    if not path.parent.is_dir() or path.parent.resolve() != path.parent:
        raise Refused('output_parent_must_exist_without_symlinks')
    try:
        path.mkdir(mode=0o700)
    except OSError:
        raise Refused('output_must_be_new') from None
    return path


def clean_env(root):
    """No inherited SSH agent, HERDR options, shell startup hooks or credentials."""
    env = {'PATH': os.defpath, 'LANG': 'C', 'LC_ALL': 'C', 'TERM': 'xterm-256color',
           'SHELL': '/bin/sh', 'HOME': str(root / 'home'), 'TMPDIR': str(root / 'tmp'),
           'XDG_CONFIG_HOME': str(root / 'config'), 'XDG_STATE_HOME': str(root / 'state'),
           'XDG_DATA_HOME': str(root / 'data'), 'XDG_CACHE_HOME': str(root / 'cache'),
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_NO_REPLACE_OBJECTS': '1'}
    for key in ('HOME', 'TMPDIR', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        Path(env[key]).mkdir(mode=0o700, parents=True, exist_ok=True)
    return env


def run(argv, *, env=None, cwd=None, timeout=30, stdout=subprocess.PIPE):
    try:
        process = subprocess.Popen([str(x) for x in argv], cwd=cwd, env=env,
                                   stdin=subprocess.DEVNULL, stdout=stdout,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        raise Refused('tool_unavailable') from None
    try:
        data, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            stop_owned(process)
        except (OSError, subprocess.TimeoutExpired):
            raise Refused('tool_cleanup_unconfirmed') from None
        raise Refused('tool_timed_out') from None
    if process.returncode:
        raise Refused('tool_failed')
    if stdout == subprocess.PIPE:
        if len(data) > 1024 * 1024:
            raise Refused('tool_output_limit')
        return data.decode('utf-8', errors='strict').strip()
    return ''


def tool(name, prefix):
    path = shutil.which(name)
    if not path:
        raise Refused(name + '_missing')
    version = run([path, 'version' if name == 'zig' else '--version'])
    if not version.startswith(prefix):
        raise Refused(name + '_version_mismatch')
    if name == 'zig' and version != '0.16.0':
        raise Refused('zig_version_mismatch')
    return path, version


def extract_source(archive, destination):
    """Only the fixed git tree is extracted; no source worktree mutation."""
    with tarfile.open(archive) as tar:
        for member in tar:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or '..' in relative.parts or not relative.parts:
                raise Refused('source_archive_path_invalid')
            target = destination.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(destination):
                raise Refused('source_archive_path_invalid')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
            elif member.issym():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or not (target.parent / member.linkname).resolve().is_relative_to(destination):
                    raise Refused('source_archive_link_invalid')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(member.linkname)
            else:
                raise Refused('source_archive_type_invalid')


def build(source, output, cargo_cache, timeout=3600, pocket_source_sha=None):
    if platform.system() not in ('Darwin', 'Linux'):
        raise Refused('host_platform_unsupported')
    source = Path(source).resolve(strict=True)
    if digest(PATCH) != PATCH_HASH:
        raise Refused('patch_hash_mismatch')
    git = shutil.which('git')
    if not git or run([git, '-C', source, 'rev-parse', 'HEAD'], env={'PATH': os.defpath, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_NO_REPLACE_OBJECTS': '1'}) != BASE:
        raise Refused('source_commit_mismatch')
    producer_head = run([git, '-C', HERE, 'rev-parse', 'HEAD'], env={'PATH': os.defpath, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_NO_REPLACE_OBJECTS': '1'})
    if not re.fullmatch(r'[0-9a-f]{40}', producer_head) or pocket_source_sha is not None and pocket_source_sha != producer_head:
        raise Refused('pocket_source_commit_mismatch')
    cargo, cargo_version = tool('cargo', 'cargo 1.96.0 ')
    _rustc, rustc_version = tool('rustc', 'rustc 1.96.0 ')
    zig, zig_version = tool('zig', '0.16.0')
    cargo_cache = Path(cargo_cache).resolve(strict=True)
    if not cargo_cache.is_dir() or any((cargo_cache / name).exists() or (cargo_cache / name).is_symlink() for name in ('config', 'config.toml', 'credentials', 'credentials.toml')):
        raise Refused('dedicated_offline_cargo_cache_required')
    out = new_output(output)
    report = {'schemaVersion': 1, 'scope': SCOPE, 'status': 'failed', 'upstreamSHA': BASE,
              'patchSHA256': PATCH_HASH, 'sourceSHA': producer_head, 'buildProfile': 'release', 'binaryDebugAssertions': False,
              'toolchains': {'cargo': cargo_version, 'rustc': rustc_version, 'zig': zig_version},
              'networkFetchRequested': False, 'sourceWorktreeModified': False}
    root = None
    preserve = False
    try:
        root = Path(tempfile.mkdtemp(prefix='hp-host-build-', dir=TEMP_PARENT)).resolve()
        env = clean_env(root)
        # Offline dependencies are explicit. Do not import ~/.cargo credentials/config.
        env.update(CARGO_HOME=str(cargo_cache), RUSTUP_HOME=os.environ.get('RUSTUP_HOME', str(Path.home() / '.rustup')),
                   ZIG=zig, RUSTC=_rustc, RUSTUP_TOOLCHAIN='1.96.0', CARGO_BUILD_JOBS='2', CARGO_PROFILE_RELEASE_DEBUG_ASSERTIONS='false')
        env['PATH'] = os.pathsep.join(dict.fromkeys([str(Path(cargo).parent), str(Path(_rustc).parent), str(Path(zig).parent), os.defpath]))
        work = root / 'source'; work.mkdir()
        with (root / 'source.tar').open('xb') as archive:
            run([git, '-C', source, 'archive', '--format=tar', BASE], env=env, stdout=archive)
        extract_source(root / 'source.tar', work)
        run([git, 'apply', '--check', PATCH], env=env, cwd=work)
        run([git, 'apply', PATCH], env=env, cwd=work)
        for case in ('pocket_input_guards_identity_rejects_bad_bytes_and_never_resizes',
                     'observer_input_modes_are_per_client_and_survive_backpressure',
                     'unreadable_observer_modes_close_only_that_observer_without_false_modes'):
            result = run([cargo, 'test', '--offline', '--locked', '--release', '--package',
                          'herdr', case], env=env, cwd=work, timeout=timeout)
            if not re.search(r'test result: ok\. 1 passed; 0 failed;', result):
                raise Refused('release_guard_test_not_proven')
        run([cargo, 'rustc', '--offline', '--locked', '--release', '--package', 'herdr', '--bin', 'herdr',
             '--', '-C', 'debug-assertions=no'], env=env, cwd=work, timeout=timeout)
        binary = work / 'target/release/herdr'
        if not binary.is_file() or binary.is_symlink():
            raise Refused('built_binary_missing')
        shutil.copyfile(binary, out / NAME); (out / NAME).chmod(0o700)
        shutil.copyfile(PATCH, out / PATCH.name)
        shutil.copyfile(work / 'LICENSE', out / 'LICENSE')
        report.update(status='built', releaseGuardTestPassed=True,
                      platform={'system': platform.system(), 'machine': platform.machine()},
                      binary={'name': NAME, 'sha256': digest(out / NAME)},
                      producerSHA256=digest(Path(__file__)),
                      upstreamSourceURL='https://github.com/herdrdev/herdr/tree/' + BASE,
                      license={'name': 'LICENSE', 'sha256': digest(out / 'LICENSE')})
    except Refused as error:
        report['errorCode'] = str(error)
        preserve = str(error) == 'tool_cleanup_unconfirmed'
        raise
    except (OSError, ValueError, UnicodeError):
        report['errorCode'] = 'local_build_failed'
        raise Refused('local_build_failed') from None
    finally:
        if root is not None:
            if preserve:
                report['retainedTemporaryRoot'] = str(root)
            else:
                try:
                    shutil.rmtree(root)
                except OSError:
                    report.update(status='failed', errorCode='build_cleanup_unconfirmed', retainedTemporaryRoot=str(root))
            report['temporaryDataRemoved'] = not root.exists()
        if report['status'] != 'built':
            (out / NAME).unlink(missing_ok=True)
        (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')

    return report


def candidate(directory):
    if platform.system() not in ('Darwin', 'Linux'):
        raise Refused('host_platform_unsupported')
    directory = Path(directory).resolve(strict=True)
    try:
        for name in ('manifest.json', PATCH.name, NAME, 'LICENSE'):
            file = directory / name
            if file.is_symlink() or not file.is_file() or file.stat().st_nlink != 1:
                raise Refused('candidate_file_invalid')
        if (directory / 'manifest.json').stat().st_size > 16384:
            raise Refused('candidate_manifest_or_hash_invalid')
        manifest = json.loads((directory / 'manifest.json').read_text())
        if not isinstance(manifest, dict) or not isinstance(manifest.get('binary'), dict) or not isinstance(manifest.get('license'), dict):
            raise Refused('candidate_manifest_or_hash_invalid')
        binary = directory / NAME
        if (manifest.get('schemaVersion') != 1 or manifest.get('status') != 'built' or manifest.get('scope') != SCOPE
                or not re.fullmatch(r'[0-9a-f]{40}', str(manifest.get('sourceSHA', '')))
                or manifest.get('upstreamSHA') != BASE or manifest.get('patchSHA256') != PATCH_HASH
                or manifest.get('buildProfile') != 'release' or manifest.get('binaryDebugAssertions') is not False
                or manifest.get('releaseGuardTestPassed') is not True or manifest.get('binary', {}).get('name') != NAME
                or binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK)
                or digest(binary) != manifest['binary']['sha256'] or digest(directory / PATCH.name) != PATCH_HASH
                or manifest['license'].get('name') != 'LICENSE' or digest(directory / 'LICENSE') != manifest['license'].get('sha256')):
            raise Refused('candidate_manifest_or_hash_invalid')
        if manifest.get('platform') != {'system': platform.system(), 'machine': platform.machine()}:
            raise Refused('candidate_platform_mismatch')
    except (OSError, ValueError, KeyError, TypeError):
        raise Refused('candidate_manifest_or_hash_invalid') from None
    return binary, manifest


def request(path, method, params=None):
    identifier = uuid.uuid4().hex
    wire = json.dumps({'id': identifier, 'method': method, 'params': params or {}}, separators=(',', ':')).encode() + b'\n'
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(1); stream.connect(str(path)); stream.sendall(wire)
        data = bytearray()
        while b'\n' not in data:
            chunk = stream.recv(4096)
            if not chunk or len(data) + len(chunk) > 1024 * 1024:
                raise Refused('rpc_response_invalid')
            data.extend(chunk)
    try:
        value = json.loads(data.split(b'\n', 1)[0])
    except (ValueError, UnicodeError):
        raise Refused('rpc_response_invalid') from None
    if not isinstance(value, dict) or value.get('id') != identifier:
        raise Refused('rpc_response_invalid')
    return value


def stop_owned(process):
    """Only the process group created by this invocation is signalled."""
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    return process.poll() is not None


def same_json(actual, expected):
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)


def probe(binary, *, deadline_seconds=20):
    """A local Unix socket only. No sshd, credentials, external host, or install."""
    result = {'status': 'failed', 'versionChecked': False, 'capabilityChecked': False,
              'namedSocketIsolationChecked': False, 'serverReportedSessionIdentity': False,
              'wrongTerminalRejected': False, 'inputQueueAcceptedBytes': 0,
              'ptyDeliveryVerified': False, 'serverStarted': False, 'ownedServerProcessStopped': False, 'temporaryDataRemoved': False}
    root = None
    try:
        root = Path(tempfile.mkdtemp(prefix='hp-host-probe-', dir=TEMP_PARENT)).resolve()
        _probe_in_root(binary, root, result, deadline_seconds)
    except Refused as error:
        result.update(status='failed', errorCode=str(error))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration, subprocess.TimeoutExpired):
        result.update(status='failed', errorCode='candidate_probe_failed')
    finally:
        if root is not None:
            if not result.get('serverStarted') or result['ownedServerProcessStopped']:
                try:
                    shutil.rmtree(root)
                    result['temporaryDataRemoved'] = not root.exists()
                except OSError:
                    result.update(status='failed', errorCode='temporary_cleanup_unconfirmed', retainedTemporaryRoot=str(root))
            else:
                # Never delete a directory still owned by an unconfirmed live server.
                result.update(status='failed', retainedTemporaryRoot=str(root))

    return result


def _probe_in_root(binary, root, result, deadline_seconds):
    env = clean_env(root)
    version = run([binary, '--version'], env=env)
    if not re.fullmatch(r'herdr 0\.9\.5(?:[-+][A-Za-z0-9._-]+)?', version):
        raise Refused('candidate_version_mismatch')
    result['versionChecked'] = True
    session = 'pocket-' + uuid.uuid4().hex[:12]
    path = root / 'config/herdr/sessions' / session / 'herdr.sock'
    process = subprocess.Popen([str(binary), '--session', session, 'server'], cwd=root, env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    result['serverStarted'] = True
    try:
        until = time.monotonic() + deadline_seconds
        while True:
            if process.poll() is not None:
                raise Refused('candidate_server_exited')
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise Refused('candidate_named_socket_invalid')
                response = request(path, 'session.snapshot')
                if response.get('error', {}).get('code') == 'server_not_running':
                    raise OSError('not_ready')
                snapshot = response.get('result', {})
                if (snapshot.get('type') != 'session_snapshot' or snapshot.get('snapshot', {}).get('version') != '0.9.5'
                        or type(snapshot['snapshot'].get('protocol')) is not int or snapshot['snapshot'].get('protocol') != 22):
                    raise Refused('candidate_snapshot_mismatch')
                break
            except (OSError, TimeoutError):
                if time.monotonic() >= until:
                    raise Refused('candidate_readiness_timeout') from None
                time.sleep(0.05)
        if (root / 'config/herdr-dev').exists() or path.is_symlink() or not stat.S_ISSOCK(path.stat().st_mode):
            raise Refused('candidate_named_socket_invalid')
        result['namedSocketIsolationChecked'] = True
        if not same_json(request(path, 'pocket.input.capabilities').get('result'), CAPABILITY):
            raise Refused('candidate_capability_mismatch')
        result['capabilityChecked'] = True
        # Reuse the existing harness's fixed CLI setup. The target and HOME are newly owned.
        created = json.loads(run([binary, '--session', session, 'workspace', 'create', '--cwd', root,
                                  '--label', 'isolated-candidate-preflight'], env=env))
        pane = created['result']['root_pane']['pane_id']
        current = request(path, 'session.snapshot')['result']['snapshot']
        terminal = next(item['terminal_id'] for item in current['panes'] if item['pane_id'] == pane)
        if not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}', pane) or not re.fullmatch(r'term_[0-9a-f]{1,123}', terminal):
            raise Refused('candidate_target_invalid')
        wrong = 'term_0' if terminal != 'term_0' else 'term_1'
        params = {'pane_id': pane, 'expected_terminal_id': wrong, 'bytes_base64': base64.b64encode(b'x').decode()}
        rejected = request(path, 'pocket.input.send', params)
        if rejected.get('error', {}).get('code') != 'pocket_input_rejected' or 'result' in rejected:
            raise Refused('candidate_wrong_target_not_rejected')
        result['wrongTerminalRejected'] = True
        params['expected_terminal_id'] = terminal
        accepted = request(path, 'pocket.input.send', params)
        if not same_json(accepted.get('result'), {'type': 'pocket_input_accepted', 'pane_id': pane,
                                      'terminal_id': terminal, 'accepted_bytes': 1}) or 'error' in accepted:
            raise Refused('candidate_queue_receipt_invalid')
        result['inputQueueAcceptedBytes'] = 1  # Literal x; never a newline/command, never retried.
        result['status'] = 'passed'
    finally:
        result['ownedServerProcessStopped'] = stop_owned(process)


def preflight(directory, output):
    binary, manifest = candidate(directory)
    out = new_output(output)
    report = {'schemaVersion': 1, 'scope': SCOPE, 'status': 'failed', 'upstreamSHA': BASE,
              'patchSHA256': PATCH_HASH, 'sourceSHA': manifest['sourceSHA'], 'binarySHA256': manifest['binary']['sha256'], 'buildProfile': 'release',
              'limitations': ['no SSH/device authorization validation', 'no server-reported session/boot identity',
                              'queue receipt is not PTY delivery or command execution', 'no install/upgrade/rollback validation']}
    try:
        report.update(probe(binary))
    except Refused as error:
        report['errorCode'] = str(error); raise
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        report['errorCode'] = 'candidate_probe_failed'
        raise Refused('candidate_probe_failed') from None
    finally:
        (out / 'preflight.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def cloud_evidence(build_dir, preflight_dir, tests, output, source_sha, zig_archive_sha):
    """Publish only typed status/hash evidence, never binaries, cache or raw logs."""
    if not re.fullmatch(r'[0-9a-f]{40}', source_sha) or zig_archive_sha != ZIG_ARCHIVE_HASH:
        raise Refused('cloud_evidence_source_invalid')
    def read(path):
        try:
            path=Path(path)
            if path.is_symlink() or not path.is_file() or path.stat().st_size>16384:return {}
            value=json.loads(path.read_text())
            return value if isinstance(value,dict) else {}
        except (OSError,ValueError):return {}
    built=read(Path(build_dir)/'manifest.json'); checked=read(Path(preflight_dir)/'preflight.json'); tested=read(tests)
    expected={'sourceSHA':source_sha,'upstreamSHA':BASE,'patchSHA256':PATCH_HASH,'buildProfile':'release'}
    def linked(value):return all(value.get(k)==v for k,v in expected.items())
    def hash_value(value):return value if isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value) else None
    def code(value):return value if isinstance(value,str) and re.fullmatch(r'[a-z_]{1,64}',value) else None
    tool_tests={'status':'not-run','testsRun':0,'failures':0,'errors':0,'skipped':0}
    if tested.get('sourceSHA')==source_sha and all(type(tested.get(k)) is int and 0<=tested[k]<=10000 for k in ('testsRun','failures','errors','skipped')):
        tool_tests.update({k:tested[k] for k in ('testsRun','failures','errors','skipped')})
        tool_tests['status']='passed' if tested.get('status')=='passed' and tested['testsRun']>0 and tested['failures']==tested['errors']==tested['skipped']==0 else 'failed'
    binary_hash=hash_value(built.get('binary',{}).get('sha256')) if isinstance(built.get('binary'),dict) else None
    build_status={'status':'not-run','releaseGuardTestPassed':False,'temporaryDataRemoved':False}
    if linked(built):
        build_status.update(status='built' if built.get('status')=='built' and binary_hash and built.get('binaryDebugAssertions') is False and built.get('releaseGuardTestPassed') is True and built.get('temporaryDataRemoved') is True else 'failed',
                            releaseGuardTestPassed=built.get('releaseGuardTestPassed') is True,temporaryDataRemoved=built.get('temporaryDataRemoved') is True)
        if code(built.get('errorCode')):build_status['errorCode']=code(built['errorCode'])
    preflight_status={'status':'not-run','inputQueueAcceptedBytes':0}
    if linked(checked) and binary_hash and checked.get('binarySHA256')==binary_hash:
        booleans=('versionChecked','capabilityChecked','namedSocketIsolationChecked','wrongTerminalRejected','serverStarted','ownedServerProcessStopped','temporaryDataRemoved')
        passed=checked.get('status')=='passed' and all(checked.get(k) is True for k in booleans) and type(checked.get('inputQueueAcceptedBytes')) is int and checked['inputQueueAcceptedBytes']==1
        preflight_status.update(status='passed' if passed else 'failed',**{k:checked.get(k) is True for k in booleans},
                                inputQueueAcceptedBytes=1 if type(checked.get('inputQueueAcceptedBytes')) is int and checked['inputQueueAcceptedBytes']==1 else 0)
        if code(checked.get('errorCode')):preflight_status['errorCode']=code(checked['errorCode'])
    toolchains={}
    for name,prefix in (('cargo','cargo 1.96.0 '),('rustc','rustc 1.96.0 '),('zig','0.16.0')):
        value=built.get('toolchains',{}).get(name) if isinstance(built.get('toolchains'),dict) else None
        if isinstance(value,str) and value.startswith(prefix) and re.fullmatch(r'[A-Za-z0-9().+_ -]{1,128}',value):toolchains[name]=value
    result={'schemaVersion':1,'scope':SCOPE,'status':'passed' if tool_tests['status']=='passed' and build_status['status']=='built' and preflight_status['status']=='passed' and len(toolchains)==3 and hash_value(built.get('producerSHA256')) else 'failed',
            **expected,'zigArchiveSHA256':zig_archive_sha,'binarySHA256':binary_hash,'producerSHA256':hash_value(built.get('producerSHA256')),
            'toolchains':toolchains,'toolTests':tool_tests,'build':build_status,'preflight':preflight_status,
            'candidateBinaryUploaded':False,'dependencyDistributionReview':'pending',
            'serverReportedSessionIdentity':False,'ptyDeliveryVerified':False}
    out=new_output(output);(out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    b = sub.add_parser('build'); b.add_argument('--source', required=True); b.add_argument('--output', required=True)
    b.add_argument('--pocket-source-sha', help='Expected pocket checkout commit; recorded and checked against this producer checkout')
    b.add_argument('--cargo-cache', required=True, help='Explicit prepopulated dependency cache without cargo config/credentials; no downloads')
    p = sub.add_parser('preflight'); p.add_argument('--candidate', required=True); p.add_argument('--output', required=True)
    e=sub.add_parser('evidence'); e.add_argument('--build-dir',required=True); e.add_argument('--preflight-dir',required=True)
    e.add_argument('--tests',required=True); e.add_argument('--output',required=True); e.add_argument('--pocket-source-sha',required=True); e.add_argument('--zig-archive-sha',required=True)
    args = parser.parse_args()
    try:
        if args.action=='build':report=build(args.source,args.output,args.cargo_cache,pocket_source_sha=args.pocket_source_sha)
        elif args.action=='preflight':report=preflight(args.candidate,args.output)
        else:report=cloud_evidence(args.build_dir,args.preflight_dir,args.tests,args.output,args.pocket_source_sha,args.zig_archive_sha)
    except Refused as error:
        print(json.dumps({'status': 'refused', 'errorCode': str(error), 'scope': SCOPE})); return 1
    except (OSError, ValueError, UnicodeError):
        print(json.dumps({'status': 'refused', 'errorCode': 'local_input_unavailable', 'scope': SCOPE})); return 1
    print(json.dumps({'status': report['status'], 'scope': SCOPE})); return 0 if report['status'] in ('built', 'passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
