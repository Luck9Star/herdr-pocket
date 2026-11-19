#!/usr/bin/env python3
"""Private host-side QA control; does not launch an Android app or adb reverse.

Run inside the existing isolated Linux lo + TEST-NET dummy namespace, with a
reviewed bundle containing herdr, peer, and ts-fixture. stdout is a private
JSON control channel; only public pairing records are returned. Network secrets
and host profiles are written to owned private files, never to an evidence log.
Android TS reachability is established by later real SSH/data, not port setup.
"""
import argparse
import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import queue
import re
import secrets
import selectors
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

from dual_overlay_loopback import check_current_namespace, read_event
from easytier_loopback import native_config
from paired_dual_demo import prepared_pairing_hosts
from paired_gui import GuiFailure, bounded_wire, owned_process, wait_for
from herdr_pocket_helper.profile import encode_profile


class HostControlError(RuntimeError):
    pass


STARTUP_STAGES = {'initialization', 'work_validation', 'bundle_validation', 'host_directory', 'et_peer_start', 'et_peer_ready',
    'ts_peer_start', 'ts_peer_ready', 'et_second_peer_start', 'et_second_peer_ready', 'materials', 'unknown'} | {
    role + '_' + step for role in ('et', 'ts') for step in
    ('version', 'host_key', 'privsep_prepare', 'sshd_check', 'sshd_start', 'herdr_start', 'workspace_create', 'capture_start', 'profile')}
STARTUP_ERRORS = {'fixture_startup_failed', 'paired_fixture_command_failed', 'sshd_privsep_directory_missing',
    'fixture_shell_unavailable', 'fixture_permission_denied', 'fixture_dynamic_dependency_missing',
    'fixture_command_failed', 'fixture_herdr_version_mismatch', 'fixture_command_timeout',
    'controlled_et_peer_not_ready', 'controlled_et_peer_exited', 'controlled_ts_material_invalid',
    'ts_fixture_exited_early', 'ts_fixture_event_invalid', 'ts_fixture_event_timeout', 'fixture_value_rejected',
    'empty_owned_private_work_directory_required', 'reviewed_fixture_binary_required',
    'isolated_unprivileged_linux_required', 'local_probe_requires_macos_provider_sandbox'}


def safe_startup_failure(value):
    if (isinstance(value, dict) and isinstance(value.get('stage'), str) and isinstance(value.get('errorCode'), str)
            and value['stage'] in STARTUP_STAGES and value['errorCode'] in STARTUP_ERRORS):
        return {'stage': value['stage'], 'errorCode': value['errorCode']}
    return {'stage': 'unknown', 'errorCode': 'fixture_startup_failed'}


def write_private(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream)
        stream.write('\n')


def live_ssh_ports(port):
    """Private source ports correlate sshd acceptance to its actual TCP lifetime."""
    if sys.platform == 'linux':
        text = subprocess.check_output(['ss', '-Htn', 'state', 'established'], text=True)
    elif sys.platform == 'darwin':
        process = subprocess.run(['/usr/sbin/lsof', '-nP', '-iTCP:' + str(port),
                                  '-sTCP:ESTABLISHED', '-Fn'], capture_output=True, text=True)
        if process.returncode not in (0, 1):
            raise HostControlError('session_socket_audit_failed')
        text = process.stdout.replace('->', ' ')
    else:
        raise HostControlError('session_socket_audit_unavailable')
    pattern = r'127\.0\.0\.1:' + str(port) + r'\s+127\.0\.0\.1:([0-9]+)(?:\s|$)'
    return {int(value) for value in re.findall(pattern, text)}


class PairingControl:
    """Approve public requests and audit independent host evidence, not app flags."""
    def __init__(self, targets, complete_auth, control_url, active_ports=live_ssh_ports, diagnostics=None,
                 *, shared_easytier=False):
        self.targets = targets
        self.complete_auth = complete_auth
        self.diagnostics = diagnostics
        self.shared_easytier = shared_easytier
        self.control_origin = None if shared_easytier else urlsplit(control_url)
        if not shared_easytier and (self.control_origin.scheme != 'https' or self.control_origin.hostname != '127.0.0.1'):
            raise HostControlError('isolated_test_control_required')
        self.active_ports = active_ports
        self.previous = {role: (0, 0) for role in targets}

    def dispatch(self, request):
        operation = request.get('op')
        if operation == 'ts_diagnostics':
            if set(request) != {'op'} or self.diagnostics is None:
                raise HostControlError('ts_diagnostics_unavailable')
            value = self.diagnostics()
            counters = ('keyRequests', 'noiseRequests', 'registerRequests', 'mapRequests', 'tlsHandshakeErrors', 'authCompletions')
            if (not isinstance(value, dict) or set(value) != {'event', 'secondClientRegistered', *counters}
                    or value.get('event') != 'diagnostics' or type(value.get('secondClientRegistered')) is not bool
                    or any(type(value.get(key)) is not int or not 0 <= value[key] <= 1000000 for key in counters)):
                raise HostControlError('ts_diagnostics_invalid')
            return dict(value, event='ts_diagnostics')
        if operation == 'complete_ts_auth':
            url = request.get('url')
            if (self.control_origin is None or request.get('authorize') is not True
                    or not isinstance(url, str) or len(url) > 4096):
                raise HostControlError('explicit_ts_authorization_required')
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or parsed.netloc != self.control_origin.netloc
                    or parsed.username is not None or parsed.password is not None):
                raise HostControlError('fixture_auth_origin_mismatch')
            if self.complete_auth(url) is not True:
                raise HostControlError('fixture_auth_not_completed')
            return {'event': 'ts_authorized', 'ok': True}
        role = request.get('role')
        if role not in self.targets:
            raise HostControlError('fixture_role_required')
        target = self.targets[role]
        if operation in ('review_pairing', 'approve_pairing'):
            raw = request.get('request')
            if not isinstance(raw, str) or not 0 < len(raw) <= 65536:
                raise HostControlError('public_pairing_request_required')
            raw = raw.encode()
            if operation == 'review_pairing':
                return dict(event='pairing_review', role=role, **target.review(raw))
            response = target.approve(raw, request_id=request.get('requestId'),
                device_fingerprint=request.get('deviceFingerprint'), reviewed=request.get('reviewed'))
            return {'event': 'pairing_approved', 'role': role, 'response': response.decode()}
        if operation == 'revoke_pairing':
            response = target.revoke()
            return {'event': 'pairing_revoked', 'role': role,
                    'response': response.decode() if response else None}
        if operation == 'audit':
            encoded = request.get('expectedBase64')
            if not isinstance(encoded, str) or len(encoded) > 5500:
                raise HostControlError('bounded_synthetic_expected_bytes_required')
            try:
                expected = base64.b64decode(encoded, validate=True)
            except ValueError:
                raise HostControlError('bounded_synthetic_expected_bytes_required') from None
            if len(expected) > 4096:
                raise HostControlError('bounded_synthetic_expected_bytes_required')
            return dict(event='host_audit', role=role, **self.audit(role, expected))
        raise HostControlError('unsupported_host_operation')

    def audit(self, role, expected):
        target = self.targets[role]
        text = bounded_wire(target.root / 'sshd.log', 2097152).decode(errors='replace')
        pattern = (r'Accepted publickey for ' + re.escape(target.config['username'])
            + r' from 127\.0\.0\.1 port ([0-9]+) ssh2: ED25519 (SHA256:[A-Za-z0-9+/]+)(?:\s|$)')
        accepted = list(re.finditer(pattern, text))
        active = self.active_ports(target.config['port'])
        captured = bounded_wire(target.root / 'received.bin', 4096)
        prior_sessions, prior_bytes = self.previous[role]
        if len(accepted) < prior_sessions or len(captured) < prior_bytes:
            raise HostControlError('host_evidence_not_monotonic')
        self.previous[role] = (len(accepted), len(captured))
        # Multiple authenticated sessions make per-session attribution ambiguous.
        # Never assign a shared pane's bytes to a guessed reconnect boundary.
        last_port_owner = {int(match[1]): index for index, match in enumerate(accepted)}
        sessions = [{'ordinal': index + 1, 'approvedDevice': match[2] == target.approval.fingerprint,
                     'active': int(match[1]) in active and last_port_owner[int(match[1])] == index,
                     'capturedBytes': len(captured) if len(accepted) == 1 else None}
                    for index, match in enumerate(accepted)]
        if self.shared_easytier:
            for session, match in zip(sessions, accepted):
                session['peerClose'] = observed_peer_close(text[match.end():], match[1])
        return {'acceptedSessions': len(accepted), 'newSessions': len(accepted) - prior_sessions,
                'sessions': sessions, 'capturedBytes': len(captured),
                'newInputBytes': len(captured) - prior_bytes, 'exactBytes': captured == expected,
                'authorizationActive': bool((target.root / 'authorized_keys').read_bytes()),
                'soleApprovedSession': len(sessions) == 1 and sessions[0]['approvedDevice'],
                'inputAttributionAmbiguous': len(sessions) > 1}


def observed_peer_close(text, port):
    source = r'127\.0\.0\.1 port ' + re.escape(port) + r'(?=[:\s]|$)'
    if re.search(r'^Received disconnect from ' + source, text, re.MULTILINE):
        return 'client_disconnect'
    if re.search(r'^Connection closed by (?:user [^\r\n]+ )?' + source, text, re.MULTILINE):
        return 'peer_eof'
    if (re.search(r'^Connection reset by (?:user [^\r\n]+ )?' + source, text, re.MULTILINE)
            or re.search(r'^Read error from (?:user [^\r\n]+ )?' + source + r': Connection reset by peer',
                         text, re.MULTILINE)):
        return 'peer_reset'
    return 'unconfirmed'


class HostHarness:
    def __init__(self, bundle, root, *, lifetime=900, local_probe=False, provider_prefix=(), shared_easytier=False):
        if type(lifetime) is not int or not 60 <= lifetime <= 1800:
            raise HostControlError('bounded_fixture_lifetime_required')
        self.lifetime = lifetime
        self.shared_easytier = shared_easytier
        self.bundle, self.root = Path(bundle), Path(root)
        self.local_probe, self.provider_prefix = local_probe, list(provider_prefix)
        self.stack = ExitStack()
        self.children = []
        self.ts = None
        self.peer = self.second_peer = None
        self.closed = False
        self.phase = 'initialization'
        self.startup_failure = None

    def __enter__(self):
        try:
            self.start()
            return self
        except BaseException as error:
            code = getattr(error, 'fixture_code', str(error))
            if isinstance(error, subprocess.TimeoutExpired): code = 'fixture_command_timeout'
            elif isinstance(error, ValueError): code = 'fixture_value_rejected'
            self.startup_failure = safe_startup_failure({'stage': self.phase, 'errorCode': code})
            self.close()
            if getattr(self, 'work_owned', False):
                write_private(self.root / 'startup-error.json', self.startup_failure)
            raise

    def set_phase(self, phase):
        if phase not in STARTUP_STAGES: raise HostControlError('fixture_startup_failed')
        self.phase = phase

    def start(self):
        if not self.local_probe:
            if sys.platform != 'linux' or os.geteuid() == 0:
                raise HostControlError('isolated_unprivileged_linux_required')
            check_current_namespace()
        elif sys.platform != 'darwin' or not self.provider_prefix:
            raise HostControlError('local_probe_requires_macos_provider_sandbox')
        self.set_phase('work_validation')
        info = self.root.stat()
        if self.root.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077 or any(self.root.iterdir()):
            raise HostControlError('empty_owned_private_work_directory_required')
        self.work_owned = True
        self.set_phase('bundle_validation')
        for name in (('herdr', 'peer') if self.shared_easytier else ('herdr', 'peer', 'ts-fixture')):
            path = self.bundle / name
            if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
                raise HostControlError('reviewed_fixture_binary_required')
        # PairingTarget deliberately accepts only owned temporary fixture roots.
        # Keep hosts in /tmp while relay/material files live in RUNNER_TEMP.
        self.set_phase('host_directory')
        hosts = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='hp-device-hosts-', dir='/tmp')))
        self.host_directory = hosts.resolve(strict=True)
        write_private(self.root / 'host-owner.json', {'directory': str(self.host_directory),
            'inode': self.host_directory.stat().st_ino, 'owner': os.getuid()})
        self.targets, self.host_processes, _ = self.stack.enter_context(prepared_pairing_hosts(
            self.bundle / 'herdr', hosts, self.set_phase, input_ack=True))
        self.env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(self.root),
                    'XDG_CONFIG_HOME': str(self.root / 'config'), 'LANG': 'C.UTF-8',
                    'PYTHONDONTWRITEBYTECODE': '1'}
        network, secret = 'hp-device-' + secrets.token_hex(12), secrets.token_hex(32)
        self.peer, peer_port, virtual_port = self.start_et_peer('et', network, secret)
        if self.shared_easytier:
            self.second_peer, second_port, second_virtual_port = self.start_et_peer('ts', network, secret)
            self.control = PairingControl(self.targets, None, None, shared_easytier=True)
            self.write_materials(network, secret,
                [('et', '10.126.126.2', virtual_port), ('ts', '10.126.126.4', second_virtual_port)],
                {'easytier': (peer_port, self.peer.pid), 'easytierSecond': (second_port, self.second_peer.pid)})
            return
        ts_root = self.root / 'ts-peer'; ts_root.mkdir(mode=0o700)
        self.set_phase('ts_peer_start')
        self.ts = subprocess.Popen(self.provider_prefix + [str(self.bundle / 'ts-fixture'),
            '-test.run=^TestServeFixture$', '-test.timeout=' + str(self.lifetime + 90) + 's'], cwd=self.root,
            env=dict(self.env, HP_TS_FIXTURE_WORK_DIR=str(ts_root),
                     HP_TS_FIXTURE_BRIDGE='127.0.0.1:' + str(self.targets['ts'].config['port'])),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.children.append(self.ts)
        self.events = queue.Queue()
        def collect():
            for line in iter(lambda: self.ts.stdout.readline(131073), b''):
                if len(line) > 131072:
                    break
                self.events.put(line)
        self.collector = threading.Thread(target=collect, daemon=True); self.collector.start()
        self.set_phase('ts_peer_ready')
        ready = read_event(self.events, 'ready', self.ts)
        control = urlsplit(ready['controlUrl'])
        if control.scheme != 'https' or control.hostname != '127.0.0.1' or ready['peerPort'] != 2222:
            raise HostControlError('controlled_ts_material_invalid')
        self.control = PairingControl(self.targets, self.complete_auth, ready['controlUrl'], diagnostics=self.ts_diagnostics)
        self.write_materials(network, secret, [('et', '10.126.126.2', virtual_port), ('ts', ready['peerIp'], 2222)],
            {'control': (control.port, self.ts.pid), 'derp': (ready['derpPort'], self.ts.pid),
             'easytier': (peer_port, self.peer.pid)},
            {'caFile': ready['caFile'], 'controlUrl': ready['controlUrl']})

    def start_et_peer(self, role, network, secret):
        tag = 'et' if role == 'et' else 'et-second'
        phase = tag.replace('-', '_')
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0)); peer_port = reserve.getsockname()[1]
        peer_root = self.root / (tag + '-peer'); peer_root.mkdir(mode=0o700)
        config = self.root / (tag + '-peer.toml')
        descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        config_text = native_config(network, secret, peer_port, server=True)
        if role != 'et':
            config_text = config_text.replace('ipv4 = "10.126.126.2/24"', 'ipv4 = "10.126.126.4/24"')
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(config_text)
        self.set_phase(phase + '_peer_start')
        peer = self.stack.enter_context(owned_process(self.provider_prefix +
            [str(self.bundle / 'peer'), str(config), str(peer_root), str(self.targets[role].config['port']),
             str(self.lifetime + 60)],
            cwd=self.root, env=self.env, log=self.root / (tag + '-peer.private.log')))
        self.children.append(peer)
        self.set_phase(phase + '_peer_ready')
        wait_for(lambda: (peer_root / 'peer-ready').is_file() or peer.poll() is not None,
                 'controlled_et_peer_not_ready', timeout=15)
        if peer.poll() is not None:
            raise HostControlError('controlled_et_peer_exited')
        virtual_port = json.loads((peer_root / 'peer-ready').read_text())['virtualTcpPort']
        return peer, peer_port, virtual_port

    def write_materials(self, network, secret, endpoints, relay_roles, ts_materials=None):
        self.set_phase('materials')
        profiles = {}
        for role, host, port in endpoints:
            target = self.targets[role]
            value = json.loads(target.public_profile())
            value.update(host=host, port=port)
            if self.shared_easytier:
                value['provider'] = 'easytier'
            profile = self.root / (role + '-host-profile.json')
            profile.write_bytes(encode_profile(value)); profile.chmod(0o600)
            profiles[role] = str(profile)
        peers = ['tcp://127.0.0.1:' + str(port) for role, (port, _) in relay_roles.items()
                 if role in ('easytier', 'easytierSecond')]
        materials = {'hostProfiles': profiles, **(ts_materials or {}),
                     'etNetwork': {'networkName': network, 'networkSecret': secret,
                                   'peerUrl': '\n'.join(peers)},
                     'udpStunRelayed': False, 'deviceTailscaleReachabilityVerified': False,
                     'clientAddressPolicy': 'Android DHCP; no fixed-client-IP acceptance condition'}
        write_private(self.root / 'materials.json', materials)
        self.relay = None
        if not self.local_probe:
            namespace = 'hp-dual-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ.get('GITHUB_RUN_ATTEMPT', '1')
            self.relay = {'namespace': namespace, **{role: port for role, (port, _) in relay_roles.items()},
                          'ownerPids': {role: pid for role, (_, pid) in relay_roles.items()},
                          'sshPorts': [target.config['port'] for target in self.targets.values()]}
            write_private(self.root / 'relay.json', self.relay)

    def ts_diagnostics(self):
        self.ts.stdin.write(b'{"op":"diagnostics"}\n')
        self.ts.stdin.flush()
        return read_event(self.events, 'diagnostics', self.ts)

    def complete_auth(self, url):
        request = (json.dumps({'op': 'complete_auth', 'url': url}) + '\n').encode()
        if len(request) > 8192:
            raise HostControlError('bounded_fixture_auth_request_required')
        self.ts.stdin.write(request)
        self.ts.stdin.flush()
        return read_event(self.events, 'auth_completed', self.ts).get('ok') is True

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.shared_peer_streams = {}
        self.cleanup = {'etPeerCleanup': False,
                        'etSecondPeerCleanup' if self.shared_easytier else 'tsPeerCleanup': False}
        try:
            if self.ts is not None and self.ts.poll() is None:
                self.ts.stdin.write(b'{"op":"stop"}\n'); self.ts.stdin.flush()
                event = read_event(self.events, 'cleanup', self.ts)
                self.cleanup['tsPeerCleanup'] = (event.get('peerClosed') is True
                    and event.get('bridgeConnections') == 0 and self.ts.wait(timeout=8) == 0)
            peers = [('et-peer', self.peer, 'etPeerCleanup')]
            if self.shared_easytier:
                peers.append(('et-second-peer', self.second_peer, 'etSecondPeerCleanup'))
            for directory, peer, check in peers:
                if peer is not None and peer.poll() is None:
                    peer_root = self.root / directory
                    (peer_root / 'stop-peer').touch()
                    if peer.wait(timeout=10) == 0:
                        stats = json.loads((peer_root / 'peer-result.json').read_text())
                        self.cleanup[check] = stats.get('activeBridgesAfterStop') == 0
                        if self.shared_easytier:
                            name = 'a' if directory == 'et-peer' else 'b'
                            counts = {key: stats.get(key) for key in
                                      ('acceptedOverlayStreams', 'loopbackTcpConnections')}
                            if all(type(value) is int and 0 <= value <= 64 for value in counts.values()):
                                self.shared_peer_streams[name] = counts
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
        finally:
            for child in self.children:
                if child.poll() is None:
                    child.terminate()
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired: child.kill(); child.wait()
            self.cleanup['hostContextsClosed'] = True
            try:
                self.stack.close()
            except Exception:
                self.cleanup['hostContextsClosed'] = False
            if hasattr(self, 'collector'):
                self.collector.join(timeout=2)
                self.cleanup['collectorStopped'] = not self.collector.is_alive()
                self.ts.stdin.close()
                self.ts.stdout.close()
            for target in getattr(self, 'targets', {}).values():
                for name in ('host', 'host.pub', 'public-profile.json', 'peer.json', 'known_hosts'):
                    (target.root / name).unlink(missing_ok=True)
            for name in ('materials.json', 'et-peer.toml', 'et-second-peer.toml', 'et-host-profile.json', 'ts-host-profile.json', 'relay.json'):
                (self.root / name).unlink(missing_ok=True)
            self.cleanup['privateMaterialsRemoved'] = not any((self.root / name).exists() for name in
                ('materials.json', 'et-peer.toml', 'et-second-peer.toml', 'et-host-profile.json', 'ts-host-profile.json', 'relay.json'))
            self.cleanup['ownedProcessesStopped'] = all(child.poll() is not None
                for child in self.children + getattr(self, 'host_processes', []))
            self.cleanup['temporaryAuthorizationsCleared'] = all(
                not (target.root / 'authorized_keys').exists() or not (target.root / 'authorized_keys').read_bytes()
                for target in getattr(self, 'targets', {}).values())
            self.cleanup['temporaryHostCredentialsRemoved'] = (not hasattr(self, 'host_directory')
                or not self.host_directory.exists())
            if self.cleanup['temporaryHostCredentialsRemoved']:
                (self.root / 'host-owner.json').unlink(missing_ok=True)

    def __exit__(self, *_):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--lifetime', type=int, default=900, help='owned QA session seconds, 60..1800; does not change pairing/auth expiry')
    parser.add_argument('--shared-easytier', action='store_true')
    args = parser.parse_args()
    if not 60 <= args.lifetime <= 1800:
        parser.error('--lifetime must be 60..1800')
    harness = HostHarness(args.bundle.resolve(strict=True), args.work.resolve(strict=True), lifetime=args.lifetime,
                          shared_easytier=args.shared_easytier)
    def emit(value):
        print(json.dumps(value), flush=True)
    try:
        with harness:
            emit({'event': 'ready', 'materialFile': str(args.work / 'materials.json'),
                  'relayManifestFile': str(args.work / 'relay.json'), 'deviceReachabilityVerified': False})
            selector = selectors.DefaultSelector(); selector.register(sys.stdin.fileno(), selectors.EVENT_READ)
            deadline = time.monotonic() + args.lifetime
            pending = bytearray()
            reason = 'lifetime-expired'
            stopping = False
            try:
                while time.monotonic() < deadline and not stopping:
                    if any(child.poll() is not None for child in harness.children):
                        reason = 'provider-exited'
                        emit({'event': 'fixture_unavailable'})
                        break
                    if not selector.select(min(1, max(0, deadline - time.monotonic()))):
                        continue
                    raw = os.read(sys.stdin.fileno(), 65536)
                    if not raw:
                        reason = 'control-eof'
                        break
                    pending.extend(raw)
                    while b'\n' in pending:
                        raw, _, rest = pending.partition(b'\n'); pending = bytearray(rest)
                        if len(raw) > 131072: raise HostControlError('bounded_control_request_required')
                        try:
                            request = json.loads(raw)
                            if not isinstance(request, dict): raise HostControlError('object_required')
                            if request.get('op') == 'stop':
                                reason, stopping = 'explicit-stop', True
                                break
                            emit(harness.control.dispatch(request))
                        except (HostControlError, GuiFailure, ValueError, KeyError):
                            emit({'event': 'rejected'})
                    if len(pending) > 131072: raise HostControlError('bounded_control_request_required')
            finally:
                selector.close()
        report = dict(event='cleanup', stopReason=reason, **harness.cleanup)
        if args.shared_easytier:
            report['sharedPeerStreams'] = harness.shared_peer_streams
        emit(report)
        return 0 if all(harness.cleanup.values()) and reason != 'provider-exited' else 1
    except Exception:
        emit(dict(event='failed', **safe_startup_failure(harness.startup_failure)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
