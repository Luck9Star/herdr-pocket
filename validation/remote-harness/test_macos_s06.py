"""Source and owned stock-SSH checks. Native XCUITest runs on its own workflow."""
import base64
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    import macos_s06 as runner
    from paired_dual_demo import fixture_sshd_config, ssh_args
    from paired_gui import GuiFailure, wait_for
    from pairing import MemoryKeyStore, PendingPairing, encode
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    runner = None

BINARY = os.environ.get('HERDR_MACOS_S06_BINARY')


@unittest.skipIf(runner is None, 'requires validation/pairing/requirements.txt')
class MacosS06Checks(unittest.TestCase):
    def test_scope_rejects_local_native_launch(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(GuiFailure, 'requires_isolated_arm64_runner'):
                runner.isolated_runner(Path('/tmp/ordinary-app'), Path('/tmp/ordinary-output'))

    def test_optional_session_changes_only_the_owned_socket_policy(self):
        root = Path('/tmp/owned')
        default = fixture_sshd_config(root, 2345, 'fixture')
        explicit = fixture_sshd_config(root, 2345, 'fixture', 's06-a')
        self.assertIn('PermitOpen [/tmp/owned/config/herdr/sessions/qa-pair/herdr.sock]:*\n', default)
        self.assertEqual(explicit, default.replace('/qa-pair/', '/s06-a/'))
        for invalid in ('default', '../bad', 'two names', None):
            with self.assertRaisesRegex(GuiFailure, 'fixture_session_name_invalid'):
                fixture_sshd_config(root, 2345, 'fixture', invalid)

    def test_native_report_rejects_missing_checks_and_fake_widths(self):
        report = {'checks': dict.fromkeys(runner.CHECKS, True), 'widths': [1440, 700, 1440]}
        self.assertEqual(runner.checked_ui_result(report), report)
        for key in runner.CHECKS:
            changed = copy.deepcopy(report)
            changed['checks'][key] = False
            with self.assertRaisesRegex(GuiFailure, 'checks_incomplete'):
                runner.checked_ui_result(changed)
        for widths in ([1440, 1440, 1440], [1440, 700], [1440, 700.0, 1440]):
            with self.assertRaisesRegex(GuiFailure, 'widths_invalid'):
                runner.checked_ui_result({**report, 'widths': widths})

    def test_progress_does_not_export_arbitrary_text(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            for phase, expected in [('resize', 'resize'), ('arbitrary text', None), ('x' * 40, None)]:
                (root / 'stage').write_text(phase)
                self.assertEqual(runner.native_stage(root), expected)

    @unittest.skipUnless(BINARY and sys.platform == 'darwin', 'requires explicit owned-stock macOS opt-in')
    def test_two_real_stock_peers_advance_their_own_terminal_and_close(self):
        keys = MemoryKeyStore()
        with tempfile.TemporaryDirectory(prefix='hps06t-', dir='/tmp') as directory:
            base = Path(directory).resolve()
            with runner.fixtures(Path(BINARY), base) as (targets, owned, metadata, configs):
                self.assertEqual(metadata['herdrSha256'], runner.HERDR_SHA256)
                with ExitStack() as readers:
                    clients = []
                    for target, config in zip(targets.values(), configs):
                        handle = keys.create()
                        pairing = PendingPairing(keys, handle, account=config['username'],
                            expected_host_key=target.host.pin, device='Owned local test', now=int(time.time()))
                        request = encode(pairing.request)
                        review = target.review(request)
                        target.approve(request, request_id=review['requestId'],
                                       device_fingerprint=review['deviceFingerprint'], reviewed=True)
                        private = target.root / 'client'
                        private.write_bytes(keys._keys[handle].private_bytes(
                            Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()))
                        private.chmod(0o600)
                        command = shlex.join([config['herdrPath'], '--session', config['session'],
                                              'terminal', 'session', 'observe', config['terminalId'],
                                              '--cols', '80', '--rows', '24'])
                        ssh = ssh_args(target.root, config['port'], config['username'], private, command)
                        client = readers.enter_context(subprocess.Popen(
                            ssh, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0))
                        readers.callback(self.stop_client, client)
                        clients.append(client)
                    for client, config in zip(clients, configs):
                        first, second = self.frame(client), self.frame(client)
                        self.assertEqual(first['type'], 'terminal.frame')
                        self.assertIs(first['full'], True)
                        self.assertIs(second['full'], False)
                        self.assertEqual((first['width'], first['height']), (80, 24))
                        self.assertEqual(second['seq'], first['seq'] + 1)
                        pattern = re.escape(config['marker'].encode()) + rb' ([0-9]{6})'
                        pixels = [base64.b64decode(frame['bytes'], validate=True) for frame in (first, second)]
                        full = re.search(pattern, pixels[0])
                        self.assertIsNotNone(full)
                        # herdr only writes the changed digits in a delta.
                        move = re.search(rb'\x1b\[12;([0-9]+)H(?:\x1b\[[0-9;]+m)*([0-9]+)', pixels[1])
                        self.assertIsNotNone(move)
                        start = int(move.group(1)) - 8
                        digits, replacement = full.group(1), move.group(2)
                        self.assertTrue(0 <= start < start + len(replacement) <= len(digits))
                        updated = digits[:start] + replacement + digits[start + len(replacement):]
                        self.assertGreater(int(updated), int(digits))
                    self.assertTrue(all(client.poll() is None for client in clients))
                for target in targets.values():
                    wait_for(lambda: runner.peer_connection_evidence(target.approval) ==
                             {'authenticationCount': 1, 'closed': True}, 'owned_stock_peer_not_closed', timeout=5)
                    self.assertEqual(target.audit(b'')['receivedBytes'], 0)
                wait_for(lambda: all(json.loads((target.root / 'pty-size.json').read_text())['elapsedMs'] >= 1000
                                     for target in targets.values()), 'owned_pty_record_too_short', timeout=5)
            for target in targets.values():
                self.assertEqual(runner.final_pty(target.root)['changes'], 0)
                self.assertEqual((target.root / 'authorized_keys').read_bytes(), b'')
                self.assertFalse((target.root / 'capture-running').exists())
                self.assertIsNotNone(target.approval.revocation_response)
            self.assertTrue(all(child.poll() is not None for child in owned))
        self.assertFalse(base.exists())

    @staticmethod
    def frame(client):
        # First frame contains the controlled few cells. Keep a bounded line
        # and a separate read deadline for each active SSH peer.
        from selectors import DefaultSelector, EVENT_READ
        with DefaultSelector() as selector:
            selector.register(client.stdout, EVENT_READ)
            if not selector.select(10):
                raise RuntimeError('owned_stock_frame_timeout')
            return json.loads(client.stdout.readline(65537))

    @staticmethod
    def stop_client(client):
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
