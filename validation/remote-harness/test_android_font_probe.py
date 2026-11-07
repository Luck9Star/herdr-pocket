"""Offline tests for the Tauri Android local-font DOM measurement contract."""
import importlib.util
from pathlib import Path
import sys
import time
import types
import unittest


# android_gui's operational runner imports reach the cryptography helper stack;
# these isolated tests need only its static exception and polling contracts.
_module_names = ('paired_gui', 'flutter_android_gui')
_previous_modules = {name: sys.modules.get(name) for name in _module_names}
paired_stub = types.ModuleType('paired_gui')
class GuiFailure(Exception):
    pass
paired_stub.GuiFailure = GuiFailure
paired_stub.wait_for = lambda check, _code, timeout=10: _wait_for(check, timeout)
sys.modules['paired_gui'] = paired_stub
flutter_stub = types.ModuleType('flutter_android_gui')
class DeviceFailure(Exception):
    pass
flutter_stub.DeviceFailure = DeviceFailure
flutter_stub.wait_system_ime = lambda *_args, **_kwargs: {}
sys.modules['flutter_android_gui'] = flutter_stub


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
spec.loader.exec_module(android_gui)
for _name, _module in _previous_modules.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module


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

    def evaluate(self, expression):
        if expression == android_gui.FONT_DIAGNOSTIC_GEOMETRY:
            return self.measured
        if "startsWith('示例已绘制')" in expression:
            return 'ready'
        if "const close=d?.querySelector('button')" in expression:
            return {'dialogOpen': True, 'nativeModal': True, 'ariaModal': True,
                    'closeFocused': True, 'triggerEnabled': True,
                    'inputControlsPresent': True, 'inputControlsHidden': False,
                    'remoteDraftFocused': False, 'keyboardShowDisabled': True,
                    'keyboardHideDisabled': True, 'remoteTextareaReadOnly': True,
                    'remoteTextareaInputMode': 'none', 'remoteTextareaFocused': False}
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


class GeometryBrowser:
    def __init__(self, measured):
        self.measured = measured

    def evaluate(self, expression):
        self.assertion = expression
        return self.measured


if __name__ == '__main__':
    unittest.main()
