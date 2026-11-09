"""Exercise the production provenance boundary without building an app."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[5]
spec=importlib.util.spec_from_file_location('flutter_ci_manifest',REPO/'validation/flutter/tool/ci.py')
ci=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)

class ProductionManifestTest(unittest.TestCase):
    def test_only_explicit_java_and_manifest_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); base=root/'validation/network-profiles/native/android';base.mkdir(parents=True)
            (root/'validation/network-profiles/android_sources.py').write_text('fixture')
            (base/'network-secrets.gradle').write_text('fixture')
            (base/'Safe.java').write_text('synthetic')
            (base/'AndroidZeroTierNative.java').write_text('bridge')
            manifest=base/'android-production-sources.txt';manifest.write_text('Safe.java\n')
            with patch.object(ci,'ROOT',root):
                # Stage 2: a non-empty manifest without the reviewed JNI
                # bridge is rejected.
                with self.assertRaises(SystemExit):
                    ci.android_network_production_sources()
                manifest.write_text('Safe.java\nAndroidZeroTierNative.java\n')
                result=ci.android_network_production_sources()
                self.assertEqual([Path(record['path']).name for record in result],
                    ['android-production-sources.txt','network-secrets.gradle','android_sources.py','Safe.java','AndroidZeroTierNative.java'])
                for invalid in ('', 'Safe.java\nSafe.java\n', '../Safe.java\n',
                    'Safe.java\nMissing.java\n', 'Missing.java\n'):
                    manifest.write_text(invalid)
                    with self.subTest(invalid=invalid),self.assertRaises(SystemExit):
                        ci.android_network_production_sources()
                (base/'Link.java').symlink_to(base/'Safe.java');manifest.write_text('Link.java\n')
                with self.assertRaises(SystemExit):ci.android_network_production_sources()

if __name__=='__main__': unittest.main()
