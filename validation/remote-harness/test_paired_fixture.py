"""No sshd, network or credentials: assert the CI authorization/evidence gate."""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

# Legacy read-only harness runs in a Python without pairing dependencies.
try:
    from paired_gui import FixtureApproval, GuiFailure, Host, WebDriver, open_host_summary, run_gui, stop_tauri_observation, widget_failure
    from pairing import MemoryKeyStore, PendingPairing, encode
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    FixtureApproval = None


@unittest.skipIf(FixtureApproval is None, 'pairing requirements are installed in the GUI workflow')
class GuiFixtureTests(unittest.TestCase):
    def test_stop_selects_visible_control_once_and_requires_stale_and_input_retirement(self):
        for selector in ('#remote-stop-dock', '#remote-stop-visible'):
            with self.subTest(selector=selector):
                driver = Mock(session='/session/test')
                driver.call.side_effect = [selector, True]
                driver.read.return_value = '观察已停止 · 画面陈旧'
                stop_tauri_observation(driver)
                driver.click.assert_called_once_with(selector)
                self.assertIn('remote-input-controls', driver.call.call_args.args[2]['script'])
        driver = Mock(session='/session/test')
        driver.call.return_value = '#unexpected'
        with self.assertRaisesRegex(GuiFailure, 'stop_control_invalid'):
            stop_tauri_observation(driver)
        driver.click.assert_not_called()

    def test_mobile_guarded_run_requires_an_independent_clipboard_receiver_check(self):
        first = dict(paneId='p', terminalId='term_ab', acceptedBytes=1, requestId='0' * 32)
        second = dict(first, acceptedBytes=9, requestId='1' * 32)
        args = SimpleNamespace(paired_gui='tauri-android', input_fixture=True)
        env = dict(GITHUB_ACTIONS='true', GITHUB_RUN_ID='38', GITHUB_REF='refs/heads/codex/test')
        target = dict(paneId='p', username='fixture', host='127.0.0.1', expectedHostKey='fixture')
        with tempfile.TemporaryDirectory(dir='/tmp', prefix='hp-mobile-38-') as directory:
            root = Path(directory)
            (root / 'authorized_keys').touch()
            with patch.dict(os.environ, env), patch('paired_gui.Host'), patch('paired_gui.FixtureApproval'), \
                    patch('paired_gui.fixture_terminal_id', return_value='term_ab'), \
                    patch('android_gui.run_android') as exercise:
                for field in (None, False, 1, True):
                    with self.subTest(checkpoint=field):
                        observed = dict(inputQueueAccepted=True, inputReceipts=[first, second])
                        if field is not None:
                            observed['pasteOperationsNoExtraSshBytes'] = field
                        exercise.return_value = observed
                        result = run_gui(args, root, env, target)
                        if field is True:
                            self.assertEqual(result['status'], 'passed')
                        else:
                            self.assertEqual(result['status'], 'failed')
                            self.assertEqual(result['errorCode'], 'mobile_clipboard_receiver_check_missing')

    def test_host_summary_requires_explicit_expansion_before_visible_read(self):
        driver = Mock()
        driver.attribute.side_effect = [None, None, 'true']
        open_host_summary(driver)
        driver.click.assert_called_once_with('#host-task-details > summary')
        self.assertEqual(driver.attribute.call_count, 3)
        driver.attribute.assert_called_with('#host-task-details', 'open')

    def test_host_summary_already_open_is_not_collapsed(self):
        driver = Mock()
        driver.attribute.return_value = 'true'
        open_host_summary(driver)
        driver.click.assert_not_called()
        driver.attribute.assert_called_once_with('#host-task-details', 'open')

    def test_read_relocates_only_stale_element_and_bounds_retries(self):
        driver = WebDriver()
        driver.element = Mock(side_effect=['/old', '/new'])
        driver.call = Mock(side_effect=[GuiFailure('webdriver_innerText_stale_element_reference'), 'ready'])
        self.assertEqual(driver.read('#summary'), 'ready')
        self.assertEqual(driver.call.call_args_list[1].args, ('GET', '/new/property/innerText'))
        driver.element = Mock(return_value='/node')
        driver.call = Mock(side_effect=GuiFailure('webdriver_innerText_stale_element_reference'))
        with self.assertRaises(GuiFailure): driver.read('#summary')
        self.assertEqual(driver.call.call_count, 5)
        driver.call = Mock(side_effect=GuiFailure('webdriver_innerText_invalid_session_id'))
        with self.assertRaises(GuiFailure): driver.read('#summary')
        self.assertEqual(driver.call.call_count, 1)

    def test_attribute_relocates_stale_but_click_is_not_replayed(self):
        driver = WebDriver()
        driver.element = Mock(side_effect=['/old', '/new'])
        driver.call = Mock(side_effect=[GuiFailure('webdriver_open_stale_element_reference'), 'true'])
        self.assertEqual(driver.attribute('#details', 'open'), 'true')
        driver.wait_control = Mock()
        driver.element = Mock(return_value='/button')
        driver.call = Mock(side_effect=GuiFailure('webdriver_click_stale_element_reference'))
        with self.assertRaises(GuiFailure): driver.click('#button')
        self.assertEqual(driver.call.call_count, 1)

    def test_driver_waits_for_the_native_form_before_sending_keys(self):
        driver = WebDriver()
        driver.session = '/session/test'
        driver.element = Mock(return_value='/field')
        driver.read = Mock(return_value='fixture')
        calls = []
        def command(method, path, data):
            calls.append(path)
            if path.endswith('/execute/sync'):
                self.assertIn("matches(':disabled')", data['script'])
                return len(calls) == 2
        driver.call = command
        driver.fill('#remote-host', 'fixture')
        self.assertEqual(calls, ['/session/test/execute/sync'] * 2 +
                         ['/field/clear', '/field/value'])

    def test_widget_failure_stage_only_emits_an_allowlisted_value(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'stage'
            path.write_text('public_request')
            self.assertEqual(str(widget_failure(path.parent, 'failed')), 'failed_public_request')
            path.write_text('unrecognized test metadata')
            self.assertEqual(str(widget_failure(path.parent, 'failed')), 'failed')

    def test_only_reviewed_key_authenticates_and_revokes(self):
        store = MemoryKeyStore()
        host_public = store.public(store.create())
        key = store.create()
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as scratch:
            host = Host(Path(scratch), 'runner', host_public)
            root = Path(folder)
            (root/'authorized_keys').write_bytes(b'')
            approval = FixtureApproval(root, {'username':'runner'}, host)
            pending = PendingPairing(store, key, account='runner', device='test phone',
                                     expected_host_key=host.pin, now=int(time.time()))
            wire = encode(pending.request)
            wrong = dict(pending.request, account='different')
            with self.assertRaisesRegex(GuiFailure, 'fixture_public_request_invalid'):
                approval.approve(encode(wrong))
            self.assertEqual((root/'authorized_keys').read_bytes(), b'')
            approval.approve(wire)
            self.assertIn(store.public(key).encode(), (root/'authorized_keys').read_bytes())
            (root/'sshd.log').write_text('Accepted publickey for runner from 127.0.0.1 port 2234 ssh2: ED25519 SHA256:wrong\n')
            with self.assertRaisesRegex(GuiFailure, 'fingerprint_not_authenticated'):
                approval.verify_ssh()
            (root/'sshd.log').write_text(f'Accepted publickey for runner from 127.0.0.1 port 2234 ssh2: ED25519 {approval.fingerprint}\n')
            (root/'capture-running').touch()
            (root/'received.bin').write_bytes(b'x')
            with self.assertRaisesRegex(GuiFailure, 'unexpected_remote_input'):
                approval.verify_ssh()
            (root/'received.bin').write_bytes(b'')
            approval.verify_ssh()
            receipt = approval.revoke()
            item = json.loads(receipt)
            self.assertEqual((item['status'], item['request_id'], item['host_key'], item['fingerprint']),
                             ('revoked', pending.request['request_id'], host.pin, approval.fingerprint))
            self.assertEqual(approval.revoke(), receipt)
            self.assertEqual((root/'authorized_keys').read_bytes(), b'')
