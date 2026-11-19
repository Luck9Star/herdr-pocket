import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import flutter_windows_direct_ssh as windows


class FlutterWindowsDirectSshTests(unittest.TestCase):
    def test_session_zero_fails_before_opening_a_desktop(self):
        sessions = SimpleNamespace(ProcessIdToSessionId=Mock(return_value=0))
        service = Mock()
        with patch.object(windows, 'win32ts', sessions, create=True), \
                patch.object(windows, 'win32service', service, create=True), \
                patch.object(windows, 'pywintypes', SimpleNamespace(error=OSError), create=True):
            with self.assertRaisesRegex(windows.GuiFailure, 'desktop_unavailable'):
                windows.check_desktop()
        service.GetProcessWindowStation.assert_not_called()

    def test_disconnected_session_fails_before_opening_a_desktop(self):
        sessions = SimpleNamespace(ProcessIdToSessionId=Mock(return_value=3),
                                   WTSQuerySessionInformation=Mock(return_value=4), WTSActive=0,
                                   WTS_CURRENT_SERVER_HANDLE=0, WTSConnectState=8)
        service = Mock()
        with patch.object(windows, 'win32ts', sessions, create=True), \
                patch.object(windows, 'win32service', service, create=True), \
                patch.object(windows, 'pywintypes', SimpleNamespace(error=OSError), create=True):
            with self.assertRaisesRegex(windows.GuiFailure, 'desktop_unavailable'):
                windows.check_desktop()
        service.GetProcessWindowStation.assert_not_called()

    def test_illegal_terminal_bounds(self):
        for invalid in ([False, 5, 300, 160], [-1, 0, 300, 160], [0, 0, 299, 160],
                        [0, 0, 300, 159], [801, 0, 300, 160], [0, 550, 300, 160]):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(windows.GuiFailure, 'geometry_invalid'):
                windows.evidence_rect(invalid, [1100, 700], minimum=(300, 160))

    @patch.object(windows, 'framebuffer', return_value=(22, (-20, 10, 1004, 710)))
    @patch.object(windows.ImageGrab, 'grab', return_value=Image.new('RGB', (1024, 700)))
    def test_screenshot_uses_surface_pixel_origin_and_not_a_window_copy(self, image_grab, framebuffer):
        frame = {'surface': [1024, 700], 'terminalBounds': [0, 30, 400, 500], 'targetBounds': [32, 5, 100, 18]}
        native = Mock(WindowFromPoint=Mock(return_value=22))
        with patch.object(windows, 'win32gui', native, create=True):
            png, evidence = windows.grab(10, 42, frame, terminal=True)
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(evidence['terminalBounds'], [0, 30, 400, 500])
        image_grab.assert_called_once_with(bbox=(-20, 10, 1004, 710), include_layered_windows=True, all_screens=True)
        self.assertEqual(framebuffer.call_count, 2)
        native.WindowFromPoint.assert_any_call((-20, 40))

    @patch.object(windows, 'framebuffer', return_value=(22, (0, 0, 1024, 700)))
    @patch.object(windows.ImageGrab, 'grab')
    def test_surface_mismatch_and_occlusion_fail_before_capture(self, image_grab, _):
        native = Mock(WindowFromPoint=Mock(return_value=23))
        frame = {'surface': [1023, 700], 'outcomeBounds': [0, 0, 200, 200]}
        with patch.object(windows, 'win32gui', native, create=True):
            with self.assertRaisesRegex(windows.GuiFailure, 'surface_mismatch'):
                windows.grab(10, 42, frame, terminal=False)
            frame['surface'] = [1024, 700]
            with self.assertRaisesRegex(windows.GuiFailure, 'window_occluded'):
                windows.grab(10, 42, frame, terminal=False)
        image_grab.assert_not_called()

    @patch.object(windows.ImageGrab, 'grab', return_value=Image.new('RGB', (1024, 700)))
    def test_handle_or_geometry_change_and_blank_outcome_fail(self, _):
        native = Mock(WindowFromPoint=Mock(return_value=22))
        frame = {'surface': [1024, 700], 'outcomeBounds': [0, 0, 200, 200]}
        before = (22, (0, 0, 1024, 700))
        with patch.object(windows, 'win32gui', native, create=True):
            with patch.object(windows, 'framebuffer', side_effect=[before, (23, before[1])]):
                with self.assertRaisesRegex(windows.GuiFailure, 'window_changed_during_capture'):
                    windows.grab(10, 42, frame, terminal=False)
            with patch.object(windows, 'framebuffer', return_value=before):
                with self.assertRaisesRegex(windows.GuiFailure, 'outcome_frame_blank'):
                    windows.grab(10, 42, frame, terminal=False)

    def test_terminal_capture_retries_pixels_with_same_server_token(self):
        geometry = {'terminalBounds': [0, 20, 400, 300]}
        pending = windows.ScreenshotGateError('terminal_screenshot_token_not_visible')
        with patch.object(windows, 'grab', side_effect=[(b'old', geometry), (b'fresh', geometry)]) as grab, \
                patch.object(windows, 'verify_terminal_screenshot',
                             side_effect=[pending, {'proofSequenceVisible': True}]) as ocr, \
                patch.object(windows.time, 'sleep'):
            png, evidence = windows.terminal_capture(10, 42, {}, 'fixture-token')
        self.assertEqual((grab.call_count, png, evidence['captureAttempts']), (2, b'fresh', 2))
        self.assertTrue(evidence['proofSequenceVisible'])
        ocr.assert_called_with(b'fresh', expected_token='fixture-token', bounds=geometry['terminalBounds'])

    def test_exchange_rejects_unowned_window_and_replayed_input(self):
        probe = dict(id=1, hostKey='A', closed=True, authAttempts=0, authSuccesses=0,
                     ptyRequests=0, shellRequests=0, inputBytes=0, outputBytes=0)
        session = dict(probe, id=2, closed=False, handshakeCompleted=True, authAccepted=True, authAttempts=1,
                       authSuccesses=1, ptyRequests=1, shellRequests=1, outputBytes=30,
                       sessionClosed=False, markerReceived=False)
        facts = [{'connections': 1, 'connectionsClosed': True, 'connectionEvents': [probe]},
                 {'connections': 2, 'connectionsClosed': False, 'connectionEvents': [probe, session]},
                 {'connections': 2, 'connectionsClosed': False,
                  'connectionEvents': [probe, dict(session, markerReceived=True, inputBytes=18)]}]
        job = SimpleNamespace(QueryInformationJobObject=Mock(return_value=(2,)), JobObjectBasicProcessIdList=3)
        fixture = Mock(snapshot=Mock(side_effect=facts))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(windows, 'win32job', job, create=True), \
                patch.object(windows, 'win32gui', Mock(), create=True), \
                patch.object(windows, 'win32con', Mock(), create=True), \
                patch.object(windows, 'find_window', return_value=10) as find, \
                patch.object(windows, 'framebuffer'), patch.object(windows, 'terminal_capture') as capture:
            root = Path(directory)
            for name, value in {'window': {'processId': 42}, 'probe': {'algorithm': 'ssh-rsa'},
                                'connected': {}, 'capture': {}}.items():
                (root / f'{name}.json').write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaisesRegex(windows.GuiFailure, 'unowned_application'):
                windows.exchange(Mock(), object(), root, fixture, {})
            find.assert_not_called()
            job.QueryInformationJobObject.return_value = (2, 42)
            report = {}
            with self.assertRaisesRegex(windows.GuiFailure, 'unexpected_input'):
                windows.exchange(Mock(), object(), root, fixture, report)
            self.assertEqual(report['checkpoint'], 'capture')
            self.assertTrue((root / 'probe.ok').exists() and (root / 'connected.ok').exists())
            self.assertFalse((root / 'capture.ok').exists())
            capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
