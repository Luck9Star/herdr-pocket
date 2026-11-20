import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from linux_pairing_keyring import (
    DENIAL_CHANNEL, KeyringEvidence, KeyringFailure, MARKER, denied_service, private_home, require_denial,
)


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

    @unittest.skipUnless(os.name == 'posix', 'private UNIX socket and symlink')
    def test_private_bus_rejects_symlinks_and_fallback_bus_addresses(self):
        with tempfile.TemporaryDirectory(prefix='herdr-pairing-keyring.', dir='/tmp') as raw, \
                socket.socket(socket.AF_UNIX) as bus:
            root = Path(raw)
            listening = root / 'owned'
            bus.bind(str(listening))
            path = root / 'bus'
            path.symlink_to(listening)
            env = {MARKER: raw, 'HOME': str(root / 'home'), 'DBUS_SESSION_BUS_ADDRESS': f'unix:path={path}'}
            with patch.dict('os.environ', env, clear=True):
                with self.assertRaisesRegex(KeyringFailure, 'private_keyring_session_required'):
                    private_home()
            path.unlink()
            listening.rename(path)
            with patch.dict('os.environ', {**env, 'DBUS_SESSION_BUS_ADDRESS': f'unix:path={path};unix:path=/run/bus'},
                            clear=True):
                with self.assertRaisesRegex(KeyringFailure, 'private_keyring_session_required'):
                    private_home()
            with patch.dict('os.environ', env, clear=True):
                self.assertEqual(private_home(), root)

    def test_denial_can_only_address_an_original_item_on_the_private_channel(self):
        verifier = KeyringEvidence.__new__(KeyringEvidence)
        verifier.namespace = 'herdr-pocket.tauri'
        verifier.verified = {'a' * 32}
        with patch('linux_pairing_keyring.private_home'), patch('linux_pairing_keyring.socket.socket') as channel, \
                patch('linux_pairing_keyring.default_collection', return_value='/login'), \
                patch.object(verifier, 'items', return_value=['/other/item']):
            with patch.dict('os.environ', {}, clear=True):
                with self.assertRaisesRegex(KeyringFailure, 'private_keyring_denial_channel_required'):
                    with denied_service(verifier, 'locked'):
                        self.fail('no channel may not change the keyring')
            with patch.dict('os.environ', {DENIAL_CHANNEL: '12'}, clear=True):
                with self.assertRaisesRegex(KeyringFailure, 'private_keyring_denial_original_reference_unproven'):
                    with denied_service(verifier, 'locked'):
                        self.fail('another collection may not be locked')
            channel.assert_not_called()

    def test_denial_requires_both_a_real_state_and_final_restoration(self):
        verifier = KeyringEvidence.__new__(KeyringEvidence)
        verifier.namespace = 'herdr-pocket.tauri'
        verifier.verified = {'a' * 32}
        for mode in ('locked', 'unavailable'):
            with self.subTest(mode=mode), \
                    patch.dict('os.environ', {DENIAL_CHANNEL: '12'}, clear=True), \
                    patch('linux_pairing_keyring.private_home'), \
                    patch('linux_pairing_keyring.default_collection', return_value='/login'), \
                    patch.object(verifier, 'items', return_value=['/login/item']), \
                    patch.object(verifier, 'handles', return_value=verifier.verified), \
                    patch('linux_pairing_keyring.require_denial') as denied, \
                    patch('linux_pairing_keyring.socket.socket') as channel:
                wire = channel.return_value.__enter__.return_value
                wire.recv.return_value = b'ok'
                with self.assertRaisesRegex(ValueError, 'fixture'):
                    with denied_service(verifier, mode) as verify:
                        verify()
                        raise ValueError('fixture')
                self.assertEqual([call.args for call in wire.sendall.call_args_list], [(mode.encode(),), (b'restore',)])
                self.assertEqual(denied.call_count, 2)

    def test_locked_and_ownerless_states_are_distinct(self):
        for mode, present, default, locked in (
            ('locked', False, '/login', True), ('locked', True, '/other', True),
            ('locked', True, '/login', False), ('unavailable', True, '/login', True),
        ):
            with self.subTest(mode=mode, present=present, default=default, locked=locked), \
                    patch('linux_pairing_keyring.service_owner_present', return_value=present), \
                    patch('linux_pairing_keyring.default_collection', return_value=default), \
                    patch('linux_pairing_keyring.collection_locked', return_value=locked):
                with self.assertRaisesRegex(KeyringFailure, 'private_keyring_.*_denial_unconfirmed'):
                    require_denial(mode, '/login')

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
            verifier.verify_existing('ssh-ed25519 reviewed')
            call.return_value = "(<{'handle': '" + 'b' * 32 + "'}>,)"
            with self.assertRaisesRegex(KeyringFailure, 'private_keyring_original_reference_changed'):
                verifier.verify_existing('ssh-ed25519 reviewed')
            with self.assertRaisesRegex(KeyringFailure, 'private_keyring_item_count_wrong'):
                verifier.verify('ssh-ed25519 reviewed')
