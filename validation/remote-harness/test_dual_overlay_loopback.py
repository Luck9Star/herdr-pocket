import hashlib
import json
import shutil
import os
from pathlib import Path
import pty
import queue
import select
import subprocess
import sys
import tempfile
import textwrap
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

    def test_workflow_uses_owned_easytier_prepare_paths(self):
        workflow = Path(__file__).resolve().parents[2] / '.github/workflows/dual-overlay-herdr-validation.yml'
        text = workflow.read_text()
        self.assertIn('--bundle "$RUNNER_TEMP/hp-easytier-bundle-$GITHUB_RUN_ID"', text)
        self.assertIn('--output "$RUNNER_TEMP/easytier-evidence"', text)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dual.et.checked_paths(root / 'hp-easytier-bundle-123', root / 'easytier-evidence', root, '123')

    def test_workflow_inline_bootstrap_reaches_fixture_validation(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github/workflows/dual-overlay-herdr-validation.yml').read_text()
        inline = workflow.split("python3 - <<'PY'\n", 1)[1].split('\n          PY\n', 1)[0]
        inline = textwrap.dedent(inline)
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'input-fixture').mkdir()
            env = dict(os.environ, RUNNER_TEMP=temp, GITHUB_RUN_ID='123', GITHUB_SHA='a' * 40)
            result = subprocess.run([sys.executable, '-c', inline], cwd=root, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('input_fixture_file_invalid', result.stderr)
        self.assertNotIn('ModuleNotFoundError', result.stderr)

    def test_workflow_inline_bootstrap_copies_only_verified_fixture(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github/workflows/dual-overlay-herdr-validation.yml').read_text()
        inline = workflow.split("python3 - <<'PY'\n", 1)[1].split('\n          PY\n', 1)[0]
        inline = textwrap.dedent(inline)
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / 'input-fixture'
            fixture.mkdir()
            bundle = Path(temp) / 'hp-easytier-bundle-123'
            bundle.mkdir()
            binary = b'synthetic fixture, never executed'
            (fixture / 'herdr').write_bytes(binary)
            patch = root / 'validation/herdr-input-extension/herdr-0.9.5-pocket-input.patch'
            shutil.copyfile(patch, fixture / patch.name)
            metadata = {'sourceSHA': 'a' * 40, 'upstreamSHA': dual.et.controlled.HERDR_COMMIT,
                        'patchSHA256': hashlib.sha256(patch.read_bytes()).hexdigest(),
                        'buildProfile': 'dev', 'configDirectory': 'herdr',
                        'scope': 'isolated validation fixture', 'binaryDebugAssertions': False,
                        'readinessAndCapabilitySmokePassed': True,
                        'binarySHA256': hashlib.sha256(binary).hexdigest()}
            (fixture / 'manifest.json').write_text(json.dumps(metadata))
            env = dict(os.environ, RUNNER_TEMP=temp, GITHUB_RUN_ID='123', GITHUB_SHA='a' * 40)
            result = subprocess.run([sys.executable, '-c', inline], cwd=root, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((bundle / 'herdr').read_bytes(), binary)

    def test_redacts_unrecognized_client_error(self):
        payload = {key: False for key in dual.BOOL_FIELDS}
        payload['error'] = 'private unexpected value'
        fields, error = dual.safe_result(payload)
        self.assertEqual(error, 'other_client_failure')
        self.assertEqual(set(fields), set(dual.BOOL_FIELDS))

    def test_both_stop_orders_require_their_own_evidence(self):
        common = {field: True for field in dual.BOOL_FIELDS}
        for first, active, inactive in (
                ('et', ('etStopped', 'etStaleRejected', 'tsAfterStop'),
                 ('tsStopped', 'tsStaleRejected', 'etAfterStop')),
                ('ts', ('tsStopped', 'tsStaleRejected', 'etAfterStop'),
                 ('etStopped', 'etStaleRejected', 'tsAfterStop'))):
            fields = dict(common)
            for field in inactive:
                fields[field] = False
            self.assertTrue(dual.case_passed(fields, first))
            fields[active[-1]] = False
            self.assertFalse(dual.case_passed(fields, first))
            fields[active[-1]] = True
            fields['tsObserverJoined'] = False
            self.assertFalse(dual.case_passed(fields, first))

    def test_fails_when_peer_exits_without_required_event(self):
        process = subprocess.Popen([sys.executable, '-c', 'pass'])
        process.wait()
        with self.assertRaisesRegex(dual.et.Failure, 'ts_fixture_exited_early'):
            dual.read_event(queue.Queue(), 'cleanup', process, timeout=1)


class PtyTests(unittest.TestCase):
    def test_separate_side_echo_and_exact_private_input(self):
        script = Path(__file__).with_name('dual_overlay_echo.py')
        for side in ('ET', 'TS'):
            with self.subTest(side=side), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                master, slave = pty.openpty()
                proc = subprocess.Popen([sys.executable, str(script), temp, side],
                                        stdin=slave, stdout=slave, stderr=subprocess.DEVNULL)
                os.close(slave)
                try:
                    deadline = time.monotonic() + 5
                    while not (root / 'capture-ready').exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue((root / 'capture-ready').exists())
                    payload = f'{side}-ONE\n{side}-TWO\n'.encode()
                    os.write(master, payload)
                    output = bytearray()
                    while f'ACK-{side}-TWO'.encode() not in output and time.monotonic() < deadline:
                        if select.select([master], [], [], .1)[0]:
                            output.extend(os.read(master, 4096))
                    self.assertIn(f'ACK-{side}-ONE'.encode(), output)
                    self.assertIn(f'ACK-{side}-TWO'.encode(), output)
                    self.assertEqual((root / 'received.bin').read_bytes(), payload)
                    (root / 'stop-capture').touch()
                    self.assertEqual(proc.wait(timeout=3), 0)
                finally:
                    if proc.poll() is None:
                        proc.kill(); proc.wait()
                    os.close(master)


if __name__ == '__main__':
    unittest.main()
