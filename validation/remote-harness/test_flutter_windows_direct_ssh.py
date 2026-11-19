import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from PIL import Image
import flutter_windows_direct_ssh as windows


class FlutterWindowsDirectSshTests(unittest.TestCase):
    def test_native_import_does_not_load_posix_pairing_modules(self):
        script = '''
import builtins
import sys
from types import SimpleNamespace

real_import = builtins.__import__
unavailable = {'fcntl', 'pwd', 'pty', 'termios', 'tty', 'grp'}

def import_windows(name, globals=None, locals=None, fromlist=(), level=0):
    if name.partition('.')[0] in unavailable:
        raise ModuleNotFoundError(f'No module named {name!r}', name=name)
    if name == 'sys' and globals and globals.get('__name__') == 'paired_gui':
        return SimpleNamespace(platform='win32', path=sys.path)
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = import_windows
import flutter_windows_direct_ssh as windows
import paired_gui

assert windows.wait_for is paired_gui.wait_for
assert not {'herdr_pocket_helper.store', 'blocked_fixture'} & sys.modules.keys()

def start_posix_process():
    with paired_gui.owned_process([], cwd=None, env=None, log=None):
        raise AssertionError('unexpected process')

for start in (lambda: paired_gui.FixtureApproval(None, None, None),
              lambda: paired_gui.run_gui(None, None, None, None),
              start_posix_process):
    try:
        start()
    except paired_gui.GuiFailure as error:
        assert str(error) == 'paired_gui_posix_required'
    else:
        raise AssertionError('POSIX pairing API ran on Windows')
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parent,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_owned_launcher_uses_base_python_and_releases_only_after_membership(self):
        gate = MagicMock()
        gate.__enter__.return_value = gate
        process = Mock(pid=42, stdin=gate)
        limits = {'BasicLimitInformation': {'LimitFlags': 0}}
        job_api = Mock(JobObjectExtendedLimitInformation=9, JobObjectBasicProcessIdList=3,
                       JobObjectBasicAccountingInformation=1, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=8192)
        def create_job(attributes, name):
            self.assertIsNone(attributes)
            self.assertRegex(name, r'^herdr-pocket-direct-[a-f0-9]{32}$')
            return Mock()
        job_api.CreateJobObject.side_effect = create_job
        native = Mock()
        job_api.QueryInformationJobObject.side_effect = [limits, (42,), {'ActiveProcesses': 0}, {'ActiveProcesses': 0}]
        # Track both sides of the gate in the same call sequence.
        native.attach_mock(job_api, 'job')
        native.attach_mock(gate.write, 'release')
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(windows, 'win32job', job_api, create=True), \
                patch.object(windows, 'win32api', Mock(), create=True), \
                patch.object(windows, 'win32con', SimpleNamespace(PROCESS_SET_QUOTA=256, PROCESS_TERMINATE=1),
                             create=True), \
                patch.object(windows.subprocess, 'Popen', return_value=process) as spawn:
            root = Path(directory)
            report = {}
            with windows.owned_job(['flutter.bat', 'test'], cwd=root, env={}, log=root / 'private.log',
                                   report=report) as (launched, job):
                self.assertIs(launched, process)
                self.assertEqual(report['checkpoint'], 'job_release_gate')
                self.assertEqual(spawn.call_args.args[0][:4], [sys._base_executable, '-I', '-S', '-c'])
                membership = job_api.QueryInformationJobObject.call_args_list[1]
                self.assertEqual(membership.args, (job, 3))
                operations = [call[0] for call in native.mock_calls]
                self.assertEqual(operations[:6], ['job.CreateJobObject', 'job.QueryInformationJobObject',
                                                 'job.SetInformationJobObject', 'job.AssignProcessToJobObject',
                                                 'job.QueryInformationJobObject', 'release'])
                gate.write.assert_called_once_with(b'run')
                self.assertEqual(limits['BasicLimitInformation']['LimitFlags'], 8192)
            job.Close.assert_called_once_with()

    def test_assignment_failure_keeps_gate_closed_and_preserves_sanitized_cleanup_diagnostic(self):
        gate = MagicMock()
        gate.__enter__.return_value = gate
        process = Mock(pid=42, stdin=gate)
        process.poll.return_value = None
        error = PermissionError('private fixture path and command')
        error.winerror = 5
        job_api = Mock(JobObjectExtendedLimitInformation=9, JobObjectBasicAccountingInformation=1,
                       JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=8192)
        job_api.AssignProcessToJobObject.side_effect = error
        job_api.QueryInformationJobObject.side_effect = [{'BasicLimitInformation': {'LimitFlags': 0}},
                                                         ValueError('private cleanup detail')]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(windows, 'win32job', job_api, create=True), \
                patch.object(windows, 'win32api', Mock(), create=True), \
                patch.object(windows, 'win32con', SimpleNamespace(PROCESS_SET_QUOTA=256, PROCESS_TERMINATE=1),
                             create=True), patch.object(windows.subprocess, 'Popen', return_value=process):
            root = Path(directory)
            report = {}
            with self.assertRaises(PermissionError) as observed:
                with windows.owned_job(['flutter.bat', 'test'], cwd=root, env={}, log=root / 'private.log',
                                       report=report):
                    self.fail('unassigned launcher must not run')
            self.assertIs(observed.exception, error)
            self.assertEqual(report, {'checkpoint': 'job_assign_process',
                                      'jobCleanupFailure': {'exceptionClass': 'ValueError'}})
            self.assertEqual(windows.runner_failure(error), {'exceptionClass': 'PermissionError', 'winError': 5})
            gate.write.assert_not_called()
            process.kill.assert_called_once_with()
            job_api.CreateJobObject.return_value.Close.assert_called_once_with()

    def test_failure_details_exclude_native_function_and_message(self):
        class TestWinError(Exception):
            def __init__(self, code, function, message):
                super().__init__(code, function, message)
                self.winerror = code

        native_error = windows.pywintypes.error if sys.platform == 'win32' else TestWinError
        with patch.object(windows, 'pywintypes', SimpleNamespace(error=native_error), create=True), \
                patch.object(windows.sys, 'platform', 'win32'):
            self.assertEqual(windows.runner_failure(native_error(87, 'private function', 'secret message')),
                             {'exceptionClass': 'PyWinTypesError', 'winError': 87})
            self.assertEqual(windows.runner_failure(native_error(90210, 'private function', 'secret message')),
                             {'exceptionClass': 'PyWinTypesError'})
            self.assertEqual(windows.runner_failure(RuntimeError('private command')), {'exceptionClass': 'OtherError'})

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
            process = Mock(poll=Mock(return_value=None))
            with self.assertRaisesRegex(windows.GuiFailure, 'unowned_application'):
                windows.exchange(process, object(), root, fixture, {}, {})
            find.assert_not_called()
            job.QueryInformationJobObject.return_value = (2, 42)
            report = {}
            with self.assertRaisesRegex(windows.GuiFailure, 'unexpected_input'):
                windows.exchange(process, object(), root, fixture, report, {})
            self.assertEqual(report['checkpoint'], 'capture')
            self.assertTrue((root / 'probe.ok').exists() and (root / 'connected.ok').exists())
            self.assertFalse((root / 'capture.ok').exists())
            capture.assert_not_called()

    def test_completion_requires_live_launcher_and_attributes_the_publish_exit_race(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = root / 'complete.json'
            report = {}
            process = Mock(poll=Mock(return_value=1))
            with self.assertRaisesRegex(windows.GuiFailure, 'application_ended_early'):
                windows.request(process, root, 'complete', report)
            self.assertEqual(report, dict(launcherExit='failure', checkpointPublishedAtExit=False))

            def publish_on_exit_check():
                completed.write_text('{}', encoding='utf-8')
                return 0

            process.poll.side_effect = publish_on_exit_check
            with self.assertRaisesRegex(windows.GuiFailure, 'application_ended_early'):
                windows.request(process, root, 'complete', report)
            self.assertEqual(report, dict(launcherExit='success', checkpointPublishedAtExit=True))
            self.assertFalse((root / 'complete.ok').exists())
            process.poll.side_effect = None
            process.poll.return_value = None
            self.assertEqual(windows.request(process, root, 'complete', {}), {})

    def test_return_stage_reports_only_allowlisted_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for phase, public in [('return_home_notice', 'return_home_notice'),
                                  ('return_home_publish', 'return_home_publish'),
                                  ('disconnect', 'disconnect'), ('private exception', None), ([], None)]:
                (root / 'stage.json').write_text(json.dumps({'phase': phase}), encoding='utf-8')
                self.assertEqual(windows.read_ui_stage(root), public)

    def test_framework_error_preserves_only_bounded_timing_geometry_and_source(self):
        before = {'phase': 'form', 'returnTapStarted': False, 'kind': 'FlutterError', 'library': 'rendering',
                  'viewportPx': [1024, 705], 'dprMilli': 1000, 'overflow': {'pixels': 12.5, 'side': 'bottom'},
                  'frame': {'source': 'direct_ssh_page', 'line': 699},
                  'creator': 'Column', 'renderSize': [200, 21], 'anchor': 'direct-form'}
        after = dict(before, phase='return_home_tap', returnTapStarted=True,
                     frame={'source': 'host_catalog_page', 'line': 581}, anchor='home-ssh-closed')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(windows.read_framework_error(root))
            for value in (before, after, dict(before, **{'overflow': {'pixels': 0, 'side': 'left'}})):
                (root / 'framework-error.json').write_text(json.dumps(value), encoding='utf-8')
                self.assertEqual(windows.read_framework_error(root), value)
            for private in (dict(before, message='private'), dict(before, phase='private'),
                            dict(before, kind='private'), dict(before, library=['private']),
                            dict(before, viewportPx=[1024, True]), dict(before, dprMilli=8001),
                            dict(before, frame={'source': 'C:/private', 'line': 9}),
                            dict(before, overflow={'pixels': float('nan'), 'side': 'left'}),
                            dict(before, anchor='private'), dict(before, creator='private')):
                (root / 'framework-error.json').write_text(json.dumps(private), encoding='utf-8')
                with self.assertRaisesRegex(windows.GuiFailure, '^windows_direct_framework_record_invalid$'):
                    windows.read_framework_error(root)

    def test_failure_retains_terminal_and_disconnect_crops_with_original_pixel_mapping(self):
        data = io.BytesIO()
        full = Image.new('RGB', (20, 20), 'red')
        full.paste('blue', (8, 8, 12, 12))
        full.save(data, format='PNG')
        png = data.getvalue()
        digest = hashlib.sha256(png).hexdigest()
        evidence = {'imageSize': [20, 20], 'imageSha256': digest}
        report = {'status': 'failed',
                  'terminal': {**evidence, 'terminalBounds': [8, 8, 4, 4]},
                  'disconnectOutcome': {**evidence, 'outcomeBounds': [9, 9, 2, 2]}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = {f'ordinary-{name}.png': png for name in ('terminal', 'disconnect', 'home')}
            windows.save_partial_crops(root, frames, report)
            self.assertEqual({path.name for path in root.iterdir()},
                             {'partial-terminal-crop.png', 'partial-disconnect-crop.png'})
            for item in report['partialFrames'].values():
                path = root / item['file']
                self.assertEqual(item['imageSha256'], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(item['sourceImageSha256'], digest)
                x, y, width, height = item['sourceBounds']
                with Image.open(path) as crop:
                    self.assertEqual(crop.tobytes(), full.crop((x, y, x + width, y + height)).tobytes())
            self.assertEqual(report['status'], 'failed')
            self.assertNotIn('returnedHome', report)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report['terminal']['imageSha256'] = '0' * 64
            with self.assertRaisesRegex(windows.GuiFailure, 'partial_source_mismatch'):
                windows.save_partial_crops(root, frames, report)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
