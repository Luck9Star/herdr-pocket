import io
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from herdr_pocket_helper import __main__ as cli, store, wire
from test_host import ephemeral_public


class ReceiptInspectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.host_key = ephemeral_public()
        self.host = store.Host(self.home, 'test_account', self.host_key)
        self.rid = 'a' * 32
        self.req = {'version': 2, 'type': wire.REQUEST, 'request_id': self.rid,
                    'account': 'test_account', 'host_key': self.host.pin,
                    'device': 'Fixture phone', 'public_key': ephemeral_public(),
                    'issued_at': 100, 'expires_at': 200}
        self.raw = wire.encode(self.req)
        self.auth = self.home / '.ssh/authorized_keys'
        self.receipt = self.home / '.ssh/herdr-pocket-receipts' / (self.rid + '.json')

    def authorize(self):
        return self.host.authorize(self.raw, self.rid, now=111)

    def snapshot(self):
        return {str(path.relative_to(self.home)): (path.stat().st_mode, path.read_bytes())
                for path in self.home.rglob('*') if path.is_file()}

    def run_cli(self, action, *, key=None, confirmed=True):
        public = self.home / 'synthetic host.pub'
        public.write_text((key or self.host_key) + ' synthetic fixture\n')
        with (patch('pwd.getpwuid', return_value=SimpleNamespace(pw_name='test_account', pw_dir=str(self.home))),
              patch.object(cli, 'confirm', side_effect=lambda action, req: req['request_id'] if confirmed else 'b' * 32) as confirm,
              patch.object(store.time, 'time', return_value=1000),
              patch('sys.stdout') as output, patch('sys.stderr', new_callable=io.StringIO) as error):
            output.buffer = io.BytesIO()
            status = cli.main([action, '--host-public-key', str(public), '--request-id', self.rid])
            text = ''.join(call.args[0] for call in output.write.call_args_list)
            return status, output.buffer.getvalue(), text, error.getvalue(), confirm.call_count

    def test_exact_readonly_inspection_recovers_expired_public_request_without_lock_or_rewrite(self):
        self.authorize()
        lock = self.receipt.parent / 'lock'
        lock.unlink()
        before = self.snapshot()
        with patch.object(store, 'replace', side_effect=AssertionError('inspection must be read-only')):
            inspected = self.host.inspect_receipt(self.rid, now=1000)
        self.assertEqual(inspected['request'], self.req)
        self.assertEqual(inspected['device_fingerprint'], wire.fingerprint(self.req['public_key']))
        self.assertEqual(inspected['receipt_phase'], 'authorized')
        self.assertEqual(inspected['observed_entry'], 'owned')
        self.assertTrue(inspected['request_expired'])
        self.assertTrue(inspected['can_revoke'])
        self.assertFalse(inspected['authorization_written'])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(lock.exists())

    def test_confirm_both_actions_on_a_nonseekable_pty(self):
        # Route only /dev/tty to our own slave. A text r+ stream fails on
        # this real POSIX character device even though StringIO supports it.
        for action in ('AUTHORIZE', 'REVOKE'):
            with self.subTest(action=action):
                master, slave = os.openpty()
                try:
                    def terminal(path, mode, *, encoding):
                        self.assertEqual(path, '/dev/tty')
                        return os.fdopen(os.dup(slave), mode, encoding=encoding)
                    os.write(master, f'{action} {self.rid}\n'.encode())
                    with patch.object(cli, 'open', create=True, side_effect=terminal):
                        self.assertEqual(cli.confirm(action, self.req), self.rid)
                finally:
                    os.close(slave)
                    os.close(master)

    def test_confirmation_uses_terminal_read_and_write_streams_and_requires_exact_phrase(self):
        for phrase, accepted in ((f'REVOKE {self.rid}\n', True), ('yes\n', False)):
            reader, writer = io.StringIO(phrase), io.StringIO()
            def terminal(path, mode, *, encoding):
                self.assertEqual((path, encoding), ('/dev/tty', 'utf-8'))
                self.assertIn(mode, ('r', 'w'))
                return nullcontext(reader if mode == 'r' else writer)
            with patch('builtins.open', side_effect=terminal):
                if accepted:
                    self.assertEqual(cli.confirm('REVOKE', self.req), self.rid)
                else:
                    with self.assertRaises(ValueError):
                        cli.confirm('REVOKE', self.req)
            self.assertIn(self.req['host_key'], writer.getvalue())
            self.assertIn(wire.fingerprint(self.req['public_key']), writer.getvalue())

    def test_missing_receipt_wrong_host_account_and_traversal_do_not_create_or_change_files(self):
        with self.assertRaises(OSError):
            self.host.inspect_receipt(self.rid, now=1000)
        self.assertEqual(list(self.home.iterdir()), [])
        self.authorize()
        before = self.snapshot()
        for host, rid in ((self.host, '../' + self.rid), (self.host, 'b' * 32),
                          (store.Host(self.home, 'another', self.host_key), self.rid),
                          (store.Host(self.home, 'test_account', ephemeral_public()), self.rid)):
            with self.subTest(account=host.account, rid=rid), self.assertRaises((OSError, ValueError)):
                host.inspect_receipt(rid, now=1000)
        self.assertEqual(self.snapshot(), before)

    def test_preexisting_or_externally_edited_authorization_is_not_offered_for_removal(self):
        self.auth.parent.mkdir(mode=0o700)
        original = (self.req['public_key'] + ' original\n').encode()
        self.auth.write_bytes(original)
        self.auth.chmod(0o600)
        self.authorize()
        inspected = self.host.inspect_receipt(self.rid, now=1000)
        self.assertFalse(inspected['authorization_added'])
        self.assertFalse(inspected['can_revoke'])
        self.assertEqual(inspected['observed_entry'], 'existing')
        with self.assertRaises(ValueError):
            self.host.review_revocation(self.rid)
        self.assertEqual(self.auth.read_bytes(), original)
        self.auth.write_bytes(b'# externally removed\n')
        self.assertFalse(self.host.inspect_receipt(self.rid, now=1000)['can_revoke'])

    def test_expired_original_revoke_and_expired_revoke_response_can_be_refreshed_without_rewriting(self):
        authorized = wire.decode(self.authorize(), now=111)
        first = wire.decode(self.host.revoke(self.rid, self.rid, now=1000), now=1000)
        self.assertEqual(first['status'], 'revoked')
        self.assertEqual((first['issued_at'], first['expires_at']), (1000, 1600))
        for field in ('request_id', 'account', 'host_key', 'fingerprint'):
            self.assertEqual(first[field], authorized[field])
        with self.assertRaises(ValueError):
            wire.decode(wire.encode(first), now=1600)
        before = self.snapshot()
        inspected = self.host.inspect_receipt(self.rid, now=2000)
        self.assertEqual(inspected['receipt_phase'], 'revoked')
        self.assertEqual(inspected['observed_entry'], 'absent')
        self.assertTrue(inspected['can_revoke'])
        with patch.object(store, 'replace', side_effect=AssertionError('refresh must not rewrite state')):
            refreshed = wire.decode(self.host.revoke(self.rid, self.rid, now=2000), now=2000)
        self.assertEqual((refreshed['issued_at'], refreshed['expires_at']), (2000, 2600))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.auth.read_bytes(), b'')
        with self.assertRaises(ValueError):
            self.host.authorize(self.raw, self.rid, now=111)
        self.assertEqual(self.snapshot(), before)

    def test_revoke_response_window_starts_after_completed_storage_work(self):
        self.authorize()
        clock = [1000]
        real_replace = store.replace
        def delayed_commit(parent, name, value, expected):
            result = real_replace(parent, name, value, expected)
            if name.endswith('.json') and b'"phase":"revoked"' in value:
                clock[0] = 2000
            return result
        with patch.object(store.time, 'time', side_effect=lambda: clock[0]), patch.object(store, 'replace', side_effect=delayed_commit):
            response = wire.decode(self.host.revoke(self.rid, self.rid), now=2000)
        self.assertEqual((response['issued_at'], response['expires_at']), (2000, 2600))
        self.assertEqual(self.auth.read_bytes(), b'')

    def test_receipt_corruption_and_links_fail_closed_before_revoke(self):
        self.authorize()
        original = self.receipt.read_bytes()
        item = json.loads(original)
        invalid = [wire.encode(dict(item, phase='unknown')), wire.encode(dict(item, added=1)),
                   wire.encode(dict(item, request=dict(self.req, request_id='b' * 32))),
                   wire.encode(dict(item, request=dict(self.req, public_key='ssh-ed25519 AAAA'))),
                   original[:-1] + b',"phase":"authorized"}']
        auth_before = self.auth.read_bytes()
        for raw in invalid:
            self.receipt.write_bytes(raw)
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                self.host.inspect_receipt(self.rid, now=1000)
            with self.assertRaises(ValueError):
                self.host.revoke(self.rid, self.rid, now=1000)
            self.assertEqual(self.auth.read_bytes(), auth_before)
        self.receipt.write_bytes(original)
        saved = self.receipt.with_suffix('.saved')
        self.receipt.rename(saved)
        self.receipt.symlink_to(saved)
        with self.assertRaises(OSError):
            self.host.inspect_receipt(self.rid, now=1000)
        self.receipt.unlink()
        os.link(saved, self.receipt)
        with self.assertRaises(ValueError):
            self.host.inspect_receipt(self.rid, now=1000)
        self.assertEqual(self.auth.read_bytes(), auth_before)

    @unittest.skipIf(os.geteuid() == 0, 'CLI requires a non-root POSIX login account')
    def test_cli_inspect_has_no_confirmation_or_authorization_and_revoke_keeps_confirmation(self):
        self.authorize()
        status, raw, text, error, confirmations = self.run_cli('inspect')
        self.assertEqual((status, raw, error, confirmations), (0, b'', '', 0))
        inspected = json.loads(text)
        self.assertEqual(inspected['request'], self.req)
        command = shlex.split(inspected['revoke_command'])
        self.assertEqual(command[:4], [sys.executable, '-m', 'herdr_pocket_helper', 'revoke'])
        self.assertEqual(command[-2:], ['--request-id', self.rid])
        before = self.auth.read_bytes()
        status, raw, _, _, confirmations = self.run_cli('revoke', confirmed=False)
        self.assertEqual((status, raw, confirmations), (1, b'', 1))
        self.assertEqual(self.auth.read_bytes(), before)
        status, raw, _, error, confirmations = self.run_cli('revoke')
        self.assertEqual((status, error, confirmations), (0, '', 1))
        self.assertEqual(wire.decode(raw, now=1000)['status'], 'revoked')
        self.assertEqual(self.auth.read_bytes(), b'')


if __name__ == '__main__':
    unittest.main()
