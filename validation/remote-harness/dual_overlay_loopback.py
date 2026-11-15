#!/usr/bin/env python3
"""Run two real provider-bound herdr sessions inside an isolated Linux netns.

The caller supplies an already prepared, private bundle: peer (EasyTier upstream
peer), ts-fixture (the controlled tsnet test executable), probe (this repository's
real-feature Rust client), lib/ (both candidate libraries), and herdr (the reviewed
input-extension binary). No real account or credential is used. Only a sanitized
manifest is emitted; raw process output stays in the temporary directory.
"""
import argparse
import ipaddress
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
from go_panic_sanitize import sanitize_go_panic


BOOL_FIELDS = ('passed', 'preloginUrlAbsent', 'preloginNeedsLogin', 'beginLoginSubmitted', 'beginLoginSucceeded', 'preloginDialRejected', 'etBanner', 'tsBanner', 'etFull', 'tsFull', 'etFirst',
               'tsFirst', 'etStopped', 'etStaleRejected', 'tsAfterStop',
               'tsStopped', 'tsStaleRejected', 'etAfterStop', 'etObserverJoined',
               'tsObserverJoined', 'localFallbackRejected', 'crossRouteRejected', 'cleanup')


CLIENT_ERRORS = {None, 'real_candidates_required', 'node_operation_failed', 'unexpected_prelogin_url',
                 'login_url_missing', 'prelogin_state_timeout', 'prelogin_dial_not_rejected', 'auth_exchange_failed',
                 'auth_exchange_timeout', 'ts_not_running', 'local_fallback_not_rejected',
                 'cross_route_not_rejected', 'overlay_banner_missing', 'banner_checkpoint_failed',
                 'banner_diagnostics_timeout', 'route_checkpoint_failed', 'route_checkpoint_timeout', 'input_ready_timeout', 'input_not_ready',
                 'frame_marker_missing', 'input_send_failed', 'input_mode_failed', 'provider_stop_failed', 'observer_join_failed', 'stale_input_not_rejected',
                 'cleanup_failed', 'executor_failed', 'dialer_failed', 'invalid_et_config'}


TS_STATES = {None, 'starting', 'engine_started', 'needs_login', 'needs_machine_auth',
             'running', 'closing', 'stopped', 'other'}


def safe_state(raw):
    return raw if isinstance(raw, (str, type(None))) and raw in TS_STATES else 'other'


def safe_result(raw):
    if not isinstance(raw, dict) or any(type(raw.get(field)) is not bool for field in BOOL_FIELDS):
        raise et.Failure('client_result_invalid')
    error = raw.get('error')
    return ({field: raw[field] for field in BOOL_FIELDS},
            error if isinstance(error, (str, type(None))) and error in CLIENT_ERRORS else 'other_client_failure')


OBSERVER_STAGES = {None, 'connecting', 'host-key-verified', 'authenticated', 'snapshot-received',
                   'full-frame-received', 'input-unavailable', 'other'}
OBSERVER_ERRORS = {None, 'invalid_config', 'invalid_private_key', 'invalid_host_key', 'host_key_mismatch',
                   'overlay_provider_unavailable', 'overlay_stale_revision', 'overlay_wrong_owner',
                   'overlay_unknown_write', 'overlay_transport_failed', 'handshake_failed',
                   'authentication_failed', 'socket_unavailable', 'snapshot_failed', 'snapshot_rejected',
                   'invalid_snapshot', 'pane_missing', 'ambiguous_pane', 'invalid_terminal_id',
                   'observe_failed', 'invalid_full_frame', 'observe_ended', 'observe_close_failed',
                   'observe_limit', 'cancelled', 'timeout', 'input_unavailable', 'listener_failed',
                   'frame_failed', 'resume_target_changed', 'session_mismatch', 'watch_invalid', 'watch_ended',
                   'watch_failed', 'watch_close_failed', 'watch_disconnected', 'watch_limit',
                   'watch_open_failed', 'watch_rejected', 'watch_stopped', 'watch_unsupported',
                   'watch_write_failed', 'unsupported_protocol', 'invalid_frame', 'sequence_gap',
                   'snapshot_limit', 'rpc_failed', 'other_observer_error'}
AUDIT_FIELDS = ('hostKeyChecked', 'hostKeyMatched', 'authStarted', 'snapshotReceived', 'fullFrameReceived')


def safe_observer(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('audit'), dict):
        raise et.Failure('observer_result_invalid')
    audit = raw['audit']
    if any(type(audit.get(field)) is not bool for field in AUDIT_FIELDS):
        raise et.Failure('observer_result_invalid')
    stage, error = raw.get('stage'), raw.get('error')
    stage = stage if isinstance(stage, (str, type(None))) and stage in OBSERVER_STAGES else 'other'
    error = error if isinstance(error, (str, type(None))) and error in OBSERVER_ERRORS else 'other_observer_error'
    return {'stage': stage, 'error': error, 'audit': {field: audit[field] for field in AUDIT_FIELDS}}


ROUTE_PROBE_FIELDS = ('etLocalRoute', 'tsLocalRoute', 'etCrossRoute', 'tsCrossRoute')
ROUTE_OUTCOMES = {None, 'dial_error', 'stream_eof', 'stream_error', 'received_bytes',
                  'dial_timeout', 'read_timeout'}


def safe_route_probes(result):
    probes = {}
    for field in ROUTE_PROBE_FIELDS:
        value = result.get(field)
        if not isinstance(value, (str, type(None))) or value not in ROUTE_OUTCOMES:
            raise et.Failure('route_probe_invalid')
        probes[field] = value
    return probes


def safe_banner_counts(result):
    attempts = {side: result.get(side + 'BannerAttempts') for side in ('et', 'ts')}
    connections = {side: result.get(side + 'BannerConnections') for side in ('et', 'ts')}
    if any(type(value) is not int or not 0 <= value <= 1000 for value in attempts.values()):
        raise et.Failure('banner_attempts_invalid')
    if any(type(value) is not int or not 0 <= value <= attempts[side]
           for side, value in connections.items()):
        raise et.Failure('banner_connections_invalid')
    return attempts, connections


def case_passed(result, stop_first):
    common = ('passed', 'preloginUrlAbsent', 'preloginNeedsLogin', 'beginLoginSubmitted', 'beginLoginSucceeded', 'preloginDialRejected', 'etBanner', 'tsBanner', 'etFull', 'tsFull',
              'etFirst', 'tsFirst', 'etObserverJoined', 'tsObserverJoined',
              'localFallbackRejected', 'crossRouteRejected', 'cleanup')
    expected = (('etStopped', 'etStaleRejected', 'tsAfterStop') if stop_first == 'et'
                else ('tsStopped', 'tsStaleRejected', 'etAfterStop'))
    inactive = (('tsStopped', 'tsStaleRejected', 'etAfterStop') if stop_first == 'et'
                else ('etStopped', 'etStaleRejected', 'tsAfterStop'))
    return all(result[field] is True for field in common + expected) and all(
        result[field] is False for field in inactive)


def read_et_diagnostics(root, peer, timeout=5):
    request = root / 'peer-diagnostics-request'
    request.touch(exist_ok=False)
    deadline = time.monotonic() + timeout
    while request.exists():
        if peer.poll() is not None:
            raise et.Failure('et_peer_diagnostics_peer_exited')
        if time.monotonic() >= deadline:
            raise et.Failure('et_peer_diagnostics_timeout')
        time.sleep(.025)
    value = json.loads((root / 'peer-diagnostics.json').read_text())
    fields = {'connectedPeerCount', 'expectedVirtualRoutePresent', 'virtualSshListenerActive'}
    if (not isinstance(value, dict) or set(value) != fields
            or type(value['connectedPeerCount']) is not int
            or not 0 <= value['connectedPeerCount'] <= 256
            or type(value['expectedVirtualRoutePresent']) is not bool
            or type(value['virtualSshListenerActive']) is not bool):
        raise et.Failure('et_peer_diagnostics_invalid')
    return value


def peer_diagnostics(output, returncode):
    lower = output.lower()
    return {'tsPeerExitBeforeCleanup': returncode,
            'tsPeerExitedBeforeCleanup': returncode is not None,
            'tsPeerPanic': b'panic:' in lower,
            'tsPeerTimeout': b'test timed out' in lower,
            'tsPeerPanicDetail': sanitize_go_panic(output)}


def wait_file(path, process, timeout=25, *, socket_expected=False):
    deadline = time.monotonic() + timeout
    ready = path.is_socket if socket_expected else path.is_file
    while not ready():
        if process.poll() is not None:
            raise et.Failure('fixture_exited_early')
        if time.monotonic() >= deadline:
            raise et.Failure('fixture_ready_timeout')
        time.sleep(.05)


def wait_file_or_exit(path, process, timeout):
    deadline = time.monotonic() + timeout
    while not path.is_file():
        if process.poll() is not None:
            return False
        if time.monotonic() >= deadline:
            raise et.Failure('fixture_ready_timeout')
        time.sleep(.025)
    return True


def negative_server_counts(before, after):
    fields = ('connections', 'authRequests', 'authAccepted')
    result = {}
    for side in ('et', 'ts'):
        if (len(before[side]) != len(fields) or len(after[side]) != len(fields)
                or any(type(value) is not int for value in before[side] + after[side])):
            raise et.Failure('negative_server_counts_invalid')
        delta = [end - start for start, end in zip(before[side], after[side])]
        if any(value < 0 or value > 256 for value in delta):
            raise et.Failure('negative_server_counts_invalid')
        result[side] = dict(zip(fields, delta))
    return result


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


def checked_isolated_namespace(links, addresses, routes):
    """Permit only loopback and one unconnected TEST-NET /32 dummy interface."""
    if not isinstance(links, list) or {item.get('ifname') for item in links} != {'lo', 'hp-dummy'} or len(links) != 2:
        raise et.Failure('isolated_links_invalid')
    by_name = {item['ifname']: item for item in links}
    if ('UP' not in by_name['lo'].get('flags', []) or
            'UP' not in by_name['hp-dummy'].get('flags', []) or
            by_name['hp-dummy'].get('linkinfo', {}).get('info_kind') != 'dummy'):
        raise et.Failure('isolated_dummy_invalid')
    if not isinstance(addresses, list) or {item.get('ifname') for item in addresses} != {'lo', 'hp-dummy'} or len(addresses) != 2:
        raise et.Failure('isolated_addresses_invalid')
    expected = {
        'lo': {('inet', '127.0.0.1', 8), ('inet6', '::1', 128)},
        'hp-dummy': {('inet', '192.0.2.1', 32)},
    }
    for item in addresses:
        found = {(addr.get('family'), addr.get('local'), addr.get('prefixlen')) for addr in item.get('addr_info', [])}
        allowed = expected[item['ifname']]
        required = {('inet', '127.0.0.1', 8)} if item['ifname'] == 'lo' else allowed
        if not required <= found <= allowed:
            raise et.Failure('isolated_addresses_invalid')
    if not isinstance(routes, list) or not routes:
        raise et.Failure('isolated_routes_invalid')
    for route in routes:
        if (route.get('table') != 'local' or route.get('type') not in ('local', 'broadcast')
                or route.get('gateway') is not None or route.get('via') is not None
                or route.get('nexthops') is not None):
            raise et.Failure('isolated_routes_invalid')
        try:
            destination = ipaddress.ip_network(route.get('dst', ''), strict=False)
        except ValueError:
            raise et.Failure('isolated_routes_invalid') from None
        if route.get('dev') == 'lo':
            allowed = (destination.version == 4 and destination.subnet_of(ipaddress.ip_network('127.0.0.0/8'))
                       or destination == ipaddress.ip_network('::1/128'))
        else:
            allowed = (route.get('dev') == 'hp-dummy'
                       and destination == ipaddress.ip_network('192.0.2.1/32'))
        if not allowed:
            raise et.Failure('isolated_routes_invalid')


def check_current_namespace():
    links = json.loads(et.command(['ip', '-j', '-d', 'link', 'show']))
    addresses = json.loads(et.command(['ip', '-j', 'address', 'show']))
    routes = (json.loads(et.command(['ip', '-j', '-4', 'route', 'show', 'table', 'all'])) +
              json.loads(et.command(['ip', '-j', '-6', 'route', 'show', 'table', 'all'])))
    checked_isolated_namespace(links, addresses, routes)


def client_et_config(network, secret, peer_port, private_loopback):
    config = et.native_config(network, secret, peer_port)
    if private_loopback:
        # Test-only control: the peer endpoint is an owned loopback listener.
        # Production defaults and the peer's own configuration remain unchanged.
        config = config.replace('[flags]\n', '[flags]\nbind_device = false\n', 1)
    return config


def run(bundle, output, stop_first, private_loopback):
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise et.Failure('linux_unprivileged_runner_required')
    check_current_namespace()
    for name in ('peer', 'ts-fixture', 'probe', 'herdr', 'lib/libheeler_easytier.so', 'lib/libhp_tailscale.so'):
        if not (bundle / name).is_file():
            raise et.Failure('prepared_bundle_incomplete')
    root = Path(tempfile.mkdtemp(prefix='hp-dual-', dir='/tmp'))
    root.chmod(0o700)
    processes, handles = [], []
    report = {'schemaVersion': 1, 'sourceSHA': os.environ.get('GITHUB_SHA', ''),
              'status': 'failed', 'stage': 'fixture', 'stopFirst': stop_first,
              'privateLoopbackTransport': private_loopback,
              'isolatedNamespace': True, 'testOnlyDummy': True, 'noExternalRoutes': True,
              'temporaryCredentialsRemoved': False,
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
LogLevel DEBUG3
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
            # Health only: pin this temporary SSH server, authenticate using its
            # temporary client key, and read socket metadata without input.
            known = d / 'known_hosts'
            host_key = ' '.join((d / 'host.pub').read_text().split()[:2])
            known.write_text(f'[127.0.0.1]:{port} {host_key}\n'); known.chmod(0o600)
            remote_command = shlex.join(['/usr/bin/python3', str(et.HARNESS / 'dual_overlay_health.py'), str(sock)])
            health_command = ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes',
                '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={known}',
                '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'IdentitiesOnly=yes',
                '-o', 'ConnectTimeout=5', '-i', str(d / 'client'), '-p', str(port),
                f'{user}@127.0.0.1', remote_command]
            try:
                health_process = subprocess.run(health_command, env=env, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, timeout=12)
                health = json.loads(health_process.stdout)
                ssh_ok = health_process.returncode == 0 and isinstance(health, dict)
                snapshot_ok = ssh_ok and health.get('snapshot') is True
                capability_ok = ssh_ok and health.get('inputCapability') is True
            except (OSError, ValueError, subprocess.TimeoutExpired):
                ssh_ok = snapshot_ok = capability_ok = False
            report[side.lower() + 'LocalHealth'] = {'sshPinnedAndAuthenticated': ssh_ok,
                'snapshot': snapshot_ok, 'inputCapability': capability_ok}
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
        request = {'stopFirst': stop_first, 'network': network, 'nativeConfig': client_et_config(network, secret, peer_port, private_loopback),
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
        wait_file(exchange / 'banner-started', client, 45)
        report['etPeerDuringBanner'] = read_et_diagnostics(root, peer)
        wait_file(exchange / 'banner-finished', client, 45)
        report['etPeerAfterBanner'] = read_et_diagnostics(root, peer)
        (exchange / 'banner-diagnostics-read').write_text('ok')
        if wait_file_or_exit(exchange / 'route-check-ready', client, 35):
            before = {side.lower(): et.log_counts(root / (side + '-sshd.log')) for side in ('ET', 'TS')}
            # Each temporary sshd has already accepted its local health login
            # and the corresponding authenticated overlay observer. This
            # baseline prevents a silent log-format mismatch from proving zero.
            report['negativeServerAuditEstablished'] = all(
                connections >= 2 and requests >= 2 and accepted >= 2
                for connections, requests, accepted in before.values())
            (exchange / 'route-check-continue').write_text('ok')
            wait_file(exchange / 'route-check-finished', client, 50)
            after = {side.lower(): et.log_counts(root / (side + '-sshd.log')) for side in ('ET', 'TS')}
            report['negativeWindowServerCounts'] = negative_server_counts(before, after)
            report['negativeServerCountsUnchanged'] = all(
                count == 0 for counts in report['negativeWindowServerCounts'].values() for count in counts.values())
            (exchange / 'route-check-captured').write_text('ok')
        client.wait(timeout=100)
        wait_file(root / 'result.json', client, 1)
        result = json.loads((root / 'result.json').read_text())
        report['client'], report['clientError'] = safe_result(result)
        report['observers'] = {side: safe_observer(result[side + 'Observer']) for side in ('et', 'ts')}
        report['bannerAttempts'], report['bannerConnections'] = safe_banner_counts(result)
        report['routeProbes'] = safe_route_probes(result)
        report['etNodeStateAfterBanner'] = safe_state(result.get('etNodeStateAfterBanner'))
        report['lastTsState'] = safe_state(result.get('lastTsState'))
        et_bytes = (hosts[0][0] / 'received.bin').read_bytes()
        ts_bytes = (hosts[1][0] / 'received.bin').read_bytes()
        expected = ((b'ET-ONE\n', b'TS-ONE\nTS-TWO\n') if stop_first == 'et'
                    else (b'ET-ONE\nET-TWO\n', b'TS-ONE\n'))
        report['independentExactInput'] = (et_bytes, ts_bytes) == expected
        ts_peer.stdin.write(b'{"op":"stop"}\n'); ts_peer.stdin.flush()
        stopped = read_event(events, 'cleanup', ts_peer, 15)
        report['tsPeerCleanup'] = stopped.get('peerClosed') is True and stopped.get('bridgeConnections') == 0
        ts_peer.wait(timeout=10)
        peer_stage = (root / 'peer-stage').read_text() if (root / 'peer-stage').is_file() else ''
        if peer_stage in {'parse-config', 'create-instance', 'start-instance', 'bind-virtual-tcp',
                          'accepting', 'stop-instance', 'drain-bridges', 'stopped'}:
            report['etPeerStageBeforeStop'] = peer_stage
        (root / 'stop-peer').touch(); peer.wait(timeout=15)
        peer_result = json.loads((root / 'peer-result.json').read_text())
        counters = ('acceptedOverlayStreams', 'loopbackTcpConnections', 'activeBridgesAfterStop')
        if (peer_result.get('loopbackDestinationOnly') is not True or
                any(type(peer_result.get(key)) is not int or not 0 <= peer_result[key] <= 256 for key in counters)):
            raise et.Failure('et_peer_result_invalid')
        report['etPeer'] = {key: peer_result[key] for key in counters}
        report['etPeer']['loopbackDestinationOnly'] = True
        if (client.returncode or ts_peer.returncode or peer.returncode
                or not case_passed(report['client'], stop_first)
                or not report['independentExactInput'] or not report['tsPeerCleanup']
                or report.get('negativeServerCountsUnchanged') is not True
                or report.get('negativeServerAuditEstablished') is not True
                or any(value not in {'dial_error', 'stream_eof', 'stream_error'}
                       for value in report['routeProbes'].values())
                or report['etPeer']['activeBridgesAfterStop'] != 0):
            raise et.Failure('dual_acceptance_failed')
        report.update(status='passed', stage='complete')
    finally:
        # A helper can terminate after ready while the product is waiting for
        # its URL. Record only bounded fixed indicators, never raw Go output.
        ts_process = locals().get('ts_peer')
        if ts_process is not None:
            text = bytearray()
            log = root / 'ts-peer.log'
            if log.is_file():
                with log.open('rb') as source:
                    source.seek(max(0, log.stat().st_size - 1048576))
                    text.extend(source.read())
            event_queue = locals().get('events')
            if event_queue is not None:
                while not event_queue.empty() and len(text) < 1048576:
                    try:
                        text.extend(event_queue.get_nowait()[:8192])
                    except queue.Empty:
                        break
            report.update(peer_diagnostics(bytes(text), ts_process.poll()))
        # A failure before the auth handshake may still have produced a safe
        # Rust result. Preserve only allowlisted fields, never its private input.
        result_file = root / 'result.json'
        if result_file.is_file() and 'client' not in report:
            try:
                result = json.loads(result_file.read_text())
                report['client'], report['clientError'] = safe_result(result)
                report['observers'] = {side: safe_observer(result[side + 'Observer']) for side in ('et', 'ts')}
                report['bannerAttempts'], report['bannerConnections'] = safe_banner_counts(result)
                report['routeProbes'] = safe_route_probes(result)
                report['etNodeStateAfterBanner'] = safe_state(result.get('etNodeStateAfterBanner'))
                report['lastTsState'] = safe_state(result.get('lastTsState'))
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
    parser.add_argument('--private-loopback', action='store_true')
    args = parser.parse_args()
    try:
        result = run(args.bundle.resolve(strict=True), args.output.resolve(), args.stop_first, args.private_loopback)
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
