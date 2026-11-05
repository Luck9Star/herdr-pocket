"""No sshd, network or credentials: assert the CI authorization/evidence gate."""
from pathlib import Path
import tempfile
import time
import unittest

# Legacy read-only harness runs in a Python without pairing dependencies.
try:
    from paired_gui import FixtureApproval, GuiFailure
    from pairing import FixturePairingHost, MemoryKeyStore, PendingPairing, encode
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    FixtureApproval = None


@unittest.skipIf(FixtureApproval is None, 'pairing requirements are installed in the GUI workflow')
class GuiFixtureTests(unittest.TestCase):
    def test_only_reviewed_key_authenticates_and_revokes(self):
        store = MemoryKeyStore()
        host_public = store.public(store.create())
        key = store.create()
        with tempfile.TemporaryDirectory() as folder, FixturePairingHost(host_public_key=host_public, fixture_account='runner') as host:
            root = Path(folder)
            (root/'authorized_keys').write_bytes(b'')
            approval = FixtureApproval(root, {'username':'runner'}, host)
            pending = PendingPairing(store, key, account='runner', device='test phone',
                                     expected_host_key=host.host_key, now=int(time.time()))
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
