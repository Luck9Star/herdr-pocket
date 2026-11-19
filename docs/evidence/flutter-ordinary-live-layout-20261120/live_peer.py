"""Use the checkout's isolated SSH fixture with deterministic real scrollback."""
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(sys.argv[1]).resolve().parent))
import direct_ssh_fixture as fixture


def handle(connection, selected_key):
    transport = paramiko.Transport(connection)
    transport.add_server_key(selected_key)
    server = fixture.Server()
    try:
        transport.start_server(server=server)
        channel = transport.accept(10)
        if channel is None or not server.shell.wait(10):
            return
        channel.sendall(''.join(f'fixture output {index:03d}\r\n' for index in range(120)).encode()
                        + b'SCROLLBACK-READY\r\n')
        while transport.is_active():
            data = channel.recv(1024)
            if not data:
                print('STDIN_EOF', flush=True)
                break
            print('INPUT', repr(data), flush=True)
            channel.sendall(b'ECHO:' + data + b'\r\n')
    except (EOFError, OSError, paramiko.SSHException):
        pass
    finally:
        transport.close()


fixture.handle = handle
fixture.main()
