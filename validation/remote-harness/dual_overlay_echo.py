#!/usr/bin/env python3
"""Private PTY fixture; records exact accepted bytes and emits fixed replies."""
import os
from pathlib import Path
import select
import sys
import termios
import time
import tty


def main():
    root = Path(sys.argv[1])
    side = sys.argv[2]
    if side not in ('ET', 'TS') or not root.is_dir():
        return 2
    expected = {b'ET-ONE\n': b'ACK-ET-ONE', b'TS-ONE\n': b'ACK-TS-ONE',
                b'TS-TWO\n': b'ACK-TS-TWO'}
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        (root / 'received.bin').write_bytes(b'')
        os.write(1, f'READY-{side}\r\n'.encode())
        (root / 'capture-ready').write_text('ready')
        received = bytearray()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and not (root / 'stop-capture').exists():
            if not select.select([fd], [], [], .1)[0]:
                continue
            chunk = os.read(fd, 128)
            if not chunk:
                break
            received.extend(chunk)
            if len(received) > 1024:
                return 1
            with (root / 'received.bin').open('ab') as output:
                output.write(chunk)
                output.flush()
            while b'\n' in received:
                line, _, remaining = received.partition(b'\n')
                received[:] = remaining
                reply = expected.get(bytes(line) + b'\n')
                if reply is None or not reply.startswith(f'ACK-{side}-'.encode()):
                    return 1
                os.write(1, reply + b'\r\n')
        return 0
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, original)


if __name__ == '__main__':
    sys.exit(main())
