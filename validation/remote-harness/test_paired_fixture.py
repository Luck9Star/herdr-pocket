"""No sshd, network or credentials: assert the CI authorization/evidence gate."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock

# Legacy read-only harness runs in a Python without pairing dependencies.
try:
    from paired_gui import FixtureApproval, GuiFailure, Host, WebDriver, widget_failure
    from pairing import MemoryKeyStore, PendingPairing, encode
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    FixtureApproval = None


@unittest.skipIf(FixtureApproval is None, 'pairing requirements are installed in the GUI workflow')
class GuiFixtureTests(unittest.TestCase):
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
                         ['/field/click', '/field/clear', '/field/value'])

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
            with self.assertRaises(ValueError):
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
