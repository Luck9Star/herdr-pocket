"""Isolated pane fixture: shared pixels/input bytes and numeric PTY evidence.

pty-size.json contains only integers. state: 1 running, 2 normal final,
3 failed. endReason: 0 running, 1 stop file, 2 deadline, 3 input limit,
4 input EOF, 5 capture/cleanup error, 6 termination signal. Samples and
SIGWINCH handler calls are observations, not a lossless resize history.
"""
import json
import math
import os
from pathlib import Path
import select
import signal
import sys
import termios
import time
import tty

class PtySizeRecorder:
    def __init__(self, root, fd, poll_interval=0.05):
        if not 0.001 <= poll_interval <= 1:
            raise ValueError('invalid_pty_sample_interval')
        self.root, self.fd = Path(root), fd
        self.interval = poll_interval
        self.started = time.monotonic()
        self.last_sample = None
        self.next_sample = self.started
        self.sampled_handlers = 0
        self.last_published = 0.0
        self.closed = False
        self.record = {'schemaVersion': 1, 'state': 1, 'endReason': 0,
            'initialRows': 0, 'initialColumns': 0, 'rows': 0, 'columns': 0,
            'samples': 0, 'changes': 0, 'readErrors': 0, 'captureErrors': 0,
            'winchHandlers': 0, 'signalSamples': 0, 'signalAvailable': 0,
            'signalsMayCoalesce': 1, 'elapsedMs': 0, 'maxSampleGapMs': 0,
            'sampleIntervalMs': math.ceil(poll_interval * 1000), 'terminationSignal': 0}

    def note_winch(self, _number, _frame):
        # Python signal callbacks only mark work. No terminal/file I/O, locks,
        # or assumption that one callback represents one kernel size change.
        self.record['winchHandlers'] += 1

    def _sample(self):
        observed_handlers = self.record['winchHandlers']
        if observed_handlers > self.sampled_handlers:
            self.record['signalSamples'] += 1
        self.sampled_handlers = observed_handlers
        now = time.monotonic()
        self.next_sample = now + self.interval
        try:
            size = os.get_terminal_size(self.fd)
            if not 1 <= size.lines <= 65535 or not 1 <= size.columns <= 65535:
                raise OSError('invalid_pty_dimensions')
        except OSError:
            self.record['readErrors'] += 1
            return
        if self.last_sample is not None:
            self.record['maxSampleGapMs'] = max(self.record['maxSampleGapMs'],
                math.ceil((now - self.last_sample) * 1000))
            if (size.lines, size.columns) != (self.record['rows'], self.record['columns']):
                self.record['changes'] += 1
        else:
            self.record['initialRows'], self.record['initialColumns'] = size.lines, size.columns
        self.last_sample = now
        self.record['rows'], self.record['columns'] = size.lines, size.columns
        self.record['samples'] += 1

    def _publish(self, durable=False):
        self.record['elapsedMs'] = math.ceil((time.monotonic() - self.started) * 1000)
        snapshot = dict(self.record)
        if not all(type(value) is int and value >= 0 for value in snapshot.values()):
            raise ValueError('invalid_numeric_pty_record')
        pending = self.root / 'pty-size.json.new'
        # Refuse an unexpected pending file/link instead of following it.
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
                json.dump(snapshot, stream, separators=(',', ':'), sort_keys=True)
                stream.write('\n'); stream.flush()
                if durable:
                    os.fsync(stream.fileno())
            os.replace(pending, self.root / 'pty-size.json')
            self.last_published = time.monotonic()
        finally:
            pending.unlink(missing_ok=True)

    def start(self):
        self.started = time.monotonic()
        self._sample()
        self._publish()
        if self.record['readErrors']:
            raise OSError('pty_size_unavailable')

    def poll(self):
        if self.closed:
            raise ValueError('pty_recorder_already_finished')
        if time.monotonic() >= self.next_sample or self.record['winchHandlers'] > self.sampled_handlers:
            previous = (self.record['changes'], self.record['readErrors'])
            self._sample()
            if previous != (self.record['changes'], self.record['readErrors']) or time.monotonic() - self.last_published >= 1:
                self._publish()

    def finish(self, reason, termination_signal=0, capture_errors=0):
        if self.closed:
            raise ValueError('pty_recorder_already_finished')
        self._sample()
        self.record.update(endReason=reason, terminationSignal=int(termination_signal), captureErrors=capture_errors)
        normal = reason in (1, 2) and not (self.record['readErrors'] or capture_errors or termination_signal)
        self.record['state'] = 2 if normal else 3
        self._publish(durable=True)
        self.closed = True


def run_fixture(root=None, timeout=900):
    root = Path(__file__).resolve().parent if root is None else Path(root)
    fd = sys.stdin.fileno()
    recorder = PtySizeRecorder(root, fd)
    saved, handlers = None, {}
    received = bytearray()
    ending_signal, reason, capture_errors = 0, 5, 0

    def stop_signal(number, _frame):
        nonlocal ending_signal
        if not ending_signal:
            ending_signal = number

    try:
        if hasattr(signal, 'SIGWINCH'):
            handlers[signal.SIGWINCH] = signal.signal(signal.SIGWINCH, recorder.note_winch)
            recorder.record['signalAvailable'] = 1
        for number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            handlers[number] = signal.signal(number, stop_signal)
        saved = termios.tcgetattr(fd)
        tty.setraw(fd)
        (root / 'received.bin').write_bytes(b'')
        data = json.loads((root / 'terminal-fixture.json').read_text())['frames'][0]['data']
        data = data.replace('No real SSH connection. Input is captured locally.',
                            'Isolated SSH fixture. Remote input must remain empty.')
        os.write(1, data.encode('utf-8'))
        # Baseline publication precedes ready; every layout experiment must
        # take place after this boundary and before explicit stop-capture.
        recorder.start()
        (root / 'capture-running').write_text(str(os.getpid()))
        (root / 'capture-ready').write_text('ready')
        deadline = time.monotonic() + timeout
        next_tick = time.monotonic()
        tick = 0
        while True:
            recorder.poll()
            if ending_signal:
                reason = 6; break
            if (root / 'stop-capture').exists():
                reason = 1; break
            if time.monotonic() >= deadline:
                reason = 2; break
            if time.monotonic() >= next_tick:
                tick += 1
                os.write(1, f'\x1b7\x1b[23;1HSynthetic observe tick {tick:06d}\x1b[K\x1b8'.encode('ascii'))
                next_tick = time.monotonic() + 0.2
            if select.select([fd], [], [], 0.05)[0]:
                incoming = os.read(fd, 4096)
                if not incoming:
                    reason = 4; break
                received.extend(incoming)
                (root / 'received.bin').write_bytes(received)
                if len(received) > 4096:
                    reason = 3; break
    except BaseException:
        capture_errors += 1
        raise
    finally:
        try:
            if saved is not None:
                termios.tcsetattr(fd, termios.TCSANOW, saved)
        except (OSError, termios.error):
            capture_errors += 1
        try:
            recorder.finish(reason, ending_signal, capture_errors)
        finally:
            for number, previous in handlers.items():
                signal.signal(number, previous)
            (root / 'capture-running').unlink(missing_ok=True)
    return 0 if recorder.record['state'] == 2 else 1


if __name__ == '__main__':
    try:
        raise SystemExit(run_fixture())
    except Exception:
        # Failure is numeric in pty-size.json; no exception text/history is
        # copied into this public evidence or a terminal diagnostic stream.
        raise SystemExit(1)
