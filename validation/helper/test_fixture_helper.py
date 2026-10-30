import json
import os
import unittest
from unittest.mock import patch
from fixture_helper import (FixtureStore, Receipt, CONFIRM_ADD, CONFIRM_REVOKE,
                            synthetic_key, canonical_key, fingerprint, request, response_matches, demo)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.obj = {'version': 1, 'type': 'fixture-public-key-request', 'request_id': 'test-01',
                    'device': 'fixture-phone', 'public_key': synthetic_key(), 'expires_at': 600}

    def test_request_bounds(self):
        self.assertEqual(request(json.dumps(self.obj).encode(), 1), self.obj)
        for field, value in [('version', True), ('version', 2), ('type', 'connect'),
                             ('request_id', '../home'), ('device', 'bad\nname'),
                             ('expires_at', 1), ('expires_at', 602), ('public_key', 'bad')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                request(json.dumps({**self.obj, field: value}).encode(), 1)
        for raw in [b'x'*2049, b'{}', b'{"version":1,"version":1}', b'[]',
                    json.dumps({**self.obj, 'path': '/not-used'}).encode()]:
            with self.assertRaises(ValueError):
                request(raw, 1)

    def test_key_injection_rejected(self):
        key = synthetic_key()
        for bad in [key+'\n', key+' comment', 'command="id" '+key, key+'\r'+key,
                    key+' '+key, key.replace('ssh-ed25519 ', 'ssh-rsa '), 'ssh-ed25519 AAAA']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                canonical_key(bad)

    def test_response_binding_expiry_consumption(self):
        response = {'version': 1, 'type': 'fixture-pairing-response', 'request_id': 'test-01',
                    'fingerprint': fingerprint(synthetic_key()), 'account': 'fixture-user',
                    'host_key': fingerprint(synthetic_key(71)), 'expires_at': 600}
        self.assertTrue(response_matches(response, self.obj, now=1))
        self.assertFalse(response_matches(response, self.obj, now=600))
        self.assertFalse(response_matches(response, self.obj, now=1, consumed=True))
        for field in ['request_id', 'fingerprint', 'account', 'host_key', 'type']:
            self.assertFalse(response_matches({**response, field: 'wrong'}, self.obj, now=1))

    def test_demo_default_has_no_change(self):
        self.assertEqual(demo('')['bytesChanged'], 0)
        self.assertTrue(demo(CONFIRM_ADD)['emptyAfterRevoke'])


class FileTests(unittest.TestCase):
    def setUp(self):
        self.store = FixtureStore()
        self.obj = {'request_id': 'test-01', 'public_key': synthetic_key()}

    def tearDown(self):
        self.store.__exit__()

    def test_confirm_add_idempotence_and_revoke(self):
        with self.assertRaises(ValueError):
            self.store.authorize(self.obj, '')
        self.assertEqual(self.store.read(), b'')
        receipt = self.store.authorize(self.obj, CONFIRM_ADD)
        first = self.store.read()
        self.assertEqual(self.store.authorize(self.obj, CONFIRM_ADD), receipt)
        self.assertEqual(self.store.read(), first)
        with self.assertRaises(ValueError):
            self.store.revoke(receipt, '')
        self.assertTrue(self.store.revoke(receipt, CONFIRM_REVOKE))
        self.assertFalse(self.store.revoke(receipt, CONFIRM_REVOKE))
        self.assertEqual(self.store.read(), b'')

    def test_preserve_existing_same_key(self):
        prior = (synthetic_key()+' original-owner\n# preserved\n').encode()
        self.store._atomic_write(prior, b'')
        receipt = self.store.authorize(self.obj, CONFIRM_ADD)
        self.assertIsNone(receipt.added_line)
        self.assertFalse(self.store.revoke(receipt, CONFIRM_REVOKE))
        self.assertEqual(self.store.read(), prior)

    def test_comment_and_misplaced_key_are_not_authorization(self):
        prior = ('# copied ' + synthetic_key() + '\n').encode()
        self.store._atomic_write(prior, b'')
        receipt = self.store.authorize(self.obj, CONFIRM_ADD)
        self.assertIsNotNone(receipt.added_line)
        self.store.revoke(receipt, CONFIRM_REVOKE)
        self.assertEqual(self.store.read(), prior)
        for text in ['command="demo" ' + synthetic_key(),
                     'ssh-ed25519 displaced ' + synthetic_key().split()[1]]:
            self.store._atomic_write(text.encode(), self.store.read())
            with self.assertRaises(ValueError):
                self.store.authorize({**self.obj, 'request_id': 'other'}, CONFIRM_ADD)

    def test_no_final_newline_is_restored_exactly(self):
        prior = b'# existing content without newline'
        self.store._atomic_write(prior, b'')
        receipt = self.store.authorize(self.obj, CONFIRM_ADD)
        self.store.revoke(receipt, CONFIRM_REVOKE)
        self.assertEqual(self.store.read(), prior)

    def test_preserve_other_lines(self):
        prior = (synthetic_key(72)+' old\n# untouched\n').encode()
        self.store._atomic_write(prior, b'')
        receipt = self.store.authorize(self.obj, CONFIRM_ADD)
        self.assertTrue(self.store.read().startswith(prior))
        self.store.revoke(receipt, CONFIRM_REVOKE)
        self.assertEqual(self.store.read(), prior)

    def test_forged_receipt_and_reused_request(self):
        receipt = self.store.authorize(self.obj, CONFIRM_ADD)
        with self.assertRaises(ValueError):
            self.store.revoke(Receipt(receipt.request_id, synthetic_key(74), receipt.added_line), CONFIRM_REVOKE)
        with self.assertRaises(ValueError):
            self.store.authorize({**self.obj, 'public_key': synthetic_key(75)}, CONFIRM_ADD)

    def test_atomic_replace_failure_keeps_original(self):
        before = self.store.read()
        with patch('fixture_helper.os.replace', side_effect=OSError('injected')), self.assertRaises(OSError):
            self.store.authorize(self.obj, CONFIRM_ADD)
        self.assertEqual(self.store.read(), before)
        self.assertEqual(os.listdir(self.store._fd), [self.store.name])

    def test_symlink_refused(self):
        os.rename(self.store.name, 'target.fixture', src_dir_fd=self.store._fd, dst_dir_fd=self.store._fd)
        os.symlink('target.fixture', self.store.name, dir_fd=self.store._fd)
        with self.assertRaises(OSError):
            self.store.authorize(self.obj, CONFIRM_ADD)
        self.assertEqual(os.stat('target.fixture', dir_fd=self.store._fd).st_size, 0)

    def test_hardlink_and_permission_refused(self):
        os.link(self.store.name, 'second.fixture', src_dir_fd=self.store._fd, dst_dir_fd=self.store._fd)
        with self.assertRaises(ValueError):
            self.store.read()
        os.unlink('second.fixture', dir_fd=self.store._fd)
        os.chmod(self.store.name, 0o644, dir_fd=self.store._fd)
        with self.assertRaises(ValueError):
            self.store.read()

    def test_stale_snapshot_refused(self):
        self.store._atomic_write(b'changed\n', b'')
        with self.assertRaises(ValueError):
            self.store._atomic_write(b'new\n', b'')
        self.assertEqual(self.store.read(), b'changed\n')

    def test_size_limit(self):
        with self.assertRaises(ValueError):
            self.store._atomic_write(b'x'*65537, b'')
        self.assertEqual(self.store.read(), b'')


if __name__ == '__main__':
    unittest.main()
