import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('android_private_ca_probe', HERE / 'android_private_ca_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class PrivateCaProbeTests(unittest.TestCase):
    def test_instrument_requires_one_well_formed_result_after_force_stop(self):
        with patch.object(probe, '_adb', side_effect=[b'', b'HP_TLS_RESULT pid=42 code=0 wrong=2 wrap=1 executable=1 javaEnv=1']) as adb:
            self.assertEqual(probe.instrument(1234), (42, 0, 2, 1, 1, 1))
            self.assertEqual(adb.call_args_list[0].args, ('shell', 'am', 'force-stop', probe.PACKAGE))
        for value in (b'', b'HP_TLS_RESULT pid=42 code=0 wrong=2 wrap=1 executable=1 javaEnv=1\nHP_TLS_RESULT pid=42 code=0 wrong=2 wrap=1 executable=1 javaEnv=1'):
            with self.subTest(value=value), patch.object(probe, '_adb', side_effect=[b'', value]):
                with self.assertRaises(probe.ReverseError):
                    probe.instrument(1234)

    def test_go_uses_standard_verification_and_private_process_environment(self):
        source = (HERE / 'android-private-ca-probe' / 'probe.go').read_text()
        wrapper = (HERE / 'android-private-ca-probe' / 'wrap.sh').read_text()
        self.assertNotIn('InsecureSkipVerify', source)
        self.assertNotIn('RootCAs:', source)
        self.assertIn('x509.UnknownAuthorityError', source)
        self.assertIn('x509.HostnameError', source)
        self.assertIn('SSL_CERT_FILE=', wrapper)
        self.assertIn('SSL_CERT_DIR=', wrapper)
        self.assertIn('exec "$@"', wrapper)


if __name__ == '__main__':
    unittest.main()
