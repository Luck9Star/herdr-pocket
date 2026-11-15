import unittest
from unittest.mock import Mock, patch
import tauri_android_dual_overlay as dual


class DualEvidenceTests(unittest.TestCase):
    def test_same_single_approved_session_and_exact_bytes_required(self):
        sample = {'acceptedSessions':1, 'newSessions':0, 'soleApprovedSession':True,
                  'inputAttributionAmbiguous':False, 'exactBytes':True, 'capturedBytes':5,
                  'sessions':[{'ordinal':1, 'approvedDevice':True, 'active':True}]}
        self.assertTrue(dual.checked_audit(sample, 5, ordinal=1, sessions_count=1, active=True))
        for patch in ({'acceptedSessions':2}, {'newSessions':1}, {'exactBytes':False},
                      {'capturedBytes':4},
                      {'sessions':[{'ordinal':2,'approvedDevice':True,'active':True}]}):
            with self.subTest(patch=patch):
                self.assertFalse(dual.checked_audit({**sample, **patch}, 5, ordinal=1, sessions_count=1, active=True))
        self.assertFalse(dual.checked_audit(sample, 5, ordinal=1, sessions_count=1, active=False))
        history = {**sample, 'acceptedSessions':2, 'soleApprovedSession':False,
                   'inputAttributionAmbiguous':True, 'sessions':[
                       {'ordinal':1,'approvedDevice':True,'active':False},
                       {'ordinal':2,'approvedDevice':True,'active':True}]}
        self.assertTrue(dual.checked_audit(history, 5, ordinal=2, sessions_count=2, active=True))
        self.assertFalse(dual.checked_audit(history, 5, ordinal=1, sessions_count=2, active=True))

    def test_removed_tab_never_types_into_surviving_session(self):
        browser = Mock()
        with patch.object(dual,'find_tab',return_value=None):
            self.assertEqual(dual.guard_stale_target(browser,'ts'), 'removed_tab_unreachable')
        browser.call.assert_not_called()
        with patch.object(dual,'find_tab',return_value='#old'), patch.object(dual,'select_tab'):
            browser.evaluate.return_value = True
            with self.assertRaises(dual.GuiFailure): dual.guard_stale_target(browser,'ts')
            browser.call.assert_not_called()
            browser.evaluate.return_value = False
            self.assertEqual(dual.guard_stale_target(browser,'ts'), 'retained_tab_disabled_keyboard_tested')
            browser.call.assert_called_once()

    def test_public_host_control_requires_matching_event(self):
        control = Mock()
        control.call.return_value = {'event':'pairing_review','requestId':'synthetic'}
        self.assertEqual(dual.host_request(control, {'op':'review_pairing'}, 'pairing_review')['requestId'], 'synthetic')
        control.call.return_value = {'event':'rejected'}
        with self.assertRaises(dual.GuiFailure):
            dual.host_request(control, {'op':'review_pairing'}, 'pairing_review')


if __name__ == '__main__': unittest.main()
