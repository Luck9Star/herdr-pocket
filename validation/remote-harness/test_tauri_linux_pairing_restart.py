import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from paired_gui import GuiFailure, checked_keyring_denial, run_tauri

if os.name != 'nt':
    import fcntl
    from tauri_linux_pairing_restart import (
        AppProcess, DENIAL_NOTICE, RestartReceipt, one_saved_host, owned_stock_app, owner_lock_state,
        process_exited, require_peers,
    )


def stat_line(pid, parent, start, state='S'):
    return f"{pid} (name with ) spaces) {state} {parent} " + '0 ' * 17 + f'{start} 0 0\n'


@unittest.skipIf(os.name == 'nt', 'native Unix process and flock evidence')
class RestartReceiptTests(unittest.TestCase):
    def test_restart_is_not_a_guarded_input_route(self):
        with self.assertRaisesRegex(GuiFailure, 'restart_requires_stock_read_only'):
            run_tauri(SimpleNamespace(input_fixture=True), None, {}, {}, SimpleNamespace(keyring=object()))

    def test_denial_proof_fails_closed_on_wrong_mode_types_and_extra_or_missing_fields(self):
        for mode in ('locked', 'unavailable'):
            proof = {'mode': mode, 'independentAppProcesses': True, 'noticeVisible': True, 'connectDisabled': True,
                     'originalHostAndIdentityRetained': True, 'authorizationUnchanged': True,
                     'exactPeerAuthentications': 1, 'firstPeerClosed': True, 'noKeyringWrites': True,
                     'receivedInputBytes': 0}
            self.assertEqual(checked_keyring_denial(proof, mode), proof)
            for invalid in (None, dict(proof, mode='off'), dict(proof, exactPeerAuthentications=True),
                            dict(proof, receivedInputBytes=False), dict(proof, receivedInputBytes=1),
                            dict(proof, raw='unapproved log'), dict(proof, noticeVisible=False),
                            {key: value for key, value in proof.items() if key != 'noKeyringWrites'}):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(GuiFailure, 'keyring_denial_proof_incomplete'):
                    checked_keyring_denial(invalid, mode)

    def test_denied_ui_requires_expected_notice_and_never_retries_the_original_restore(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt = RestartReceipt(None, root, {'XDG_DATA_HOME': str(root/'data')}, {}, None)
        receipt.denial_catalog = b'original'
        for changes, expected in (({}, None), ({'#host-restore-status': DENIAL_NOTICE['unavailable']}, 'notice_missing'),
                                  ({'#remote-connect': False}, 'controls_changed'),
                                  ({'#pair-create': False}, 'controls_changed'),
                                  ({'#pair-request': 'new key'}, 'controls_changed')):
            replies = {'#host-restore-status': DENIAL_NOTICE['locked'], '#host-restore-review': True,
                       '#remote-review': False, '#remote-connect': True, '#pair-create': True, '#pair-request': ''}
            driver = MagicMock()
            driver.read.side_effect = lambda selector, prop=None: (replies | changes)[selector]
            def one_sample(sample, error):
                if not sample():
                    raise GuiFailure(error)
            with patch.object(receipt, 'open_original', return_value='second') as original, \
                    patch.object(receipt, 'saved_catalog', return_value=b'original'), \
                    patch('tauri_linux_pairing_restart.wait_for', side_effect=one_sample):
                if expected:
                    with self.assertRaisesRegex(GuiFailure, expected):
                        receipt.second_denied(driver, 7, 'locked')
                else:
                    self.assertEqual(receipt.second_denied(driver, 7, 'locked'), 'second')
                    driver.wait_control.assert_called_once_with('#host-restore-status')
                original.assert_called_once_with(driver, 7)
                driver.click.assert_not_called()

    def test_binary_ancestry_lifetime_and_private_env_must_match(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            binary = root / 'herdr-pocket-tauri-probe'
            binary.touch()
            env = {'HOME': '/isolated/home', 'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/isolated/bus',
                   'XDG_CONFIG_HOME': '/isolated/config', 'XDG_DATA_HOME': '/isolated/data',
                   'XDG_STATE_HOME': '/isolated/state', 'XDG_CACHE_HOME': '/isolated/cache',
                   'XDG_RUNTIME_DIR': '/isolated/runtime'}
            for pid, parent, start in ((21, 20, 300), (22, 21, 301), (23, 1, 302)):
                item = root / str(pid)
                item.mkdir()
                (item / 'stat').write_text(stat_line(pid, parent, start))
                if pid != 21:
                    (item / 'exe').symlink_to(binary)
                    (item / 'environ').write_bytes(b'\0'.join(f'{key}={value}'.encode() for key, value in env.items()))
            app = owned_stock_app(20, binary, env, root)
            self.assertEqual(app, AppProcess(22, 301))
            self.assertFalse(process_exited(app, root))
            with self.assertRaisesRegex(GuiFailure, 'restart_app_private_environment_mismatch'):
                owned_stock_app(20, binary, {**env, 'XDG_DATA_HOME': '/other'}, root)
            with self.assertRaisesRegex(GuiFailure, 'restart_stock_app_ambiguous'):
                (root / '23' / 'stat').write_text(stat_line(23, 21, 302))
                owned_stock_app(20, binary, env, root)
            (root / '22' / 'stat').write_text(stat_line(22, 1, 301, 'Z'))
            self.assertTrue(process_exited(app, root))
            (root / '22' / 'stat').write_text(stat_line(22, 1, 399))
            self.assertTrue(process_exited(app, root))
            (root / '22' / 'stat').write_text('')
            self.assertFalse(process_exited(app, root))

    def test_owner_lock_must_be_released_without_being_replaced(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'owner.lock'
            path.touch(mode=0o600)
            with path.open('rb') as original:
                fcntl.flock(original, fcntl.LOCK_EX | fcntl.LOCK_NB)
                file_id, available = owner_lock_state(path)
                self.assertFalse(available)
            self.assertEqual(owner_lock_state(path, file_id), (file_id, True))
            other = path.with_suffix('.replacement')
            other.touch(mode=0o600)
            other.replace(path)
            with self.assertRaisesRegex(GuiFailure, 'restart_owner_lock_replaced'):
                owner_lock_state(path, file_id)

    def test_peer_attests_two_distinct_closed_connections_with_original_key(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            approval = SimpleNamespace(root=root, config={'username': 'fixture'}, fingerprint='SHA256:original')
            path = root / 'sshd.log'
            first = ('Accepted publickey for fixture from 127.0.0.1 port 30000 ssh2: ED25519 SHA256:original\n'
                     'Received disconnect from 127.0.0.1 port 30000:11: closed\n')
            second = 'Accepted publickey for fixture from 127.0.0.1 port 30001 ssh2: ED25519 SHA256:original\n'
            path.write_text(first)
            self.assertTrue(require_peers(approval, 1, all_closed=True))
            self.assertFalse(require_peers(approval, 2, all_closed=False))
            path.write_text(first + second)
            self.assertTrue(require_peers(approval, 2, all_closed=False))
            self.assertFalse(require_peers(approval, 2, all_closed=True))
            path.write_text(first + second + 'Disconnected from user fixture 127.0.0.1 port 30001\n')
            self.assertTrue(require_peers(approval, 2, all_closed=True))
            for unexpected in (second.replace('original', 'different'), second.replace('30001', '30000'),
                               second + second.replace('30001', '30002')):
                path.write_text(first + unexpected)
                with self.assertRaisesRegex(GuiFailure, 'restart_unexpected_authentication'):
                    require_peers(approval, 2, all_closed=False)
            path.write_text(first + second + 'Read error from remote host 127.0.0.1 port 30001: Connection reset by peer\n')
            with self.assertRaisesRegex(GuiFailure, 'restart_peer_reset'):
                require_peers(approval, 2, all_closed=False)

    def test_saved_home_requires_a_unique_canonical_id(self):
        driver = SimpleNamespace(session='/session/fixture', call=lambda *args: [])
        self.assertIsNone(one_saved_host(driver))
        driver.call = lambda *args: ['0' * 32]
        self.assertEqual(one_saved_host(driver), '0' * 32)
        for invalid in (['0' * 32, '1' * 32], ['untrusted selector'], '0' * 32):
            driver.call = lambda *args: invalid
            with self.assertRaisesRegex(GuiFailure, 'restart_saved_host_not_unique'):
                one_saved_host(driver)
