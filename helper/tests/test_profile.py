import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from herdr_pocket_helper import __main__ as cli
from herdr_pocket_helper.profile import encode_profile


def synthetic_profile():
    key = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    return {'version': 1, 'type': 'herdr-connection-profile', 'host': 'host.example',
            'port': 22, 'username': 'test_account', 'provider': 'direct', 'session': 'phone-1',
            'socketPath': '/home/test_account/.config/herdr/sessions/phone-1/herdr.sock',
            'herdrPath': '/usr/local/bin/herdr', 'expectedHostKey': key}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.obj = synthetic_profile()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.pub = self.home / 'synthetic-host.pub'
        self.pub.write_text(self.obj['expectedHostKey'] + ' synthetic fixture\n')

    def run_cli(self, fmt='json', **changed):
        obj = dict(self.obj, **changed)
        args = ['profile', '--host-public-key', str(self.pub), '--host', obj['host'],
                '--port', str(obj['port']), '--provider', obj['provider'], '--session', obj['session'],
                '--socket-path', obj['socketPath'], '--herdr-path', obj['herdrPath'], '--format', fmt]
        with (patch.object(cli.os, 'getuid', return_value=1001),
              patch.object(cli.os, 'geteuid', return_value=1001),
              patch('pwd.getpwuid', return_value=SimpleNamespace(pw_name='test_account', pw_dir=str(self.home))),
              patch('herdr_pocket_helper.store.Host', side_effect=AssertionError('profile must not construct Host')),
              patch('sys.stdout') as out, patch('sys.stderr', new_callable=io.StringIO) as err):
            out.buffer = io.BytesIO()
            status = cli.main(args)
            return status, out.buffer.getvalue(), err.getvalue()

    def test_json_public_coordinates_use_current_account_without_authorization(self):
        status, raw, error = self.run_cli()
        self.assertEqual((status, error), (0, ''))
        self.assertEqual(json.loads(raw), self.obj)
        self.assertEqual(set(self.home.iterdir()), {self.pub})
        self.assertLessEqual(len(raw), 2048)

    def test_svg_is_a_vector_qr_for_exact_public_json(self):
        status, svg, error = self.run_cli('svg')
        self.assertEqual((status, error), (0, ''))
        root = ET.fromstring(svg)
        self.assertEqual(root.tag, '{http://www.w3.org/2000/svg}svg')
        self.assertIsNotNone(root.find('{http://www.w3.org/2000/svg}path'))
        # The existing renderer receives the complete public record as QR data.
        import qrcode
        with patch.object(qrcode, 'make', wraps=qrcode.make) as make:
            self.run_cli('svg')
        self.assertEqual(json.loads(make.call_args.args[0]), self.obj)
        self.assertEqual(set(self.home.iterdir()), {self.pub})

    def test_invalid_profile_leaves_no_authorization_or_partial_output(self):
        status, raw, error = self.run_cli(session='default')
        self.assertEqual((status, raw), (1, b''))
        self.assertIn('不能授权设备', error)
        self.assertEqual(set(self.home.iterdir()), {self.pub})

    def test_strict_types_paths_host_and_public_key(self):
        invalid = {
            'version': [True, 1.0, 2], 'port': [True, 22.0, 0, 65536],
            'host': ['', 'host.', '-host', 'host..example', 'a' * 64, '例.example',
                     '[2001:db8::1]', 'fe80::1%en0', '2001:xyz::1'],
            'username': ['root name', 'Upper', 'a' * 33],
            'provider': ['unknown', None], 'session': ['', 'default', 'bad/name', 'a' * 65],
            'socketPath': ['/herdr/sessions/phone-1/herdr.sock',
                           '/home/x/herdr/sessions/other/herdr.sock',
                           '/home//herdr/sessions/phone-1/herdr.sock',
                           '/home/./herdr/sessions/phone-1/herdr.sock',
                           '/home/../herdr/sessions/phone-1/herdr.sock'],
            'herdrPath': ['relative', '/', '/bin/herdr/', '/bin/../herdr', '/bin/./herdr',
                          '/bin//herdr', '/bin/herdr\n', '/bin/herdr\x85', '/' + 'x' * 1024],
            'expectedHostKey': [self.obj['expectedHostKey'] + ' comment', 'ssh-ed25519 AAAA']}
        for name, values in invalid.items():
            for value in values:
                with self.subTest(field=name, value=value), self.assertRaises(ValueError):
                    encode_profile(dict(self.obj, **{name: value}))
        with self.assertRaises(ValueError):
            encode_profile(dict(self.obj, extra=True))
        missing = dict(self.obj)
        del missing['username']
        with self.assertRaises(ValueError):
            encode_profile(missing)

    def test_utf8_paths_and_ipv6_and_total_byte_bound(self):
        for host in ('2001:db8::1', '::1', '192.0.2.1', 'host-1.example'):
            self.assertEqual(json.loads(encode_profile(dict(self.obj, host=host)))['host'], host)
        self.assertIn('会话'.encode(), encode_profile(dict(self.obj, herdrPath='/用户/会话/herdr')))
        boundary = dict(self.obj, herdrPath='/' + 'x' * 1023)
        extra = 2048 - len(encode_profile(boundary))
        boundary['socketPath'] = '/home' + 'x' * extra + boundary['socketPath'][5:]
        self.assertEqual(len(encode_profile(boundary)), 2048)
        with patch('sys.stdout') as out:
            out.buffer = io.BytesIO()
            cli.emit_response(encode_profile(boundary), 'json', newline=False)
            self.assertEqual(len(out.buffer.getvalue()), 2048)
        with self.assertRaises(ValueError):
            encode_profile(dict(boundary, socketPath='/h' + boundary['socketPath'][1:]))
        with self.assertRaises(ValueError):
            encode_profile(dict(self.obj, host='h' * 63 + '.' + 'h' * 63 + '.' + 'h' * 63 + '.' + 'h' * 61,
                                socketPath='/' + 'x' * 970 + '/herdr/sessions/phone-1/herdr.sock',
                                herdrPath='/' + 'y' * 1023))

    def test_shared_valid_vectors_can_be_produced(self):
        path = Path(__file__).resolve().parents[2] / 'validation/shared/connection-profile-v1.json'
        vectors = json.loads(path.read_text())
        for case in vectors['valid']:
            with self.subTest(case=case['name']):
                obj = json.loads(case['raw'])
                self.assertEqual(json.loads(encode_profile(obj)), obj)


if __name__ == '__main__':
    unittest.main()
