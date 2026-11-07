"""Synthetic receipt-clock and public-control checks; no device or keys."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent))
stub = types.ModuleType('paired_gui')
stub.GuiFailure = type('GuiFailure', (Exception,), {})
def bounded_wait(check, code, **_):
    for _ in range(3):
        if check():
            return True
    raise stub.GuiFailure(code)
stub.wait_for = bounded_wait
previous = sys.modules.get('paired_gui')
sys.modules['paired_gui'] = stub
try:
    spec = importlib.util.spec_from_file_location('revocation_android_gui', Path(__file__).with_name('android_gui.py'))
    android = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(android)
finally:
    if previous is None:
        sys.modules.pop('paired_gui', None)
    else:
        sys.modules['paired_gui'] = previous

class ReceiptClockTests(unittest.TestCase):
    def receipt(self, **changes):
        return json.dumps({'status':'revoked','issued_at':101,'expires_at':201,'unused':'PRIVATE',**changes}).encode()
    def progress(self):
        return types.SimpleNamespace(data={},publish=Mock())
    def test_one_second_lag_waits_without_review_or_accept_actions(self):
        browser=Mock();browser.evaluate.side_effect=[100,101];progress=self.progress()
        android.wait_fixture_revocation_clock(browser,self.receipt(),progress)
        self.assertEqual(progress.data['revocationClock'],{'attempts':2,'issuedAtReached':True,'notExpired':True})
        self.assertNotIn('PRIVATE',json.dumps(progress.data));browser.click.assert_not_called();browser.call.assert_not_called()
    def test_persistent_future_or_expired_receipt_fails_closed_without_actions(self):
        for clock in (100,201):
            browser=Mock();browser.evaluate.return_value=clock
            with self.subTest(clock=clock),self.assertRaisesRegex(android.GuiFailure,'android_revoke_device_time_unready'):
                android.wait_fixture_revocation_clock(browser,self.receipt())
            browser.click.assert_not_called();browser.call.assert_not_called()
    def test_malformed_device_clock_and_wire_are_static_failures(self):
        for clock in (True,101.5,'PRIVATE'):
            browser=Mock();browser.evaluate.return_value=clock
            with self.assertRaisesRegex(android.GuiFailure,'android_revoke_clock_invalid'):
                android.wait_fixture_revocation_clock(browser,self.receipt())
        for raw in (b'PRIVATE',self.receipt(issued_at=True),self.receipt(expires_at=702),self.receipt(status='authorized')):
            with self.assertRaisesRegex(android.GuiFailure,'android_revoke_clock_invalid'):
                android.wait_fixture_revocation_clock(Mock(),raw)
    def test_controls_export_only_booleans_and_cannot_grant_review(self):
        browser=Mock();browser.evaluate.return_value={'acceptPresent':True,'acceptDisabled':False,'sourceChecked':True,
            'previewVisible':True,'fieldsDisabled':False,'documentHidden':False,'unused':'PRIVATE'}
        progress=self.progress();android.require_revocation_review_controls(browser,progress)
        self.assertNotIn('PRIVATE',json.dumps(progress.data));self.assertEqual(len(progress.data['revocationControls']),6)
        browser.click.assert_not_called();browser.call.assert_not_called()
    def test_missed_review_or_disabled_accept_has_precise_diagnostic_without_retry(self):
        for checked,disabled in ((False,True),(True,True)):
            browser=Mock();browser.evaluate.return_value={'acceptPresent':True,'acceptDisabled':disabled,'sourceChecked':checked,
                'previewVisible':True,'fieldsDisabled':False,'documentHidden':False}
            progress=self.progress()
            with self.assertRaisesRegex(android.GuiFailure,'android_revoke_controls_unconfirmed'):
                android.require_revocation_review_controls(browser,progress)
            self.assertEqual(progress.data['revocationControls']['sourceChecked'],checked);browser.click.assert_not_called()

if __name__=='__main__':unittest.main()
