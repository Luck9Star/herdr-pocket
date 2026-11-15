#!/usr/bin/env python3
"""Run two real provider-bound herdr sessions inside an isolated Linux netns.

The caller supplies an already prepared, private bundle: peer (EasyTier upstream
peer), ts-fixture (the controlled tsnet test executable), probe (this repository's
real-feature Rust client), lib/ (both candidate libraries), and herdr (the reviewed
input-extension binary). No real account or credential is used. Only a sanitized
manifest is emitted; raw process output stays in the temporary directory.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import queue
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

import easytier_loopback as et


BOOL_FIELDS = ('passed', 'preloginUrlAbsent', 'preloginDialRejected', 'etFull', 'tsFull', 'etFirst',
               'tsFirst', 'etStopped', 'etStaleRejected', 'tsAfterStop',
               'tsStopped', 'tsStaleRejected', 'etAfterStop', 'etObserverJoined',
               'tsObserverJoined', 'localFallbackRejected', 'crossRouteRejected', 'cleanup')


CLIENT_ERRORS = {None, 'real_candidates_required', 'node_operation_failed', 'unexpected_prelogin_url',
                 'login_url_missing', 'prelogin_dial_not_rejected', 'auth_exchange_failed',
                 'auth_exchange_timeout', 'ts_not_running', 'local_fallback_not_rejected',
                 'cross_route_not_rejected', 'input_ready_timeout', 'input_not_ready',
                 'frame_marker_missing', 'input_send_failed', 'input_mode_failed', 'provider_stop_failed', 'observer_join_failed', 'stale_input_not_rejected',
                 'cleanup_failed', 'executor_failed', 'dialer_failed', 'invalid_et_config'}


def safe_result(raw):
    if not isinstance(raw, dict) or any(type(raw.get(field)) is not bool for field in BOOL_FIELDS):
        raise et.Failure('client_result_invalid')
    error = raw.get('error')
    return ({field: raw[field] for field in BOOL_FIELDS},
            error if isinstance(error, (str, type(None))) and error in CLIENT_ERRORS else 'other_client_failure')


def case_passed(result, stop_first):
    common = ('passed', 'preloginUrlAbsent', 'preloginDialRejected', 'etFull', 'tsFull',
              'etFirst', 'tsFirst', 'etObserverJoined', 'tsObserverJoined',
              'localFallbackRejected', 'crossRouteRejected', 'cleanup')
    expected = (('etStopped', 'etStaleRejected', 'tsAfterStop') if stop_first == 'et'
                else ('tsStopped', 'tsStaleRejected', 'etAfterStop'))
    inactive = (('tsStopped', 'tsStaleRejected', 'etAfterStop') if stop_first == 'et'
                else ('etStopped', 'etStaleRejected', 'tsAfterStop'))
    return all(result[field] is True for field in common + expected) and all(
        result[field] is False for field in inactive)


def wait_file(path, process, timeout=25, *, socket_expected=False):
    deadline = time.monotonic() + timeout
    ready = path.is_socket if socket_expected else path.is_file
    while not ready():
        if process.poll() is not None:
            raise et.Failure('fixture_exited_early')
        if time.monotonic() >= deadline:
            raise et.Failure('fixture_ready_timeout')
        time.sleep(.05)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def read_event(events, expected, process, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None and events.empty():
            raise et.Failure('ts_fixture_exited_early')
        try:
            line = events.get(timeout=.1)
        except queue.Empty:
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue  # Go test's final PASS is not a protocol event.
        if not isinstance(event, dict) or event.get('event') != expected:
            raise et.Failure('ts_fixture_event_invalid')
        return event
    raise et.Failure('ts_fixture_event_timeout')


def run(bundle, output, stop_first):
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise et.Failure('linux_unprivileged_runner_required')
    et.checked_namespace(json.loads(et.command(['ip', '-j', 'link', 'show'])))
    for name in ('peer', 'ts-fixture', 'probe', 'herdr', 'lib/libheeler_easytier.so', 'lib/libhp_tailscale.so'):
        if not (bundle / name).is_file():
            raise et.Failure('prepared_bundle_incomplete')
    root = Path(tempfile.mkdtemp(prefix='hp-dual-', dir='/tmp'))
    root.chmod(0o700)
    processes, handles = [], []
    report = {'schemaVersion': 1, 'sourceSHA': os.environ.get('GITHUB_SHA', ''),
              'status': 'failed', 'stage': 'fixture', 'stopFirst': stop_first,
              'loopbackOnlyNamespace': True, 'temporaryCredentialsRemoved': False,
              'ownedProcessesStopped': False, 'tsPeerCleanup': False}
    report['binarySha256'] = {name: et.digest(bundle / name) for name in
                              ('peer', 'ts-fixture', 'probe', 'herdr',
                               'lib/libheeler_easytier.so', 'lib/libhp_tailscale.so')}
    output.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('HERDR_') and k not in ('SSH_AUTH_SOCK', 'SSH_AGENT_PID', 'BASH_ENV')}
    env.update(SHELL='/bin/sh', LD_LIBRARY_PATH=str(bundle / 'lib'))

    def spawn(argv, name, extra=None, pipe=False):
        log = (root / (name + '.log')).open('wb'); handles.append(log)
        child_env = dict(env, **(extra or {}))
        child = subprocess.Popen([str(x) for x in argv], env=child_env, start_new_session=True,
                                 stdin=subprocess.PIPE if pipe else subprocess.DEVNULL,
                                 stdout=subprocess.PIPE if pipe else log, stderr=log)
        processes.append(child)
        return child

    try:
        user = pwd.getpwuid(os.getuid()).pw_name
        et.command(['sudo', 'mkdir', '-p', '/run/sshd'])
        hosts = []
        for side in ('ET', 'TS'):
            report['stage'] = side.lower() + '-ssh'
            d = root / side; d.mkdir(mode=0o700)
            host_env = dict(env, XDG_CONFIG_HOME=str(d / 'config'), XDG_STATE_HOME=str(d / 'state'),
                            XDG_DATA_HOME=str(d / 'data'), XDG_CACHE_HOME=str(d / 'cache'))
            for key in ('host', 'client'):
                et.command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'isolated', '-f', d / key])
            authorized = d / 'authorized_keys'; authorized.write_bytes((d / 'client.pub').read_bytes()); authorized.chmod(0o600)
            port = free_port()
            config = d / 'sshd_config'
            config.write_text(f'''Port {port}
ListenAddress 127.0.0.1
HostKey {d}/host
PidFile {d}/sshd.pid
AuthorizedKeysFile {authorized}
StrictModes no
UsePAM yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthenticationMethods publickey
PermitRootLogin no
AllowUsers {user}
PermitTTY no
AllowAgentForwarding no
AllowTcpForwarding local
AllowStreamLocalForwarding local
X11Forwarding no
PrintMotd no
UseDNS no
LogLevel ERROR
''')
            et.command(['sudo', '/usr/sbin/sshd', '-t', '-f', config])
            sshd = spawn(['sudo', '/usr/sbin/sshd', '-D', '-e', '-f', config], side + '-sshd', host_env)
            deadline = time.monotonic() + 10
            while True:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.5) as conn:
                        if not conn.recv(256).startswith(b'SSH-2.0-'):
                            raise et.Failure('ssh_canary_invalid')
                    break
                except OSError:
                    if sshd.poll() is not None or time.monotonic() >= deadline:
                        raise et.Failure('ssh_canary_unavailable')
                    time.sleep(.05)
            shutil.copy2(bundle / 'herdr', d / 'herdr')
            conf = d / 'config/herdr'; conf.mkdir(parents=True)
            (conf / 'config.toml').write_text('[update]\nversion_check = false\nmanifest_check = false\n')
            report['stage'] = side.lower() + '-herdr'
            server = spawn([d / 'herdr', '--session', 'pocket-probe', 'server'], side + '-herdr', host_env)
            sock = conf / 'sessions/pocket-probe/herdr.sock'; wait_file(sock, server, socket_expected=True)
            deadline = time.monotonic() + 15
            while True:
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                        channel.settimeout(.5); channel.connect(str(sock))
                        channel.sendall(b'{"id":"ready","method":"session.snapshot","params":{}}\n')
                        data = bytearray()
                        while b'\n' not in data and len(data) <= 1_048_576:
                            chunk = channel.recv(4096)
                            if not chunk: break
                            data.extend(chunk)
                        value = json.loads(data.split(b'\n', 1)[0])
                        if len(data) <= 1_048_576 and isinstance(value.get('result'), dict): break
                except (OSError, ValueError):
                    pass
                if server.poll() is not None or time.monotonic() >= deadline:
                    raise et.Failure('herdr_readiness_timeout')
                time.sleep(.05)
            created = json.loads(et.command([d / 'herdr', '--session', 'pocket-probe', 'workspace',
                                             'create', '--cwd', d, '--label', 'dual-overlay'], env=host_env))
            pane = created['result']['root_pane']['pane_id']
            if not isinstance(pane, str) or not pane or len(pane) > 128:
                raise et.Failure('pane_invalid')
            report['stage'] = side.lower() + '-pane'
            echo = et.HARNESS / 'dual_overlay_echo.py'
            et.command([d / 'herdr', '--session', 'pocket-probe', 'pane', 'run', pane,
                        shlex.join(['/usr/bin/python3', str(echo), str(d), side])], env=host_env)
            wait_file(d / 'capture-ready', server)
            recovery = d / 'recovery'; recovery.mkdir(mode=0o700)
            remote = {'schemaVersion': 1, 'host': '', 'port': 1, 'username': user,
                      'expectedHostKey': ' '.join((d / 'host.pub').read_text().split()[:2]),
                      'privateKeyPem': (d / 'client').read_text(), 'socketPath': str(sock),
                      'herdrPath': str(d / 'herdr'), 'session': 'pocket-probe', 'paneId': pane,
                      'reviewConfirmed': True}
            hosts.append((d, port, remote, recovery))
        network, secret = 'hp-dual-' + secrets.token_hex(12), secrets.token_hex(32)
        peer_port = free_port()
        peer_config = root / 'peer.toml'
        peer_config.write_text(et.native_config(network, secret, peer_port, server=True)); peer_config.chmod(0o600)
        report['stage'] = 'easytier-peer'
        peer = spawn([bundle / 'peer', peer_config, root, hosts[0][1]], 'et-peer')
        wait_file(root / 'peer-ready', peer)
        virtual_port = json.loads((root / 'peer-ready').read_text())['virtualTcpPort']
        hosts[0][2].update(host=et.OVERLAY_HOST, port=virtual_port)
        ts_dir = root / 'ts-fixture'; ts_dir.mkdir(mode=0o700)
        report['stage'] = 'tailscale-peer'
        ts_peer = spawn([bundle / 'ts-fixture', '-test.run=^TestServeFixture$', '-test.timeout=180s'],
                        'ts-peer', {'HP_TS_FIXTURE_WORK_DIR': str(ts_dir),
                                    'HP_TS_FIXTURE_BRIDGE': f'127.0.0.1:{hosts[1][1]}'}, pipe=True)
        events = queue.Queue()
        def collect():
            for line in ts_peer.stdout:
                events.put(line)
        threading.Thread(target=collect, daemon=True).start()
        ready = read_event(events, 'ready', ts_peer)
        if (ready.get('peerPort') != 2222 or not isinstance(ready.get('peerIp'), str)
                or not str(ready.get('controlUrl', '')).startswith('https://127.0.0.1:')):
            raise et.Failure('ts_fixture_ready_invalid')
        ca = Path(ready.get('caFile', '')).resolve(strict=True)
        if not ca.is_relative_to(ts_dir.resolve()):
            raise et.Failure('ts_fixture_ca_invalid')
        hosts[1][2].update(host=ready['peerIp'], port=2222)
        node_dir = root / 'ts-node'; node_dir.mkdir(mode=0o700)
        exchange = root / 'exchange'; exchange.mkdir(mode=0o700)
        request = {'stopFirst': stop_first, 'network': network, 'nativeConfig': et.native_config(network, secret, peer_port),
                   'controlUrl': ready['controlUrl'], 'nodeDir': str(node_dir), 'exchange': str(exchange),
                   'etRecovery': str(hosts[0][3]), 'tsRecovery': str(hosts[1][3]),
                   'etRemote': hosts[0][2], 'tsRemote': hosts[1][2], 'localPort': hosts[0][1]}
        request_file = root / 'request.json'; et.write_json(request_file, request); request_file.chmod(0o600)
        report['stage'] = 'explicit-auth-and-observe'
        client = spawn([bundle / 'probe', request_file, root / 'result.json'], 'client', {'SSL_CERT_FILE': str(ca)})
        wait_file(exchange / 'auth-url', client, 45)
        auth_url = (exchange / 'auth-url').read_text()
        ts_peer.stdin.write((json.dumps({'op': 'complete_auth', 'url': auth_url}) + '\n').encode()); ts_peer.stdin.flush()
        auth = read_event(events, 'auth_completed', ts_peer)
        if auth.get('ok') is not True:
            raise et.Failure('ts_auth_not_completed')
        (exchange / 'auth-complete').write_text('ok')
        client.wait(timeout=100)
        wait_file(root / 'result.json', client, 1)
        result = json.loads((root / 'result.json').read_text())
        report['client'], report['clientError'] = safe_result(result)
        et_bytes = (hosts[0][0] / 'received.bin').read_bytes()
        ts_bytes = (hosts[1][0] / 'received.bin').read_bytes()
        expected = ((b'ET-ONE\n', b'TS-ONE\nTS-TWO\n') if stop_first == 'et'
                    else (b'ET-ONE\nET-TWO\n', b'TS-ONE\n'))
        report['independentExactInput'] = (et_bytes, ts_bytes) == expected
        ts_peer.stdin.write(b'{"op":"stop"}\n'); ts_peer.stdin.flush()
        stopped = read_event(events, 'cleanup', ts_peer, 15)
        report['tsPeerCleanup'] = stopped.get('peerClosed') is True and stopped.get('bridgeConnections') == 0
        ts_peer.wait(timeout=10)
        (root / 'stop-peer').touch(); peer.wait(timeout=15)
        if client.returncode or ts_peer.returncode or peer.returncode or not case_passed(report['client'], stop_first) \
                or not report['independentExactInput'] or not report['tsPeerCleanup']:
            raise et.Failure('dual_acceptance_failed')
        report.update(status='passed', stage='complete')
    finally:
        # A failure before the auth handshake may still have produced a safe
        # Rust result. Preserve only allowlisted fields, never its private input.
        result_file = root / 'result.json'
        if result_file.is_file() and 'client' not in report:
            try:
                report['client'], report['clientError'] = safe_result(json.loads(result_file.read_text()))
            except (ValueError, OSError, et.Failure):
                report['clientError'] = 'client_result_invalid'
        for d, *_ in locals().get('hosts', []):
            (d / 'stop-capture').touch()
        (root / 'stop-peer').touch()
        for process in reversed(processes):
            if process.poll() is None:
                try:
                    # The two root-owned sshd processes are children of sudo.
                    subprocess.run(['sudo', 'kill', '-TERM', '--', '-' + str(process.pid)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                    process.wait(timeout=3)
                except (subprocess.TimeoutExpired, ProcessLookupError):
                    subprocess.run(['sudo', 'kill', '-KILL', '--', '-' + str(process.pid)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired: pass
        for handle in handles:
            handle.close()
        report['ownedProcessesStopped'] = all(p.poll() is not None for p in processes)
        shutil.rmtree(root)
        report['temporaryCredentialsRemoved'] = not root.exists()
        if not report['ownedProcessesStopped'] or not report['temporaryCredentialsRemoved']:
            report['status'] = 'failed'
        et.write_json(output / 'manifest.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--stop-first', required=True, choices=('et', 'ts'))
    args = parser.parse_args()
    try:
        result = run(args.bundle.resolve(strict=True), args.output.resolve(), args.stop_first)
    except Exception as error:
        path = args.output / 'manifest.json'
        result = json.loads(path.read_text()) if path.is_file() else {'status': 'failed', 'stage': 'precondition'}
        result['error'] = str(error) if isinstance(error, et.Failure) else type(error).__name__
        args.output.mkdir(parents=True, exist_ok=True)
        et.write_json(path, result)
    print(json.dumps({'status': result['status'], 'stage': result['stage'], 'error': result.get('error')}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
