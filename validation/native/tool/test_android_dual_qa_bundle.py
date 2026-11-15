import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import android_dual_qa_bundle as qa


class QABundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.normal = Path(self.temp.name) / 'normal'
        self.variant = Path(self.temp.name) / 'qa'
        self.normal.mkdir()
        self.variant.mkdir()
        (self.normal / 'manifest.json').write_text('{}')
        for name in qa.LIBRARIES:
            (self.normal / name).write_bytes(b'normal-' + name.encode())
            (self.variant / name).write_bytes(b'qa-ts' if name == qa.android_tailscale.LIBRARY else (self.normal / name).read_bytes())
        (self.variant / qa.QA_FILE).write_bytes(qa.SOURCE.read_bytes())
        self.record = {'schemaVersion': 1, 'variant': 'test-only-private-ca-android-x86_64',
                       'sourceCommit': 'a' * 40, 'normalManifestSha256': qa.sha(self.normal / 'manifest.json'),
                       'qaSourceSha256': qa.sha(qa.SOURCE),
                       'files': {name: qa.sha(self.variant / name) for name in qa.LIBRARIES}}
        self.save()

    def save(self):
        (self.variant / 'qa-manifest.json').write_text(json.dumps(self.record))

    def verify(self):
        with patch.object(qa.android_bundle, 'verify'), patch.object(qa.android_bundle, 'elf'):
            return qa.verify(self.normal, self.variant, 'a' * 40, 'readelf')

    def test_accepts_separate_qa_and_same_non_ts_libraries(self):
        self.assertEqual(self.verify()['sourceCommit'], 'a' * 40)

    def test_rejects_modified_non_ts_even_if_manifest_rehashed(self):
        name = qa.LIBRARIES[0]
        (self.variant / name).write_bytes(b'changed')
        self.record['files'][name] = qa.sha(self.variant / name)
        self.save()
        with self.assertRaisesRegex(ValueError, 'non-TS'):
            self.verify()

    def test_rejects_substituted_normal_ts_and_extra_files(self):
        name = qa.android_tailscale.LIBRARY
        (self.variant / name).write_bytes((self.normal / name).read_bytes())
        self.record['files'][name] = qa.sha(self.variant / name)
        self.save()
        with self.assertRaisesRegex(ValueError, 'indistinguishable'):
            self.verify()
        (self.variant / 'extra').touch()
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            self.verify()

    def test_source_is_android_x86_only_and_fixed_private_paths(self):
        source = qa.SOURCE.read_text()
        self.assertIn('//go:build android && amd64', source)
        self.assertEqual(source.count('/data/user/0/'), 2)
        self.assertNotIn('InsecureSkipVerify', source)


if __name__ == '__main__':
    unittest.main()
