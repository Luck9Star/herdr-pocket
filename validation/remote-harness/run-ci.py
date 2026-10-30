#!/usr/bin/env python3
"""Run both real read-only adapters against one ephemeral, runner-only SSH target.

No CLI output, key, connection config or server response is published. The report
is reconstructed from a small typed allowlist rather than trusting an adapter to
have redacted its complete output. Existing SSH probe and user state are untouched.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

REPO = Path(__file__).resolve().parents[2]
HERDR_SHA = '14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d'
HERDR_URL = 'https://github.com/herdrdev/herdr/releases/download/v0.9.5/herdr-linux-x86_64'
HERDR_COMMIT = '2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01'
BOOL_FIELDS = ('hostKeyChecked', 'hostKeyMatched', 'authStarted',
               'snapshotReceived', 'fullFrameReceived')
CASES = ('positive', 'wrong-pin', 'missing-session', 'cross-session', 'cancel', 'reconnect')


class ProbeFailure(Exception):
    """Only static, non-secret error codes may leave this module."""


def require_runner(env):
    if env.get('GITHUB_ACTIONS') != 'true' or not re.fullmatch(r'\d+', env.get('GITHUB_RUN_ID', '')):
        raise ProbeFailure('ci_only')
    if not env.get('GITHUB_REF', '').startswith('refs/heads/codex/'):
        raise ProbeFailure('codex_branch_only')


def safe_report(raw, expected_case):
    """Copy only typed evidence, never arbitrary adapter details or stderr."""
    if not isinstance(raw, dict) or raw.get('case') != expected_case:
        raise ProbeFailure('invalid_case_report')
    if raw.get('status') not in ('passed', 'failed'):
        raise ProbeFailure('invalid_report_status')
    clean = {'status': raw['status'], 'case': expected_case}
    for field in BOOL_FIELDS:
        if type(raw.get(field)) is not bool:
            raise ProbeFailure('invalid_report_boolean')
        clean[field] = raw[field]
    for field in ('generation', 'lateEventsIgnored'):
        value = raw.get(field)
        if type(value) is not int or not 0 <= value <= 1_000_000:
            raise ProbeFailure('invalid_report_counter')
        clean[field] = value
    code = raw.get('errorCode')
    if code is not None and (not isinstance(code, str) or
                             not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', code)):
        raise ProbeFailure('invalid_error_code')
    clean['errorCode'] = code
    return clean


def validate_evidence(result, case):
    if result['status'] != 'passed':
        raise ProbeFailure('adapter_case_failed')
    if case == 'positive':
        if not all(result[field] for field in BOOL_FIELDS) or result['errorCode'] is not None:
            raise ProbeFailure('positive_evidence_incomplete')
    elif case == 'wrong-pin':
        if not (result['hostKeyChecked'] and not result['hostKeyMatched'] and
                not result['authStarted'] and not result['fullFrameReceived']):
            raise ProbeFailure('host_key_rejection_not_proven')
    elif case == 'missing-session':
        # The socket is intentionally still the existing fixture socket. Only
        # the requested session differs. Rejecting its snapshot binding before
        # observe is valid and stronger than waiting for missing-session exec.
        if not (result['hostKeyChecked'] and result['hostKeyMatched'] and
                result['authStarted'] and result['snapshotReceived'] and
                not result['fullFrameReceived'] and result['errorCode']):
            raise ProbeFailure('missing_session_rejection_not_proven')
    elif case == 'cancel':
        if not (result['hostKeyChecked'] and result['hostKeyMatched'] and
                result['authStarted'] and result['snapshotReceived'] and
                not result['fullFrameReceived'] and result['errorCode'] == 'cancelled'):
            raise ProbeFailure('after_snapshot_cancel_not_proven')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--flutter-app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require_runner(os.environ)
    # Import only on the supported Linux CI route; unit tests remain portable.
    import pwd

    if args.output.exists():
        raise ProbeFailure('output_already_exists')
    args.output.mkdir(parents=True)
    out = args.output.resolve()
    root = Path(tempfile.mkdtemp(prefix='hp-mobile-' + os.environ['GITHUB_RUN_ID'] + '-', dir='/tmp'))
    os.chmod(root, 0o700)
    processes = []
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('HERDR_') and k not in ('SSH_AUTH_SOCK', 'SSH_AGENT_PID', 'BASH_ENV')}
    env.update(XDG_CONFIG_HOME=str(root / 'config'), XDG_STATE_HOME=str(root / 'state'),
               XDG_DATA_HOME=str(root / 'data'), XDG_CACHE_HOME=str(root / 'cache'), SHELL='/bin/sh')
    report = {
        'schemaVersion': 1, 'milestone': 'M1a-mobile-readonly',
        'sourceSHA': os.environ['GITHUB_SHA'],
        'runUrl': 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' + os.environ['GITHUB_RUN_ID'],
        'platform': 'Ubuntu 24.04 x86_64 loopback OpenSSH',
        'runnerImage': {'imageOS': os.environ.get('ImageOS'), 'imageVersion': os.environ.get('ImageVersion')},
        'herdr': {'version': '0.9.5', 'sourceCommit': HERDR_COMMIT, 'asset': HERDR_URL, 'sha256': HERDR_SHA},
        'status': 'failed', 'checks': [],
        'scope': 'Actual GUI adapter code in command-line runners; not a GUI click, phone, overlay or continuous observe acceptance',
        'cancelScope': 'Actual SSH after-snapshot cancellation before observe full; adapter unit tests separately check stale generation publication',
        'unverified': ['mobile touch', 'real mobile IME', 'camera pairing', 'protected key storage',
                       'overlays', 'remote input', 'continuous observe', 'production credentials'],
    }

    def command(argv, timeout=60, cwd=None):
        # Keep all output inside this process. Commands may print ephemeral
        # public keys or remote data; neither belongs in artifacts or Actions logs.
        try:
            completed = subprocess.run([str(x) for x in argv], env=env, cwd=cwd,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ProbeFailure('fixture_command_timeout') from exc
        if completed.returncode:
            raise ProbeFailure('fixture_command_failed')
        if len(completed.stdout) > 2_097_152 or len(completed.stderr) > 2_097_152:
            raise ProbeFailure('fixture_command_output_limit')
        return completed.stdout

    def spawn(argv, log_name):
        handle = (root / log_name).open('wb')
        proc = subprocess.Popen([str(x) for x in argv], env=env, stdout=handle,
                                stderr=subprocess.STDOUT, start_new_session=True)
        processes.append((proc, handle))
        return proc

    def publish():
        write_json(out / 'manifest.json', report)

    def start_session(name):
        server = spawn([root / 'herdr', '--session', name, 'server'], name + '-server.log')
        sock = root / 'config/herdr/sessions' / name / 'herdr.sock'
        deadline = time.monotonic() + 20
        while True:
            if server.poll() is not None:
                raise ProbeFailure('herdr_exited_before_ready')
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as ready:
                    ready.settimeout(0.5)
                    ready.connect(str(sock))
                    ready.sendall(b'{"id":"readiness","method":"session.snapshot","params":{}}\n')
                    data = bytearray()
                    while b'\n' not in data and len(data) <= 1_048_576:
                        chunk = ready.recv(4096)
                        if not chunk:
                            break
                        data.extend(chunk)
                    if len(data) <= 1_048_576 and isinstance(json.loads(data.split(b'\n', 1)[0]).get('result'), dict):
                        return sock
            except (OSError, ValueError):
                pass
            if time.monotonic() > deadline:
                raise ProbeFailure('herdr_readonly_readiness_timeout')
            time.sleep(0.1)

    try:
        version = subprocess.run(['/usr/sbin/sshd', '-V'], env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=5)
        version_text = (version.stdout + version.stderr).decode('ascii', errors='replace').strip()
        report['openSshVersion'] = version_text if re.fullmatch(r'OpenSSH_[ -~]{1,240}', version_text) else 'not_recorded'
        with urllib.request.urlopen(HERDR_URL, timeout=60) as response:
            binary = response.read(100 * 1024 * 1024 + 1)
        if len(binary) > 100 * 1024 * 1024 or hashlib.sha256(binary).hexdigest() != HERDR_SHA:
            raise ProbeFailure('herdr_hash_or_size_mismatch')
        herdr = root / 'herdr'
        herdr.write_bytes(binary)
        herdr.chmod(0o700)
        for name in ('host', 'wrong', 'client'):
            command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C',
                     'ephemeral-herdr-pocket-mobile', '-f', root / name])
        authorized = root / 'authorized_keys'
        authorized.write_bytes((root / 'client.pub').read_bytes())
        authorized.chmod(0o600)
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        username = pwd.getpwuid(os.getuid()).pw_name
        (root / 'sshd_config').write_text(f'''Port {port}
ListenAddress 127.0.0.1
HostKey {root}/host
PidFile {root}/sshd.pid
AuthorizedKeysFile {authorized}
StrictModes no
UsePAM yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthenticationMethods publickey
PermitRootLogin no
AllowUsers {username}
PermitTTY no
AllowAgentForwarding no
AllowTcpForwarding local
AllowStreamLocalForwarding local
X11Forwarding no
PrintMotd no
LogLevel VERBOSE
''')
        command(['sudo', 'mkdir', '-p', '/run/sshd'])
        command(['sudo', '/usr/sbin/sshd', '-t', '-f', root / 'sshd_config'])
        spawn(['sudo', '/usr/sbin/sshd', '-D', '-e', '-f', root / 'sshd_config'], 'sshd.log')
        sock = start_session('pocket-probe')

        # Fixture creation is privileged test setup, separate from both adapters.
        # Adapters only receive session.snapshot and fixed observe capabilities.
        created = json.loads(command([herdr, '--session', 'pocket-probe', 'workspace',
                                      'create', '--cwd', root, '--label', 'mobile-readonly']))
        pane = created['result']['root_pane']['pane_id']
        if not isinstance(pane, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}', pane):
            raise ProbeFailure('fixture_pane_invalid')
        shutil.copy2(REPO / 'validation/remote-harness/capture_input.py', root / 'capture_input.py')
        shutil.copy2(REPO / 'validation/shared/fixture.json', root / 'terminal-fixture.json')
        command([herdr, '--session', 'pocket-probe', 'pane', 'run', pane,
                 shlex.join(['python3', str(root / 'capture_input.py')])])
        deadline = time.monotonic() + 10
        while not (root / 'capture-ready').exists():
            if time.monotonic() > deadline:
                raise ProbeFailure('readonly_receiver_not_ready')
            time.sleep(0.05)
        # An existing second session with the same human pane ID must not make
        # a socket/session mismatch acceptable. No wrapper overrides XDG for
        # the adapters: each must derive the root from its reviewed socket.
        start_session('pocket-other')
        other = json.loads(command([herdr, '--session', 'pocket-other', 'workspace',
                                    'create', '--cwd', root, '--label', 'other-readonly']))
        if other['result']['root_pane']['pane_id'] != pane:
            raise ProbeFailure('cross_session_pane_collision_not_established')
        report['crossSessionFixture'] = {'bothSessionsExist': True, 'samePaneId': True,
                                         'expected': 'reject mismatched socket/session before publishing full'}
        config = {'schemaVersion': 1, 'host': '127.0.0.1', 'port': port, 'username': username,
                  'expectedHostKey': ' '.join((root / 'host.pub').read_text().split()[:2]),
                  'privateKeyPem': (root / 'client').read_text(), 'socketPath': str(sock),
                  'herdrPath': str(herdr), 'session': 'pocket-probe', 'paneId': pane,
                  'reviewConfirmed': True}
        adapters = (
            ('rust', [str(REPO / 'validation/transport-rust/target/debug/remote-probe')], REPO),
            ('dart', ['dart', 'run', 'tool/remote_probe.dart'], args.flutter_app.resolve()),
        )
        for adapter, prefix, cwd in adapters:
            for test_id in CASES:
                case = {'reconnect': 'positive', 'cross-session': 'missing-session'}.get(test_id, test_id)
                cfg = dict(config)
                if case == 'wrong-pin':
                    cfg['expectedHostKey'] = ' '.join((root / 'wrong.pub').read_text().split()[:2])
                if case == 'missing-session':
                    cfg['session'] = 'pocket-other' if test_id == 'cross-session' else 'pocket-missing'
                cfg_path = root / (adapter + '-' + test_id + '-config.json')
                write_json(cfg_path, cfg)
                cfg_path.chmod(0o600)
                result_path = root / (adapter + '-' + test_id + '-result.json')
                item = {'adapter': adapter, 'testId': test_id, 'status': 'failed'}
                try:
                    if not (root / 'capture-running').exists():
                        raise ProbeFailure('readonly_receiver_stopped')
                    completed = subprocess.run(prefix + ['--config', str(cfg_path), '--case', case,
                                               '--output', str(result_path)], env=env, cwd=cwd,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
                    if not result_path.is_file() or result_path.stat().st_size > 65536:
                        raise ProbeFailure('adapter_report_missing_or_large')
                    result = safe_report(json.loads(result_path.read_text()), case)
                    item['result'] = result
                    validate_evidence(result, case)
                    if completed.returncode:
                        raise ProbeFailure('adapter_exit_nonzero')
                    if not (root / 'capture-running').exists() or (root / 'received.bin').read_bytes():
                        raise ProbeFailure('readonly_input_boundary_failed')
                    item.update(status='passed', receivedInputBytes=0)
                except ProbeFailure as exc:
                    item['errorCode'] = str(exc)
                except subprocess.TimeoutExpired:
                    item['errorCode'] = 'adapter_timeout'
                except Exception:
                    item['errorCode'] = 'adapter_report_invalid'
                finally:
                    cfg_path.unlink(missing_ok=True)
                    result_path.unlink(missing_ok=True)
                report['checks'].append(item)
                publish()
        report['status'] = 'passed' if all(c['status'] == 'passed' for c in report['checks']) else 'failed'
        report['receivedInputBytes'] = len((root / 'received.bin').read_bytes())
        report['fixtureSharedBetweenAdapters'] = True
        for source, dest in ((REPO / 'validation/shared/remote-contract.json', 'remote-contract.json'),
                             (REPO / 'validation/transport-rust/Cargo.lock', 'transport-Cargo.lock'),
                             (args.flutter_app / 'pubspec.lock', 'flutter-pubspec.lock')):
            shutil.copy2(source, out / dest)
    except ProbeFailure as exc:
        report['errorCode'] = str(exc)
    except Exception:
        # Never stringify exceptions that can contain stdout or connection data.
        report['errorCode'] = 'fixture_setup_failed'
    finally:
        (root / 'stop-capture').write_text('stop')
        stopped = True
        for proc, handle in reversed(processes):
            if proc.poll() is None:
                subprocess.run(['sudo', 'kill', '-TERM', '--', '-' + str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    subprocess.run(['sudo', 'kill', '-KILL', '--', '-' + str(proc.pid)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        stopped = False
            handle.close()
        # These names are created above only. No parent directory or user state
        # is recursively removed; logs/config stay private to this disposable CI.
        for name in ('client', 'client.pub', 'host', 'host.pub', 'wrong', 'wrong.pub',
                     'authorized_keys'):
            (root / name).unlink(missing_ok=True)
        report['cleanup'] = {'ownedProcessesStopped': stopped, 'ephemeralKeysRemoved': True,
                             'userAuthorizationFilesTouched': False, 'rawLogsUploaded': False}
        if not stopped:
            report.update(status='failed', errorCode='owned_process_cleanup_failed')
        publish()
        (out / 'SHA256SUMS').write_text(''.join(
            hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
            for p in sorted(out.iterdir()) if p.is_file() and p.name != 'SHA256SUMS'))
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']),
                      'passed': sum(c['status'] == 'passed' for c in report['checks'])}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ProbeFailure as exc:
        print(json.dumps({'status': 'failed', 'errorCode': str(exc)}))
        raise SystemExit(1)
