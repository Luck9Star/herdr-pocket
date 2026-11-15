import json
import os
from pathlib import Path
import pty
import queue
import select
import subprocess
import sys
import tempfile
import time
import unittest

import dual_overlay_loopback as dual


class EventTests(unittest.TestCase):
    def test_selects_json_event_without_publishing_other_output(self):
        events = queue.Queue()
        events.put(b'PASS\n')
        events.put(json.dumps({'event': 'ready', 'peerPort': 2222}).encode())
        process = subprocess.Popen([sys.executable, '-c', 'pass'])
        try:
            self.assertEqual(dual.read_event(events, 'ready', process)['peerPort'], 2222)
        finally:
            process.wait()

    def test_redacts_unrecognized_client_error(self):
        payload = {key: False for key in dual.BOOL_FIELDS}
        payload['error'] = 'private unexpected value'
        fields, error = dual.safe_result(payload)
        self.assertEqual(error, 'other_client_failure')
        self.assertEqual(set(fields), set(dual.BOOL_FIELDS))

    def test_fails_when_peer_exits_without_required_event(self):
        process = subprocess.Popen([sys.executable, '-c', 'pass'])
        process.wait()
        with self.assertRaisesRegex(dual.et.Failure, 'ts_fixture_exited_early'):
            dual.read_event(queue.Queue(), 'cleanup', process, timeout=1)


class PtyTests(unittest.TestCase):
    def test_separate_side_echo_and_exact_private_input(self):
        script = Path(__file__).with_name('dual_overlay_echo.py')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            master, slave = pty.openpty()
            proc = subprocess.Popen([sys.executable, str(script), temp, 'TS'],
                                    stdin=slave, stdout=slave, stderr=subprocess.DEVNULL)
            os.close(slave)
            try:
                deadline = time.monotonic() + 5
                while not (root / 'capture-ready').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((root / 'capture-ready').exists())
                os.write(master, b'TS-ONE\nTS-TWO\n')
                output = bytearray()
                while b'ACK-TS-TWO' not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        output.extend(os.read(master, 4096))
                self.assertIn(b'ACK-TS-ONE', output)
                self.assertIn(b'ACK-TS-TWO', output)
                self.assertEqual((root / 'received.bin').read_bytes(), b'TS-ONE\nTS-TWO\n')
                (root / 'stop-capture').touch()
                self.assertEqual(proc.wait(timeout=3), 0)
            finally:
                if proc.poll() is None:
                    proc.kill(); proc.wait()
                os.close(master)


if __name__ == '__main__':
    unittest.main()
