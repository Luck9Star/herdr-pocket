import importlib.util
from pathlib import Path
import unittest

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


if __name__ == '__main__': unittest.main()
