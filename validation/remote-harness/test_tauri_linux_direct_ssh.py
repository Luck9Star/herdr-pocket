"""Loopback and deterministic negative controls for the Linux Tauri lane."""
import base64
import importlib.util
import io
import sys
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if importlib.util.find_spec('paramiko') is None or importlib.util.find_spec('PIL') is None:
    raise unittest.SkipTest('ordinary SSH and screenshot test dependencies are missing')
import paramiko
from PIL import Image
from screen_proof_token import token_lines
from tauri_linux_direct_ssh import (
    DesktopDriver,
    DirectSshFixture,
    GuiFailure,
    ScreenshotGateError,
    capture_terminal,
    decode_viewport_capture,
    port_is_released,
    probe_evidence,
    session_evidence,
    wait_for,
)
from terminal_screenshot_gate import ECHO_MARKER


def real_peer_evidence():
    with DirectSshFixture(screen_proof=True, channel_deadline=time.monotonic() + 20) as fixture:
        with paramiko.Transport(('127.0.0.1', fixture.port)) as probe:
            probe.start_client(timeout=3)
            key = probe.get_remote_server_key()
            assert f'{key.get_name()} {key.get_base64()}' == fixture.public_key
        assert fixture.wait_for_connections_closed(1, timeout=4)
        initial = fixture.snapshot()
        with paramiko.Transport(('127.0.0.1', fixture.port)) as session:
            session.start_client(timeout=3)
            session.auth_password(fixture.username, fixture.password)
            with session.open_session(timeout=3) as channel:
                channel.settimeout(3)
                channel.get_pty()
                channel.invoke_shell()
                assert b'POCKET-ANDROID-READY' in channel.recv(1024)
                def shell_with_recorded_output():
                    facts = fixture.snapshot()
                    return facts if facts['connectionEvents'][1]['outputBytes'] > 0 else None

                no_input = wait_for(shell_with_recorded_output, 'test_fixture_shell_no_output', timeout=3)
                channel.sendall(b'hp-check\r')
                expected = (ECHO_MARKER, *token_lines(fixture.screen_token))
                rendered = b''
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not all(term.encode() in rendered for term in expected):
                    rendered += channel.recv(1024)
                assert all(term.encode() in rendered for term in expected)
                pre_close = fixture.snapshot()
        assert fixture.wait_for_connections_closed(2, timeout=4)
        post_close = fixture.snapshot()
    assert fixture.password == '' and port_is_released(fixture.port)
    return initial, no_input, pre_close, post_close


class PeerEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.initial, cls.no_input, cls.pre_close, cls.post_close = real_peer_evidence()

    def test_real_isolated_probe_password_pty_single_line_and_closed_peer(self):
        probe_evidence(self.initial, 1)
        session_evidence(self.no_input, sent=False, closed=False)
        session_evidence(self.pre_close, sent=True, closed=False)
        session_evidence(self.post_close, sent=True, closed=True)

    def test_probe_can_end_after_seeing_host_key_before_key_exchange_completes(self):
        discovery = deepcopy(self.initial)
        discovery['connectionEvents'][0]['handshakeCompleted'] = False
        probe_evidence(discovery, 1)

    def test_probe_with_authentication_or_injected_connection_is_refused(self):
        unexpected = deepcopy(self.initial)
        unexpected['connectionEvents'][0]['authAttempts'] = 1
        with self.assertRaisesRegex(GuiFailure, 'probe_not_empty'):
            probe_evidence(unexpected, 1)
        with self.assertRaisesRegex(GuiFailure, 'connection_count_invalid'):
            probe_evidence(self.pre_close, 1)

    def test_session_replay_missing_marker_and_premature_close_are_refused(self):
        for field, value, code in (('inputBytes', 18, 'unexpected_input'),
                                   ('markerReceived', False, 'unexpected_input'),
                                   ('authAttempts', 2, 'password_shell_unproven'),
                                   ('ptyRequests', 2, 'password_shell_unproven'),
                                   ('shellRequests', 2, 'password_shell_unproven'),
                                   ('closed', True, 'close_order_invalid')):
            with self.subTest(field=field):
                unexpected = deepcopy(self.pre_close)
                unexpected['connectionEvents'][1][field] = value
                with self.assertRaisesRegex(GuiFailure, code):
                    session_evidence(unexpected, sent=True, closed=False)
        mislabeled = deepcopy(self.post_close)
        mislabeled['connectionEvents'][1]['closeReason'] = 'fixture_stopped'
        with self.assertRaisesRegex(GuiFailure, 'close_order_invalid'):
            session_evidence(mislabeled, sent=True, closed=True)


class WebDriverTests(unittest.TestCase):
    def test_native_click_and_physical_keys_are_each_sent_once(self):
        driver = DesktopDriver()
        driver.session = '/session/fixture'
        driver.call = Mock(side_effect=[True, [{'element-6066-11e4-a52e-4f735466cecf': 'focus'}], None, None])
        driver.click('#ssh-focus')
        driver.send_test_line()
        calls = [call.args for call in driver.call.call_args_list]
        self.assertEqual(calls[2], ('POST', '/session/fixture/element/focus/click', {}))
        self.assertEqual(calls[3][:2], ('POST', '/session/fixture/actions'))
        keys = calls[3][2]['actions'][0]['actions']
        self.assertEqual(''.join(key['value'] for key in keys[::2]), 'hp-check\ue007')
        self.assertTrue(all(down['type'] == 'keyDown' and up == dict(down, type='keyUp')
                            for down, up in zip(keys[::2], keys[1::2])))
        self.assertEqual(len(calls), 4)


class ScreenshotBindingTests(unittest.TestCase):
    def setUp(self):
        buffer = io.BytesIO()
        Image.new('RGB', (400, 160)).save(buffer, 'PNG')
        self.png = buffer.getvalue()
        self.encoded = base64.b64encode(self.png).decode('ascii')
        self.driver = Mock(session='/session/fixture')
        self.driver.call.return_value = self.encoded
        self.geometry = {'viewport': [400, 160], 'bounds': [0, 0, 400, 150], 'endpointBounds': [0, 0, 90, 22]}

    def test_malformed_or_unregistered_image_fails_before_ocr(self):
        for encoded, size in (('%%%%', [400, 160]), (self.encoded, [800, 320]), ('', [400, 160])):
            with self.subTest(size=size), self.assertRaisesRegex(GuiFailure, 'viewport_png_invalid'):
                decode_viewport_capture(encoded, size)

    @patch('tauri_linux_direct_ssh.verify_terminal_screenshot')
    @patch('tauri_linux_direct_ssh.terminal_geometry')
    def test_target_or_geometry_change_during_capture_fails_before_ocr(self, geometry, verify):
        geometry.side_effect = [self.geometry, dict(self.geometry, bounds=[0, 0, 400, 149])]
        with self.assertRaisesRegex(GuiFailure, 'geometry_changed'):
            capture_terminal(self.driver, 'fixture@127.0.0.1:2222', 'public-screen-token')
        verify.assert_not_called()

    @patch('tauri_linux_direct_ssh.time.sleep')
    @patch('tauri_linux_direct_ssh.verify_terminal_screenshot')
    @patch('tauri_linux_direct_ssh.terminal_geometry')
    def test_missing_visual_proof_only_rechecks_original_pixels(self, geometry, verify, _):
        geometry.return_value = self.geometry
        verify.side_effect = [ScreenshotGateError('terminal_screenshot_echo_not_visible'), {'verified': True}]
        png, proof = capture_terminal(self.driver, 'fixture@127.0.0.1:2222', 'public-screen-token')
        self.assertEqual(png, self.png)
        self.assertEqual(proof['captureAttempt'], 2)
        self.assertEqual(verify.call_args.kwargs, {'expected_token': 'public-screen-token', 'bounds': [0, 0, 400, 150]})
        self.assertEqual([call.args for call in self.driver.call.call_args_list],
                         [('GET', '/session/fixture/screenshot'), ('GET', '/session/fixture/screenshot')])


if __name__ == '__main__':
    unittest.main()
