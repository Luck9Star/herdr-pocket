import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from android_private_go_crash import summarize


class SummaryTests(unittest.TestCase):
    def test_real_go_panic(self):
        if not shutil.which('go'):
            self.skipTest('Go is unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'main.go')
            with open(path, 'w') as f:
                f.write('package main\nfunc main() { panic("secret-42") }\n')
            env = dict(os.environ, GOTRACEBACK='crash')
            run = subprocess.run(['go', 'run', path], capture_output=True, env=env, timeout=60)
        result = summarize(run.stderr)
        self.assertEqual(result['panic']['message_sha256'], hashlib.sha256(b'secret-42').hexdigest())
        self.assertEqual(result['origin']['function'], 'main.main')
        self.assertEqual(result['origin']['file'], 'main.go')
        self.assertNotIn('secret-42', json.dumps(result))
        self.assertNotIn(tmp, json.dumps(result))

    def test_real_nil_and_locked_thread_panics(self):
        if not shutil.which('go'):
            self.skipTest('Go is unavailable')
        cases = (
            ('package main\nfunc main() { var p *int; *p = 1 }\n', b'[signal SIG'),
            ('package main\nimport "runtime"\nfunc main() { runtime.LockOSThread(); panic("locked") }\n', b'locked to thread'),
        )
        for program, marker in cases:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, 'main.go')
                with open(path, 'w') as f:
                    f.write(program)
                run = subprocess.run(['go', 'run', path], capture_output=True,
                                     env=dict(os.environ, GOTRACEBACK='crash'), timeout=60)
                self.assertIn(marker, run.stderr)
                result = summarize(run.stderr)
                self.assertEqual(result['origin']['function'], 'main.main')
                self.assertEqual(result['origin']['file'], 'main.go')
                self.assertNotIn(tmp, json.dumps(result))
                self.assertNotIn('0x', json.dumps(result))

    def test_public_project_and_crypto_symbols(self):
        raw = (b'panic: wrapped: private-token\n[signal SIGSEGV: code=0x1 addr=0x0 pc=0x42]\n\n'
               b'goroutine 3 [running, locked to thread]:\n'
               b'herdr.local/tailscale-runtime.(*Runner).Start(0x123)\n\t/a/runner.go:42 +0x1\n'
               b'crypto/tls.(*Conn).Handshake(0x42)\n\t/b/conn.go:43 +0x2\n')
        result = summarize(raw)
        self.assertEqual(result['origin']['function'], 'herdr.local/tailscale-runtime.(*Runner).Start')
        self.assertEqual(result['frames'][1]['function'], 'crypto/tls.(*Conn).Handshake')
        self.assertNotIn('private-token', json.dumps(result))
        self.assertNotIn('0x', json.dumps(result))

    def test_runtime_frames_receiver_generic_and_arguments(self):
        raw = (b'panic: runtime error: invalid memory address or nil pointer dereference\n\n'
               b'goroutine 1 [running]:\n'
               b'runtime.panicmem()\n\t/usr/local/go/src/runtime/panic.go:262 +0x19\n'
               b'tailscale.com/tsnet.(*Server).Start[...]({0xdeadbeef, 0x42})\n'
               b'\t/private/path/tsnet.go:123 +0xa1\n\n'
               b'goroutine 2 [running]:\nmain.main()\n\t/private/other.go:2 +0x1\n')
        result = summarize(raw)
        self.assertEqual(result['panic']['category'], 'nil_pointer')
        self.assertEqual(result['origin']['function'], 'tailscale.com/tsnet.(*Server).Start[...]')
        self.assertEqual(result['origin']['file'], 'tsnet.go')
        self.assertEqual(len(result['frames']), 2)
        self.assertNotIn('0xdeadbeef', json.dumps(result))
        self.assertNotIn('/private/', json.dumps(result))

    def test_no_false_origin(self):
        result = summarize(b'panic: private\n\nruntime stack:\nruntime.throw()\n\t/x/runtime.go:1\n\ngoroutine 9 [running]:\nmain.main()\n\t/x/main.go:1\n')
        self.assertIsNone(result['origin'])
        self.assertEqual(result['frames'], [])

    def test_untrusted_frame_and_dynamic_message(self):
        raw = (b'panic: token=super-secret\n\ngoroutine 1 [running]:\n'
               b'evil.secretUser(0x123)\n\t/home/person/private-secret.go:32 +0x123\n')
        result = summarize(raw)
        self.assertNotIn('secret', json.dumps(result))
        self.assertIsNone(result['origin']['function'])
        self.assertIsNone(result['origin']['file'])
        self.assertEqual(result['panic']['message_sha256'], hashlib.sha256(b'token=super-secret').hexdigest())

    def test_empty_truncation_and_limit(self):
        self.assertEqual(summarize(b'')['status'], 'empty')
        self.assertTrue(summarize(b'panic: x\n')['truncated'])
        self.assertTrue(summarize(b'panic: x\n\ngoroutine 1 [running]:\nmain.main()')['truncated'])
        self.assertTrue(summarize(b'x' * (1024 * 1024 + 1))['truncated'])


if __name__ == '__main__':
    unittest.main()
