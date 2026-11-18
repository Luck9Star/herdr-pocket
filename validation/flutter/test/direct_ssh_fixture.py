"""Disposable loopback SSH peer used only by direct_ssh_fixture_runner.py."""
import os
from pathlib import Path
import socket
import threading

import paramiko


class Server(paramiko.ServerInterface):
    def __init__(self):
        self.shell = threading.Event()

    def check_auth_password(self, username, password):
        print('AUTH', username, flush=True)
        return (paramiko.AUTH_SUCCESSFUL if (username, password) == ('fixture', 'temporary')
                else paramiko.AUTH_FAILED)

    def check_auth_publickey(self, username, offered):
        expected = os.environ.get('HERDR_FIXTURE_PUBLIC_KEY')
        accepted = expected and offered.get_base64() == Path(expected).read_text().split()[1]
        print('PUBLICKEY', username, flush=True)
        return paramiko.AUTH_SUCCESSFUL if username == 'fixture' and accepted else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return 'publickey,password'

    def check_channel_request(self, kind, chanid):
        return (paramiko.OPEN_SUCCEEDED if kind == 'session'
                else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED)

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        print('PTY', width, height, flush=True)
        return True

    def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
        print('RESIZE', width, height, flush=True)
        return True

    def check_channel_shell_request(self, channel):
        self.shell.set()
        return True


def handle(conn, selected_key):
    transport = paramiko.Transport(conn)
    transport.add_server_key(selected_key)
    server = Server()
    try:
        transport.start_server(server=server)
        channel = transport.accept(10)
        if channel is None:
            return
        server.shell.wait(10)
        channel.send('fixture 中文 shell\r\n'.encode())
        while transport.is_active():
            data = channel.recv(1024)
            if not data:
                break
            print('INPUT', repr(data), flush=True)
            channel.send(data)
    except (EOFError, OSError, paramiko.SSHException):
        pass
    finally:
        transport.close()


def main():
    key = paramiko.RSAKey.generate(2048)
    other_key = paramiko.RSAKey.generate(2048)
    rotate = os.environ.get('HERDR_FIXTURE_ROTATE_KEY') == '1'
    connections = 0
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', int(os.environ.get('HERDR_FIXTURE_PORT', '0'))))
        listener.listen(10)
        print('PORT', listener.getsockname()[1], flush=True)
        while True:
            conn, _ = listener.accept()
            connections += 1
            selected = other_key if rotate and connections > 1 else key
            threading.Thread(target=handle, args=(conn, selected), daemon=True).start()


if __name__ == '__main__':
    main()
