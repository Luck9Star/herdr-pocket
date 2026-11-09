import importlib.util
from pathlib import Path
import sys
import json
import shutil
import subprocess
import types
import unittest
from unittest.mock import patch

stub = types.ModuleType("paired_gui")
stub.GuiFailure = type("GuiFailure", (Exception,), {})
stub.wait_for = lambda check, code, **kwargs: check()
previous = sys.modules.get("paired_gui")
sys.modules["paired_gui"] = stub
try:
    spec = importlib.util.spec_from_file_location("tui_android_gui", Path(__file__).with_name("android_gui.py"))
    android = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(android)
finally:
    if previous is None:
        sys.modules.pop("paired_gui", None)
    else:
        sys.modules["paired_gui"] = previous


class FakeBrowser:
    def __init__(self):
        self.full = 1
        self.delta = 1
        self.clicks = []
        self.receipts = []
        self.wrong_target = False
        self.duplicate = False
        self.no_frame = False

    def read(self, selector, prop='textContent'):
        if selector == '#remote-input-target':
            return '目标：other · term_a' if self.wrong_target else '目标：p · term_a'
        if selector == '#remote-input-status':
            return '逐键输入已启用'
        raise AssertionError(selector)

    def click(self, selector, trace=None):
        self.clicks.append(selector)
        if trace is not None:
            trace.append({'activeElement': 'xterm-helper-textarea'})
        if 'data-remote-key=' in selector and not self.no_frame:
            self.delta += 1

    def evaluate(self, expression):
        if 'Number(c.dataset.fullFrames' in expression:
            return [self.full, self.delta]
        if 'remote-more-keys' in expression or "dataset.state === 'active'" in expression:
            return True
        if "querySelectorAll('.xterm-rows > div')" in expression:
            # Exact lines prevent Detail: x from matching the earlier Detail: xy.
            assert "lines.includes(marker)" in expression
            return True
        raise AssertionError(expression)

    def receipt(self, previous, pane, length):
        ident = 'a' * 32 if self.duplicate else f'{len(self.receipts)+3:032x}'
        item = {'requestId': ident, 'paneId': pane, 'terminalId': 'term_a', 'acceptedBytes': length}
        self.receipts.append(item)
        return str(len(self.receipts)), item


class Approval:
    def __init__(self, browser):
        self.browser = browser
        self.targets = []

    def start_tui(self, *, terminal_id):
        self.targets.append(terminal_id)
        self.browser.full += 1


def immediate_wait(check, error, timeout=None):
    result = check()
    if not result:
        raise android.GuiFailure(error)
    return result


class AndroidTuiTests(unittest.TestCase):
    def setUp(self):
        self.browser = FakeBrowser()
        self.approval = Approval(self.browser)
        self.wait = patch.object(android, 'wait_for', immediate_wait)
        self.wait.start()
        self.addCleanup(self.wait.stop)

    def exercise(self):
        return android.exercise_tui(self.browser, self.approval, 'p', 'term_a', 'prior', ['a' * 32])

    def test_sequence_screens_and_receipts(self):
        result = self.exercise()
        self.assertEqual(self.approval.targets, ['term_a'])
        self.assertEqual([r['acceptedBytes'] for r in result['receipts']], [3, 1, 1, 3, 4, 4, 3, 3, 5, 5])
        self.assertEqual(result['screenChecks'], ['initial', 'select-next', 'focus-detail',
                         'erase-character', 'focus-list', 'insert-row', 'delete-row',
                         'open-help', 'close-help', 'refresh'])
        self.assertTrue(result['observedInitialFull'])
        keys = [item.split('"')[1] for item in self.browser.clicks if 'data-remote-key=' in item]
        self.assertEqual(keys, [key for key, _, _ in android.STEPS])

    def test_wrong_target_never_starts_fixture(self):
        self.browser.wrong_target = True
        with self.assertRaisesRegex(android.GuiFailure, 'android_tui_target_mismatch'):
            self.exercise()
        self.assertEqual(self.approval.targets, [])

    def test_duplicate_receipt_does_not_continue(self):
        self.browser.duplicate = True
        with self.assertRaisesRegex(android.GuiFailure, 'android_tui_receipt_mismatch'):
            self.exercise()
        self.assertEqual(len(self.browser.receipts), 1)

    def test_old_screen_without_new_frame_rejected(self):
        self.browser.no_frame = True
        with self.assertRaisesRegex(android.GuiFailure, 'android_tui_screen_missing'):
            self.exercise()
        self.assertEqual(len(self.browser.receipts), 1)

    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute DOM expression')
    def test_real_dom_expression_requires_exact_lines_and_normalizes_nbsp(self):
        class Capture:
            def evaluate(self, expression):
                self.expression = expression
                return True
        capture = Capture()
        android.tui_screen_matches(capture, 'initial')
        initial = capture.expression
        android.tui_screen_matches(capture, 'erase-character')
        erased = capture.expression
        code = """const [initial, erased] = JSON.parse(process.argv[1]);
          let lines=[];
          const terminal={scrollIntoView(){},querySelectorAll(){return lines.map(textContent=>({textContent}));}};
          const document={querySelector(s){return s==='#remote-captured'?{dataset:{state:'active'}}:terminal;}};
          const check=(expression, rows)=>{lines=rows;return eval(expression)};
          const start=['Pocket TUI','F1 Help\u00a0\u00a0\u00a0F5 Refresh\u00a0\u00a0\u00a0F10 Finish','> Build'];
          const before=['Pocket TUI','> Review','Focus: detail','Detail: xy'];
          const after=['Pocket TUI','> Review','Focus: detail','Detail: x'];
          console.log(JSON.stringify([check(initial,start),check(initial,['Pocket TUI','F10 Finish','> Build']),
                                      check(erased,before),check(erased,after)]));"""
        actual = subprocess.check_output([shutil.which('node'), '-e', code, json.dumps([initial, erased])], text=True)
        self.assertEqual(json.loads(actual), [True, False, False, True])

    def test_no_new_initial_full_rejected(self):
        self.approval.start_tui = lambda **kwargs: None
        with self.assertRaisesRegex(android.GuiFailure, 'android_tui_initial_full_missing'):
            self.exercise()
        self.assertEqual(self.browser.receipts, [])


if __name__ == '__main__':
    unittest.main()
