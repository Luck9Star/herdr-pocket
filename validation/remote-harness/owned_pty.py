"""Disposable POSIX PTYs and termios comparisons for the isolated harness."""
from contextlib import contextmanager
import fcntl
import os
import pty
import struct
import sys
import termios


@contextmanager
def new_pty(rows=24, columns=80):
    master, slave = pty.openpty()
    try:
        resize(slave, rows, columns)
        yield master, slave
    finally:
        os.close(master)
        os.close(slave)


def resize(fd, rows, columns):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))


def restored_modes(attributes):
    # Darwin may set PENDIN while switching from raw to canonical mode. This
    # kernel input-queue marker is not a requested echo/canonical/signal mode.
    # Compare every other attribute, rather than dropping the whole lflag word.
    result = list(attributes)
    if sys.platform == 'darwin':
        result[3] &= ~getattr(termios, 'PENDIN', 0)
    return result
