import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from herdr_pocket_helper import store, wire
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def ephemeral_public():
    return Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()


class HostTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.host = store.Host(self.home, 'test_account', ephemeral_public())
        self.rid = 'a' * 32
        self.req = {'version':2,'type':wire.REQUEST,'request_id':self.rid,'device':'Pocket phone',
                    'public_key':ephemeral_public(),'account':'test_account','host_key':self.host.pin,
                    'issued_at':100,'expires_at':200}
        self.raw = wire.encode(self.req)
        self.auth = self.home/'.ssh'/'authorized_keys'

    def add(self):
        return wire.decode(self.host.authorize(self.raw, self.rid, now=111), now=111)

    def preset(self, data):
        self.auth.parent.mkdir(mode=0o700)
        self.auth.write_bytes(data)
        self.auth.chmod(0o600)

    def test_preview_expiration_and_confirmation_leave_directory_untouched(self):
        self.host.review(self.raw, 111)
        for changed in (dict(self.req,account='another'), dict(self.req,host_key='SHA256:'+'A'*43)):
            with self.assertRaises(ValueError):
                self.host.authorize(wire.encode(changed), self.rid, now=111)
        with self.assertRaises(ValueError):
            self.host.authorize(self.raw, 'b'*32, now=111)
        with self.assertRaises(ValueError):
            self.host.authorize(self.raw, self.rid, now=201)
        self.assertFalse(self.auth.parent.exists())

    def test_exact_revoke_after_restart_preserves_unrelated_bytes(self):
        initial = b'# existing file without final newline'
        self.preset(initial)
        self.assertTrue(self.add()['authorization_added'])
        self.assertTrue(self.add()['authorization_added'])
        reopened = store.Host(self.home, 'test_account', self.req['public_key'])
        with self.assertRaises(ValueError):
            reopened.review_revocation(self.rid)
        self.assertEqual(self.host.review_revocation(self.rid)['public_key'], self.req['public_key'])
        out = wire.decode(self.host.revoke(self.rid, self.rid, now=300), now=300)
        self.assertEqual(out['status'],'revoked')
        self.assertEqual(self.auth.read_bytes(),initial)
        self.host.revoke(self.rid, self.rid, now=301)
        with self.assertRaises(ValueError):
            self.add()

    def test_preexisting_authorization_is_never_owned_or_removed(self):
        original = (self.req['public_key']+' original\n').encode()
        self.preset(original)
        self.assertFalse(self.add()['authorization_added'])
        with self.assertRaises(ValueError):
            self.host.revoke(self.rid,self.rid,now=150)
        self.assertEqual(self.auth.read_bytes(),original)

    def test_external_edit_and_duplicate_refuse_revoke(self):
        self.add()
        line=self.auth.read_bytes()
        for data in (line+line,line.replace(b'herdr-pocket:v2:',b'edited:')):
            self.auth.write_bytes(data)
            with self.assertRaises(ValueError):
                self.host.revoke(self.rid,self.rid,now=150)
            self.assertEqual(self.auth.read_bytes(),data)

    def test_symlink_and_hardlink_refused(self):
        self.preset(b'# original\n')
        foreign = self.home/'foreign'
        self.auth.rename(foreign)
        for add_link in (lambda:self.auth.symlink_to(foreign), lambda:os.link(foreign,self.auth)):
            add_link()
            with self.assertRaises((ValueError,OSError)):
                self.add()
            self.auth.unlink()
            self.assertEqual(foreign.read_text(),'# original\n')

    def test_interrupted_add_and_revoke_recover_using_receipt(self):
        real = store.replace
        def interrupt(parent,name,value,expected):
            if name.endswith('.json') and b'"phase":"authorized"' in value:
                raise OSError('simulated interruption after append')
            return real(parent,name,value,expected)
        with patch.object(store,'replace',side_effect=interrupt), self.assertRaises(OSError):
            self.add()
        first=self.auth.read_bytes()
        self.assertTrue(self.add()['authorization_added'])
        self.assertEqual(self.auth.read_bytes(),first)
        def interrupted_revoke(parent,name,value,expected):
            if name.endswith('.json') and b'"phase":"revoked"' in value:
                raise OSError('simulated interruption after removal')
            return real(parent,name,value,expected)
        with patch.object(store,'replace',side_effect=interrupted_revoke), self.assertRaises(OSError):
            self.host.revoke(self.rid,self.rid,now=151)
        self.assertEqual(self.auth.read_bytes(),b'')
        self.host.revoke(self.rid,self.rid,now=152)

    def test_response_svg_and_json_encode_only_public_pairing_fields(self):
        from herdr_pocket_helper.__main__ import emit_response
        response = self.host.authorize(self.raw,self.rid,now=111)
        for fmt in ('json','svg'):
            with patch('sys.stdout') as output:
                output.buffer = io.BytesIO()
                emit_response(response,fmt)
                rendered = output.buffer.getvalue()
            if fmt=='svg':
                self.assertIn(b'<svg',rendered)
            else:
                self.assertEqual(wire.decode(rendered,now=111)['status'],'authorized')
