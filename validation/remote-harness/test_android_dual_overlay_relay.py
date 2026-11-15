"""Owned relay validation; loopback-only fixtures, no adb or namespace writes."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('android_dual_overlay_relay', HERE / 'android_dual_overlay_relay.py')
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


class Echo:
    def __init__(self):
        self.sock = socket.socket(); self.sock.bind(('127.0.0.1', 0)); self.sock.listen(16); self.sock.settimeout(.1)
        self.port = self.sock.getsockname()[1]; self.stop = threading.Event(); self.threads = []
        self.thread = threading.Thread(target=self.serve); self.thread.start()
    def serve(self):
        while not self.stop.is_set():
            try: client, _ = self.sock.accept()
            except socket.timeout: continue
            except OSError: return
            t = threading.Thread(target=self.echo, args=(client,)); self.threads.append(t); t.start()
    @staticmethod
    def echo(client):
        with client:
            while True:
                data = client.recv(65536)
                if not data: return
                client.sendall(data)
    def close(self):
        self.stop.set(); self.sock.close(); self.thread.join(3)
        for t in self.threads: t.join(3)
        assert not self.thread.is_alive() and not any(t.is_alive() for t in self.threads)


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve(); self.root.chmod(0o700)
        self.env = patch.dict(os.environ, {'RUNNER_TEMP':str(self.root), 'GITHUB_ACTIONS':'true', 'GITHUB_RUN_ID':'12', 'GITHUB_RUN_ATTEMPT':'2'})
        self.env.start(); self.manifest = self.root / 'manifest.json'
        self.write({'namespace':'hp-dual-12-2', 'control':11001, 'derp':11002, 'easytier':11003, 'sshPorts':[11004,11005], 'ownerPids':dict.fromkeys(relay.ROLES,os.getpid())})
    def tearDown(self):
        self.env.stop(); self.temp.cleanup()
    def write(self, data):
        self.manifest.write_text(json.dumps(data)); self.manifest.chmod(0o600)
    def test_rejects_unowned_namespace_ports_and_manifest(self):
        data = json.loads(self.manifest.read_text())
        for key, value in [('namespace','hp-dual-12-3'), ('control',11004), ('derp',True), ('sshPorts',[11004]), ('easytier',0)]:
            with self.subTest(key=key):
                self.write({**data, key:value})
                with self.assertRaises(relay.RelayError): relay.checked_manifest(self.manifest)
        self.write(data); self.manifest.chmod(0o644)
        with self.assertRaises(relay.RelayError): relay.checked_manifest(self.manifest)
        self.manifest.chmod(0o600)
        alias = self.root/'link'; alias.symlink_to(self.manifest)
        with self.assertRaises(relay.RelayError): relay.checked_manifest(alias)
        with patch.dict(os.environ, {'GITHUB_ACTIONS':'false'}):
            with self.assertRaises(relay.RelayError): relay.checked_manifest(self.manifest)
    def test_listener_rejection_codes_are_fixed_and_keep_all_guards(self):
        config = relay.checked_manifest(self.manifest)
        for failure, expected in (('process', 'listener_process_stat_failed'),
                                  ('uid', 'listener_process_uid_mismatch'),
                                  ('namespace_read', 'listener_process_namespace_unreadable'),
                                  ('namespace', 'listener_process_namespace_mismatch')):
            def checked_stat(path):
                value = str(path)
                if failure == 'process' and value.startswith('/proc/') and not value.endswith('/ns/net'):
                    raise PermissionError('private detail must not escape')
                if failure == 'namespace_read' and value.endswith('/ns/net'):
                    raise PermissionError('private detail must not escape')
                return SimpleNamespace(st_uid=os.getuid() + (1 if failure == 'uid' else 0),
                    st_ino=99 if failure == 'namespace' and value.endswith('/ns/net') else 42)
            with self.subTest(failure=failure), patch.object(relay.os, 'stat', side_effect=checked_stat):
                with self.assertRaisesRegex(relay.RelayError, '^' + expected + '$'):
                    relay._verify_owned_listeners(config)

    def test_actual_listener_guard_rejects_wrong_owner_or_wildcard(self):
        config=relay.checked_manifest(self.manifest)
        def fake_stat(path):
            return SimpleNamespace(st_ino=42, st_uid=os.getuid())
        lines=b'LISTEN 0 10 127.0.0.1:11001 0.0.0.0:* users:(("owned",pid=123,fd=3))\nLISTEN 0 10 127.0.0.1:11002 0.0.0.0:* users:(("owned",pid=123,fd=4))\nLISTEN 0 10 127.0.0.1:11003 0.0.0.0:* users:(("owned",pid=123,fd=5))\n'
        config['ownerPids']=dict.fromkeys(relay.ROLES,123)
        with patch.object(relay.os,'stat',side_effect=fake_stat), patch.object(relay.subprocess,'run',return_value=subprocess.CompletedProcess([],0,lines,b'')):
            relay._verify_owned_listeners(config)
        scoped = lines.replace(b'127.0.0.1:11003', b'127.0.0.1%lo:11003')
        with patch.object(relay.os,'stat',side_effect=fake_stat), patch.object(relay.subprocess,'run',return_value=subprocess.CompletedProcess([],0,scoped,b'')):
            checks = relay._verify_owned_listeners(config)
            self.assertTrue(checks['easytier']['samePortDeviceBoundLoopback'])
            self.assertTrue(checks['easytier']['exactListenerOwnedByPid'])
        for altered in (lines.replace(b'127.0.0.1:11001',b'0.0.0.0:11001'), lines.replace(b'pid=123',b'pid=124'),
                        lines.replace(b'127.0.0.1:11001',b'127.0.0.1%hp-dummy:11001'),
                        lines.replace(b'127.0.0.1:11001',b'192.0.2.1%lo:11001')):
            with patch.object(relay.os,'stat',side_effect=fake_stat), patch.object(relay.subprocess,'run',return_value=subprocess.CompletedProcess([],0,altered,b'')):
                with self.assertRaises(relay.RelayError) as caught: relay._verify_owned_listeners(config)
                self.assertEqual(set(caught.exception.listener_checks), set(relay.ROLES))
                self.assertTrue(all(type(flag) is bool for checks in caught.exception.listener_checks.values() for flag in checks.values()))
        def foreign(path):
            return SimpleNamespace(st_ino=99 if str(path).endswith('/ns/net') else 42, st_uid=os.getuid())
        with patch.object(relay.os,'stat',side_effect=foreign):
            with self.assertRaises(relay.RelayError): relay._verify_owned_listeners(config)

    def test_three_loopback_streams_concurrently_and_cleanup(self):
        peers = [Echo() for _ in range(3)]
        self.addCleanup(lambda: [p.close() for p in peers])
        self.write({'namespace':'hp-dual-12-2', **dict(zip(relay.ROLES,[p.port for p in peers])), 'sshPorts':[1,2], 'ownerPids':dict.fromkeys(relay.ROLES,os.getpid())})
        workers = []
        def spawn(port):
            proc = subprocess.Popen([sys.executable, str(HERE/'android_dual_overlay_relay.py'), '--worker', str(port)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
            workers.append(proc); return proc
        with relay.AndroidDualOverlayRelay(self.manifest, _spawn=spawn, _check_namespace=lambda _:None, _check_listeners=lambda _:None) as instance:
            self.assertEqual(set(instance.ports),set(relay.ROLES))
            self.assertTrue(all(s.getsockname()[0] == '127.0.0.1' for s in instance._listeners))
            clients = [socket.create_connection(('127.0.0.1',instance.ports[k]),timeout=5) for k in relay.ROLES]
            try:
                for i, sock in enumerate(clients): sock.sendall(bytes([i])*8192)
                for i, sock in enumerate(clients):
                    result=b''
                    while len(result)<8192: result+=sock.recv(8192-len(result))
                    self.assertEqual(result,bytes([i])*8192)
            finally:
                for sock in clients: sock.close()
        self.assertTrue(workers); self.assertTrue(all(p.poll() is not None for p in workers))
        for role in relay.ROLES:
            self.assertEqual(instance.stats()[role]['accepted'],1)
            self.assertEqual(instance.stats()[role]['upstreamBytes'],8192)
            self.assertEqual(instance.stats()[role]['downstreamBytes'],8192)
        self.assertFalse(any(t.is_alive() for t in instance._threads))
        for port in instance.ports.values():
            with self.assertRaises(OSError): socket.create_connection(('127.0.0.1',port),timeout=.2)
    def test_partial_listener_start_failure_closes_prior_socket(self):
        real_socket = socket.socket
        created = []
        class Broken:
            closed = False
            def setsockopt(self, *args): pass
            def bind(self, address): raise OSError('synthetic bind failure')
            def close(self): self.closed = True
        broken = Broken()
        def factory(*args):
            if created: return broken
            sock = real_socket(*args); created.append(sock); return sock
        instance = relay.AndroidDualOverlayRelay(self.manifest, _check_namespace=lambda _:None, _check_listeners=lambda _:None)
        with patch.object(relay.socket, 'socket', side_effect=factory):
            with self.assertRaises(OSError): instance.__enter__()
        self.assertEqual(created[0].fileno(),-1)
        self.assertTrue(broken.closed)
        self.assertFalse(any(t.is_alive() for t in instance._threads))

    def test_start_failure_and_active_connection_close(self):
        with self.assertRaises(relay.RelayError):
            with relay.AndroidDualOverlayRelay(self.manifest, _check_namespace=lambda _: (_ for _ in ()).throw(relay.RelayError('missing'))): pass
        instance = relay.AndroidDualOverlayRelay(self.manifest, _check_namespace=lambda _:None, _check_listeners=lambda _:None,
            _spawn=lambda _: subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True))
        with instance:
            client = socket.create_connection(('127.0.0.1',instance.ports['control']),timeout=3)
        client.close()
        self.assertFalse(any(t.is_alive() for t in instance._threads))
        self.assertFalse(instance._workers)


@unittest.skipUnless(os.environ.get('HP_RELAY_LINUX_TEST') == '1' and sys.platform == 'linux', 'opt-in Linux namespace test')
class LinuxNamespaceTests(unittest.TestCase):
    def test_owned_namespace_real_listeners_and_cleanup(self):
        import pwd
        import time
        root = Path(os.environ['RUNNER_TEMP']).resolve() / ('relay-test-' + os.environ['GITHUB_RUN_ID'])
        root.mkdir(mode=0o700)
        namespace = 'hp-dual-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
        script = """import os,socket,threading
s=socket.socket();s.bind(('127.0.0.1',0));s.listen(16)
print(str(os.getpid())+' '+str(s.getsockname()[1]),flush=True)
def serve(c):
 with c:
  while True:
   b=c.recv(65536)
   if not b: return
   c.sendall(b)
while True:
 c,_=s.accept();threading.Thread(target=serve,args=(c,),daemon=True).start()
"""
        peers=[]
        try:
            for _ in relay.ROLES:
                child=subprocess.Popen(['sudo','-n','ip','netns','exec',namespace,'runuser','-u',pwd.getpwuid(os.getuid()).pw_name,'--',sys.executable,'-u','-c',script],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
                peers.append(child)
            records=[]
            for child in peers:
                ready,_,_=__import__('select').select([child.stdout],[],[],15)
                self.assertTrue(ready, 'owned listener not ready')
                parts=child.stdout.readline().decode('ascii').split()
                self.assertEqual(len(parts),2)
                records.append(tuple(map(int,parts)))
            config={'namespace':namespace, **{role:records[i][1] for i,role in enumerate(relay.ROLES)},
                    'ownerPids':{role:records[i][0] for i,role in enumerate(relay.ROLES)},'sshPorts':[1,2]}
            manifest=root/'manifest.json';manifest.write_text(json.dumps(config));manifest.chmod(0o600)
            relay._namespace_exists(namespace)
            relay._verify_owned_listeners(relay.checked_manifest(manifest))
            bad={**config,'ownerPids':{**config['ownerPids'],'control':config['ownerPids']['derp']}}
            manifest.write_text(json.dumps(bad));manifest.chmod(0o600)
            with self.assertRaises(relay.RelayError): relay._verify_owned_listeners(relay.checked_manifest(manifest))
            bad={**config,'control':1}
            manifest.write_text(json.dumps(bad));manifest.chmod(0o600)
            with self.assertRaises(relay.RelayError): relay.checked_manifest(manifest)
            manifest.write_text(json.dumps(config));manifest.chmod(0o600)
            with relay.AndroidDualOverlayRelay(manifest) as bridge:
                ports=list(bridge.ports.values()); clients=[socket.create_connection(('127.0.0.1',p),timeout=10) for p in ports]
                try:
                    for i,c in enumerate(clients): c.sendall(bytes([i])*4096)
                    for i,c in enumerate(clients):
                        received=b''
                        while len(received)<4096: received+=c.recv(4096-len(received))
                        self.assertEqual(received,bytes([i])*4096)
                finally:
                    for c in clients: c.close()
            for port in ports:
                with socket.socket() as check:
                    check.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                    check.bind(('127.0.0.1',port))
            print('relay_linux: 3_loopback_streams=true wrong_pid_rejected=true ssh_port_rejected=true listeners_rebound=true')
        finally:
            for child in peers:
                try: relay._stop_process(child)
                finally:
                    if child.stdout: child.stdout.close()
            for path in root.iterdir(): path.unlink()
            root.rmdir()


if __name__ == '__main__': unittest.main()
