import unittest
from go_panic_sanitize import sanitize_go_panic


class PanicSanitizationTests(unittest.TestCase):
    def test_only_first_crashing_goroutine_and_allowlisted_symbols(self):
        raw = b'''panic: runtime error: invalid memory address or nil pointer dereference secret=do-not-export\n\ngoroutine 17 [running]:\nruntime.gopanic(0xabc, 0x123)\n\t/opt/go/src/runtime/panic.go:42 +0x12\nherdr.local/tailscale-runtime/fixture.(*Fixture).Diagnostics(0xsecret)\n\t/tmp/ts-cabi-candidate/fixture/diagnostics.go:65 +0x99\ntailscale.com/net/netmon.(*Monitor).InterfaceState(0x1)\n\t/tmp/ts-cabi-candidate/upstream/tailscale/net/netmon/netmon.go:420 +0x1\nuser.private.Secret(0xdead)\n\t/tmp/personal/secret.go:777 +0x1\n\ngoroutine 18 [running]:\nruntime.another(0x1)\n\t/opt/go/src/runtime/another.go:1 +0x1\n'''
        result=sanitize_go_panic(raw)
        self.assertEqual(result['category'],'nil_pointer')
        self.assertEqual([frame['file'] for frame in result['frames']],['panic.go','diagnostics.go','netmon.go'])
        for forbidden in ('secret','0x','/tmp/','goroutine 18','user.private'):
            self.assertNotIn(forbidden,str(result))
    def test_unknown_path_and_untrusted_function_are_dropped(self):
        raw=b'panic: sensitive contents\n\ngoroutine 1 [running]:\nruntime.bad(123)\n\t/tmp/private/file.go:3 +0x1\n'
        self.assertEqual(sanitize_go_panic(raw),{'category':'other','frames':[]})
        self.assertEqual(sanitize_go_panic(b'ordinary log'),{'category':'none','frames':[]})

if __name__=='__main__': unittest.main()
