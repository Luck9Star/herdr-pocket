#!/usr/bin/env python3
"""Runner-only TCP relay for the three owned dual-overlay fixture endpoints.

No adb commands are run here. The caller owns adb reverse and namespace setup.
The private manifest is a runner-created 0600 JSON file under RUNNER_TEMP:
{"namespace":"hp-dual-RUN-ATTEMPT", "control":port, "derp":port,
 "easytier":port, "sshPorts":[port, port], "ownerPids":{role:pid}}.
The namespace and each loopback listener must belong to these owned processes.
The returned ports listen only on host loopback; workers dial namespace loopback.
"""
import json
import os
import pwd
from pathlib import Path
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import threading

ROLES = ('control', 'derp', 'easytier')


class RelayError(ValueError):
    pass


def checked_manifest(path, env=None):
    env = os.environ if env is None else env
    run, attempt = env.get('GITHUB_RUN_ID', ''), env.get('GITHUB_RUN_ATTEMPT', '')
    if env.get('GITHUB_ACTIONS') != 'true' or not re.fullmatch(r'[0-9]+', run) or not re.fullmatch(r'[0-9]+', attempt):
        raise RelayError('owned_runner_required')
    root = Path(env.get('RUNNER_TEMP', '/nonexistent')).resolve(strict=True)
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_relative_to(root) or path == root:
        raise RelayError('private_manifest_path_required')
    info = path.stat()
    parent = path.parent.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or
            parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700 or info.st_size > 4096):
        raise RelayError('private_manifest_permissions_required')
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError, UnicodeError):
        raise RelayError('private_manifest_invalid') from None
    if not isinstance(data, dict) or set(data) != {'namespace', *ROLES, 'sshPorts', 'ownerPids'}:
        raise RelayError('private_manifest_invalid')
    if data['namespace'] != f'hp-dual-{run}-{attempt}':
        raise RelayError('owned_namespace_required')
    ports = [data[k] for k in ROLES]
    ssh = data['sshPorts']
    if (not isinstance(ssh, list) or len(ssh) != 2 or
            any(type(p) is not int or not 1 <= p <= 65535 for p in ports + ssh) or
            len(set(ports + ssh)) != 5):
        raise RelayError('owned_ports_required')
    owners = data['ownerPids']
    if not isinstance(owners, dict) or set(owners) != set(ROLES) or any(type(pid) is not int or pid <= 1 for pid in owners.values()):
        raise RelayError('owned_processes_required')
    return data


def _namespace_exists(namespace):
    result = subprocess.run(['ip', 'netns', 'list'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=10, check=False)
    if result.returncode:
        raise RelayError('namespace_check_failed')
    if namespace not in [line.split()[0] for line in result.stdout.decode('utf-8', 'strict').splitlines() if line.split()]:
        raise RelayError('owned_namespace_missing')


def _verify_owned_listeners(config):
    """Read-only check: same network namespace, runner UID, exact loopback listener and PID."""
    try:
        ns_inode = os.stat('/run/netns/' + config['namespace']).st_ino
        for pid in config['ownerPids'].values():
            if os.stat(f'/proc/{pid}').st_uid != os.getuid() or os.stat(f'/proc/{pid}/ns/net').st_ino != ns_inode:
                raise RelayError('owned_processes_required')
        result = subprocess.run(['sudo', '-n', 'ip', 'netns', 'exec', config['namespace'], 'ss', '-H', '-ltnp'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
        if result.returncode:
            raise RelayError('listener_check_failed')
        lines = result.stdout.decode('utf-8', 'strict').splitlines()
        for role in ROLES:
            endpoint = re.compile(r'(?:^|\s)127\.0\.0\.1:' + str(config[role]) + r'(?:\s|$)')
            owner = re.compile(r'\bpid=' + str(config['ownerPids'][role]) + r'(?:,|\))')
            if not any(endpoint.search(line) and owner.search(line) for line in lines):
                raise RelayError('owned_listener_required')
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        raise RelayError('listener_check_failed') from None


def _worker(port):
    # This child is started by the parent inside its already checked namespace.
    with socket.create_connection(('127.0.0.1', port), timeout=10) as target:
        target.setblocking(False)
        source_open = True
        while True:
            readers = [target] + ([sys.stdin.buffer] if source_open else [])
            ready, _, _ = select.select(readers, [], [], 1)
            if sys.stdin.buffer in ready:
                data = os.read(sys.stdin.fileno(), 65536)
                if not data:
                    source_open = False
                    target.shutdown(socket.SHUT_WR)
                else:
                    target.setblocking(True); target.sendall(data); target.setblocking(False)
            if target in ready:
                data = target.recv(65536)
                if not data:
                    return
                sys.stdout.buffer.write(data); sys.stdout.buffer.flush()


def _signal_process(process, sig):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, sig)
    except (ProcessLookupError, PermissionError):
        if process.poll() is None:
            process.send_signal(sig)


def _stop_process(process):
    _signal_process(process, signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        _signal_process(process, signal.SIGKILL)
        process.wait(timeout=2)


class AndroidDualOverlayRelay:
    """Context manager exposing {control, derp, easytier} host loopback ports."""
    def __init__(self, manifest, *, _spawn=None, _check_namespace=None, _check_listeners=None):
        self.config = checked_manifest(manifest)
        self._check = _check_namespace or _namespace_exists
        self._spawn = _spawn or self._spawn_worker
        self._check_listeners = _check_listeners or _verify_owned_listeners
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._listeners = []
        self._clients = set()
        self._workers = set()
        self._threads = []
        self.ports = {}
        self._started = False
        self._cleanup_failed = threading.Event()

    def _spawn_worker(self, port):
        return subprocess.Popen(['sudo', '-n', 'ip', 'netns', 'exec', self.config['namespace'],
                                 'runuser', '-u', pwd.getpwuid(os.getuid()).pw_name, '--', sys.executable, str(Path(__file__).resolve()), '--worker', str(port)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                close_fds=True, start_new_session=True)

    def __enter__(self):
        if self._started:
            raise RelayError('relay_already_started')
        self._started = True
        try:
            self._check(self.config['namespace'])
            self._check_listeners(self.config)
            forbidden = set(self.config['sshPorts']) | {self.config[role] for role in ROLES}
            for role in ROLES:
                for _ in range(16):
                    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self._listeners.append(listener)
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    listener.bind(('127.0.0.1', 0))
                    if listener.getsockname()[1] not in forbidden:
                        break
                    listener.close(); self._listeners.remove(listener)
                else:
                    raise RelayError('safe_listener_port_unavailable')
                listener.listen(16); listener.settimeout(.2)
                self.ports[role] = listener.getsockname()[1]
            for role, listener in zip(ROLES, self._listeners):
                thread = threading.Thread(target=self._accept, args=(listener, self.config[role]), daemon=True)
                self._threads.append(thread); thread.start()
            return self
        except BaseException:
            self.close()
            raise

    def _accept(self, listener, port):
        while not self._stop.is_set():
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                if self._stop.is_set() or len(self._clients) >= 16:
                    client.close(); continue
                self._clients.add(client)
                thread = threading.Thread(target=self._bridge, args=(client, port), daemon=True)
                self._threads.append(thread); thread.start()

    def _bridge(self, client, port):
        process = None
        try:
            if self._stop.is_set():
                return
            self._check_listeners(self.config)
            if self._stop.is_set():
                return
            process = self._spawn(port)
            with self._lock:
                self._workers.add(process)
            def upstream():
                try:
                    while not self._stop.is_set():
                        data = client.recv(65536)
                        if not data: break
                        process.stdin.write(data); process.stdin.flush()
                except (OSError, ValueError, BrokenPipeError):
                    pass
                finally:
                    try: process.stdin.close()
                    except (OSError, ValueError): pass
            thread = threading.Thread(target=upstream, daemon=True)
            with self._lock: self._threads.append(thread)
            thread.start()
            while not self._stop.is_set():
                data = os.read(process.stdout.fileno(), 65536)
                if not data: break
                client.sendall(data)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        finally:
            try: client.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            client.close()
            if process is not None:
                try:
                    _stop_process(process)
                except (OSError, subprocess.SubprocessError):
                    self._cleanup_failed.set()
                for pipe in (process.stdin, process.stdout):
                    try: pipe.close()
                    except (OSError, ValueError): pass
            with self._lock:
                self._clients.discard(client)
                if process is not None: self._workers.discard(process)

    def close(self):
        self._stop.set()
        for listener in self._listeners:
            listener.close()
        with self._lock:
            clients, workers = list(self._clients), list(self._workers)
        for client in clients:
            try: client.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            client.close()
        for process in workers:
            try: _signal_process(process, signal.SIGTERM)
            except OSError: self._cleanup_failed.set()
        for thread in self._threads:
            if thread is not threading.current_thread() and thread.ident is not None:
                thread.join(timeout=3)
        if self._cleanup_failed.is_set() or any(thread.is_alive() for thread in self._threads):
            raise RelayError('relay_thread_cleanup_failed')

    def __exit__(self, *_):
        self.close()


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--worker' or not re.fullmatch(r'[0-9]{1,5}', sys.argv[2]) or not 1 <= int(sys.argv[2]) <= 65535:
        raise SystemExit('worker_only')
    _worker(int(sys.argv[2]))
