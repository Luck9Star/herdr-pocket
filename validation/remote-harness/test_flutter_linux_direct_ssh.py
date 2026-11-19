"""Deterministic checks for the Flutter Linux native evidence driver."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

if importlib.util.find_spec('paramiko') is None or importlib.util.find_spec('PIL') is None:
    raise unittest.SkipTest('ordinary SSH and screenshot test dependencies are missing')
from flutter_linux_direct_ssh import (
    SDK_ADDITIONS,
    GuiFailure,
    ScreenshotGateError,
    capture,
    capture_geometry,
    key_rejection_evidence,
    locked_dependencies,
    read_exchange,
    rotation_session,
    window_geometry,
)
from PIL import Image

XWININFO = '''
xwininfo: Window id: 0x200003 "herdr_flutter_probe"

  Absolute upper-left X:  24
  Absolute upper-left Y:  32
  Width: 1280
  Height: 720
  Border width: 0
  Map State: IsViewable
'''
WINDOW = (24, 32, 1280, 720)
REQUEST = {'surface': [1280, 720], 'terminalBounds': [8, 150, 1264, 480], 'targetBounds': [480, 100, 320, 18]}


class PixelCoordinatesTests(unittest.TestCase):
    def test_visible_window_bounds_translate_to_original_framebuffer(self):
        self.assertEqual(window_geometry(XWININFO), ('0x200003', WINDOW))
        bounds, target = capture_geometry(REQUEST, WINDOW, (1920, 1080))
        self.assertEqual(bounds, [32, 182, 1264, 480])
        self.assertEqual(target, [504, 132, 320, 18])

    def test_hidden_window_or_nonmatching_or_clipped_surface_fails(self):
        with self.assertRaisesRegex(GuiFailure, 'window_not_viewable'):
            window_geometry(XWININFO.replace('IsViewable', 'IsUnMapped'))
        with self.assertRaisesRegex(GuiFailure, 'surface_mismatch'):
            capture_geometry(dict(REQUEST, surface=[1280, 750]), WINDOW, (1920, 1080))
        with self.assertRaisesRegex(GuiFailure, 'surface_mismatch'):
            capture_geometry(REQUEST, WINDOW, (1300, 750))
        with self.assertRaisesRegex(GuiFailure, 'bounds_invalid'):
            capture_geometry(dict(REQUEST, terminalBounds=[-1, 150, 1264, 480]), WINDOW, (1920, 1080))
        with self.assertRaisesRegex(GuiFailure, 'target_overlaps_terminal'):
            capture_geometry(dict(REQUEST, targetBounds=[480, 143, 320, 18]), WINDOW, (1920, 1080))

    @patch.dict('os.environ', {'DISPLAY': ':109'})
    @patch('flutter_linux_direct_ssh.verify_terminal_screenshot')
    @patch('flutter_linux_direct_ssh.ImageGrab.grab')
    @patch('flutter_linux_direct_ssh.native_window')
    def test_window_change_fails_before_ocr(self, geom, grab, verify):
        geom.side_effect = [('id', WINDOW), ('id', (25, *WINDOW[1:]))]
        grab.return_value = Image.new('RGB', (1920, 1080))
        with self.assertRaisesRegex(GuiFailure, 'window_changed'):
            capture(REQUEST, 'fixture-token')
        verify.assert_not_called()

    @patch.dict('os.environ', {'DISPLAY': ':109'})
    @patch('flutter_linux_direct_ssh.time.sleep')
    @patch('flutter_linux_direct_ssh.verify_terminal_screenshot')
    @patch('flutter_linux_direct_ssh.ImageGrab.grab')
    @patch('flutter_linux_direct_ssh.native_window')
    def test_ocr_wait_only_rereads_pixels_and_retains_the_full_frame(self, geom, grab, verify, _):
        geom.return_value = ('id', WINDOW)
        grab.side_effect = lambda **_: Image.new('RGB', (1920, 1080))
        verify.side_effect = [ScreenshotGateError('terminal_screenshot_token_not_visible'), {'verified': True}]
        png, evidence = capture(REQUEST, 'fixture-token')
        self.assertEqual(png, verify.call_args.args[0])
        self.assertEqual(verify.call_args.kwargs, {'expected_token': 'fixture-token', 'bounds': [32, 182, 1264, 480]})
        self.assertEqual(evidence['captureAttempt'], 2)
        self.assertEqual(grab.call_count, 2)
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))


class PrivateExchangeTests(unittest.TestCase):
    def test_bounded_atomically_published_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'probe.pending').write_text('{}')
            self.assertIsNone(read_exchange(root, 'probe'))
            (root / 'probe.pending').rename(root / 'probe.json')
            self.assertEqual(read_exchange(root, 'probe'), {})
            (root / 'probe.json').write_text(' ' * 1025)
            with self.assertRaisesRegex(GuiFailure, 'invalid_exchange'):
                read_exchange(root, 'probe')

    def test_key_negative_checkpoints_require_consumed_material_and_zero_new_connections(self):
        probe = {'id': 1, 'hostKey': 'A', 'closed': True, 'authAttempts': 0,
                 'authSuccesses': 0, 'ptyRequests': 0, 'shellRequests': 0,
                 'inputBytes': 0, 'outputBytes': 0}
        facts = {'connections': 1, 'connectionsClosed': True, 'connectionEvents': [probe]}
        fixture = Mock()
        fixture.snapshot.return_value = facts
        modes = {'passwordToKeyCleared': True, 'keyToPasswordCleared': True, 'sameTrust': True}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(key_rejection_evidence(fixture, root, 'mode-switch', modes),
                             dict(modes, connections=1, authenticationAttempts=0))
            rejected = {'rejectedLocally': True}
            self.assertEqual(key_rejection_evidence(fixture, root, 'wrong-passphrase', rejected),
                             dict(rejected, connections=1, authenticationAttempts=0))
            for unsafe in [{'rejectedLocally': 1}, {'rejectedLocally': False}, dict(rejected, extra=True)]:
                with self.assertRaisesRegex(GuiFailure, 'key_checkpoint_invalid'):
                    key_rejection_evidence(fixture, root, 'wrong-passphrase', unsafe)
            target = root / 'target.json'
            target.touch()
            with self.assertRaisesRegex(GuiFailure, 'key_material_not_consumed'):
                key_rejection_evidence(fixture, root, 'wrong-passphrase', rejected)
            target.unlink()
            fixture.snapshot.return_value = dict(facts, connections=2, connectionEvents=[probe, probe])
            with self.assertRaisesRegex(GuiFailure, 'connection_count_invalid'):
                key_rejection_evidence(fixture, root, 'wrong-passphrase', rejected)

    def test_rotated_session_requires_b_exactly_once_and_closes_before_exit(self):
        session = {'id': 4, 'hostKey': 'B', 'authAttempts': 1, 'authSuccesses': 1,
                   'ptyRequests': 1, 'shellRequests': 1, 'outputBytes': 102,
                   'handshakeCompleted': True, 'authAccepted': True, 'inputBytes': 9,
                   'markerReceived': True, 'singleMarkerLineExact': True,
                   'closed': True, 'sessionClosed': True, 'closeReason': 'peer_eof'}

        def check(expected, **changes):
            facts = {'connections': 4, 'connectionsClosed': True,
                     'connectionEvents': [{}, {}, {}, dict(session, **changes)]}
            if expected is None:
                rotation_session(facts, sent=True, closed=True)
            else:
                with self.assertRaisesRegex(GuiFailure, expected):
                    rotation_session(facts, sent=True, closed=True)

        check(None)
        check('signed_session_unproven', hostKey='A')
        check('signed_session_unproven', authAttempts=2)
        check('key_input_not_exact', inputBytes=18)
        check('key_input_not_exact', singleMarkerLineExact=False)
        check('close_order_invalid', closeReason='fixture_stopped')

    def test_only_the_existing_sdk_lock_extension_is_accepted(self):
        block = '    source: sdk\n    version: "0.0.0"\n'
        source = 'packages:\n  terminal_view:\n    version: "0.5.0"\n'
        after = source + ''.join(f'  {name}:\n{block}' for name in sorted(SDK_ADDITIONS))
        self.assertEqual(locked_dependencies(source, after), sorted(SDK_ADDITIONS))
        with self.assertRaisesRegex(GuiFailure, 'dependency_drift'):
            locked_dependencies(source, after.replace('0.5.0', '0.5.1'))
        with self.assertRaisesRegex(GuiFailure, 'not_sdk'):
            locked_dependencies(source, after.replace('source: sdk', 'source: hosted', 1))


if __name__ == '__main__':
    unittest.main()
