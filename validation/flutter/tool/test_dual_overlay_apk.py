import tempfile
from pathlib import Path
import unittest
import zipfile

import dual_overlay_apk as apk


class DualOverlayApkTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'bundle'; self.bundle.mkdir()
        self.project = self.root / 'app'; self.project.mkdir()
        for name in apk.LIBRARIES:
            (self.bundle / name).write_bytes(name.encode())

    def tearDown(self):
        self.temp.cleanup()

    def make_apk(self, *, change=None, extra_abi=False):
        path = self.root / 'app.apk'
        with zipfile.ZipFile(path, 'w') as archive:
            for name in apk.LIBRARIES:
                data = (self.bundle / name).read_bytes()
                archive.writestr('lib/x86_64/' + name, b'wrong' if change == name else data)
            if extra_abi:
                archive.writestr('lib/arm64-v8a/libflutter.so', b'other')
        return path

    def test_packaging_matches_checked_native_files_and_only_x86_64(self):
        installed = apk.install(self.bundle, self.project)
        result = apk.verify(self.bundle, self.make_apk())
        self.assertEqual(result['libraries'], installed)
        with self.assertRaisesRegex(ValueError, 'unexpected_existing_native_libraries'):
            apk.install(self.bundle, self.project)

    def test_altered_library_or_extra_architecture_fails(self):
        with self.assertRaisesRegex(ValueError, 'apk_native_library_mismatch'):
            apk.verify(self.bundle, self.make_apk(change=apk.LIBRARIES[0]))
        with self.assertRaisesRegex(ValueError, 'apk_abi_mismatch'):
            apk.verify(self.bundle, self.make_apk(extra_abi=True))


if __name__ == '__main__':
    unittest.main()
