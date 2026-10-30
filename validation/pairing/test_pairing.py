import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_ssh_public_key
from pairing import (MemoryKeyStore, PendingPairing, FixturePairingHost, CONFIRM_ADD,
                     CONFIRM_REVOKE, encode, decode, fingerprint, public_key)


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.keys = MemoryKeyStore()
        self.handle = self.keys.create()
        self.host_public = self.keys.public(self.keys.create())
        self.phone = self.pending()
        self.host = FixturePairingHost(host_public_key=self.host_public)

    def tearDown(self):
        self.host.__exit__()

    def pending(self):
        return PendingPairing(self.keys, self.handle, account='fixture-user',
                              expected_host_key=fingerprint(self.host_public), device='Test phone', now=100)

    def authorize(self):
        return self.host.authorize(encode(self.phone.request), now=101, confirmation=CONFIRM_ADD)

    def accept(self, response=None):
        self.phone.accept(response or self.authorize(), now=102, source_reviewed=True)

    def test_mature_generated_key_sign_verify_and_fingerprint(self):
        public = self.keys.public(self.handle)
        signature = self.keys.sign(self.handle, b'isolated-test')
        load_ssh_public_key(public.encode()).verify(signature, b'isolated-test')
        with self.assertRaises(InvalidSignature):
            load_ssh_public_key(public.encode()).verify(signature, b'changed')
        self.assertEqual(len(fingerprint(public)), 50)
        self.assertNotEqual(public, self.host_public)

    def test_no_export_and_locked_unavailable_deleted_fail_closed(self):
        self.assertFalse(hasattr(self.keys, 'export'))
        self.assertFalse(hasattr(self.keys, 'import_key'))
        for field in ('locked', 'available'):
            setattr(self.keys, field, field == 'locked')
            with self.assertRaises(RuntimeError):
                self.keys.create()
            with self.assertRaises(RuntimeError):
                self.keys.sign(self.handle, b'test')
            setattr(self.keys, field, field != 'locked')
        self.keys.delete(self.handle)
        with self.assertRaises(KeyError):
            self.keys.public(self.handle)
        with self.assertRaises(KeyError):
            self.pending()

    def test_confirmation_and_bad_request_cannot_write(self):
        for confirmation in ('', 'AUTHORIZE', True):
            with self.assertRaises(ValueError):
                self.host.authorize(encode(self.phone.request), now=101, confirmation=confirmation)
        for changes in ({'account': 'root'}, {'host_key': fingerprint(self.keys.public(self.handle))},
                        {'expires_at': 101}, {'public_key': 'bad'}):
            with self.assertRaises(ValueError):
                self.host.authorize(encode({**self.phone.request, **changes}), now=101, confirmation=CONFIRM_ADD)
        self.assertEqual(self.host.store.read(), b'')

    def test_offline_authorization_wait_retry_connected_revoke(self):
        self.accept()
        self.assertEqual(self.phone.state, 'authorized-unverified')
        generation = self.phone.connect(explicit=True)
        self.assertTrue(self.phone.connection_result(generation, pinned_ssh_authenticated=False))
        self.assertEqual(self.phone.state, 'waiting-connectivity')
        with self.assertRaises(ValueError):
            self.phone.connect(explicit=False)
        generation = self.phone.connect(explicit=True)
        self.phone.connection_result(generation, pinned_ssh_authenticated=True)
        self.assertEqual(self.phone.state, 'paired')
        revoked = self.host.revoke(self.phone.request['request_id'], now=900, confirmation=CONFIRM_REVOKE)
        self.phone.accept(revoked, now=901, source_reviewed=True)
        self.assertEqual(self.phone.state, 'revoked')
        self.assertEqual(self.host.store.read(), b'')
        with self.assertRaises(ValueError):
            self.phone.connect(explicit=True)
        with self.assertRaises(ValueError):
            self.host.authorize(encode(self.phone.request), now=102, confirmation=CONFIRM_ADD)

    def test_source_not_authenticated_by_binding(self):
        response = self.authorize()
        for value in (False, 1, 'yes'):
            with self.assertRaises(ValueError):
                self.phone.accept(response, now=102, source_reviewed=value)
        self.assertEqual(self.phone.state, 'awaiting-host')

    def test_response_target_mismatch_not_consumed(self):
        response = decode(self.authorize(), now=102)
        for key, value in [('request_id', 'f'*32), ('account', 'other'),
                           ('host_key', fingerprint(self.keys.public(self.handle))),
                           ('fingerprint', fingerprint(self.host_public)), ('type', 'connect')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.phone.accept(encode({**response, key: value}), now=102, source_reviewed=True)
            self.assertFalse(self.phone.consumed)
        self.accept(encode(response))

    def test_host_idempotence_phone_duplicate_and_revoked_tombstone(self):
        first = self.authorize()
        before = self.host.store.read()
        self.assertEqual(self.authorize(), first)
        self.assertEqual(self.host.store.read(), before)
        self.accept(first)
        with self.assertRaises(ValueError):
            self.accept(first)
        changed = self.pending().request
        changed['request_id'] = self.phone.request['request_id']
        changed['device'] = 'other phone'
        with self.assertRaises(ValueError):
            self.host.authorize(encode(changed), now=102, confirmation=CONFIRM_ADD)
        self.host.revoke(self.phone.request['request_id'], now=102, confirmation=CONFIRM_REVOKE)
        with self.assertRaises(ValueError):
            self.authorize()

    def test_cancel_before_authorization_rejects_late_response(self):
        response = self.authorize()
        self.phone.cancel()
        with self.assertRaises(ValueError):
            self.accept(response)
        self.assertEqual(self.phone.authorization, 'unknown')
        self.assertNotEqual(self.host.store.read(), b'')

    def test_cancel_after_authorization_preserves_cleanup_and_late_ssh_ignored(self):
        self.accept()
        generation = self.phone.connect(explicit=True)
        self.phone.cancel()
        self.assertFalse(self.phone.connection_result(generation, pinned_ssh_authenticated=True))
        self.assertEqual(self.phone.authorization, 'authorized')
        self.assertEqual(self.phone.state, 'cancelled')
        revoked = self.host.revoke(self.phone.request['request_id'], now=103, confirmation=CONFIRM_REVOKE)
        self.phone.accept(revoked, now=104, source_reviewed=True)
        self.assertEqual(self.phone.authorization, 'revoked')

    def test_unknown_authorization_accepts_reviewed_revoke_after_cancel_or_expiry(self):
        for expire in (False, True):
            with self.subTest(expire=expire), FixturePairingHost(host_public_key=self.host_public) as host:
                phone = self.pending()
                authorized = host.authorize(encode(phone.request), now=101, confirmation=CONFIRM_ADD)
                if expire:
                    phone.tick(700)
                    now = 701
                else:
                    phone.cancel()
                    now = 102
                self.assertEqual(phone.authorization, 'unknown')
                revoked = host.revoke(phone.request['request_id'], now=now, confirmation=CONFIRM_REVOKE)
                with self.assertRaises(ValueError):
                    phone.accept(revoked, now=now, source_reviewed=False)
                mismatched = {**decode(revoked, now=now), 'request_id': 'f' * 32}
                with self.assertRaises(ValueError):
                    phone.accept(encode(mismatched), now=now, source_reviewed=True)
                self.assertEqual(phone.authorization, 'unknown')
                phone.accept(revoked, now=now, source_reviewed=True)
                self.assertEqual((phone.state, phone.authorization), ('revoked', 'revoked'))
                self.assertTrue(phone.consumed)
                self.assertEqual(host.store.read(), b'')
                with self.assertRaises(ValueError):
                    phone.accept(revoked, now=now, source_reviewed=True)
                with self.assertRaises(ValueError):
                    phone.accept(authorized, now=now, source_reviewed=True)
                with self.assertRaises(ValueError):
                    phone.connect(explicit=True)

    def test_expiry_not_host_revocation(self):
        response = self.authorize()
        self.phone.tick(700)
        self.assertEqual(self.phone.state, 'expired')
        with self.assertRaises(ValueError):
            self.phone.accept(response, now=700, source_reviewed=True)
        self.assertNotEqual(self.host.store.read(), b'')
        other = self.pending()
        other_response = self.host.authorize(encode(other.request), now=102, confirmation=CONFIRM_ADD)
        other.accept(other_response, now=103, source_reviewed=True)
        other.tick(900)
        self.assertEqual(other.authorization, 'authorized')

    def test_expiry_bound_future_times_and_boolean_integers(self):
        obj = self.phone.request
        for changes in ({'version': True}, {'version': 1}, {'issued_at': 102},
                        {'issued_at': -1}, {'expires_at': 1000}, {'expires_at': True},
                        {'device': 'bad\n'}, {'request_id': '../path'}, {'account': '-evil'},
                        {'host_key': 'SHA256:bad'}, {'extra': 'no'}, {'private_key': 'no'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                decode(encode({**obj, **changes}), now=101)
        for raw in (b'{}', b'[]', b'x'*2049, b'{"version":2,"version":2}', b'\xff'):
            with self.assertRaises(ValueError):
                decode(raw, now=101)

    def test_private_key_options_comments_and_wrong_key_formats_rejected(self):
        key = self.keys.public(self.handle)
        for bad in (key+'\n', key+' comment', 'command="id" '+key,
                    key.replace('ssh-ed25519', 'ssh-rsa'), 'ssh-ed25519 AAAA'):
            with self.assertRaises(ValueError):
                public_key(bad)

    def test_wire_rejects_utf16_utf32_and_utf8_bom(self):
        text = encode(self.phone.request).decode('utf-8')
        for encoding in ('utf-16', 'utf-16-le', 'utf-16-be', 'utf-32', 'utf-32-le', 'utf-32-be', 'utf-8-sig'):
            with self.subTest(encoding=encoding), self.assertRaises(ValueError):
                decode(text.encode(encoding), now=101)

    def test_preexisting_key_is_preserved_and_not_claimed_revoked(self):
        old = (self.keys.public(self.handle)+' original-owner\n').encode()
        self.host.store._atomic_write(old, b'')
        response = decode(self.authorize(), now=102)
        self.assertFalse(response['authorization_added'])
        self.accept(encode(response))
        with self.assertRaises(ValueError):
            self.host.revoke(self.phone.request['request_id'], now=103, confirmation=CONFIRM_REVOKE)
        self.assertEqual(self.host.store.read(), old)

    def test_atomic_write_failure_has_no_consumption_or_key(self):
        with patch('fixture_helper.os.replace', side_effect=OSError('injected')):
            with self.assertRaises(OSError):
                self.authorize()
        self.assertEqual(self.host._records, {})
        self.assertEqual(self.host.store.read(), b'')

    def test_old_generation_cannot_complete_new_attempt(self):
        self.accept()
        old = self.phone.connect(explicit=True)
        self.phone.connection_result(old, pinned_ssh_authenticated=False)
        new = self.phone.connect(explicit=True)
        self.assertFalse(self.phone.connection_result(old, pinned_ssh_authenticated=True))
        self.assertTrue(self.phone.connection_result(new, pinned_ssh_authenticated=True))

    def test_host_preview_is_public_and_readonly(self):
        preview = self.host.preview(encode(self.phone.request), now=100)
        self.assertEqual(preview['account'], 'fixture-user')
        self.assertEqual(preview['fingerprint'], fingerprint(self.keys.public(self.handle)))
        self.assertFalse(preview['real_authorization'])
        self.assertEqual(self.host.store.read(), b'')
        host_fixture = (Path(__file__).parent / 'fixtures/host-public-key.txt').read_text().strip()
        request_fixture = json.loads((Path(__file__).parent / 'fixtures/request-v2.json').read_text())
        self.assertEqual(fingerprint(host_fixture), request_fixture['host_key'])

    def test_schema_fields_agree_with_runtime(self):
        import pairing
        schema = json.loads((Path(__file__).parent / 'protocol-v2.schema.json').read_text())
        for name, fields in [('request', pairing.REQUEST_FIELDS), ('response', pairing.RESPONSE_FIELDS)]:
            definition = schema['$defs'][name]
            self.assertEqual(set(definition['required']), fields)
            self.assertEqual(set(definition['properties']), fields)
            self.assertFalse(definition['additionalProperties'])

    def test_connection_event_rejects_truthy_nonboolean(self):
        self.accept()
        generation = self.phone.connect(explicit=True)
        for value in ('false', 1, None):
            with self.assertRaises(ValueError):
                self.phone.connection_result(generation, pinned_ssh_authenticated=value)
        self.assertEqual(self.phone.state, 'connecting')

    def test_public_fixtures(self):
        directory = Path(__file__).parent / 'fixtures'
        request = decode((directory / 'request-v2.json').read_bytes(), now=100)
        response = decode((directory / 'authorized-v2.json').read_bytes(), now=101)
        self.assertEqual(response['fingerprint'], fingerprint(request['public_key']))
        self.assertEqual(request['request_id'], response['request_id'])
        for path in directory.glob('*.json'):
            raw = path.read_text()
            self.assertNotIn('PRIVATE KEY', raw)
            self.assertNotIn('private_key', raw)


if __name__ == '__main__':
    unittest.main()
