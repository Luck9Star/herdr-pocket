import hashlib
import json
import unittest

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from paired_gui import GuiFailure
import flutter_android_documents_oracle as oracle

PASSWORD = 'fixture password only'


def catalog(font):
    return json.dumps({'schemaVersion': 4, 'profiles': [], 'pendingCreation': None,
                       'networkProfiles': [], 'preferences': {'terminalFontSize': font}},
                      separators=(',', ':')).encode()


def archive(payload):
    header = b'HPKT\x01\x01' + bytes(range(16)) + bytes(range(12))
    key = hashlib.pbkdf2_hmac('sha256', PASSWORD.encode(), header[6:22], 600_000, dklen=32)
    return header + AESGCM(key).encrypt(header[22:34], payload, header)


class OracleTest(unittest.TestCase):
    def test_schema_and_types_are_exact(self):
        self.assertEqual(oracle.catalog(catalog(19), 19), catalog(19))
        for raw in (catalog(19).replace(b'"schemaVersion":4', b'"schemaVersion":4.0'),
                    catalog(19).replace(b'"terminalFontSize":19', b'"terminalFontSize":19.0'),
                    catalog(19).replace(b'"pendingCreation":null', b'"pendingCreation":{}'),
                    catalog(19).replace(b'"profiles":[]', b'"profiles":[{}]'),
                    catalog(19).replace(b'"schemaVersion":4', b'"schemaVersion":4,"schemaVersion":4')):
            with self.subTest(raw=raw), self.assertRaises(GuiFailure):
                oracle.catalog(raw, 19)

    def test_independent_decryption_and_authentication(self):
        payload = b'{"version":2,"hosts":[],"networks":[],"preferences":{"terminalFontSize":19}}'
        raw = archive(payload)
        oracle.archive(raw, PASSWORD)
        for invalid, password in ((raw, 'wrong'), (raw[:-1] + bytes([raw[-1] ^ 1]), PASSWORD),
                                  (archive(payload.replace(b':19', b':19.0')), PASSWORD),
                                  (archive(payload.replace(b'"version":2', b'"version":2,"version":2')), PASSWORD)):
            with self.subTest(password=password), self.assertRaises(GuiFailure):
                oracle.archive(invalid, password)

    def test_full_ledger_requires_exact_bytes_and_single_apply(self):
        ledger = oracle.Ledger()
        for stage in ('initial19', 'cancel', 'export'):
            ledger.record(stage, catalog(19))
        ledger.record('control13', catalog(13))
        for stage in ('wrong_password', 'tampered', 'preview'):
            ledger.record(stage, catalog(13))
        with self.assertRaisesRegex(GuiFailure, 'apply_not_dispatched'):
            ledger.record('apply', catalog(19))
        ledger.begin_apply()
        with self.assertRaisesRegex(GuiFailure, 'apply_dispatch_forbidden'):
            ledger.begin_apply()
        ledger.record('apply', catalog(19))
        with self.assertRaises(GuiFailure):
            ledger.record('apply', catalog(19))

    def test_byte_drift_and_reordering_fail_closed(self):
        ledger = oracle.Ledger()
        with self.assertRaisesRegex(GuiFailure, 'checkpoint_order_invalid'):
            ledger.record('cancel', catalog(19))
        ledger.record('initial19', catalog(19))
        with self.assertRaisesRegex(GuiFailure, 'catalog_changed'):
            ledger.record('cancel', catalog(19) + b' ')
        self.assertEqual(ledger.index, 1)


if __name__ == '__main__':
    unittest.main()
