import unittest
from pathlib import Path

import android_crash_symbolize as symbolize


SAMPLE = b'''*** *** *** *** *** *** *** *** *** *** *** *** *** *** ***
Build fingerprint: 'x'
pid: 1234, tid: 1234, name: dev.herdr.herdr_flutter_probe  >>> dev.herdr.herdr_flutter_probe <<<
signal 6 (SIGABRT), code -1 (SI_QUEUE), fault addr --------
Abort message: 'x'
    #00 pc 000000000004a1b0  /data/app/~~a==/com.x-y==/lib/x86_64/libhp_tailscale.so (BuildId: ab)
    #01 pc 000000000002f3c4  /apex/com.android.runtime/lib64/bionic/libc.so (BuildId: cd)
    #02 pc 000000000004b220  /data/app/~~a==/com.x-y==/lib/x86_64/libherdr_flutter_network_runtime.so (BuildId: ef)
    #03 pc 00000000000c1234  /data/app/~~a==/com.x-y==/lib/x86_64/libabi_shim.so (BuildId: 12)
'''

OTHER = b'''    #00 pc 000000000004a1b0  /data/app/~~a==/com.x-y==/lib/x86_64/libhp_tailscale.so (BuildId: ab)
'''


class ExtractFramesTests(unittest.TestCase):
    def test_extracts_module_basename_and_pc(self):
        frames = symbolize.extract_frames(SAMPLE)
        self.assertEqual([f['module'] for f in frames],
            ['libhp_tailscale.so', 'libc.so', 'libherdr_flutter_network_runtime.so',
             'libabi_shim.so'])
        self.assertEqual(frames[0]['pc'], '000000000004a1b0')

    def test_drops_duplicates(self):
        frames = symbolize.extract_frames(OTHER + OTHER)
        self.assertEqual(len(frames), 1)

    def test_report_keeps_only_own_modules(self):
        report = symbolize.bounded_report(symbolize.extract_frames(SAMPLE), '/nonexistent')
        modules = {entry['module'] for entry in report}
        self.assertIn('libhp_tailscale.so', modules)
        self.assertNotIn('libc.so', modules)

    def test_report_never_leaks_full_paths(self):
        report = symbolize.bounded_report(symbolize.extract_frames(SAMPLE), '/nonexistent')
        for entry in report:
            for value in entry.values():
                self.assertNotIn('/data/app', value)
                self.assertNotIn('/apex', value)


if __name__ == '__main__':
    unittest.main()
