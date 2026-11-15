import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import tauri_android_dual_apk as check


class TauriDualApkTests(unittest.TestCase):
    def test_requires_exact_provider_bytes_and_one_abi(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); qa=root/'qa';qa.mkdir();apk=root/'app.apk'
            for name in check.PROVIDERS:(qa/name).write_bytes(('real-'+name).encode())
            def write(*, forged=False, extra=False):
                with zipfile.ZipFile(apk,'w') as out:
                    for name in check.PROVIDERS:
                        out.writestr('lib/x86_64/'+name,b'forged' if forged and name==check.PROVIDERS[0] else (qa/name).read_bytes())
                    out.writestr('lib/x86_64/'+check.APP,b'fixture')
                    if extra:out.writestr('lib/arm64-v8a/libother.so',b'fixture')
            with patch.object(check.android_bundle,'elf') as elf:
                write();check.verify(apk,qa,'readelf');self.assertEqual(elf.call_count,3)
                write(forged=True)
                with self.assertRaisesRegex(ValueError,'hash_mismatch'):check.verify(apk,qa,'readelf')
                write(extra=True)
                with self.assertRaisesRegex(ValueError,'abi_invalid'):check.verify(apk,qa,'readelf')


if __name__=='__main__':unittest.main()
