"""Owned loopback sshd policy regression; real sockets require explicit opt-in.

HERDR_OWNED_SSHD_STREAMLOCAL_AB=1 runs cold old/new sshd processes using only
temporary keys, known_hosts, authorization files, Unix sockets and TCP listeners.
"""
import contextlib
import json
import os
from pathlib import Path
import pwd
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import unittest

try:
    from paired_dual_demo import fixture_sshd_config
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography': raise
    fixture_sshd_config = None

PAYLOAD = b'owned-streamlocal-echo\n'


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.server.accepted += 1
        data = self.request.recv(4096)
        if data: self.request.sendall(data)


@contextlib.contextmanager
def endpoint(address, unix=False):
    server = (socketserver.UnixStreamServer if unix else socketserver.TCPServer)(address, Echo)
    server.accepted = 0
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.05), daemon=True)
    worker.start()
    try: yield server
    finally:
        server.shutdown(); server.server_close(); worker.join(2)


@contextlib.contextmanager
def owned_process(args, log, env):
    with log.open('wb') as stream:
        child = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=stream,
                                 env=env, start_new_session=True)
        try: yield child
        finally:
            child.terminate()
            try: child.wait(5)
            except subprocess.TimeoutExpired: child.kill(); child.wait(5)


def wait_for(check, child):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        if child.poll() is not None: raise RuntimeError('owned_ssh_process_exited')
        if check(): return
        time.sleep(.03)
    raise RuntimeError('owned_ssh_process_not_ready')


def old_policy(config, sock):
    current = f'AllowTcpForwarding local\nAllowStreamLocalForwarding local\nPermitOpen [{sock}]:*\n'
    if config.count(current) != 1: raise RuntimeError('fixture_streamlocal_policy_changed')
    return config.replace(current, 'AllowTcpForwarding no\n')


def cold_start_ab():
    if os.geteuid() == 0: raise RuntimeError('unprivileged_fixture_owner_required')
    with tempfile.TemporaryDirectory(prefix='hp-streamlocal-ab-', dir='/tmp') as folder:
        root = Path(folder).resolve(); root.chmod(0o700)
        env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(root), 'LANG': 'C'}
        for name in ('host', 'client'):
            subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(root/name)],
                           env=env, check=True)
        (root/'authorized_keys').write_bytes((root/'client.pub').read_bytes())
        (root/'authorized_keys').chmod(0o600)
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
        (root/'known_hosts').write_text(f'[127.0.0.1]:{port} ' + (root/'host.pub').read_text())
        target = root/'config/herdr/sessions/qa-pair/herdr.sock'; target.parent.mkdir(parents=True)
        other = root/'other.sock'
        username = pwd.getpwuid(os.getuid()).pw_name
        current = fixture_sshd_config(root, port, username)
        ssh = ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
               '-o', 'IdentityAgent=none', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'UserKnownHostsFile=' + str(root/'known_hosts'), '-o', 'GlobalKnownHostsFile=/dev/null',
               '-o', 'ControlMaster=no', '-o', 'ControlPath=none', '-i', str(root/'client'), '-p', str(port)]
        destination = username + '@127.0.0.1'
        sshd = (['sudo', '-n'] if os.uname().sysname == 'Linux' else []) + ['/usr/sbin/sshd']
        reports = []
        with endpoint(str(target), True) as allowed, endpoint(str(other), True) as forbidden, endpoint(('127.0.0.1', 0)) as tcp:
            for label, text in [('old', old_policy(current, target)), ('new', current)]:
                config = root/'sshd_config'; config.write_text(text)
                subprocess.run(sshd + ['-t', '-f', str(config)], env=env, check=True, capture_output=True)
                def ready():
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.2) as connection:
                            return connection.recv(128).startswith(b'SSH-2.0-')
                    except OSError: return False
                server_log = root/(label + '-sshd.log')
                with owned_process(sshd + ['-D', '-e', '-f', str(config)], server_log, env) as server:
                    wait_for(ready, server)
                    attempts = {}
                    for role, path in [('approved', target), ('other', other)]:
                        local = root/(label + '-' + role + '.sock')
                        with owned_process(ssh + ['-o', 'ExitOnForwardFailure=yes', '-N', '-L',
                                                  str(local) + ':' + str(path), destination],
                                           root/(label + '-' + role + '.log'), env) as forward:
                            wait_for(local.exists, forward)
                            with socket.socket(socket.AF_UNIX) as channel:
                                channel.settimeout(3); channel.connect(str(local)); channel.sendall(PAYLOAD)
                                try: received = channel.recv(4096)
                                except (ConnectionResetError, socket.timeout): received = b''
                        attempts[role] = received == PAYLOAD
                    before = tcp.accepted
                    value = subprocess.run(ssh + ['-W', '127.0.0.1:' + str(tcp.server_address[1]), destination],
                                           input=PAYLOAD, env=env, capture_output=True, timeout=10)
                    attempts['tcpRejected'] = (value.returncode != 0 and not value.stdout and tcp.accepted == before
                                               and b'administratively prohibited' in value.stderr)
                    attempts.update(approvedAccepts=allowed.accepted, otherAccepts=forbidden.accepted, tcpAccepts=tcp.accepted)
                attempts['authenticatedConnections'] = server_log.read_bytes().count(b'Accepted publickey')
                reports.append(dict(configuration=label, **attempts))
        return dict(sshdVersion=subprocess.run(['/usr/sbin/sshd', '-V'], capture_output=True, text=True).stderr.strip(),
                    coldStartPerConfiguration=True, cases=reports,
                    scope='owned temporary keys, Unix echo and loopback sshd; no device or herdr snapshot claim')


@unittest.skipIf(fixture_sshd_config is None, 'requires existing pinned pairing environment')
class FixturePolicyTests(unittest.TestCase):
    def test_only_fixture_unix_path_is_permitted(self):
        root = Path('/owned-fixture')
        text = fixture_sshd_config(root, 2222, 'fixture')
        self.assertIn('ListenAddress 127.0.0.1\n', text)
        self.assertIn('AllowTcpForwarding local\nAllowStreamLocalForwarding local\n', text)
        self.assertIn('PermitOpen [/owned-fixture/config/herdr/sessions/qa-pair/herdr.sock]:*\n', text)
        self.assertNotIn('PermitOpen any', text)
        self.assertIn('PasswordAuthentication no\n', text)
        self.assertIn('AllowAgentForwarding no\n', text)
        self.assertIn('PermitRootLogin no\n', text)

    @unittest.skipUnless(os.environ.get('HERDR_OWNED_SSHD_STREAMLOCAL_AB') == '1', 'owned sshd A/B is opt-in')
    def test_cold_start_exact_unix_allowed_other_unix_and_tcp_denied(self):
        report = cold_start_ab()
        print(json.dumps(report, sort_keys=True))
        self.assertEqual(report['cases'], [
            dict(configuration='old', approved=False, other=False, tcpRejected=True,
                 approvedAccepts=0, otherAccepts=0, tcpAccepts=0, authenticatedConnections=3),
            dict(configuration='new', approved=True, other=False, tcpRejected=True,
                 approvedAccepts=1, otherAccepts=0, tcpAccepts=0, authenticatedConnections=3)])


if __name__ == '__main__': unittest.main()
