"""Isolated checks of Android driver's receipt and direct-key boundary."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

HARNESS = Path(__file__).resolve().parents[2] / 'remote-harness'
sys.path.insert(0, str(HARNESS))
spec = importlib.util.spec_from_file_location('android_gui', HARNESS / 'android_gui.py')
android = importlib.util.module_from_spec(spec)
stub = types.ModuleType('paired_gui')
stub.GuiFailure = type('GuiFailure', (Exception,), {})
stub.wait_for = lambda predicate, label, **_: predicate() or (_ for _ in ()).throw(stub.GuiFailure(label))
previous = sys.modules.get('paired_gui')
sys.modules['paired_gui'] = stub
try:
    spec.loader.exec_module(android)
finally:
    if previous is None:
        del sys.modules['paired_gui']
    else:
        sys.modules['paired_gui'] = previous


class AndroidInputDriverTest(unittest.TestCase):
    def test_copy_seeds_only_fixed_synthetic_text_with_real_copy_user_gesture(self):
        view = object.__new__(android.AndroidWebView)
        view.fill = Mock()
        view.evaluate = Mock(return_value=True)
        view.copy_synthetic_clipboard()
        view.fill.assert_called_once_with('#remote-input-draft', '测')
        expression = view.evaluate.call_args.args[0]
        self.assertIn("document.execCommand('copy')", expression)
        self.assertNotIn('readText', expression)
        self.assertNotIn('getData', expression)
        self.assertEqual(view.evaluate.call_args.kwargs, {'user_gesture': True})
        view.evaluate.return_value = False
        with self.assertRaisesRegex(android.GuiFailure, 'android_synthetic_clipboard_copy_failed'):
            view.copy_synthetic_clipboard()

    def test_evaluate_forwards_explicit_user_gesture_and_fails_closed(self):
        view = object.__new__(android.AndroidWebView)
        view.call = Mock(return_value={'result': {'value': True}})
        self.assertIs(view.evaluate('copy-fixture', user_gesture=True), True)
        view.call.assert_called_once_with('Runtime.evaluate', {
            'expression': 'copy-fixture', 'returnByValue': True, 'userGesture': True})
        view.call.return_value = {'exceptionDetails': {'text': 'private'}}
        with self.assertRaisesRegex(android.GuiFailure, '^android_control_operation_failed$'):
            view.evaluate('copy-fixture')

    def test_input_requires_both_explicit_opt_in_and_fixture(self):
        for flag, fixture in ((True, None), (False, 'fixture')):
            args = types.SimpleNamespace(android_guarded_input=flag, input_fixture=fixture)
            with self.assertRaisesRegex(android.GuiFailure, 'android_guarded_input_fixture_mismatch'):
                android.run_android(args, None, None, None, None)

    def test_key_uses_focused_xterm_without_enter(self):
        view = object.__new__(android.AndroidWebView)
        view.evaluate = lambda _: True
        calls = []
        view.call = lambda method, params: calls.append((method, params))
        view.direct_key('k')
        self.assertEqual([item[1]['type'] for item in calls], ['keyDown', 'keyUp'])
        self.assertEqual(calls[0][1]['text'], 'k')
        with self.assertRaises(android.GuiFailure):
            view.direct_key('Enter')
        calls.clear()
        view.hidden_key_probe()
        self.assertEqual([item[1]['type'] for item in calls], ['keyDown', 'keyUp'])
        self.assertEqual(calls[0][1]['text'], 'z')

    def test_receipt_is_parsed_and_checked(self):
        view = object.__new__(android.AndroidWebView)
        receipt = {'requestId': 'a' * 32, 'paneId': 'p', 'terminalId': 't', 'acceptedBytes': 9}
        view.evaluate = lambda _: json.dumps(receipt)
        _, actual = view.receipt(None, 'p', 9)
        self.assertEqual(actual, receipt)
        receipt['acceptedBytes'] = True
        with self.assertRaises(android.GuiFailure):
            view.receipt(None, 'p', 1)


class AndroidPasteDriverTest(unittest.TestCase):
    class View:
        def __init__(self, bad=None):
            self.bad = bad
            self.draft = ''
            self.review = False
            self.events = []
            self.reads = 0
            self.draft_focused = True

        def copy_synthetic_clipboard(self):
            self.events.append('synthetic-copy')
            self.draft = '测'

        def fill(self, selector, value):
            self.events.append(('fill', value))
            self.draft = value

        def click(self, selector):
            self.events.append(selector)
            if selector == '#remote-read-paste':
                if not self.draft_focused:
                    raise AssertionError('paste requires explicit draft focus after the previous review')
                self.draft_focused = False
                self.review = True; self.reads += 1
            elif selector == '#remote-input-draft-mode':
                self.draft_focused = True
            elif selector == '#remote-paste-cancel':
                self.review = False
                if self.bad == 'cancel-draft': self.draft = 'changed'
            elif selector == '#remote-paste-append':
                self.review = False
                self.draft += '测' if self.bad != 'append-draft' else 'changed'
            else:
                raise AssertionError(selector)

        def read(self, selector, prop='textContent'):
            return {'#remote-paste-preview': 'wrong' if self.bad == 'preview' else '测',
                    '#remote-input-status': '草稿仅在核对并确认后发送。' if self.draft_focused else '观察模式',
                    '#remote-paste-target': '目标：p · term_10' if self.bad == 'target' else '目标：p · term_1',
                    '#remote-input-draft': self.draft}[selector]

        def evaluate(self, expression):
            if 'activeElement' in expression:
                return self.draft_focused
            if 'dataset.receipt' in expression:
                return 'changed' if self.bad == 'receipt' else 'original-receipt'
            if 'preview-area' in expression:
                return self.bad != 'send-preview'
            if 'paste-review' in expression:
                return not self.review
            raise AssertionError(expression)

    receipt = {'paneId': 'p', 'terminalId': 'term_1'}

    def test_two_production_reads_cancel_then_append_keep_only_previous_remote_byte(self):
        view = self.View()
        approval = Mock()
        approval.verify_ssh.side_effect = lambda expected: view.events.append(('receiver', expected, view.draft))
        result = android.exercise_local_paste(view, approval, self.receipt, 'original-receipt')
        self.assertEqual(view.events, ['synthetic-copy', ('fill', 'Pocket'),
            '#remote-read-paste', '#remote-paste-cancel', ('receiver', b'k', 'Pocket'),
            '#remote-input-draft-mode', '#remote-read-paste', '#remote-paste-append', ('receiver', b'k', 'Pocket测')])
        self.assertEqual(view.reads, 2)
        self.assertTrue(all(value is True for value in result.values()))
        self.assertNotIn('测', json.dumps(result, ensure_ascii=False))

    def test_changed_preview_target_draft_receipt_or_unexpected_remote_bytes_cannot_pass(self):
        for bad in ('preview', 'target', 'cancel-draft', 'append-draft', 'receipt', 'send-preview'):
            with self.subTest(bad=bad), self.assertRaises(android.GuiFailure):
                android.exercise_local_paste(self.View(bad), Mock(), self.receipt, 'original-receipt')
        approval = Mock(); approval.verify_ssh.side_effect = android.GuiFailure('unexpected_remote_input')
        with self.assertRaisesRegex(android.GuiFailure, '^unexpected_remote_input$'):
            android.exercise_local_paste(self.View(), approval, self.receipt, 'original-receipt')

    def test_device_preconditions_prevent_any_copy_or_install(self):
        import tempfile
        with tempfile.NamedTemporaryFile() as apk:
            args = types.SimpleNamespace(android_guarded_input=True, input_fixture='owned-fixture', tauri_app=apk.name)
            for bad in ('devices', 'ro.kernel.qemu', 'ro.build.version.sdk', 'get-current-user'):
                def adb(*parts, **kwargs):
                    values = {'devices': 'List of devices attached\nemulator-5554\tdevice',
                              'ro.kernel.qemu': '1', 'ro.build.version.sdk': '35', 'get-current-user': '0'}
                    if parts[-1] == bad:
                        return 'List of devices attached\nemulator-5554\tdevice\nphone\tdevice' if bad == 'devices' else 'wrong'
                    return values[parts[-1]]
                with self.subTest(bad=bad), patch.dict(android.os.environ, {'GITHUB_ACTIONS': 'true', 'ANDROID_SERIAL': android.SERIAL}), \
                        patch.object(android, 'adb', side_effect=adb), patch.object(android, 'AndroidWebView') as view:
                    with self.assertRaises(android.GuiFailure):
                        android.run_android(args, None, None, {'host': '127.0.0.1', 'port': 2222}, Mock())
                    view.assert_not_called()

    def test_stock_production_runner_does_not_seed_or_read_clipboard(self):
        import tempfile
        view = Mock()
        view.evaluate.side_effect = lambda expression: 1 if 'Frames' in expression else True
        view.read.side_effect = lambda selector, *args: {
            '#pair-request': 'public fixture request', '#pair-status': '授权响应已审查',
            '#remote-panes button': 'p · term_1', '#remote-captured': '陈旧',
        }[selector]
        approval = Mock(); approval.approve.return_value = b'public fixture response'
        def adb(*parts, **kwargs):
            values = {('devices',): 'List of devices attached\nemulator-5554\tdevice',
                ('shell', 'getprop', 'ro.kernel.qemu'): '1',
                ('shell', 'getprop', 'ro.build.version.sdk'): '35',
                ('shell', 'am', 'get-current-user'): '0',
                ('shell', 'pm', 'list', 'packages'): '',
                ('shell', 'pidof', android.PACKAGE): '42',
                ('shell', 'cat', '/proc/net/unix'): '@webview_devtools_remote_42',
                ('forward', 'tcp:0', 'localabstract:webview_devtools_remote_42'): '12345'}
            return values.get(parts, '')
        with tempfile.NamedTemporaryFile() as apk, \
                patch.dict(android.os.environ, {'GITHUB_ACTIONS': 'true', 'ANDROID_SERIAL': android.SERIAL}), \
                patch.object(android, 'adb', side_effect=adb), patch.object(android, 'AndroidWebView', return_value=view):
            args = types.SimpleNamespace(android_guarded_input=False, input_fixture=None, tauri_app=apk.name)
            config = {'host': '127.0.0.1', 'port': 2222, 'username': 'fixture', 'session': 'pocket-probe',
                      'herdrPath': '/tmp/owned/herdr', 'socketPath': '/tmp/owned/socket', 'expectedHostKey': 'fixture', 'paneId': 'p'}
            result = android.run_android(args, None, None, config, approval)
        view.copy_synthetic_clipboard.assert_not_called()
        view.receipt.assert_not_called(); approval.verify_ssh.assert_not_called()
        self.assertFalse(result['inputQueueAccepted'])
        self.assertEqual(result['inputReceipts'], [])
        self.assertFalse(any('paste' in field.lower() or 'clipboard' in field.lower() for field in result))
        self.assertNotIn(('#remote-read-paste',), [call.args for call in view.click.call_args_list])

class AndroidDraftReentryTest(unittest.TestCase):
    class View:
        def __init__(self, target='p · term_1', unbound='', restored='Pocket测'):
            self.target = target
            self.unbound = unbound
            self.restored = restored
            self.calls = []
            self.selected = False

        def read(self, selector, prop='textContent'):
            self.calls.append(('read', selector))
            if selector == '#remote-input-draft':
                return self.restored if self.selected else self.unbound
            if selector == '#remote-input-status':
                return '草稿仅在核对并确认后发送。'
            raise AssertionError(selector)

        def click(self, selector):
            self.calls.append(('click', selector))
            if selector == '#remote-panes button':
                self.selected = True

        def evaluate(self, expression):
            self.calls.append(('evaluate', expression))
            if 'firstChild' in expression:
                return self.target
            return True

    def test_review_then_exact_target_then_draft_check(self):
        view = self.View()
        android.restore_reviewed_draft(view, 'p', 'term_1', lambda _: 1)
        clicks = [value for action, value in view.calls if action == 'click']
        self.assertEqual(clicks, ['#host-restore-review', '#host-restore', '#remote-review',
                                  '#remote-connect', '#remote-panes button', '#remote-input-draft-mode'])
        reads = [i for i, item in enumerate(view.calls) if item == ('read', '#remote-input-draft')]
        selection = view.calls.index(('click', '#remote-panes button'))
        self.assertLess(reads[0], selection)
        self.assertGreater(reads[1], selection)

    def test_draft_before_binding_and_changed_terminal_fail_closed(self):
        for view, error in ((self.View(unbound='old'), 'android_unbound_draft_exposed'),
                            (self.View(target='p · term_10'), 'android_reentry_target_mismatch'),
                            (self.View(restored='different'), 'android_reentry_draft_changed')):
            with self.subTest(error=error), self.assertRaisesRegex(android.GuiFailure, error):
                android.restore_reviewed_draft(view, 'p', 'term_1', lambda _: 1)


if __name__ == '__main__':
    unittest.main()
