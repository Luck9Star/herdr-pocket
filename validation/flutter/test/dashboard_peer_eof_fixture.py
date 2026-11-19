"""Local-only SSH peer for the dashboard EOF widget regression."""
import io
import json
import socket
import sys
import threading

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def new_key():
    pem = ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption()).decode()
    return pem, paramiko.Ed25519Key.from_private_key(io.StringIO(pem))


class DashboardPeer(paramiko.ServerInterface):
    def __init__(self, watch):
        self.watch = watch
        self.status = 'blocked'
        self.subscribers = set()
        self.lock = threading.Lock()
        self.client_pem, self.client_key = new_key()

    def check_auth_publickey(self, username, key):
        if username == 'fixture' and key.asbytes() == self.client_key.asbytes():
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return 'publickey'

    def check_channel_request(self, kind, chanid):
        if kind == 'direct-streamlocal@openssh.com':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    @staticmethod
    def send(channel, record):
        channel.sendall((json.dumps(record) + '\n').encode())

    def channel(self, channel):
        try:
            request = json.loads(channel.makefile('rb').readline(65536))
            response = {'id': request['id']}
            method = request['method']
            if method == 'session.snapshot':
                with self.lock:
                    status = self.status
                response['result'] = {'type': 'session_snapshot', 'snapshot': {
                    'version': '0.9.5', 'protocol': 22, 'panes': [
                        {'pane_id': 'w1:p1', 'terminal_id': 'term_abcd', 'agent_status': status}]}}
            elif method == 'events.subscribe' and self.watch:
                response['result'] = {'type': 'subscription_started'}
                if any(sub.get('pane_id') == 'w1:p1' for sub in request['params']['subscriptions']):
                    with self.lock:
                        self.subscribers.add(channel)
            elif method in {'events.subscribe', 'pocket.input.capabilities'}:
                response['error'] = {'code': 'method_not_found', 'message': 'fixture unsupported'}
            else:
                raise ValueError('unknown dashboard fixture method')
            self.send(channel, response)
            while channel.recv(64):
                pass
        except (OSError, EOFError):
            pass
        finally:
            with self.lock:
                self.subscribers.discard(channel)
            channel.close()

    def accept_channels(self, transport):
        while transport.is_active():
            channel = transport.accept(timeout=0.1)
            if channel is not None:
                threading.Thread(target=self.channel, args=(channel,), daemon=True).start()

    def advance(self):
        with self.lock:
            self.status = 'working'
            channels = [channel for channel in self.subscribers if not channel.closed]
        assert len(channels) == 1
        self.send(channels[0], {'event': 'pane.agent_status_changed',
                               'data': {'pane_id': 'w1:p1', 'workspace_id': 'w1', 'agent_status': 'working'}})


def main():
    peer = DashboardPeer(sys.argv[1] == 'watch')
    _, host_key = new_key()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(15)
        print(json.dumps({'port': listener.getsockname()[1],
                          'key': f'{host_key.get_name()} {host_key.get_base64()}',
                          'client': peer.client_pem}), flush=True)
        incoming, _ = listener.accept()
        transport = paramiko.Transport(incoming)
        try:
            transport.add_server_key(host_key)
            transport.start_server(server=peer)
            threading.Thread(target=peer.accept_channels, args=(transport,), daemon=True).start()
            for line in sys.stdin:
                assert transport.is_authenticated()
                if line.strip() == 'advance':
                    peer.advance()
                    print('advanced', flush=True)
                elif line.strip() == 'close':
                    transport.close()
                    print('authenticated-peer-closed', flush=True)
                    break
                else:
                    raise ValueError('unknown dashboard fixture command')
        finally:
            transport.close()


if __name__ == '__main__':
    main()
