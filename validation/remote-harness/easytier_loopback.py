#!/usr/bin/env python3
"""Opt-in Linux EasyTier -> product OverlayDialer -> real SSH/herdr acceptance.

Prepare downloads/builds pinned public sources before isolation. Run refuses a
network namespace containing anything except lo. Only allowlisted booleans,
counts, hashes and fixed error labels are published; credentials and raw logs
remain in a private temporary tree and are deleted. No GUI/vault/device claim.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

REPO = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('controlled_ssh_bootstrap', HARNESS / 'run-ci.py')
controlled = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controlled)
CASES = ('positive', 'wrong-pin', 'no-route', 'peer-gone')
OVERLAY_HOST = '10.126.126.2'
BOOLS = ('passed', 'nodeStarted', 'candidateAbi', 'sshBannerViaOverlay',
         'peerStoppedBeforeAttempt', 'attemptCheckpointReached', 'frameMarkerPresent', 'nativeStopCompleted')
COUNTS = {'bannerConnections': 64, 'frameColumns': 65535, 'frameRows': 65535,
          'reservedNodesAfterCleanup': 8, 'reservedStreamsAfterCleanup': 32}
ERRORS = {None, 'overlay_provider_unavailable', 'overlay_stale_revision',
          'overlay_wrong_owner', 'overlay_unknown_write', 'overlay_transport_failed',
          'host_key_mismatch', 'cancelled', 'handshake_failed', 'timeout', 'invalid_config',
          'invalid_private_key', 'authentication_failed', 'socket_unavailable', 'snapshot_failed',
          'snapshot_rejected', 'observe_failed', 'invalid_full_frame', 'observe_ended'}
CLIENT_ERRORS = {None, 'real_candidate_feature_required', 'test_executor_failed',
    'invalid_native_config', 'native_node_start_failed', 'product_dialer_create_failed',
    'overlay_banner_missing', 'banner_stream_cleanup_failed', 'peer_stop_request_failed',
    'peer_stop_not_confirmed', 'client_checkpoint_failed', 'client_permission_missing',
    'real_herdr_frame_missing', 'unexpected_transport_failure',
    'negative_case_did_not_reject', 'ssh_stream_cleanup_failed', 'native_cleanup_failed'}


class Failure(Exception):
    """Only fixed labels; never use subprocess output or upstream errors here."""


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_diagnostics(bundle):
    path = bundle / 'build.log'
    text = path.read_text(errors='replace')[-2_097_152:] if path.exists() else ''
    return {'rustErrorCodes': sorted(set(re.findall(r'error\[(E[0-9]{4})\]', text))),
            'locations': [{'file': Path(name).name, 'line': int(line), 'column': int(column)}
                          for name, line, column in re.findall(r'-->\s+([A-Za-z0-9_./-]+\.rs):([0-9]{1,6}):([0-9]{1,6})', text)[:20]]}


def safe_client_result(raw, case):
    if (not isinstance(raw, dict) or type(raw.get('schemaVersion')) is not int
            or raw.get('schemaVersion') != 1 or raw.get('case') != case):
        raise Failure('client_report_schema')
    result = {'schemaVersion': 1, 'case': case}
    for field in BOOLS:
        if type(raw.get(field)) is not bool:
            raise Failure('client_report_boolean')
        result[field] = raw[field]
    for field, upper in COUNTS.items():
        value = raw.get(field)
        if type(value) is not int or not 0 <= value <= upper:
            raise Failure('client_report_counter')
        result[field] = value
    audit = raw.get('audit')
    if not isinstance(audit, dict):
        raise Failure('client_report_audit')
    result['audit'] = {}
    for field in controlled.BOOL_FIELDS:
        if type(audit.get(field)) is not bool:
            raise Failure('client_report_audit')
        result['audit'][field] = audit[field]
    # A failing probe can publish a diagnostic label, never arbitrary text.
    error = raw.get('errorCode')
    if not (error is None or isinstance(error, str)) or error not in CLIENT_ERRORS:
        raise Failure('client_report_error_label')
    result['errorCode'] = error
    transport_error = raw.get('transportErrorCode')
    if not (transport_error is None or isinstance(transport_error, str)) or transport_error not in ERRORS:
        raise Failure('client_report_transport_error')
    result['transportErrorCode'] = transport_error
    return result


def validate_case(result, connections, requests, accepted, target_connections):
    case, audit = result['case'], result['audit']
    if not (result['passed'] and result['nodeStarted'] and result['candidateAbi']
            and result['sshBannerViaOverlay'] and result['bannerConnections'] >= 1
            and result['attemptCheckpointReached'] and connections >= 1
            and result['nativeStopCompleted'] and result['reservedNodesAfterCleanup'] == 0
            and result['reservedStreamsAfterCleanup'] == 0):
        raise Failure('client_case_or_cleanup_failed')
    if case == 'positive':
        if not (all(audit.values()) and result['frameMarkerPresent']
                and result['frameRows'] > 0 and result['frameColumns'] > 0
                and requests >= 1 and accepted == 1 and target_connections == 1):
            raise Failure('real_overlay_frame_not_proven')
    elif case == 'wrong-pin':
        if not (audit['hostKeyChecked'] and not audit['hostKeyMatched']
                and not any(audit[field] for field in ('authStarted', 'snapshotReceived', 'fullFrameReceived'))
                and not result['frameMarkerPresent'] and requests == accepted == 0
                and target_connections == 1
                and result['transportErrorCode'] == 'host_key_mismatch'):
            raise Failure('wrong_pin_zero_auth_not_proven')
    else:
        if (any(audit.values()) or requests or accepted
                or target_connections != 0
                or result['transportErrorCode'] not in ('overlay_transport_failed', 'handshake_failed', 'timeout')):
            raise Failure('no_system_tcp_fallback_not_proven')
        if case == 'peer-gone' and not result['peerStoppedBeforeAttempt']:
            raise Failure('peer_disappearance_not_proven')


def native_config(network, secret, peer_port, server=False):
    # B's public upstream data-plane listener bridges only to its loopback SSH.
    lines = [f'instance_id = "{uuid.uuid4()}"', 'dhcp = false',
             f'ipv4 = "10.126.126.{2 if server else 3}/24"',
             'ipv6_public_addr_provider = false', 'ipv6_public_addr_auto = false',
             'stun_servers = []', 'tcp_stun_servers = []', 'stun_servers_v6 = []',
             f'listeners = {json.dumps([f"tcp://127.0.0.1:{peer_port}"] if server else [])}']
    if not server:
        lines += ['[[peer]]', f'uri = "tcp://127.0.0.1:{peer_port}"']
    lines += ['[network_identity]', f'network_name = {json.dumps(network)}',
              f'network_secret = {json.dumps(secret)}', '[flags]', 'no_tun = true',
              'enable_ipv6 = false', 'disable_upnp = true', 'disable_p2p = true',
              'disable_tcp_hole_punching = true', 'disable_udp_hole_punching = true',
              'enable_exit_node = false', 'accept_dns = false', 'private_mode = true',
              'relay_network_whitelist = ""']
    return '\n'.join(lines) + '\n'


def log_counts(path):
    text = path.read_text(errors='replace') if path.exists() else ''
    return (len(re.findall(r'Connection from 127\.0\.0\.1 port \d+ on ', text)),
            len(re.findall(r'userauth-request for user .* method ', text)),
            len(re.findall(r'Accepted publickey for ', text)))


def checked_namespace(links):
    if (not isinstance(links, list) or len(links) != 1 or links[0].get('ifname') != 'lo'
            or 'UP' not in links[0].get('flags', [])):
        raise Failure('loopback_only_namespace_required')


def checked_paths(bundle, output, runner_temp, run_id):
    root = Path(runner_temp).resolve(strict=True)
    if (bundle.is_symlink() or bundle.parent.resolve() != root
            or bundle.name != 'hp-easytier-bundle-' + run_id):
        raise Failure('owned_bundle_path_required')
    if output.is_symlink() or output.parent.resolve() != root or output.name != 'easytier-evidence':
        raise Failure('owned_evidence_path_required')


def command(argv, *, env=None, cwd=None, timeout=30, log=None):
    if log is not None:
        with log.open('wb') as handle:
            done = subprocess.run([str(x) for x in argv], env=env, cwd=cwd,
                                  stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
    else:
        done = subprocess.run([str(x) for x in argv], env=env, cwd=cwd,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if done.returncode:
        raise Failure('controlled_command_failed')
    return done.stdout if log is None else b''


def initial_report():
    controlled.require_runner(os.environ)
    source = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch('[a-f0-9]{40}', source):
        raise Failure('fixed_source_sha_required')
    return {'schemaVersion': 1, 'milestone': 'easytier-real-overlay-ssh',
            'sourceSHA': source, 'runId': os.environ['GITHUB_RUN_ID'],
            'status': 'running', 'stage': 'prepare', 'cases': [],
            'scope': 'Linux loopback-only namespace; real candidate ABI and product Rust runtime/SSH; temporary in-memory source',
            'unverified': ['GUI', 'platform vault', 'Android', 'physical network', 'three-provider concurrency'],
            'cleanup': {'temporaryCredentialsRemoved': False, 'ownedProcessesStopped': False}}


def prepare(bundle, output, report):
    bundle.mkdir(mode=0o700)
    log = bundle / 'build.log'
    env = {k: v for k, v in os.environ.items() if k != 'CARGO_TARGET_DIR'}
    report['stage'] = 'native-candidate-build'; write_json(output / 'manifest.json', report)
    command([sys.executable, REPO / 'validation/native/tool/portable_candidate.py'],
            env=env, timeout=4200, log=log)
    native_work = Path(env['RUNNER_TEMP']) / ('herdr-native-candidate-' + env['GITHUB_RUN_ID'])
    native = native_work / 'reference/native/easytier'
    # Preserve the reviewed product library; the peer calls only upstream APIs.
    library_dir = bundle / 'lib'; library_dir.mkdir()
    library = library_dir / 'libheeler_easytier.so'
    shutil.copy2(native / 'target/debug/libheeler_easytier.so', library)
    # Add a fixture example, leaving the reviewed library and its lock untouched.
    (native / 'examples').mkdir(exist_ok=True)
    shutil.copy2(HARNESS / 'easytier_peer.rs', native / 'examples/pocket_easytier_peer.rs')
    build_env = dict(env, PROTOC=str(native_work / 'protoc/bin/protoc'), CARGO_BUILD_JOBS='2')
    report['stage'] = 'upstream-peer-build'; write_json(output / 'manifest.json', report)
    command(['cargo', '+1.95.0', 'build', '--locked', '--example', 'pocket_easytier_peer'],
            env=build_env, cwd=native, timeout=900, log=log)
    shutil.copy2(native / 'target/debug/examples/pocket_easytier_peer', bundle / 'peer')
    report['stage'] = 'product-probe-build'; write_json(output / 'manifest.json', report)
    build_env.update(HEELER_ET_LIB_DIR=str(library_dir), CARGO_TARGET_DIR=str(bundle / 'target'))
    command(['cargo', '+1.96.0', 'build', '--locked', '--features', 'real-easytier',
             '--manifest-path', REPO / 'validation/overlay-runtime/easytier-loopback/Cargo.toml'],
            env=build_env, timeout=900, log=log)
    shutil.copy2(bundle / 'target/debug/herdr-easytier-loopback', bundle / 'probe')
    report['stage'] = 'pinned-herdr-download'; write_json(output / 'manifest.json', report)
    with urllib.request.urlopen(controlled.HERDR_URL, timeout=60) as response:
        binary = response.read(100 * 1024 * 1024 + 1)
    if len(binary) > 100 * 1024 * 1024 or hashlib.sha256(binary).hexdigest() != controlled.HERDR_SHA:
        raise Failure('herdr_source_hash_mismatch')
    (bundle / 'herdr').write_bytes(binary); (bundle / 'herdr').chmod(0o700)
    report['provenance'] = {
        'heelerCommit': '6a2817fc02aeb552df251d9478753c22fd4738bb',
        'easytierCommit': '728ba94b5029240add6204eed591f22e4e039e6b',
        'portableManifestSha256': digest(REPO / 'validation/native/patches/portable-manifest.json'),
        'nativeLibrarySha256': digest(library), 'peerBinarySha256': digest(bundle / 'peer'),
        'probeBinarySha256': digest(bundle / 'probe'), 'herdrSha256': controlled.HERDR_SHA}
    report.update(status='prepared', stage='prepared')


def run(bundle, output, report):
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise Failure('linux_unprivileged_runner_required')
    checked_namespace(json.loads(command(['ip', '-j', 'link', 'show'])))
    report['loopbackOnlyNamespace'] = True
    root = Path(tempfile.mkdtemp(prefix='hp-et-', dir='/tmp')); root.chmod(0o700)
    processes = []
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('HERDR_') and k not in ('SSH_AUTH_SOCK', 'SSH_AGENT_PID', 'BASH_ENV')}
    env.update(XDG_CONFIG_HOME=str(root / 'config'), XDG_STATE_HOME=str(root / 'state'),
               XDG_DATA_HOME=str(root / 'data'), XDG_CACHE_HOME=str(root / 'cache'),
               SHELL='/bin/sh', LD_LIBRARY_PATH=str(bundle / 'lib'))

    def spawn(argv, name, privileged=False):
        handle = (root / name).open('wb')
        process = subprocess.Popen([str(x) for x in argv], env=env,
                                   stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append((process, handle, privileged))
        return process

    def wait_file(path, process, seconds=15):
        until = time.monotonic() + seconds
        while not path.exists():
            if process.poll() is not None: raise Failure('controlled_peer_exited_early')
            if time.monotonic() >= until: raise Failure('controlled_ready_timeout')
            time.sleep(0.05)

    def free_port():
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0)); return reserve.getsockname()[1]

    def canary(port):
        until = time.monotonic() + 5
        while True:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.5) as connection:
                    return connection.recv(256).startswith(b'SSH-2.0-')
            except OSError:
                if time.monotonic() >= until: raise Failure('local_ssh_canary_unavailable')
                time.sleep(0.05)

    try:
        report['stage'] = 'isolated-ssh-herdr-fixture'; write_json(output / 'manifest.json', report)
        shutil.copy2(bundle / 'herdr', root / 'herdr')
        for key in ('host', 'wrong', 'client'):
            command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C',
                     'ephemeral-easytier-acceptance', '-f', root / key], env=env)
        authorized = root / 'authorized_keys'; authorized.write_bytes((root / 'client.pub').read_bytes())
        authorized.chmod(0o600)
        ssh_port, peer_port = free_port(), free_port()
        username = pwd.getpwuid(os.getuid()).pw_name
        config = root / 'sshd_config'
        config.write_text(f'''Port {ssh_port}
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
UseDNS no
LogLevel DEBUG3
''')
        command(['sudo', 'mkdir', '-p', '/run/sshd'])
        command(['sudo', '/usr/sbin/sshd', '-t', '-f', config], env=env)
        sshd = spawn(['sudo', '/usr/sbin/sshd', '-D', '-e', '-f', config], 'sshd.log', True)
        report['localSshCanaryBeforeOverlay'] = canary(ssh_port)
        fixture_config = root / 'config/herdr'; fixture_config.mkdir(parents=True)
        (fixture_config / 'config.toml').write_text('[update]\nversion_check = false\nmanifest_check = false\n')
        herdr = spawn([root / 'herdr', '--session', 'pocket-probe', 'server'], 'herdr.log')
        sock = fixture_config / 'sessions/pocket-probe/herdr.sock'
        wait_file(sock, herdr)
        until = time.monotonic() + 15
        while True:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as ready:
                    ready.settimeout(0.5); ready.connect(str(sock))
                    ready.sendall(b'{"id":"readiness","method":"session.snapshot","params":{}}\n')
                    data = bytearray()
                    while b'\n' not in data and len(data) <= 1_048_576:
                        chunk = ready.recv(4096)
                        if not chunk: break
                        data.extend(chunk)
                    value = json.loads(data.split(b'\n', 1)[0])
                    if len(data) <= 1_048_576 and isinstance(value.get('result'), dict): break
            except (OSError, ValueError):
                pass
            if time.monotonic() >= until or herdr.poll() is not None:
                raise Failure('herdr_readiness_timeout')
            time.sleep(0.05)
        created = json.loads(command([root / 'herdr', '--session', 'pocket-probe', 'workspace',
                                      'create', '--cwd', root, '--label', 'easytier-readonly'], env=env))
        pane = created['result']['root_pane']['pane_id']
        if not isinstance(pane, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}', pane):
            raise Failure('controlled_pane_invalid')
        shutil.copy2(HARNESS / 'capture_input.py', root / 'capture_input.py')
        shutil.copy2(REPO / 'validation/shared/fixture.json', root / 'terminal-fixture.json')
        command([root / 'herdr', '--session', 'pocket-probe', 'pane', 'run', pane,
                 shlex.join(['/usr/bin/python3', str(root / 'capture_input.py')])], env=env)
        wait_file(root / 'capture-ready', herdr)
        network, secret = 'hp-loopback-' + secrets.token_hex(12), secrets.token_hex(32)
        peer_config = root / 'peer.toml'
        peer_config.write_text(native_config(network, secret, peer_port, server=True)); peer_config.chmod(0o600)
        peer = spawn([bundle / 'peer', peer_config, root, ssh_port], 'peer.log')
        wait_file(root / 'peer-ready', peer)
        virtual_port = json.loads((root / 'peer-ready').read_text()).get('virtualTcpPort')
        if type(virtual_port) is not int or not 1 <= virtual_port <= 65535:
            raise Failure('controlled_virtual_port_invalid')
        remote = {'schemaVersion': 1, 'host': OVERLAY_HOST, 'port': virtual_port, 'username': username,
                  'expectedHostKey': ' '.join((root / 'host.pub').read_text().split()[:2]),
                  'privateKeyPem': (root / 'client').read_text(), 'socketPath': str(sock),
                  'herdrPath': str(root / 'herdr'), 'session': 'pocket-probe', 'paneId': pane,
                  'reviewConfirmed': True}
        for case in CASES:
            report['stage'] = 'probe-' + case; write_json(output / 'manifest.json', report)
            request = dict(remote)
            if case == 'wrong-pin': request['expectedHostKey'] = ' '.join((root / 'wrong.pub').read_text().split()[:2])
            if case == 'no-route': request.update(host='127.0.0.1', port=ssh_port)
            case_input, case_output = root / 'client-input.json', root / 'client-result.json'
            write_json(case_input, {'case': case, 'network': network,
                'nativeConfig': native_config(network, secret, peer_port), 'overlayHost': OVERLAY_HOST,
                'overlayPort': virtual_port,
                'peerControl': str(root), 'remote': request}); case_input.chmod(0o600)
            case_output.unlink(missing_ok=True)
            (root / 'client-ready').unlink(missing_ok=True)
            (root / 'continue-client').unlink(missing_ok=True)
            time.sleep(0.1); before = log_counts(root / 'sshd.log')
            process = spawn([bundle / 'probe', case_input, case_output], 'client.log')
            wait_file(root / 'client-ready', process, seconds=45)
            if (root / 'client-ready').read_text() != case:
                raise Failure('client_checkpoint_case_mismatch')
            checkpoint = log_counts(root / 'sshd.log')
            (root / 'continue-client').write_text(case)
            process.wait(timeout=40)
            if not case_output.is_file(): raise Failure('client_report_missing')
            result = safe_client_result(json.loads(case_output.read_text()), case)
            time.sleep(0.1); after = log_counts(root / 'sshd.log')
            counts = [end - start for start, end in zip(before, after)]
            target_counts = [end - start for start, end in zip(checkpoint, after)]
            result.update(sshConnections=counts[0], serverAuthRequests=counts[1], serverAuthAccepted=counts[2])
            result.update(targetAttemptSshConnections=target_counts[0],
                          targetAttemptAuthRequests=target_counts[1], targetAttemptAuthAccepted=target_counts[2])
            report['cases'].append(result); write_json(output / 'manifest.json', report)
            validate_case(result, *counts, target_counts[0])
            if process.returncode: raise Failure('client_exit_nonzero')
        peer.wait(timeout=8)
        report['peerStoppedCleanly'] = peer.returncode == 0 and (root / 'peer-stopped').is_file()
        peer_result = json.loads((root / 'peer-result.json').read_text())
        counters = ('acceptedOverlayStreams', 'loopbackTcpConnections', 'activeBridgesAfterStop')
        if (peer_result.get('schemaVersion') != 1 or peer_result.get('loopbackDestinationOnly') is not True
                or any(type(peer_result.get(field)) is not int or not 0 <= peer_result[field] <= 256 for field in counters)):
            raise Failure('peer_evidence_invalid')
        report['peer'] = {field: peer_result[field] for field in counters}
        report['peer']['loopbackDestinationOnly'] = True
        if (peer_result['activeBridgesAfterStop'] != 0
                or peer_result['acceptedOverlayStreams'] != peer_result['loopbackTcpConnections']
                or peer_result['loopbackTcpConnections'] != sum(case['sshConnections'] for case in report['cases'])):
            raise Failure('independent_peer_connections_not_matched')
        report['localSshCanaryAfterPeerStopped'] = canary(ssh_port)
        report['inputBytes'] = (root / 'received.bin').stat().st_size
        report['readOnlyZeroInput'] = report['inputBytes'] == 0
        if not all(report[x] for x in ('peerStoppedCleanly', 'localSshCanaryAfterPeerStopped', 'readOnlyZeroInput')):
            raise Failure('final_peer_or_readonly_state_failed')
        report.update(status='passed', stage='complete')
    finally:
        (root / 'stop-capture').touch(); (root / 'stop-peer').touch()
        time.sleep(0.2)
        for process, handle, privileged in reversed(processes):
            try:
                if process.poll() is None:
                    if privileged:
                        subprocess.run(['sudo', 'kill', '-TERM', '--', '-' + str(process.pid)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                    else: os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        if privileged:
                            subprocess.run(['sudo', 'kill', '-KILL', '--', '-' + str(process.pid)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                        else: os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            finally:
                handle.close()
        report['cleanup']['ownedProcessesStopped'] = all(p.poll() is not None for p, _, _ in processes)
        stages = {'parse-config', 'create-instance', 'start-instance', 'bind-virtual-tcp',
                  'accepting', 'stop-instance', 'drain-bridges', 'stopped'}
        if (root / 'peer-stage').is_file():
            stage = (root / 'peer-stage').read_text()
            if stage in stages: report['peerStage'] = stage
        shutil.rmtree(root)
        report['cleanup']['temporaryCredentialsRemoved'] = not root.exists()


def finalize(bundle, report, namespace):
    expected = 'hp-et-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    if namespace != expected:
        raise Failure('owned_namespace_name_required')
    names = command(['ip', 'netns', 'list']).decode().splitlines()
    exists = any(line.split()[0] == namespace for line in names if line.split())
    remaining = []
    if exists:
        text = command(['sudo', 'ip', 'netns', 'pids', namespace]).decode().split()
        if any(not re.fullmatch(r'[1-9][0-9]*', item) for item in text):
            raise Failure('invalid_namespace_process_list')
        until = time.monotonic() + 3
        while text and time.monotonic() < until:
            time.sleep(0.05)
            text = command(['sudo', 'ip', 'netns', 'pids', namespace]).decode().split()
        remaining = text
        if remaining:
            subprocess.run(['sudo', 'kill', '-TERM', '--', *remaining],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            time.sleep(0.2)
            live = command(['sudo', 'ip', 'netns', 'pids', namespace]).decode().split()
            if live:
                command(['sudo', 'kill', '-KILL', '--', *live])
        command(['sudo', 'ip', 'netns', 'delete', namespace])
    report['cleanup']['namespaceProcessesBeforeTeardown'] = len(remaining)
    report['cleanup']['namespaceRemoved'] = not any(
        line.split()[0] == namespace for line in command(['ip', 'netns', 'list']).decode().splitlines() if line.split())
    if bundle.exists(): shutil.rmtree(bundle)
    report['cleanup']['preparedBundleRemoved'] = not bundle.exists()
    if remaining:
        report.update(status='failed', errorCode='namespace_process_leak')
    if report['status'] == 'prepared':
        report.update(status='failed', errorCode='isolated_run_not_started')
    if report['status'] == 'passed' and not all(report['cleanup'][field] for field in
            ('temporaryCredentialsRemoved', 'ownedProcessesStopped', 'namespaceRemoved', 'preparedBundleRemoved')):
        raise Failure('final_cleanup_incomplete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'run', 'finalize'))
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--namespace')
    args = parser.parse_args()
    try:
        report = initial_report()
        checked_paths(args.bundle, args.output, os.environ.get('RUNNER_TEMP', ''), os.environ['GITHUB_RUN_ID'])
    except Failure as error:
        print(json.dumps({'status': 'failed', 'stage': 'precondition', 'errorCode': str(error)}))
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        if args.phase == 'prepare': prepare(args.bundle, args.output, report)
        else:
            report = json.loads((args.output / 'manifest.json').read_text())
            if args.phase == 'finalize': finalize(args.bundle, report, args.namespace)
            else:
                if report.get('status') != 'prepared': raise Failure('prepared_bundle_required')
                run(args.bundle.resolve(strict=True), args.output, report)
    except Exception as error:
        report['status'] = 'failed'
        report['errorCode'] = (str(error) if isinstance(error, Failure)
                               else 'controlled_timeout' if isinstance(error, subprocess.TimeoutExpired)
                               else 'invalid_controlled_json' if isinstance(error, json.JSONDecodeError)
                               else 'unexpected_runner_error')
        report['errorKind'] = type(error).__name__
        if args.phase == 'prepare': report['buildDiagnostics'] = build_diagnostics(args.bundle)
    write_json(args.output / 'manifest.json', report)
    print(json.dumps({'status': report['status'], 'stage': report['stage'],
                      'errorCode': report.get('errorCode')}))
    return 0 if report['status'] in ('prepared', 'passed') else 1


if __name__ == '__main__':
    sys.exit(main())
