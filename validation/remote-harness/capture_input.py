"""CI-only pane fixture: render shared bytes and record any unexpected input."""
import json
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
received = bytearray()
try:
    tty.setraw(fd)
    (root / 'received.bin').write_bytes(b'')
    (root / 'capture-running').write_text(str(os.getpid()))
    data = json.loads((root / 'terminal-fixture.json').read_text())['frames'][0]['data']
    data = data.replace('No real SSH connection. Input is captured locally.',
                        'Isolated SSH fixture. Remote input must remain empty.')
    os.write(1, data.encode('utf-8'))
    (root / 'capture-ready').write_text('ready')
    deadline = time.monotonic() + 900
    next_tick = time.monotonic()
    tick = 0
    while time.monotonic() < deadline and not (root / 'stop-capture').exists():
        if time.monotonic() >= next_tick:
            # A fixed row changes without accepting input or resizing the PTY.
            # Save/restore the cursor so the shared fixture remains comparable.
            tick += 1
            os.write(1, f'\x1b7\x1b[23;1HSynthetic observe tick {tick:06d}\x1b[K\x1b8'.encode('ascii'))
            next_tick = time.monotonic() + 0.2
        if select.select([fd], [], [], 0.05)[0]:
            received.extend(os.read(fd, 4096))
            (root / 'received.bin').write_bytes(received)
            if len(received) > 4096:
                break
finally:
    (root / 'capture-running').unlink(missing_ok=True)
    termios.tcsetattr(fd, termios.TCSANOW, saved)
