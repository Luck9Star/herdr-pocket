from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from linux_pairing_keyring import KeyringEvidence, KeyringFailure, MARKER, private_home


class PrivateKeyringTests(unittest.TestCase):
    def test_public_probe_cannot_join_arbitrary_bus(self):
        with tempfile.TemporaryDirectory(prefix='herdr-pairing-keyring.', dir='/tmp') as raw:
            env = {MARKER: raw, 'HOME': str(Path(raw) / 'home'),
                   'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus'}
            with patch.dict('os.environ', env, clear=True):
                with self.assertRaisesRegex(KeyringFailure, 'private_keyring_session_required'):
                    private_home()

    def test_search_accepts_only_unlocked_exact_items(self):
        path = '/org/freedesktop/secrets/collection/login/1'
        with patch('linux_pairing_keyring.bus_call') as call:
            call.return_value = '(@ao [], @ao [])'
            self.assertEqual(KeyringEvidence.items('herdr-pocket.flutter'), [])
            call.return_value = f"([objectpath '{path}'], @ao [])"
            self.assertEqual(KeyringEvidence.items('herdr-pocket.flutter'), [path])
            for invalid in (f"(@ao [], [objectpath '{path}'])", f"([objectpath '{path}', '{path}'], @ao [])"):
                call.return_value = invalid
                with self.assertRaisesRegex(KeyringFailure, 'private_keyring_items_unverified'):
                    KeyringEvidence.items('herdr-pocket.flutter')

    def test_requires_one_new_key_with_matching_public_material(self):
        handle = 'a' * 32
        with patch('linux_pairing_keyring.private_home'), patch('linux_pairing_keyring.KeyringEvidence.items') as items, \
                patch('linux_pairing_keyring.bus_call') as call, patch('linux_pairing_keyring.subprocess.run') as run:
            items.return_value = []
            verifier = KeyringEvidence('flutter', Path('/bin/ls'))
            with self.assertRaisesRegex(KeyringFailure, 'private_keyring_item_count_wrong'):
                verifier.verify('ssh-ed25519 reviewed')
            run.assert_not_called()
            items.return_value = ['/org/freedesktop/secrets/collection/login/1']
            call.return_value = "(<{'handle': '" + handle + "'}>,)"
            run.return_value = subprocess.CompletedProcess([], 0, 'ssh-ed25519 different\n')
            with self.assertRaisesRegex(KeyringFailure, 'private_keyring_public_key_mismatch'):
                verifier.verify('ssh-ed25519 reviewed')
            self.assertFalse(verifier.verified)
            run.return_value = subprocess.CompletedProcess([], 0, 'ssh-ed25519 reviewed\n')
            verifier.verify('ssh-ed25519 reviewed')
            run.assert_called_with(['/bin/ls', 'herdr-pocket.flutter', handle], capture_output=True, text=True, timeout=15)
            self.assertEqual(verifier.verified, {handle})
            with self.assertRaisesRegex(KeyringFailure, 'private_keyring_item_count_wrong'):
                verifier.verify('ssh-ed25519 reviewed')
