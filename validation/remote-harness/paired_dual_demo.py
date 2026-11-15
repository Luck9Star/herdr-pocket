#!/usr/bin/env python3
"""Opt-in two-host real SSH/herdr pairing QA, without apps or overlay claims.

Uses only newly generated test keys. Device keys are MemoryKeyStore test doubles,
temporarily exported only for OpenSSH's actual possession proof. A real phone
instead supplies its own public request and retains its own private key.
"""
import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from paired_dual_fixture import PairingTarget, distinct_targets
from paired_gui import GuiFailure, bounded_wire, fixture_terminal_id, owned_process, wait_for
from pairing import MemoryKeyStore, PendingPairing, encode

HERE = Path(__file__).resolve().parent
PAYLOAD = {'et': b'ET-PAIRED\n', 'ts': b'TS-PAIRED\n'}


def command(args, env, timeout=10):
    value = subprocess.run(list(map(str, args)), env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
    if value.returncode or len(value.stdout) > 2097152:
        raise RuntimeError('paired_fixture_command_failed')
    return value.stdout


def line(process):
    selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
    try:
        if not selector.select(10): raise RuntimeError('paired_fixture_ssh_timeout')
        return process.stdout.readline(128)
    finally: selector.close()


def ssh_args(root, port, username, key, remote):
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-o', 'BatchMode=yes',
            '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'UserKnownHostsFile=' + str(root / 'known_hosts'),
            '-o', 'ConnectTimeout=5', '-i', str(key), '-p', str(port),
            username + '@127.0.0.1', remote]


def receive(root, role):
    """One authenticated SSH session; read-only snapshot, then fixed QA bytes."""
    root = root.resolve(strict=True)
    config = json.loads((root / 'peer.json').read_text())
    fixture_terminal_id(config)
    sys.stdout.buffer.write(b'READY\n'); sys.stdout.buffer.flush()
    data = sys.stdin.buffer.readline(1025)
    if data != PAYLOAD[role]: raise RuntimeError('unexpected_fixture_input')
    command([root / 'herdr', '--session', config['session'], 'pane', 'send-text',
             config['paneId'], data.decode()], dict(os.environ))
    sys.stdout.buffer.write(b'ACK\n'); sys.stdout.buffer.flush()
    if sys.stdin.buffer.read(1): raise RuntimeError('unexpected_extra_input')


@contextmanager
def prepared_pairing_hosts(binary, base):
    """Own two empty-authorization OpenSSH/herdr fixtures until context exit."""
    processes, targets, metadata = [], {}, {}
    with ExitStack() as stack:
        try:
            for role in ('et', 'ts'):
                root = base / role; root.mkdir(mode=0o700)
                env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(root),
                       'XDG_CONFIG_HOME': str(root / 'config'), 'LANG': 'C.UTF-8',
                       'PYTHONDONTWRITEBYTECODE': '1'}
                shutil.copy2(binary, root / 'herdr'); (root / 'herdr').chmod(0o700)
                version = command([root / 'herdr', '--version'], env).decode().strip()
                if version != 'herdr 0.9.5': raise RuntimeError('fixture_herdr_version_mismatch')
                metadata['herdrVersion'] = version
                metadata['herdrSha256'] = hashlib.sha256((root / 'herdr').read_bytes()).hexdigest()
                command(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', root / 'host'], env)
                public = ' '.join((root / 'host.pub').read_text().split()[:2])
                (root / 'authorized_keys').write_bytes(b''); (root / 'authorized_keys').chmod(0o600)
                with socket.socket() as reserve:
                    reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
                username = pwd.getpwuid(os.getuid()).pw_name
                pam = 'yes' if sys.platform == 'linux' else 'no'
                (root / 'sshd_config').write_text(f'''Port {port}
    ListenAddress 127.0.0.1
    HostKey {root}/host
    PidFile {root}/sshd.pid
    AuthorizedKeysFile {root}/authorized_keys
    StrictModes no
    UsePAM {pam}
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PubkeyAuthentication yes
    AuthenticationMethods publickey
    PermitRootLogin no
    AllowUsers {username}
    PermitUserRC no
    AllowAgentForwarding no
    AllowTcpForwarding no
    X11Forwarding no
    PrintMotd no
    LogLevel VERBOSE
    SetEnv HOME={root} XDG_CONFIG_HOME={root}/config PYTHONDONTWRITEBYTECODE=1
    ''')
                sshd = (['sudo', '-n'] if sys.platform == 'linux' else []) + ['/usr/sbin/sshd']
                command(sshd + ['-t', '-f', root / 'sshd_config'], env)
                server = stack.enter_context(owned_process(sshd + ['-D', '-e', '-f', root / 'sshd_config'],
                    cwd=root, env=env, log=root / 'sshd.log')); processes.append(server)
                def reachable():
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.2) as sock:
                            return sock.recv(128).startswith(b'SSH-2.0-')
                    except OSError: return False
                wait_for(reachable, 'fixture_ssh_not_ready', timeout=5)
                config_root = root / 'config/herdr'; config_root.mkdir(parents=True)
                (config_root / 'config.toml').write_text('[update]\nversion_check = false\nmanifest_check = false\n')
                herdr = stack.enter_context(owned_process([root / 'herdr', '--session', 'qa-pair', 'server'],
                    cwd=root, env=env, log=root / 'herdr.log')); processes.append(herdr)
                sock = config_root / 'sessions/qa-pair/herdr.sock'
                wait_for(sock.exists, 'fixture_herdr_not_ready', timeout=10)
                created = json.loads(command([root / 'herdr', '--session', 'qa-pair', 'workspace',
                    'create', '--cwd', root, '--label', role], env))
                pane = created['result']['root_pane']['pane_id']
                shutil.copy2(HERE / 'capture_input.py', root / 'capture_input.py')
                shutil.copy2(HERE.parent / 'shared/fixture.json', root / 'terminal-fixture.json')
                command([root / 'herdr', '--session', 'qa-pair', 'pane', 'run', pane,
                    shlex.join([sys.executable, str(root / 'capture_input.py')])], env)
                wait_for((root / 'capture-ready').exists, 'fixture_capture_not_ready', timeout=10)
                config = dict(host='127.0.0.1', port=port, username=username, session='qa-pair',
                    socketPath=str(sock), herdrPath=str(root / 'herdr'), expectedHostKey=public, paneId=pane)
                (root / 'peer.json').write_text(json.dumps(config)); (root / 'peer.json').chmod(0o600)
                target = PairingTarget(role, root, config); targets[role] = target
                independent = command(['/usr/bin/ssh-keygen', '-lf', root / 'host.pub', '-E', 'sha256'], env).decode().split()[1]
                if independent != target.host.pin: raise RuntimeError('fixture_pin_review_mismatch')
                (root / 'public-profile.json').write_bytes(target.public_profile())
                (root / 'known_hosts').write_text(f'[127.0.0.1]:{port} {public}\n')
            distinct_targets(targets['et'], targets['ts'])
            yield targets, processes, metadata
        finally:
            for target in targets.values():
                target.revoke()
                (target.root / 'stop-capture').touch()
                wait_for(lambda: not (target.root / 'capture-running').exists(),
                         'fixture_capture_not_stopped', timeout=5)


def demo(binary, output):
    if os.geteuid() == 0: raise RuntimeError('unprivileged_fixture_owner_required')
    report = {'schemaVersion': 1, 'passed': False,
              'scope': 'two local real OpenSSH/herdr peers; MemoryKeyStore devices; not GUI, platform vault, guarded mobile input or overlay routing',
              'pairingRequestsSigned': False, 'devicePossessionProof': 'OpenSSH public-key authentication'}
    processes, targets = [], {}
    with tempfile.TemporaryDirectory(prefix='hp-pair2-', dir='/tmp') as temporary:
        base = Path(temporary).resolve()
        env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(base),
               'XDG_CONFIG_HOME': str(base / 'config'), 'LANG': 'C.UTF-8',
               'PYTHONDONTWRITEBYTECODE': '1'}
        keys = MemoryKeyStore(); handles = {}; requests = {}; clients = []
        try:
            with ExitStack() as stack, prepared_pairing_hosts(binary, base) as prepared:
                targets, processes, metadata = prepared
                report.update(metadata)
                for role, target in targets.items():
                    root = target.root
                    username = target.config['username']
                    handle = keys.create(); handles[role] = handle
                    requests[role] = PendingPairing(keys, handle, account=username,
                        expected_host_key=target.host.pin, device='synthetic-' + role, now=int(time.time()))
                    private = keys._keys[handle].private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
                    (root / 'device').write_bytes(private); (root / 'device').chmod(0o600); del private
                distinct_targets(targets['et'], targets['ts'])
                cross = 0
                for role, other in [('et', 'ts'), ('ts', 'et')]:
                    try: targets[other].review(encode(requests[role].request))
                    except ValueError: cross += 1
                if cross != 2: raise RuntimeError('cross_host_request_accepted')
                responses = {}
                for role, target in targets.items():
                    raw = encode(requests[role].request); review = target.review(raw)
                    responses[role] = target.approve(raw, request_id=review['requestId'],
                        device_fingerprint=review['deviceFingerprint'], reviewed=True)
                cross = 0
                for role, other in [('et', 'ts'), ('ts', 'et')]:
                    try: requests[other].accept(responses[role], now=int(time.time()), source_reviewed=True)
                    except ValueError: cross += 1
                if cross != 2: raise RuntimeError('cross_host_response_accepted')
                for role, target in targets.items():
                    requests[role].accept(responses[role], now=int(time.time()), source_reviewed=True)
                    other = 'ts' if role == 'et' else 'et'; root = target.root
                    result = subprocess.run(ssh_args(root, target.config['port'], target.config['username'],
                        targets[other].root / 'device', 'true'), env=env, capture_output=True, timeout=8)
                    if result.returncode == 0: raise RuntimeError('cross_host_device_authenticated')
                    wrong_fingerprint = targets[other].approval.fingerprint
                    rejected = (r'Failed publickey for ' + re.escape(target.config['username'])
                        + r' from 127\.0\.0\.1 port [0-9]+ ssh2: ED25519 '
                        + re.escape(wrong_fingerprint) + r'(?:\s|$)')
                    wait_for(lambda: re.search(rejected, bounded_wire(root / 'sshd.log', 2097152).decode(errors='replace')),
                             'cross_host_key_not_observed', timeout=5)
                for role, target in targets.items():
                    root = target.root
                    requests[role].connect(explicit=True)
                    remote = shlex.join([sys.executable, str(Path(__file__).resolve()), 'receive', str(root), role])
                    log = stack.enter_context((root / 'client.log').open('wb'))
                    client = subprocess.Popen(ssh_args(root, target.config['port'], target.config['username'],
                        root / 'device', remote), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
                    clients.append(client)
                    if line(client) != b'READY\n': raise RuntimeError('paired_ssh_snapshot_failed')
                    requests[role].connection_result(requests[role].generation, pinned_ssh_authenticated=True)
                for (role, target), client in zip(targets.items(), clients):
                    client.stdin.write(PAYLOAD[role]); client.stdin.flush()
                    if line(client) != b'ACK\n': raise RuntimeError('paired_ssh_input_failed')
                    wait_for(lambda: bounded_wire(target.root / 'received.bin', 4096) == PAYLOAD[role],
                        'paired_input_not_received', timeout=5)
                audits = {role: target.audit(PAYLOAD[role]) for role, target in targets.items()}
                if any(v['acceptedSessions'] != 1 or v['approvedDeviceSessions'] != 1
                       or v['otherAcceptedDeviceSessions'] != 0 for v in audits.values()):
                    raise RuntimeError('paired_ssh_session_identity_mismatch')
                if not all(p.poll() is None for p in clients) or any(p.state != 'paired' for p in requests.values()):
                    raise RuntimeError('paired_sessions_not_concurrent')
                report.update(passed=True, hostFingerprintsIndependentlyMatched=True,
                    crossRequestRejected=True, crossResponseRejected=True, crossDeviceSshRejected=True,
                    crossDeviceKeyObservedAndRejected=True,
                    twoAuthenticatedSessionsAlive=all(p.poll() is None for p in clients), hosts=audits)
                for client in clients:
                    client.stdin.close()
                    if client.wait(timeout=5) != 0: raise RuntimeError('paired_ssh_close_failed')
                for role, target in targets.items():
                    receipt = target.revoke()
                    requests[role].accept(receipt, now=int(time.time()), source_reviewed=True)
                    (target.root / 'stop-capture').touch()
                    wait_for(lambda: not (target.root / 'capture-running').exists(),
                             'paired_capture_not_stopped', timeout=5)
                report.update(authenticatedSessionsClosed=True, captureProgramsStopped=True,
                              matchingRevocationsReviewed=all(p.state == 'revoked' for p in requests.values()))
        finally:
            for client in clients:
                if client.poll() is None:
                    client.stdin.close()
                    try: client.wait(timeout=5)
                    except subprocess.TimeoutExpired: client.kill(); client.wait()
            for target in targets.values():
                target.revoke()
                (target.root / 'stop-capture').touch()
            report['ownedServersStopped'] = all(p.poll() is not None for p in processes)
            report['temporaryAuthorizationsCleared'] = all(not (t.root/'authorized_keys').read_bytes() for t in targets.values())
    report['temporaryCredentialsRemoved'] = not base.exists()
    if not all(report.get(key) is True for key in ('ownedServersStopped', 'temporaryAuthorizationsCleared', 'temporaryCredentialsRemoved')):
        report['passed'] = False
    output.write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'receive':
        receive(Path(sys.argv[2]), sys.argv[3]); return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--herdr', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        report = demo(args.herdr.resolve(strict=True), args.output.resolve())
    except (OSError, ValueError, KeyError, RuntimeError, GuiFailure, subprocess.SubprocessError):
        report = {'passed': False, 'error': 'paired_fixture_failed'}
        args.output.write_text(json.dumps(report) + '\n')
    print(json.dumps(report))
    if not report['passed']: raise SystemExit(1)


if __name__ == '__main__': main()
