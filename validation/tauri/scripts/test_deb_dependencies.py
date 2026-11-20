import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from linux_pairing_notices import NOTICE_FILES, SOURCE, TAURI_DEB_NOTICE_DIR, verify_deb

spec=importlib.util.spec_from_file_location('deb_dependencies',Path(__file__).with_name('check-deb-dependencies.py'))
check=importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class DebianDependenciesTests(unittest.TestCase):
    def test_required_groups_and_alternative(self):
        self.assertTrue(check.valid_dependencies('fonts-noto-cjk | fonts-wqy-microhei, libwebkit2gtk-4.1-0, libgtk-3-0'))
        self.assertTrue(check.valid_dependencies('libgtk-3-0 (>= 3), libwebkit2gtk-4.1-0, fonts-wqy-microhei | fonts-noto-cjk'))
        for value in ('fonts-noto-cjk, libgtk-3-0, libwebkit2gtk-4.1-0',
                      'fonts-noto-cjk | fonts-wqy-microhei, libgtk-3-0',
                      'fonts-noto-cjk | fonts-wqy-microhei, libwebkit2gtk-4.1-0'):
            with self.subTest(value=value): self.assertFalse(check.valid_dependencies(value))


    @unittest.skipUnless(shutil.which('dpkg-deb'), 'requires the Debian package reader')
    def test_linux_package_notice_payload_must_match_vendored_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'package'
            control = root / 'DEBIAN'
            control.mkdir(parents=True)
            (control / 'control').write_text('Package: herdr-pocket-notice-test\nVersion: 0.1\nArchitecture: all\n'
                'Maintainer: Test <test@example.invalid>\nDescription: isolated fixture\n')
            config = Path(__file__).resolve().parents[1] / 'src-tauri/tauri.conf.json'
            files = json.loads(config.read_text())['bundle']['linux']['deb']['files']
            for installed, original in files.items():
                path = root / installed.lstrip('/')
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(config.parent / original, path)
            archive = root.parent / 'notices.deb'

            def build():
                subprocess.run(['dpkg-deb', '--build', '--root-owner-group', root, archive],
                               check=True, capture_output=True)

            build()
            self.assertEqual(verify_deb(archive), {
                f'{TAURI_DEB_NOTICE_DIR}/{name}': hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
                for name in NOTICE_FILES})
            upstream = root / TAURI_DEB_NOTICE_DIR / 'UPSTREAM'
            original = upstream.read_bytes()
            upstream.write_bytes(b'!' + original[1:])
            build()
            with self.assertRaisesRegex(ValueError, 'Linux pairing notice mismatch'):
                verify_deb(archive)
            upstream.unlink()
            build()
            with self.assertRaisesRegex(ValueError, 'Linux pairing notices missing'):
                verify_deb(archive)


if __name__ == '__main__': unittest.main()
