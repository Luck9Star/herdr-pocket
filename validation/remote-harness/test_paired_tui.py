"""Owned local PTY and safe attestation tests; no SSH host or user keys."""
import json
from types import SimpleNamespace
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from guarded_input import DIRECT, DRAFT, TUI_KEY_LENGTHS, TUI_SCREEN_CHECKS
import paired_tui

if os.name == 'posix':
    import termios
    from owned_pty import new_pty, restored_modes
    from phone_tui_probe import production_bytes
    try:
        from paired_gui import FixtureApproval, GuiFailure, run_gui
    except ModuleNotFoundError as missing:
        if missing.name != 'cryptography':
            raise
        FixtureApproval = None
else:
    FixtureApproval = None

HERE = Path(__file__).resolve().parent


def wait(probe, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = probe()
        if value: return value
        time.sleep(.02)
    raise AssertionError('fixture_timeout')


class PairedTuiTests(unittest.TestCase):
    def test_report_requires_exact_types_and_order_and_redacts_extra_fields(self):
        good = paired_tui.EXPECTED
        self.assertEqual(paired_tui.validate_report(json.dumps(good)),
                         {'applicationStateMatched': True, 'actionCount': 10})
        for changed in (dict(good, refreshes=True), dict(good, helpOpen=0),
                        dict(good, actions=list(reversed(good['actions']))),
                        dict(good, private='never publish'), dict(good, status='timeout')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                paired_tui.validate_report(json.dumps(changed))


@unittest.skipIf(FixtureApproval is None, 'requires POSIX and the paired GUI dependencies')
class HostTuiTests(unittest.TestCase):
    def test_start_validates_original_identity_and_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as td:
            approval = FixtureApproval(Path(td), {}, None)
            with patch('paired_gui.fixture_terminal_id', return_value='term_a'), \
                    patch.object(approval, 'verify_ssh') as ssh, \
                    patch('paired_gui.wait_for', side_effect=GuiFailure('paired_tui_start_timeout')):
                with self.assertRaisesRegex(GuiFailure, 'paired_tui_start_timeout'):
                    approval.start_tui(terminal_id='term_a')
                ssh.assert_called_once_with(DIRECT + DRAFT)
                with self.assertRaisesRegex(GuiFailure, 'paired_tui_already_started'):
                    approval.start_tui(terminal_id='term_a')
                self.assertEqual((Path(td)/'start-tui').read_bytes(), b'start\n')

    def test_host_attestation_rechecks_original_target_bytes_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            approval = FixtureApproval(root, {}, None)
            approval.tui_started = True; approval.tui_terminal_id = 'term_a'
            (root/'tui-complete').write_text('complete\n')
            (root/'tui-result.json').write_text(json.dumps(paired_tui.EXPECTED))
            with patch('paired_gui.fixture_terminal_id', return_value='term_a'), patch.object(approval, 'verify_ssh') as ssh:
                evidence = approval.verify_tui(terminal_id='term_a')
                ssh.assert_called_once_with(DIRECT + DRAFT)
                self.assertEqual(evidence, {'sameTarget': True, 'initialInputMatched': True,
                    'finalInputMatched': True, 'terminalModesRestored': True,
                    'postFinishKernelInputAbsent': True, 'applicationStateMatched': True, 'actionCount': 10})
                with self.assertRaisesRegex(GuiFailure, 'paired_tui_state_invalid'):
                    approval.verify_tui(terminal_id='term_a')
            changed = FixtureApproval(root, {}, None)
            changed.tui_started = True; changed.tui_terminal_id = 'term_a'
            with patch('paired_gui.fixture_terminal_id', return_value='term_b'), patch.object(changed, 'verify_ssh') as ssh:
                with self.assertRaisesRegex(GuiFailure, 'paired_tui_target_changed'):
                    changed.verify_tui(terminal_id='term_a')
                ssh.assert_not_called()

    def test_start_rejects_wrong_original_bytes_or_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); approval = FixtureApproval(root, {}, None)
            with patch('paired_gui.fixture_terminal_id', return_value='term_other'), patch.object(approval, 'verify_ssh') as ssh:
                with self.assertRaisesRegex(GuiFailure, 'paired_tui_target_changed'):
                    approval.start_tui(terminal_id='term_a')
                ssh.assert_not_called()
                self.assertFalse((root/'start-tui').exists())
            approval = FixtureApproval(root, {}, None)
            with patch('paired_gui.fixture_terminal_id', return_value='term_a'), \
                    patch.object(approval, 'verify_ssh', side_effect=GuiFailure('unexpected_remote_input')):
                with self.assertRaisesRegex(GuiFailure, 'unexpected_remote_input'):
                    approval.start_tui(terminal_id='term_a')
                self.assertFalse((root/'start-tui').exists())

    def test_run_gui_accepts_host_attestation_only_before_revoke(self):
        from copy import deepcopy
        env = dict(GITHUB_ACTIONS='true', GITHUB_RUN_ID='38', GITHUB_REF='refs/heads/codex/test')
        target = dict(paneId='p', username='fixture', host='127.0.0.1', expectedHostKey='fixture')
        args = SimpleNamespace(paired_gui='tauri-android', input_fixture=True, android_tui=True)
        receipt = lambda n, size: {'paneId':'p', 'terminalId':'term_ab', 'acceptedBytes':size, 'requestId':f'{n:032x}'}
        prior = [receipt(1, 1), receipt(2, 9)]
        raw = {'observedInitialFull':True, 'screenChecks':list(TUI_SCREEN_CHECKS),
               'receipts':[receipt(i + 3, size) for i, size in enumerate(TUI_KEY_LENGTHS)]}
        host = {'sameTarget':True, 'actionCount':10}
        with tempfile.TemporaryDirectory(dir='/tmp', prefix='hp-mobile-38-') as td:
            root = Path(td); (root/'authorized_keys').touch()
            approval = Mock(); approval.applied = True; revoked = []
            approval.fingerprint_authenticated.return_value = True
            approval.revoke.side_effect = lambda: revoked.append(True)
            approval.verify_tui.side_effect = lambda *, terminal_id: host if terminal_id == 'term_ab' and not revoked else None
            with patch.dict(os.environ, env), patch('paired_gui.Host'), \
                    patch('paired_gui.FixtureApproval', return_value=approval), \
                    patch('paired_gui.fixture_terminal_id', return_value='term_ab'), \
                    patch('android_gui.run_android') as exercise:
                exercise.return_value = {'inputQueueAccepted':True, 'inputReceipts':prior,
                    'pasteOperationsNoExtraSshBytes':True, 'tui':deepcopy(raw), 'hostTui':{'forged':True}}
                result = run_gui(args, root, env, target)
                self.assertEqual(result['status'], 'passed')
                self.assertEqual(result['hostTui'], host)
                self.assertTrue(result['matchedDeviceKeyInSshd'])
                self.assertEqual(len(result['tui']['receipts']), 10)
                approval.verify_tui.assert_called_once_with(terminal_id='term_ab')
                self.assertEqual(revoked, [True])
                self.assertEqual(approval.verify_ssh.call_args.args, (DIRECT + DRAFT,))
                revoked.clear(); approval.verify_tui.reset_mock()
                invalid = deepcopy(raw); invalid['private'] = 'must not appear'
                exercise.return_value = {'inputQueueAccepted':True, 'inputReceipts':prior,
                    'pasteOperationsNoExtraSshBytes':True, 'tui':invalid, 'hostTui':{'forged':True}}
                rejected = run_gui(args, root, env, target)
                self.assertEqual(rejected['status'], 'failed')
                self.assertNotIn('tui', rejected); self.assertNotIn('hostTui', rejected)
                self.assertNotIn('must not appear', json.dumps(rejected))
                approval.verify_tui.assert_not_called()

                # Keep independent PTY evidence even when a later phone action
                # failed. The browser cannot substitute its own host result.
                revoked.clear()
                (root/'tui-complete').write_text('complete\n')
                approval.tui_started = True
                approval.tui_verified = False
                exercise.side_effect = GuiFailure('later_phone_step_failed')
                partial = run_gui(args, root, env, target)
                self.assertEqual(partial['status'], 'failed')
                self.assertEqual(partial['errorCode'], 'later_phone_step_failed')
                self.assertEqual(partial['hostTui'], host)
                self.assertNotIn('tui', partial)
                self.assertTrue(revoked)


@unittest.skipUnless(os.name == 'posix', 'requires an owned POSIX PTY')
class OwnedTuiTests(unittest.TestCase):
    def test_stop_during_tui_returns_terminal_and_never_restarts(self):
        with tempfile.TemporaryDirectory(prefix='hp-owned-paired-tui-stop-') as folder:
            root = Path(folder)
            for name in ('capture_input.py', 'phone_tui_fixture.py'):
                shutil.copy2(HERE / name, root / name)
            (root/'terminal-fixture.json').write_text(json.dumps({'frames':[{'data':'synthetic'}]}))
            with new_pty() as (master, slave):
                original_tty = termios.tcgetattr(slave)
                proc = subprocess.Popen([sys.executable, str(root/'capture_input.py')], cwd=root,
                    env={'TERM':'xterm-256color', 'LC_ALL':'C', 'PATH':os.defpath},
                    stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
                try:
                    wait(lambda: (root/'capture-ready').exists())
                    os.write(master, DIRECT + DRAFT)
                    wait(lambda: (root/'received.bin').read_bytes() == DIRECT + DRAFT)
                    (root/'start-tui').write_bytes(b'start\n')
                    def ready():
                        while select.select([master], [], [], 0)[0]:
                            os.read(master, 8192)
                        return (root/'tui-ready').exists()
                    wait(ready)
                    (root/'stop-capture').write_text('stop')
                    def stopped():
                        while select.select([master], [], [], 0)[0]:
                            try: os.read(master, 8192)
                            except OSError: break
                        return proc.poll() is not None
                    wait(stopped, timeout=5)
                    self.assertEqual(restored_modes(termios.tcgetattr(slave)), restored_modes(original_tty))
                    report = json.loads((root/'tui-result.json').read_text())
                    self.assertEqual(report['status'], 'cancelled')
                    self.assertEqual(report['actions'], [])
                    self.assertEqual((root/'received.bin').read_bytes(), DIRECT + DRAFT)
                    self.assertFalse((root/'capture-running').exists())
                    self.assertEqual(os.get_terminal_size(slave), (80, 24))
                    self.assertEqual(json.loads((root/'pty-size.json').read_text())['changes'], 0)
                    with self.assertRaises(ValueError): paired_tui.validate_report(json.dumps(report))
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        try: proc.wait(timeout=3)
                        except subprocess.TimeoutExpired: proc.kill(); proc.wait()

    @unittest.skipUnless(shutil.which('node'), 'existing Node runtime needed for production codec')
    def test_owned_pty_same_capture_then_tui_restores_and_keeps_initial_log(self):
        with tempfile.TemporaryDirectory(prefix='hp-owned-paired-tui-') as folder:
            root = Path(folder)
            for name in ('capture_input.py', 'phone_tui_fixture.py'):
                shutil.copy2(HERE / name, root / name)
            (root/'terminal-fixture.json').write_text(json.dumps({'frames':[{'data':'synthetic'}]}))
            with new_pty() as (master, slave):
                proc = subprocess.Popen([sys.executable, str(root/'capture_input.py')], cwd=root,
                    env={'TERM':'xterm-256color', 'LC_ALL':'C', 'PATH':os.defpath},
                    stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
                screen = bytearray()
                def drain():
                    while select.select([master], [], [], 0)[0]:
                        try: data = os.read(master, 8192)
                        except OSError: break
                        if not data: break
                        screen.extend(data)
                    return True
                try:
                    wait(lambda: (root/'capture-ready').exists())
                    os.write(master, DIRECT + DRAFT)
                    wait(lambda: (root/'received.bin').read_bytes() == DIRECT + DRAFT)
                    (root/'start-tui').write_bytes(b'start\n')
                    wait(lambda: drain() and (root/'tui-ready').exists())
                    self.assertIn(b'Pocket TUI', screen)
                    for encoded in production_bytes('tauri', shutil.which('node'), True):
                        os.write(master, encoded); time.sleep(.09); drain()
                    wait(lambda: drain() and ((root/'tui-complete').exists() or proc.poll() is not None))
                    self.assertTrue((root/'tui-complete').exists(), f'fixture exited {proc.poll()}')
                    self.assertEqual(paired_tui.validate_report((root/'tui-result.json').read_bytes())['actionCount'], 10)
                    self.assertEqual((root/'received.bin').read_bytes(), DIRECT + DRAFT)
                    self.assertEqual(os.get_terminal_size(slave), (80, 24))
                    (root/'stop-capture').write_text('stop')
                    proc.wait(timeout=5)
                    size = json.loads((root/'pty-size.json').read_text())
                    self.assertEqual((proc.returncode, size['state'], size['changes'], size['readErrors']), (0, 2, 0, 0))
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        try: proc.wait(timeout=3)
                        except subprocess.TimeoutExpired: proc.kill(); proc.wait()


if __name__ == '__main__': unittest.main()
