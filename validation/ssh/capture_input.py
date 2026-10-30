"""Temporary raw PTY receiver; launched only inside the isolated herdr test pane."""
import os
from pathlib import Path
import select
import sys
import termios
import time
import tty

root = Path(__file__).resolve().parent
fd = sys.stdin.fileno()
saved = termios.tcgetattr(fd)
data = b''
try:
    tty.setraw(fd)
    (root / 'capture-running').write_text(str(os.getpid()))
    (root / 'capture-ready').write_text('ready')
    os.write(1, b'FIXTURE_CAPTURE_READY\r\n')
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not (root / 'stop-capture').exists():
        if select.select([fd], [], [], 0.05)[0]:
            data += os.read(fd, 4096)
            (root / 'received.bin').write_bytes(data)
            if len(data) > 4096:
                break
finally:
    (root / 'capture-running').unlink(missing_ok=True)
    termios.tcsetattr(fd, termios.TCSANOW, saved)
