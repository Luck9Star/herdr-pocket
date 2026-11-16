"""The Go panic classifier must read padded threadtime, not a package name.

`logcat -s Go:E` prints `E Go      : panic: ...`. The tag is padded to eight
columns and the line does not name the application package. A classifier
that requires `E Go:` or that matches `runtime error:` before the specific
cause reports nothing, or hides the cause. An upstream or standard-library
panic has no frame in this package, so its symbols must survive too.

Device frames carry a receiver, as in "dns.(*Manager).Set(", and package
paths may contain '-', as in "herdr.local/tailscale-runtime".
"""
import unittest

import android_go_log as golog
from android_ts_node_probe import _go_log_evidence, safe_go_log

# Real threadtime shape: tag "Go" padded to 8 columns. No package name.
PADDED = (
    b'11-16 02:31:44.123  4242  4242 E Go      : panic: runtime error: '
    b'invalid memory address or nil pointer dereference\n'
    b'11-16 02:31:44.124  4242  4242 E Go      : \n'
    b'11-16 02:31:44.125  4242  4242 E Go      : goroutine 12 [running]:\n'
    b'11-16 02:31:44.126  4242  4242 E Go      : '
    b'herdr.local/tailscale-runtime.(*manager).start(0x1)\n'
    b'11-16 02:31:44.127  4242  4242 E Go      : \tcore.go:10 +0x20\n'
)

# Upstream panic: the frames are in tailscale and the standard library only.
UPSTREAM = (
    b'11-16 02:31:44.200  4242  4242 E Go      : panic: runtime error: '
    b'invalid memory address or nil pointer dereference\n'
    b'11-16 02:31:44.201  4242  4242 E Go      : [signal SIGSEGV: '
    b'segmentation violation code=0x1 addr=0x18 pc=0x7f00]\n'
    b'11-16 02:31:44.202  4242  4242 E Go      : goroutine 20 [running]:\n'
    b'11-16 02:31:44.203  4242  4242 E Go      : '
    b'tailscale.com/net/dns.(*Manager).Set(0xc000010000, {0x1, 0x2})\n'
    b'11-16 02:31:44.204  4242  4242 E Go      : '
    b'\t/home/runner/go/pkg/mod/tailscale.com@v1.104.1/net/dns/manager.go:412 +0x1a5\n'
    b'11-16 02:31:44.205  4242  4242 E Go      : '
    b'tailscale.com/wgengine/magicsock.(*Conn).receiveIPv4(0xc000020000)\n'
    b'11-16 02:31:44.206  4242  4242 E Go      : '
    b'\t/home/runner/go/pkg/mod/tailscale.com@v1.104.1/wgengine/magicsock/magicsock.go:990\n'
    b'11-16 02:31:44.207  4242  4242 E Go      : runtime.gopanic({0x7f00, 0x1})\n'
    b'11-16 02:31:44.208  4242  4242 E Go      : '
    b'\t/home/runner/go/src/runtime/panic.go:785 +0x132\n'
    b'11-16 02:31:44.209  4242  4242 E Go      : main.(*manager).closeNode(0x1)\n'
)


class GoLogClassificationTests(unittest.TestCase):
    def test_padded_threadtime_without_package_name(self):
        self.assertNotIn(b'dev.herdr', PADDED)
        self.assertIn(b'E Go      :', PADDED)
        evidence = golog.classify(PADDED)
        self.assertEqual(evidence['panicClass'], 'go-panic')
        self.assertEqual(evidence['reason'], 'nil-pointer')
        self.assertEqual(evidence['appFunction'],
                         'herdr.local/tailscale-runtime.manager.start')
        self.assertEqual(evidence['firstFrame'],
                         'herdr.local/tailscale-runtime.manager.start')

    def test_upstream_panic_keeps_upstream_frames(self):
        """No frame in this package: the upstream symbols must survive."""
        evidence = golog.classify(UPSTREAM)
        self.assertEqual(evidence['reason'], 'nil-pointer')
        self.assertEqual(evidence['appFunction'], 'main.manager.closeNode')
        self.assertEqual(evidence['firstFrame'], 'tailscale.com/net/dns.Manager.Set')
        self.assertEqual(evidence['upstreamFrames'],
                         ['tailscale.com/net/dns.Manager.Set',
                          'tailscale.com/wgengine/magicsock.Conn.receiveIPv4'])

    def test_upstream_only_has_no_application_frame(self):
        text = UPSTREAM.replace(
            b'11-16 02:31:44.209  4242  4242 E Go      : main.(*manager).closeNode(0x1)\n', b'')
        evidence = golog.classify(text)
        self.assertEqual(evidence['appFunction'], 'none')
        self.assertEqual(evidence['firstFrame'], 'tailscale.com/net/dns.Manager.Set')
        self.assertTrue(evidence['upstreamFrames'])

    def test_receiver_frame_is_not_truncated_at_the_receiver(self):
        """A method frame must not collapse to the package prefix."""
        evidence = golog.classify(UPSTREAM)
        self.assertNotEqual(evidence['firstFrame'], 'tailscale.com/net/dns.')
        self.assertNotEqual(evidence['firstFrame'], 'tailscale.com/net/dns')

    def test_symbol_has_no_arguments_addresses_or_lines(self):
        evidence = golog.classify(UPSTREAM)
        for symbol in [evidence['firstFrame'], evidence['appFunction']] + evidence['upstreamFrames']:
            if symbol == 'none':
                continue
            self.assertNotIn('(', symbol)
            self.assertNotIn(')', symbol)
            self.assertNotIn('*', symbol)
            self.assertNotIn('0x', symbol)
            self.assertNotIn(':', symbol)
            self.assertNotIn(' ', symbol)

    def test_source_position_line_is_not_a_frame(self):
        text = (b'11-16 02:31:44.203  4242  4242 E Go      : '
                b'\t/home/runner/go/src/runtime/proc.go:400 +0x1\n')
        self.assertFalse(golog.classify(text)['available'])

    def test_standard_library_frame_is_kept_when_first(self):
        text = (b'11-16 02:31:44.203  4242  4242 E Go      : '
                b'internal/poll.(*FD).Read(0xc000030000)\n')
        evidence = golog.classify(text)
        self.assertEqual(evidence['firstFrame'], 'internal/poll.FD.Read')
        self.assertEqual(evidence['upstreamFrames'], [])

    def test_runtime_frame_is_skipped(self):
        text = (b'11-16 02:31:44.203  4242  4242 E Go      : runtime.goexit({})\n'
                b'11-16 02:31:44.204  4242  4242 E Go      : '
                b'tailscale.com/tsnet.(*Server).Run(0x1)\n')
        evidence = golog.classify(text)
        self.assertEqual(evidence['firstFrame'], 'tailscale.com/tsnet.Server.Run')

    def test_index_and_slice_are_not_collapsed(self):
        index = (b'11-16 02:31:44.123  4242  4242 E Go      : '
                 b'panic: runtime error: index out of range [3] with length 2\n')
        bounds = (b'11-16 02:31:44.123  4242  4242 E Go      : '
                  b'panic: runtime error: slice bounds out of range [:3] with capacity 2\n')
        self.assertEqual(golog.classify(index)['reason'], 'index-out-of-range')
        self.assertEqual(golog.classify(bounds)['reason'], 'slice-bounds')

    def test_unpadded_go_tag_is_not_the_device_format(self):
        text = b'11-16 02:31:44.123  4242  4242 E Go: panic: send on closed channel\n'
        self.assertFalse(golog.classify(text)['available'])

    def test_package_line_without_go_tag_is_not_evidence(self):
        text = (b'11-16 02:31:44.123  4242  4242 F libc    : '
                b'Fatal signal 6 (SIGABRT), code -1 (SI_QUEUE) in tid 4242 (dev.herdr.herdr_flutter_probe)\n')
        self.assertFalse(golog.classify(text)['available'])

    def test_raw_panic_text_is_not_returned(self):
        text = (b'11-16 02:31:44.123  4242  4242 E Go      : panic: '
                b'secret-detail-' + b'Z' * 80 + b'\n')
        blob = repr(golog.classify(text)).encode()
        self.assertNotIn(b'secret-detail', blob)
        self.assertNotIn(b'ZZZZ', blob)

    def test_empty_is_unavailable(self):
        self.assertFalse(golog.classify(b'')['available'])


class SafeGoLogTests(unittest.TestCase):
    def test_unknown_reason_is_rejected(self):
        value = {'available': True, 'panicClass': 'go-panic', 'reason': 'raw text',
                 'appFunction': 'none', 'firstFrame': 'none', 'upstreamFrames': []}
        self.assertEqual(safe_go_log(value), {'available': False})

    def test_whitelisted_enums_and_symbols_are_kept(self):
        value = {'available': True, 'panicClass': 'go-panic', 'reason': 'nil-pointer',
                 'appFunction': 'main.manager.closeNode',
                 'firstFrame': 'tailscale.com/net/dns.Manager.Set',
                 'upstreamFrames': ['tailscale.com/net/dns.Manager.Set']}
        result = safe_go_log(value)
        self.assertTrue(result['available'])
        self.assertEqual(result['firstFrame'], 'tailscale.com/net/dns.Manager.Set')

    def test_symbol_with_arguments_is_rejected(self):
        value = {'available': True, 'panicClass': 'go-panic', 'reason': 'nil-pointer',
                 'appFunction': 'main.foo(0x1)', 'firstFrame': 'none', 'upstreamFrames': []}
        self.assertEqual(safe_go_log(value), {'available': False})

    def test_non_upstream_in_upstream_list_is_rejected(self):
        value = {'available': True, 'panicClass': 'go-panic', 'reason': 'nil-pointer',
                 'appFunction': 'none', 'firstFrame': 'none',
                 'upstreamFrames': ['main.foo']}
        self.assertEqual(safe_go_log(value), {'available': False})

    def test_capture_asks_for_this_pid_go_tag_only(self):
        seen = []

        def adb(*parts, timeout=30):
            seen.append(parts)
            reply = type('Reply', (), {})()
            reply.returncode = 0
            reply.stdout = PADDED
            return reply

        result = _go_log_evidence(adb, 4242)
        self.assertEqual(seen, [('shell', 'logcat', '-d', '-b', 'main',
                                 '--pid', '4242', '-s', 'Go:E')])
        self.assertEqual(result['reason'], 'nil-pointer')
        self.assertEqual(result['appFunction'],
                         'herdr.local/tailscale-runtime.manager.start')


if __name__ == '__main__':
    unittest.main()
