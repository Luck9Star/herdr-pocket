#!/usr/bin/env python3
"""Shared owned Linux/API35 host, relay and reverse lifetime for both shells.

Build/install the chosen app and prepare the disposable AVD before entering.
One direction gets one fresh context; app data reset belongs to its UI runner.
materials/control are private and must never be copied to CI logs/evidence.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

from android_dual_overlay_relay import AndroidDualOverlayRelay, RelayError
from android_dual_overlay_reverse import OwnedReverseMappings, SERIAL, assert_owned_avd, _adb
from dual_overlay_loopback import read_event
from android_dual_overlay_hosts import safe_startup_failure

HERE = Path(__file__).resolve().parent
CONTROLLER_CLEANUP = {'tsPeerCleanup', 'etPeerCleanup', 'hostContextsClosed', 'collectorStopped',
    'privateMaterialsRemoved', 'ownedProcessesStopped', 'temporaryAuthorizationsCleared',
    'temporaryHostCredentialsRemoved'}


class SessionError(RuntimeError):
    pass


def command(args, timeout=30):
    result = subprocess.run([str(arg) for arg in args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise SessionError('controlled_session_command_failed')
    return result.stdout


class PrivateHostControl:
    EVENTS = {'review_pairing': 'pairing_review', 'approve_pairing': 'pairing_approved',
              'revoke_pairing': 'pairing_revoked', 'complete_ts_auth': 'ts_authorized',
              'audit': 'host_audit', 'ts_diagnostics': 'ts_diagnostics', 'stop': 'cleanup'}

    def __init__(self, process):
        self.process, self.events, self.lock = process, queue.Queue(), threading.Lock()
        self.reader_failed = False
        self.failure = None
        def collect():
            for line in iter(lambda: process.stdout.readline(131073), b''):
                if len(line) > 131072:
                    self.reader_failed = True
                    return
                try:
                    value = json.loads(line)
                    if isinstance(value, dict) and value.get('event') == 'failed':
                        self.failure = safe_startup_failure(value)
                except ValueError:
                    pass
                self.events.put(line)
        self.reader = threading.Thread(target=collect, daemon=True); self.reader.start()

    def ready(self, timeout=60):
        return read_event(self.events, 'ready', self.process, timeout)

    def call(self, request, timeout=20):
        operation = request.get('op') if isinstance(request, dict) else None
        if operation not in self.EVENTS:
            raise SessionError('host_control_operation_required')
        raw = (json.dumps(request) + '\n').encode()
        if len(raw) > 131072:
            raise SessionError('bounded_host_control_required')
        with self.lock:
            if self.reader_failed or self.process.poll() is not None:
                raise SessionError('host_control_unavailable')
            self.process.stdin.write(raw); self.process.stdin.flush()
            return read_event(self.events, self.EVENTS[operation], self.process, timeout)


def signal_owned_residents(namespace_path, inode, owner, sig, pids):
    """Root-only cleanup: pidfds prevent PID reuse from targeting another task."""
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise SessionError('root_namespace_cleanup_required')
    path = Path(namespace_path)
    if (path.parent != Path('/run/netns') or not re.fullmatch(r'hp-dual-[0-9]+-[0-9]+', path.name)
            or path.stat().st_ino != inode or sig not in (signal.SIGTERM, signal.SIGKILL)):
        raise SessionError('owned_namespace_cleanup_required')
    for pid in pids:
        try:
            descriptor = os.pidfd_open(pid)
        except ProcessLookupError:
            continue
        try:
            try:
                if Path('/proc/' + str(pid) + '/ns/net').stat().st_ino != inode:
                    raise SessionError('namespace_resident_changed')
                status = Path('/proc/' + str(pid) + '/status').read_text()
                uids = re.search(r'^Uid:\s+([0-9]+)\s+([0-9]+)', status, re.M)
                if not uids or any(int(value) not in (0, owner) for value in uids.groups()):
                    raise SessionError('namespace_resident_owner_changed')
                signal.pidfd_send_signal(descriptor, sig)
            except (ProcessLookupError, FileNotFoundError):
                pass
        finally:
            os.close(descriptor)


class AndroidDualOverlaySession:
    def __init__(self, bundle, work_root, *, host_source, source_checkout,
                 device=SERIAL, lifetime=900, _host_only=False, _relay_only=False):
        if not re.fullmatch(r'[0-9a-f]{40}', host_source) or device != SERIAL:
            raise SessionError('fixed_host_source_and_owned_device_required')
        if type(lifetime) is not int or not 60 <= lifetime <= 1800:
            raise SessionError('bounded_fixture_lifetime_required')
        self.bundle = Path(bundle).resolve(strict=True)
        self.work_root = Path(work_root).resolve(strict=True)
        self.source_checkout = Path(source_checkout).resolve(strict=True)
        self.host_source, self.lifetime = host_source, lifetime
        self.host_only = _host_only
        self.relay_only = _relay_only
        self.namespace = None
        self.namespace_inode = None
        self.namespace_owned = False
        self.host_record = None
        self.private = self.process = self.control = self.relay = self.reverse = None
        self.closed = False
        self.report = {'hostSource': host_source, 'deviceApi35Verified': False,
                       'hostReady': False, 'relayRoles': 0, 'reverseMappings': 0,
                       'udpStunRelayed': False, 'deviceUserspaceReachabilityVerified': False,
                       'cleanup': {}}

    def _namespace_exists(self):
        return self.namespace in [line.split()[0] for line in
            command(['ip', 'netns', 'list']).decode().splitlines() if line.split()]

    def _same_namespace(self):
        return (self.namespace_inode is not None and self.namespace_path.exists()
                and self.namespace_path.stat().st_ino == self.namespace_inode)

    def __enter__(self):
        try:
            self.start()
            return self
        except BaseException as original:
            try: self.close()
            except Exception: original.cleanup_code = 'shared_session_cleanup_failed'
            raise

    def start(self):
        env = os.environ
        if (sys.platform != 'linux' or os.geteuid() == 0 or env.get('GITHUB_ACTIONS') != 'true'
                or not re.fullmatch(r'[0-9]+', env.get('GITHUB_RUN_ID', ''))
                or not re.fullmatch(r'[0-9]+', env.get('GITHUB_RUN_ATTEMPT', ''))):
            raise SessionError('owned_linux_runner_required')
        root = Path(env['RUNNER_TEMP']).resolve(strict=True)
        if not self.work_root.is_relative_to(root) or self.work_root.stat().st_uid != os.getuid():
            raise SessionError('owned_runner_work_directory_required')
        self.report['stage'] = 'device-and-bundle'
        if not (self.host_only or self.relay_only):
            assert_owned_avd()
            self.report['deviceApi35Verified'] = True
        command([sys.executable, self.source_checkout / 'validation/remote-harness/dual_overlay_shared_bundle.py',
                 'verify', '--bundle', self.bundle, '--source-sha', self.host_source, '--restore-executable'], 60)
        self.private = Path(tempfile.mkdtemp(prefix='hp-device-overlay-', dir=self.work_root))
        self.private.chmod(0o700)
        self.namespace = 'hp-dual-' + env['GITHUB_RUN_ID'] + '-' + env['GITHUB_RUN_ATTEMPT']
        self.namespace_path = Path('/run/netns') / self.namespace
        self.report['stage'] = 'namespace'
        if self._namespace_exists():
            raise SessionError('owned_namespace_collision')
        command(['sudo', '-n', 'ip', 'netns', 'add', self.namespace])
        self.namespace_owned = True
        self.namespace_inode = self.namespace_path.stat().st_ino
        prefix = ['sudo', '-n', 'ip', 'netns', 'exec', self.namespace]
        for args in [['ip', 'link', 'set', 'lo', 'up'],
                     ['ip', 'link', 'add', 'hp-dummy', 'type', 'dummy'],
                     ['sysctl', '-q', '-w', 'net.ipv6.conf.hp-dummy.disable_ipv6=1'],
                     ['ip', 'address', 'add', '192.0.2.1/32', 'dev', 'hp-dummy'],
                     ['ip', 'link', 'set', 'hp-dummy', 'up']]:
            command(prefix + args)
        host_work = self.private / 'hosts'; host_work.mkdir(mode=0o700)
        # Only fixed CI metadata goes in argv/env. Private requests use pipes.
        values = {key: env[key] for key in ('GITHUB_ACTIONS', 'GITHUB_REF', 'GITHUB_RUN_ID',
                  'GITHUB_RUN_ATTEMPT', 'RUNNER_TEMP')}
        values.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', PYTHONDONTWRITEBYTECODE='1')
        args = prefix + ['runuser', '-u', pwd.getpwuid(os.getuid()).pw_name, '--', 'env']
        args += [key + '=' + value for key, value in values.items()]
        args += [sys.executable, str(HERE / 'android_dual_overlay_hosts.py'), '--bundle', str(self.bundle),
                 '--work', str(host_work), '--lifetime', str(self.lifetime)]
        self.report['stage'] = 'host-controller'
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, start_new_session=True)
        self.control = PrivateHostControl(self.process)
        ready = self.control.ready()
        if ready.get('deviceReachabilityVerified') is not False:
            raise SessionError('host_controller_readiness_invalid')
        self.materials = json.loads(self._private_file(ready['materialFile'], 16384))
        self.host_record = json.loads(self._private_file(host_work / 'host-owner.json', 4096))
        if (self.materials.get('udpStunRelayed') is not False
                or self.materials.get('deviceTailscaleReachabilityVerified') is not False):
            raise SessionError('host_material_reachability_claim_invalid')
        self.report['hostReady'] = True
        if self.host_only:
            self.report['stage'] = 'host-only-ready'
            return
        manifest = Path(ready['relayManifestFile'])
        self._private_file(manifest, 4096)
        self.report['stage'] = 'relay-and-reverse'
        try:
            self.relay = AndroidDualOverlayRelay(manifest)
            self.relay.__enter__()
        except RelayError as error:
            allowed = {'owned_runner_required', 'private_manifest_path_required', 'private_manifest_permissions_required',
                'private_manifest_invalid', 'owned_namespace_required', 'owned_ports_required', 'owned_processes_required',
                'namespace_check_failed', 'owned_namespace_missing', 'listener_check_failed', 'owned_listener_required',
                'relay_already_started', 'safe_listener_port_unavailable', 'relay_thread_cleanup_failed',
                'listener_process_stat_failed', 'listener_process_uid_mismatch', 'listener_process_namespace_mismatch',
                'listener_process_namespace_unreadable'}
            self.report['relayFailure'] = str(error) if str(error) in allowed else 'controlled_relay_failed'
            checks = getattr(error, 'listener_checks', None)
            keys = {'exactLoopbackListener', 'expectedPidVisible', 'exactListenerOwnedByPid',
                    'samePortDeviceBoundLoopback', 'samePortListener', 'samePortMappedLoopback', 'samePortWildcard', 'samePortIPv6Loopback'}
            if (isinstance(checks, dict) and set(checks) == {'control', 'derp', 'easytier'}
                    and all(isinstance(value, dict) and set(value) == keys
                        and all(type(flag) is bool for flag in value.values()) for value in checks.values())):
                self.report['listenerChecks'] = checks
            raise
        self.report['relayRoles'] = len(self.relay.ports)
        self.report['listenerChecks'] = self.relay.listener_checks
        if self.relay_only:
            self.report['stage'] = 'host-relay-only-ready'
            return
        self.reverse = OwnedReverseMappings(self.relay)
        self.reverse.__enter__()
        self.report['reverseMappings'] = self.reverse.installed_count
        self.report['stage'] = 'ready'

    def _private_file(self, path, limit):
        path = Path(path)
        resolved = path.resolve(strict=True)
        if path.is_symlink() or not resolved.is_relative_to(self.private) or not path.is_file():
            raise SessionError('owned_private_material_required')
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > limit:
            raise SessionError('bounded_private_material_required')
        return path.read_bytes()

    def read_host_profile(self, role):
        if role not in ('et', 'ts'):
            raise SessionError('host_role_required')
        value = json.loads(self._private_file(self.materials['hostProfiles'][role], 2048))
        if value.get('provider') != {'et': 'easytier', 'ts': 'tailscale'}[role]:
            raise SessionError('overlay_host_profile_required')
        return value

    def read_ca(self):
        value = self._private_file(self.materials['caFile'], 65536)
        if b'BEGIN CERTIFICATE' not in value or b'PRIVATE KEY' in value:
            raise SessionError('public_test_ca_required')
        return value

    def _residents(self):
        values = command(['sudo', '-n', 'ip', 'netns', 'pids', self.namespace]).split()
        if any(not value.isdigit() for value in values):
            raise SessionError('namespace_residents_invalid')
        return [int(value) for value in values]

    def _remove_host_private_directory(self):
        record = self.host_record
        if record is None and self.private is not None:
            path = self.private / 'hosts/host-owner.json'
            if path.exists(): record = json.loads(self._private_file(path, 4096))
        if record is None: return True
        if not isinstance(record, dict) or set(record) != {'directory', 'inode', 'owner'}:
            raise SessionError('host_cleanup_record_invalid')
        path = Path(record['directory'])
        if (path.parent != Path('/tmp').resolve() or not path.name.startswith('hp-device-hosts-')
                or record['owner'] != os.getuid() or type(record['inode']) is not int):
            raise SessionError('owned_host_cleanup_required')
        if not path.exists(): return True
        info = path.stat()
        if path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_ino != record['inode']:
            raise SessionError('host_cleanup_owner_changed')
        if self.namespace_owned and self.namespace_path.exists():
            raise SessionError('host_namespace_not_drained')
        shutil.rmtree(path)
        return not path.exists()

    def _remove_namespace(self):
        if not self.namespace_owned:
            return self.namespace is None or not self._namespace_exists()
        if not self._same_namespace():
            raise SessionError('owned_namespace_changed')
        for sig, budget in ((signal.SIGTERM, 5), (signal.SIGKILL, 3)):
            pids = self._residents()
            if not pids: break
            command(['sudo', '-n', sys.executable, str(Path(__file__).resolve()), '--signal-owned',
                     str(self.namespace_path), str(self.namespace_inode), str(os.getuid()), str(int(sig)),
                     ','.join(str(pid) for pid in pids)])
            deadline = time.monotonic() + budget
            while self._residents() and time.monotonic() < deadline: time.sleep(.05)
        if self._residents():
            raise SessionError('owned_namespace_residents_remain')
        if not self._same_namespace():
            raise SessionError('owned_namespace_changed')
        command(['sudo', '-n', 'ip', 'netns', 'delete', self.namespace])
        return not self._namespace_exists()

    def close(self):
        if self.closed: return
        self.closed = True
        cleanup = self.report['cleanup']
        for name, resource in [('reverseRemoved', self.reverse), ('relayStopped', self.relay)]:
            try:
                if resource is not None: resource.close()
                cleanup[name] = resource is None or name != 'reverseRemoved' or resource.cleanup_confirmed
            except Exception: cleanup[name] = False
        cleanup['controllerStopped'] = self.process is None
        if self.process is not None:
            try:
                result = self.control.call({'op': 'stop'}, timeout=45)
                cleanup['controllerStopped'] = (result.get('stopReason') == 'explicit-stop'
                    and all(result.get(key) is True for key in CONTROLLER_CLEANUP)
                    and self.process.wait(timeout=10) == 0)
            except Exception: cleanup['controllerStopped'] = False
        try: cleanup['namespaceRemoved'] = self._remove_namespace()
        except Exception: cleanup['namespaceRemoved'] = False
        try: cleanup['hostPrivateDirectoryRemoved'] = self._remove_host_private_directory()
        except Exception: cleanup['hostPrivateDirectoryRemoved'] = False
        if self.process is not None:
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: cleanup['controllerStopped'] = False
            exit_code = self.process.poll()
            self.report['controllerProcessExited'] = exit_code is not None
            self.report['controllerExitType'] = ('running' if exit_code is None else
                'success' if exit_code == 0 else 'signal' if exit_code < 0 else 'nonzero')
            if self.control is not None:
                self.control.reader.join(timeout=2)
                cleanup['controlReaderStopped'] = not self.control.reader.is_alive()
            if self.process.poll() is not None:
                self.process.stdin.close(); self.process.stdout.close()
        else:
            self.report['controllerProcessExited'] = False
            self.report['controllerExitType'] = 'not_started'
        if self.private is not None:
            failure = self.control.failure if self.control is not None else None
            path = self.private / 'hosts/startup-error.json'
            if failure is None and path.is_file():
                failure = safe_startup_failure(json.loads(self._private_file(path, 4096)))
            if failure is not None:
                self.report['hostStartupFailure'] = safe_startup_failure(failure)
            shutil.rmtree(self.private)
        cleanup['privateFilesRemoved'] = self.private is None or not self.private.exists()
        if not all(cleanup.values()):
            raise SessionError('shared_overlay_session_cleanup_incomplete')

    def __exit__(self, kind, original, _):
        try: self.close()
        except SessionError:
            if original is None: raise
            original.cleanup_code = 'shared_overlay_session_cleanup_incomplete'


def smoke(args):
    result = {'schemaVersion': 1, 'status': 'failed', 'hostSource': args.host_source,
              'scope': 'owned API35 x86_64 AVD, real host fixtures, three TCP relays/reverse and cleanup; no product provider SSH, peer protocol or userspace reachability claim',
              'deviceProviderReachabilityVerified': False, 'udpStunRelayed': False, 'rounds': []}
    if args.host_only:
        result['scope'] = 'Linux real host controller startup/stop only; no AVD, relay, reverse or device validation'
    if args.relay_only:
        result['scope'] = 'Linux real host controller and owned relay verification/cleanup only; no AVD, reverse or device validation'
    previous_keys = None
    try:
        for _ in range(2):
            current = AndroidDualOverlaySession(args.bundle, args.work_root,
                host_source=args.host_source, source_checkout=args.source_checkout, lifetime=180, _host_only=args.host_only, _relay_only=args.relay_only)
            row = {}
            try:
                with current:
                    keys = [current.read_host_profile(role)['expectedHostKey'] for role in ('et', 'ts')]
                    row['newHostIdentities'] = (len(set(keys)) == 2 and (previous_keys is None
                        or all(key != previous for key, previous in zip(keys, previous_keys))))
                    previous_keys = keys
                    row['publicCaAvailable'] = bool(current.read_ca())
                    row['noPreapprovedDevice'] = all(current.control.call({'op': 'audit', 'role': role,
                        'expectedBase64': ''})['acceptedSessions'] == 0 for role in ('et', 'ts'))
                    for role in (() if args.host_only or args.relay_only else ('control', 'derp', 'easytier')):
                        port = current.relay.config[role]
                        path = '/key?v=1' if role == 'control' else '/'
                        request = '' if role == 'easytier' else 'GET ' + path + ' HTTP/1.0\\r\\nHost: 127.0.0.1\\r\\n\\r\\n'
                        script = "{ printf '" + request + "'; sleep 1; } | /system/bin/toybox nc -w 3 127.0.0.1 " + str(port)
                        script += "; hp_status=$?; printf '\\nHP_RETURN:%s\\n' \"$hp_status\""
                        output = _adb('shell', script, timeout=15)
                        codes = re.findall(rb'HP_RETURN:([0-9]+)', output)
                        if len(codes) != 1 or int(codes[0]) != 0:
                            raise SessionError('device_tcp_probe_failed')
                        if role == 'control':
                            row['controlPlaintextRejected'] = bool(re.match(rb'HTTP/1\.[01] 400', output))
                        if role == 'derp':
                            row['derpHttpResponse'] = output.startswith(b'HTTP/1.')
                    if not (args.host_only or args.relay_only):
                        deadline = time.monotonic() + 8
                        while time.monotonic() < deadline:
                            with current.relay._lock:
                                idle = not current.relay._clients and not current.relay._workers
                            if idle: break
                            time.sleep(.05)
                        if not idle: raise SessionError('transport_connections_not_drained')
                        row['roleTcpCounters'] = current.relay.stats()
                        if not all(value['accepted'] >= 1 and value['workerFailures'] == 0
                                   for value in row['roleTcpCounters'].values()):
                            raise SessionError('three_owned_tcp_paths_not_proven')
                    required = ['newHostIdentities', 'publicCaAvailable', 'noPreapprovedDevice']
                    if not (args.host_only or args.relay_only): required += ['controlPlaintextRejected', 'derpHttpResponse']
                    if not all(row.get(field) is True for field in required):
                        raise SessionError('transport_smoke_not_proven')
                row['status'] = 'passed'
            finally:
                row['session'] = current.report
                result['rounds'].append(row)
        result['status'] = 'passed'
    except Exception:
        result['errorCode'] = 'controlled_session_smoke_failed'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'rounds': len(result['rounds'])}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    if len(sys.argv) == 7 and sys.argv[1] == '--signal-owned':
        try:
            signal_owned_residents(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]),
                                   [int(value) for value in sys.argv[6].split(',')])
        except Exception:
            raise SystemExit(1)
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--smoke', action='store_true', required=True)
        diagnosis = parser.add_mutually_exclusive_group()
        diagnosis.add_argument('--host-only', action='store_true', help='Linux fixture diagnosis only; no device claim')
        diagnosis.add_argument('--relay-only', action='store_true', help='Linux owned relay diagnosis; no device claim')
        for name in ('bundle', 'work-root', 'source-checkout', 'output'):
            parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--host-source', required=True)
        raise SystemExit(smoke(parser.parse_args()))
