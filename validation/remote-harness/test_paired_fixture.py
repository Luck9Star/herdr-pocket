"""No sshd, network or credentials: assert the CI authorization/evidence gate."""
from pathlib import Path
from types import SimpleNamespace
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

# Legacy read-only harness runs in a Python without pairing dependencies.
try:
    from paired_gui import FixtureApproval, GuiFailure, Host, WebDriver, run_gui, widget_failure
    from pairing import MemoryKeyStore, PendingPairing, encode
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    FixtureApproval = None


@unittest.skipIf(FixtureApproval is None, 'pairing requirements are installed in the GUI workflow')
class GuiFixtureTests(unittest.TestCase):
    def test_mobile_guarded_run_requires_an_independent_clipboard_receiver_check(self):
        first = dict(paneId='p', terminalId='term_ab', acceptedBytes=1, requestId='0' * 32)
        second = dict(first, acceptedBytes=9, requestId='1' * 32)
        args = SimpleNamespace(paired_gui='tauri-android', input_fixture=True)
        env = dict(GITHUB_ACTIONS='true', GITHUB_RUN_ID='38', GITHUB_REF='refs/heads/codex/test')
        target = dict(paneId='p', username='fixture', host='127.0.0.1', expectedHostKey='fixture')
        with tempfile.TemporaryDirectory(dir='/tmp', prefix='hp-mobile-38-') as directory:
            root = Path(directory)
            (root / 'authorized_keys').touch()
            with patch.dict(os.environ, env), patch('paired_gui.Host'), patch('paired_gui.FixtureApproval'), \
                    patch('paired_gui.fixture_terminal_id', return_value='term_ab'), \
                    patch('android_gui.run_android') as exercise:
                for field in (None, False, 1, True):
                    with self.subTest(checkpoint=field):
                        observed = dict(inputQueueAccepted=True, inputReceipts=[first, second])
                        if field is not None:
                            observed['pasteOperationsNoExtraSshBytes'] = field
                        exercise.return_value = observed
                        result = run_gui(args, root, env, target)
                        if field is True:
                            self.assertEqual(result['status'], 'passed')
                        else:
                            self.assertEqual(result['status'], 'failed')
                            self.assertEqual(result['errorCode'], 'mobile_clipboard_receiver_check_missing')

    def test_driver_waits_for_the_native_form_before_sending_keys(self):
        driver = WebDriver()
        driver.session = '/session/test'
        driver.element = Mock(return_value='/field')
        driver.read = Mock(return_value='fixture')
        calls = []
        def command(method, path, data):
            calls.append(path)
            if path.endswith('/execute/sync'):
                self.assertIn("matches(':disabled')", data['script'])
                return len(calls) == 2
        driver.call = command
        driver.fill('#remote-host', 'fixture')
        self.assertEqual(calls, ['/session/test/execute/sync'] * 2 +
                         ['/field/clear', '/field/value'])

    def test_widget_failure_stage_only_emits_an_allowlisted_value(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'stage'
            path.write_text('public_request')
            self.assertEqual(str(widget_failure(path.parent, 'failed')), 'failed_public_request')
            path.write_text('unrecognized test metadata')
            self.assertEqual(str(widget_failure(path.parent, 'failed')), 'failed')

    def test_only_reviewed_key_authenticates_and_revokes(self):
        store = MemoryKeyStore()
        host_public = store.public(store.create())
        key = store.create()
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as scratch:
            host = Host(Path(scratch), 'runner', host_public)
            root = Path(folder)
            (root/'authorized_keys').write_bytes(b'')
            approval = FixtureApproval(root, {'username':'runner'}, host)
            pending = PendingPairing(store, key, account='runner', device='test phone',
                                     expected_host_key=host.pin, now=int(time.time()))
            wire = encode(pending.request)
            wrong = dict(pending.request, account='different')
            with self.assertRaisesRegex(GuiFailure, 'fixture_public_request_invalid'):
                approval.approve(encode(wrong))
            self.assertEqual((root/'authorized_keys').read_bytes(), b'')
            approval.approve(wire)
            self.assertIn(store.public(key).encode(), (root/'authorized_keys').read_bytes())
            (root/'sshd.log').write_text('Accepted publickey for runner from 127.0.0.1 port 2234 ssh2: ED25519 SHA256:wrong\n')
            with self.assertRaisesRegex(GuiFailure, 'fingerprint_not_authenticated'):
                approval.verify_ssh()
            (root/'sshd.log').write_text(f'Accepted publickey for runner from 127.0.0.1 port 2234 ssh2: ED25519 {approval.fingerprint}\n')
            (root/'capture-running').touch()
            (root/'received.bin').write_bytes(b'x')
            with self.assertRaisesRegex(GuiFailure, 'unexpected_remote_input'):
                approval.verify_ssh()
            (root/'received.bin').write_bytes(b'')
            approval.verify_ssh()
            approval.revoke()
            self.assertEqual((root/'authorized_keys').read_bytes(), b'')
