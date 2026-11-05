import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('flutter_ci', Path(__file__).with_name('ci.py'))
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class AndroidNoticeTests(unittest.TestCase):
    def test_exact_native_notice_is_required_inside_apk(self):
        source = ci.ROOT / 'validation/pairing/native/android/notices/BOUNCY-CASTLE-LICENSE.md'
        with tempfile.TemporaryDirectory() as temp:
            apk = Path(temp) / 'synthetic.apk'
            for contents in [None, b'incorrect notice', source.read_bytes()]:
                with zipfile.ZipFile(apk, 'w') as bundle:
                    if contents is not None:
                        bundle.writestr('assets/BOUNCY-CASTLE-LICENSE.md', contents)
                if contents == source.read_bytes():
                    proof = ci.verify_android_notice(apk)
                    self.assertTrue(proof['matched'])
                    self.assertEqual(proof['assetSha256'], proof['sharedSource']['sha256'])
                else:
                    with self.assertRaises(SystemExit):
                        ci.verify_android_notice(apk)

    def test_manifest_separates_native_sources_runtime_and_manual_identity(self):
        metadata = ci.pairing_provenance('macos', None)
        self.assertEqual(len(metadata['androidSources']), 5)
        self.assertEqual(len(metadata['appleSources']), 2)
        self.assertFalse(metadata['privateKeyExport'])
        self.assertIn('NOT RUN', metadata['systemStoreRuntime'])
        for entry in metadata['androidSources'] + metadata['appleSources']:
            self.assertEqual(len(entry['sha256']), 64)


if __name__ == '__main__':
    unittest.main()
