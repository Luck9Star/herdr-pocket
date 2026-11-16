import json
import unittest

import tauri_android_dual_overlay as dual
from paired_gui import GuiFailure

ACQUIRE = {'epoch': 1, 'focused': True}
VERIFY = {'same': True, 'focused': True}
BEFORE = {'sent': 0, 'resolved': 0, 'rejected': 0, 'cmdId': None, 'profileId': None}
SENT = {'sent': 1, 'resolved': 0, 'rejected': 0, 'cmdId': 'a' * 32, 'profileId': 'a' * 32}
RESOLVED = {'sent': 1, 'resolved': 1, 'rejected': 0, 'cmdId': 'a' * 32, 'profileId': 'a' * 32}


class FakeBrowser:
    """Feeds scripted probe/observer responses; records every dispatched activation."""

    def __init__(self, probes=None, snapshots=None, *, auto_confirm=True, confirm_after_pumps=1,
                 repeat_probe=None, uninstall_value=True):
        self.expectedConfirmation = None
        self.confirmationObserved = False
        self.confirmDiagnostic = {'stalePreviousSuccess': True}
        self.calls = []
        self.expressions = []
        self.pumps = 0
        self._probes = list(probes or [])
        self._repeat_probe = repeat_probe
        self._snapshots = list(snapshots or [dict(BEFORE)])
        self._auto_confirm = auto_confirm
        self._confirm_after = confirm_after_pumps
        self._uninstall_value = uninstall_value

    def evaluate(self, expression):
        self.expressions.append(expression)
        if '__dualStopObserver' in expression:
            if 'x.original' in expression:
                return self._uninstall_value
            value = self._snapshots.pop(0) if self._snapshots else None
            if not self._snapshots and value is not None:
                self._snapshots.append(value)
            return dict(value) if value is not None else None
        if self._repeat_probe is not None:
            return dict(self._repeat_probe)
        return self._probes.pop(0)

    def call(self, method, params=None):
        self.calls.append((method, dict(params or {})))
        if method == 'Runtime.evaluate' and (params or {}).get('expression') == 'true':
            self.pumps += 1
            if self._auto_confirm and self.pumps >= self._confirm_after:
                self.confirmationObserved = True
        return {}


class StopNodeOnceTests(unittest.TestCase):
    def setUp(self):
        self._settle = dual.STOP_READBACK_SETTLE
        self._acquire = dual.STOP_ACQUIRE_TIMEOUT
        dual.STOP_READBACK_SETTLE = 0.001
        dual.STOP_ACQUIRE_TIMEOUT = 2

    def tearDown(self):
        dual.STOP_READBACK_SETTLE = self._settle
        dual.STOP_ACQUIRE_TIMEOUT = self._acquire

    def stop(self, browser, *, role='et', expected='a' * 32, stage='stop_first', distinct_ids=(), attempts=None):
        attempts = attempts if attempts is not None else []
        profile = dual.stop_node_once(browser, '#et-card', role, 'QA ET · EasyTier', 'QA host ET', expected,
                                      stage=stage, attempts=attempts, distinct_ids=distinct_ids, confirm_timeout=3)
        return profile, attempts

    def key_events(self, browser):
        return [(method, params) for method, params in browser.calls if method == 'Input.dispatchKeyEvent']

    def test_async_resolve_after_delay_verifies(self):
        browser = FakeBrowser([ACQUIRE, VERIFY], [dict(BEFORE), dict(SENT), dict(SENT), dict(RESOLVED)])
        profile, attempts = self.stop(browser)
        self.assertEqual(profile, 'a' * 32)
        keys = self.key_events(browser)
        self.assertEqual([params['type'] for _, params in keys], ['keyDown', 'keyUp'])
        self.assertEqual(keys[0][1].get('text'), '\r')
        self.assertEqual(keys[0][1].get('nativeVirtualKeyCode'), 13)
        self.assertNotIn('text', keys[1][1])
        self.assertFalse(any(method == 'Input.dispatchMouseEvent' for method, _ in browser.calls))
        for expression in browser.expressions:
            self.assertNotIn('.click(', expression)
        self.assertIsNone(browser.expectedConfirmation)
        attempt = attempts[0]
        self.assertEqual(attempt['stage'], 'stop_first')
        self.assertEqual(attempt['role'], 'et')
        self.assertEqual(attempt['acquires'], 1)
        self.assertEqual(attempt['readbacks'], 2)
        self.assertTrue(attempt['confirmObserved'])
        self.assertTrue(attempt['roleMatch'])
        self.assertEqual(attempt['sentDelta'], 1)
        self.assertEqual(attempt['resolvedDelta'], 1)
        self.assertEqual(attempt['rejectedDelta'], 0)
        self.assertIsNone(attempt['errorCode'])

    def test_confirm_wait_pumps_events_until_observed(self):
        browser = FakeBrowser([ACQUIRE, VERIFY], [dict(BEFORE), dict(RESOLVED)], confirm_after_pumps=3)
        _, attempts = self.stop(browser)
        self.assertGreaterEqual(browser.pumps, 3, 'late dialog events only arrive via side-effect-free pumps')
        self.assertTrue(attempts[0]['confirmObserved'])

    def test_confirm_not_observed_never_replays_enter(self):
        browser = FakeBrowser([ACQUIRE, VERIFY], [dict(BEFORE)], auto_confirm=False)
        attempts = []
        with self.assertRaises(GuiFailure) as caught:
            self.stop(browser, attempts=attempts)
        self.assertEqual(str(caught.exception), 'dual_stop_confirmation_not_observed')
        self.assertEqual(len(self.key_events(browser)), 2, 'exactly one Enter pair, never replayed')
        self.assertFalse(attempts[0]['confirmObserved'])
        self.assertEqual(attempts[0]['errorCode'], 'dual_stop_confirmation_not_observed')
        self.assertIsNone(browser.expectedConfirmation)

    def test_reacquire_until_same_node_stable_twice(self):
        browser = FakeBrowser([ACQUIRE, {'same': False, 'focused': True},
                               {'epoch': 2, 'focused': True}, VERIFY],
                              [dict(BEFORE), dict(RESOLVED)])
        profile, attempts = self.stop(browser)
        self.assertEqual(profile, 'a' * 32)
        self.assertEqual(attempts[0]['acquires'], 2)
        self.assertEqual(len(self.key_events(browser)), 2)

    def test_never_stable_button_never_activates(self):
        browser = FakeBrowser(repeat_probe={'same': False, 'focused': True}, snapshots=[dict(BEFORE)])
        attempts = []
        with self.assertRaises(GuiFailure) as caught:
            self.stop(browser, attempts=attempts)
        self.assertEqual(str(caught.exception), 'dual_stop_button_unstable')
        self.assertEqual(self.key_events(browser), [])
        self.assertEqual(attempts[0]['errorCode'], 'dual_stop_button_unstable')

    def test_replayed_stop_detected(self):
        replay = {'sent': 2, 'resolved': 1, 'rejected': 0, 'cmdId': 'a' * 32, 'profileId': 'a' * 32}
        browser = FakeBrowser([ACQUIRE, VERIFY], [dict(BEFORE), replay])
        attempts = []
        with self.assertRaises(GuiFailure) as caught:
            self.stop(browser, attempts=attempts)
        self.assertEqual(str(caught.exception), 'dual_stop_replayed')
        self.assertEqual(attempts[0]['sentDelta'], 2)

    def test_rejected_stop_detected(self):
        rejected = {'sent': 1, 'resolved': 0, 'rejected': 1, 'cmdId': 'a' * 32, 'profileId': 'a' * 32}
        browser = FakeBrowser([ACQUIRE, VERIFY], [dict(BEFORE), rejected])
        with self.assertRaises(GuiFailure) as caught:
            self.stop(browser)
        self.assertEqual(str(caught.exception), 'dual_stop_rejected')

    def test_wrong_target_detected(self):
        mismatch = {'sent': 1, 'resolved': 1, 'rejected': 0, 'cmdId': 'c' * 32, 'profileId': 'a' * 32}
        browser = FakeBrowser([ACQUIRE, VERIFY], [dict(BEFORE), mismatch])
        attempts = []
        with self.assertRaises(GuiFailure) as caught:
            self.stop(browser, attempts=attempts)
        self.assertEqual(str(caught.exception), 'dual_stop_target_mismatch')
        self.assertFalse(attempts[0]['roleMatch'])

    def test_non_distinct_target_detected(self):
        browser = FakeBrowser([ACQUIRE, VERIFY], [dict(BEFORE), dict(RESOLVED)])
        attempts = []
        with self.assertRaises(GuiFailure) as caught:
            self.stop(browser, distinct_ids=('a' * 32,), attempts=attempts)
        self.assertEqual(str(caught.exception), 'dual_stop_target_not_distinct')
        self.assertTrue(attempts[0]['roleMatch'])

    def test_invalid_expected_target_refuses(self):
        browser = FakeBrowser([ACQUIRE, VERIFY], [dict(BEFORE)])
        with self.assertRaises(GuiFailure):
            dual.stop_node_once(browser, '#et-card', 'et', 'QA ET · EasyTier', 'QA host ET', '',
                                stage='stop_first', attempts=[])

    def test_public_attempts_never_leak_raw_identifiers_or_errors(self):
        browser = FakeBrowser([ACQUIRE, VERIFY], [dict(BEFORE), dict(RESOLVED)])
        attempts = []
        self.stop(browser, attempts=attempts)
        failing = FakeBrowser([ACQUIRE, VERIFY], [dict(BEFORE)], auto_confirm=False)
        failing_attempts = []
        with self.assertRaises(GuiFailure):
            self.stop(failing, attempts=failing_attempts)
        allowed_keys = {'stage', 'role', 'acquires', 'readbacks', 'activation', 'confirmObserved',
                        'roleMatch', 'sentDelta', 'resolvedDelta', 'rejectedDelta', 'errorCode'}
        for attempt in attempts + failing_attempts:
            self.assertTrue(set(attempt).issubset(allowed_keys))
            for key, value in attempt.items():
                serialized = json.dumps(value, ensure_ascii=False, default=str)
                self.assertNotIn('a' * 32, serialized)
                self.assertNotIn('QA host', serialized)
                if key == 'errorCode':
                    self.assertTrue(value is None or value.replace('_', 'a').isalpha() and value.replace('_', '').islower())


class StopObserverTests(unittest.TestCase):
    def test_snapshot_rejects_invalid_shapes(self):
        class Browser:
            def __init__(self, value):
                self.value = value

            def evaluate(self, _expression):
                return self.value
        for value in (None, {'sent': 'x', 'resolved': 0, 'rejected': 0},
                      {'sent': -1, 'resolved': 0, 'rejected': 0},
                      {'sent': 0, 'resolved': 0, 'rejected': 0, 'cmdId': 17}):
            with self.assertRaises(GuiFailure):
                dual.stop_observer_snapshot(Browser(value))

    def test_snapshot_returns_counters_and_target(self):
        class Browser:
            def __init__(self, _value=None):
                pass

            def evaluate(self, _expression):
                return dict(RESOLVED)
        self.assertEqual(dual.stop_observer_snapshot(Browser()), RESOLVED)

    def test_uninstall_restores_original_ipc(self):
        browser = FakeBrowser()
        self.assertTrue(dual.uninstall_stop_observer(browser))
        failing = FakeBrowser(uninstall_value=False)
        with self.assertRaises(GuiFailure):
            dual.uninstall_stop_observer(failing)

    def test_probe_acquire_stamps_nonce_and_focuses(self):
        probe = dual.stop_button_probe('#et-card', 'acquire')
        self.assertIn('停止节点', probe)
        self.assertIn('__dualStopEpoch', probe)
        self.assertIn('b.focus()', probe)
        self.assertNotIn('.click(', probe)

    def test_probe_verify_pins_the_nonce(self):
        probe = dual.stop_button_probe('#et-card', 'verify', 7)
        self.assertIn('b.__dualStopEpoch===7', probe)
        self.assertNotIn('window.__dualStopEpoch=', probe)


if __name__ == '__main__':
    unittest.main()
