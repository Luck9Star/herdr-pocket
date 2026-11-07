"""Offline tests for the Tauri Android local-font DOM measurement contract."""
import importlib.util
import json
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch


# android_gui's operational runner imports reach the cryptography helper stack;
# these isolated tests need only its static exception and polling contracts.
paired_stub = types.ModuleType('paired_gui')
class GuiFailure(Exception):
    pass
paired_stub.GuiFailure = GuiFailure
paired_stub.wait_for = lambda check, _code, timeout=10: _wait_for(check, timeout)


def _wait_for(check, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.001)
    raise GuiFailure('test_phase_timeout')


spec = importlib.util.spec_from_file_location('android_gui', Path(__file__).with_name('android_gui.py'))
android_gui = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'paired_gui': paired_stub}):
    spec.loader.exec_module(android_gui)


def geometry(**changes):
    value = {'rowCount': 8, 'columns': 16, 'columnRatio': 16.001,
             'markerColumns': [15] * 8, 'markerOffsets': [15.01] * 8,
             'cellWidthPx': 9.25, 'screenWidthPx': 148.01}
    value.update(changes)
    return value


class FakeBrowser:
    def __init__(self, measured=None):
        self.measured = measured or geometry()
        self.closed = False
        self.clicks = []
        self.samples = []

    def evaluate(self, expression):
        if expression == android_gui.FONT_DIAGNOSTIC_GEOMETRY:
            return self.measured
        if 'function readThemeMeasurement(id)' in expression:
            return android_gui.theme_prompt_expectations()[self.samples[-1]]
        if "startsWith('示例已绘制')" in expression:
            return 'ready'
        if "const close=d?.querySelector('button')" in expression:
            return {'dialogOpen': True, 'nativeModal': True, 'ariaModal': True,
                    'closeFocused': True, 'triggerEnabled': True,
                    'inputControlsPresent': True, 'inputControlsHidden': False,
                    'remoteDraftFocused': False, 'keyboardShowDisabled': True,
                    'keyboardHideDisabled': True, 'remoteTextareaReadOnly': True,
                    'remoteTextareaInputMode': json.loads('"none"'), 'remoteTextareaFocused': False}
        if "document.querySelector('#remote-font-diagnostics')?.disabled===false" in expression:
            return True
        if "document.activeElement===document.querySelector('#remote-font-diagnostics')" in expression:
            return self.closed
        if "!!document.querySelector('.terminal-font-diagnostics[open]')" in expression:
            return not self.closed
        if "!document.querySelector('.terminal-font-diagnostics')" in expression:
            return self.closed
        raise AssertionError('unexpected_browser_expression')

    def click(self, selector):
        self.clicks.append(selector)
        if selector == '.terminal-font-diagnostics button':
            self.closed = True

    def select_font_sample(self, ident):
        self.samples.append(ident)


class Approval:
    def __init__(self):
        self.expected = []

    def verify_ssh(self, expected):
        self.expected.append(expected)


class AndroidFontProbeTests(unittest.TestCase):
    def test_geometry_records_eight_rows_and_real_cell_positions_only(self):
        value = android_gui.font_diagnostic_geometry(GeometryBrowser(geometry()))
        self.assertEqual(value, {'rowCount': 8, 'columns': 16, 'markerColumn': 15,
            'markerColumnZeroBased': 14,
            'markerPositionStatus': 'verified', 'markerColumns': [15] * 8,
            'cellWidthPx': 9.25, 'screenWidthPx': 148.01,
            'columnRatio': 16.001})
        self.assertNotIn('sampleText', value)

    def test_unavailable_marker_coordinates_are_reported_without_claiming_verification(self):
        raw = geometry(markerColumns=[15, None, None, None, None, None, None, None],
                       markerOffsets=[15.01, None, None, None, None, None, None, None])
        value = android_gui.font_diagnostic_geometry(GeometryBrowser(raw))
        self.assertEqual(value['markerPositionStatus'], 'partially_measurable')
        self.assertIsNone(value['markerColumnZeroBased'])
        self.assertEqual(value['markerColumns'][0], 15)
        self.assertEqual(value['markerColumns'][1:], [None] * 7)

    def test_geometry_fails_closed_when_grid_or_marker_is_not_measurable(self):
        for measurement in (None, geometry(rowCount=7), geometry(columns=15),
                            geometry(markerColumns=[15] * 7 + [14]),
                            geometry(markerOffsets=[15.01] * 7 + [15.3]),
                            geometry(cellWidthPx=0)):
            with self.subTest(measurement=measurement):
                with self.assertRaises(android_gui.GuiFailure):
                    android_gui.font_diagnostic_geometry(GeometryBrowser(measurement))

    def test_normal_entry_is_input_locked_safe_and_returns_to_observation(self):
        browser = FakeBrowser()
        approval = Approval()
        delta = iter((4, 5, 6))
        evidence = android_gui.exercise_font_diagnostics(browser, approval, lambda _name: next(delta))
        self.assertTrue(evidence['inputLocked'])
        self.assertTrue(evidence['safeFocus'])
        self.assertTrue(evidence['focusRestored'])
        self.assertTrue(evidence['observationContinued'])
        self.assertTrue(evidence['inputControlsPresent'])
        self.assertFalse(evidence['inputControlsHidden'])
        self.assertEqual(evidence['receivedInputBytesDuringProbe'], 0)
        self.assertEqual(evidence['deltaFramesBefore'], 4)
        self.assertEqual(evidence['deltaFramesDuring'], 5)
        self.assertEqual(evidence['deltaFramesAfter'], 6)
        self.assertEqual(approval.expected, [b'', b''])
        self.assertEqual(browser.clicks, ['#remote-font-diagnostics', '.terminal-font-diagnostics button'])
        self.assertEqual(browser.samples,['powerlevel10k','oh-my-posh'])
        self.assertEqual(evidence['localThemePromptCursors'],android_gui.theme_prompt_expectations())

    def test_theme_measurement_rejects_wrong_cursor_boolean_coercion_and_extra_fields(self):
        expected=android_gui.theme_prompt_expectations()['powerlevel10k']
        for measured in ([14,0], {**expected,'terminalText':'PRIVATE'},
                         *({**expected,field:value} for field in expected
                           for value in (True,False,'0',0.0,-1,999)),
                         android_gui.theme_prompt_expectations()['oh-my-posh']):
            with self.subTest(measured=measured),self.assertRaises(android_gui.GuiFailure):
                android_gui.theme_prompt_measurement(GeometryBrowser(measured),'powerlevel10k')

    def test_pending_or_old_sample_measurements_wait_for_current_ready_callback(self):
        expected=android_gui.theme_prompt_expectations()['oh-my-posh']
        browser=SequenceBrowser([None,None,expected])
        with patch.object(android_gui,'wait_for',bounded_wait):
            self.assertEqual(android_gui.theme_prompt_measurement(browser,'oh-my-posh'),expected)
        self.assertEqual(browser.reads,3)
        self.assertTrue(browser.expression.endswith(')("oh-my-posh")'))

    def test_missing_or_permanently_stale_theme_measurements_fail_closed(self):
        for pending in (None,False,{}):
            browser=SequenceBrowser([pending,pending,pending])
            with self.subTest(pending=pending),patch.object(android_gui,'wait_for',bounded_wait):
                with self.assertRaises(android_gui.GuiFailure):
                    android_gui.theme_prompt_measurement(browser,'powerlevel10k')

    def test_normal_theme_select_uses_native_keys_once_and_rejects_out_of_order_samples(self):
        browser=object.__new__(android_gui.AndroidWebView)
        selected=['glyphs']
        browser.click=Mock()
        browser.read=Mock(side_effect=lambda _selector,_attribute:selected[0])
        def dispatch(_method,params):
            if params['type']=='keyUp' and params['key']=='Enter':
                selected[0]={'glyphs':'powerlevel10k','powerlevel10k':'oh-my-posh'}[selected[0]]
        browser.call=Mock(side_effect=dispatch)
        browser.select_font_sample('powerlevel10k')
        browser.select_font_sample('oh-my-posh')
        self.assertEqual(browser.click.call_count,2)
        self.assertEqual(browser.call.call_count,8)
        self.assertEqual([call.args[1]['key'] for call in browser.call.call_args_list],
                         ['ArrowDown','ArrowDown','Enter','Enter'] * 2)
        for ident in ('powerlevel10k','unknown',None):
            with self.subTest(ident=ident),self.assertRaises(android_gui.GuiFailure):
                browser.select_font_sample(ident)
        self.assertEqual(browser.click.call_count,2)


def bounded_wait(check, code, timeout=10):
    for _ in range(3):
        result=check()
        if result:return result
    raise android_gui.GuiFailure(code)


class SequenceBrowser:
    def __init__(self, values):
        self.values=iter(values)
        self.reads=0

    def evaluate(self, expression):
        self.expression=expression
        self.reads+=1
        return next(self.values)


class GeometryBrowser:
    def __init__(self, measured):
        self.measured = measured

    def evaluate(self, expression):
        self.assertion = expression
        return self.measured


if __name__ == '__main__':
    unittest.main()
