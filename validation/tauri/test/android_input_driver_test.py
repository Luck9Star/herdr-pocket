"""Isolated checks of Android driver's receipt and direct-key boundary."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

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
