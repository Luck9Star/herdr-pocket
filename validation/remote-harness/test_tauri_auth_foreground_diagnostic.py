import json
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch

import tauri_auth_foreground_diagnostic as diag
import tauri_android_dual_overlay as dual


class ForegroundDiagnosticTests(unittest.TestCase):
    def test_verified_system_component_root_and_system_ids_only(self):
        package = 'com.android.intentresolver'
        activity = package + '/com.android.internal.app.ChooserActivity'
        nodes = [ET.Element('node', {'package': package, 'resource-id': 'android:id/content',
                                    'text': 'https://127.0.0.1:43123/private-secret?token=secret'}),
                 ET.Element('node', {'package': package, 'resource-id': package + ':id/resolver_list'}),
                 ET.Element('node', {'package': 'personal.app', 'resource-id': 'android:id/private'}),
                 ET.Element('node', {'package': package, 'resource-id': 'personal.app:id/private'})]
        result = diag.summarize(activity, activity, activity, nodes, {'android', package}, {'owned.app'}, 43123)
        self.assertEqual(result['activityComponent'], activity)
        self.assertEqual(result['rootPackage'], package)
        self.assertEqual(result['systemResourceIds'], ['android:id/content', package + ':id/resolver_list'])
        self.assertTrue(result['loopbackHostPortSeen'])
        self.assertTrue(result['windowStableAcrossTree'])
        encoded = json.dumps(result)
        for value in ('https:', 'private', 'secret', '43123', 'personal.app'): self.assertNotIn(value, encoded)

    def test_personal_invalid_or_overlong_components_are_not_published(self):
        for value in ('personal.app/.Activity', 'android/.Activity extras=secret',
                      'android/.Activity?url=https://secret', 'android/' + 'x' * 300):
            result = diag.summarize(value, value, value, [ET.Element('node', {'package': 'personal.app', 'text': '127.0.0.1:1'})],
                                    {'android'}, {'owned.app'}, 1)
            self.assertIsNone(result['activityComponent']); self.assertIsNone(result['rootPackage'])
            self.assertFalse(result['loopbackHostPortSeen'])
            self.assertEqual(result['systemResourceIds'], [])

    def test_window_parser_is_canonical_and_ambiguous_focus_is_unavailable(self):
        raw = 'mCurrentFocus=Window{123abc u0 android/.ResolverActivity}\nEXTRAS private URL'
        self.assertEqual(diag.window_component(raw), 'android/android.ResolverActivity')
        self.assertIsNone(diag.window_component(raw + '\nmCurrentFocus=Window{aaa u0 android/.Other}'))
        self.assertEqual(diag.system_packages('package:android\npackage:com.android.intentresolver\npackage:bad/extra'),
                         {'android', 'com.android.intentresolver'})

    def test_capture_reads_two_window_samples_and_never_sends_input(self):
        calls = []
        def adb(*args, **kwargs):
            calls.append(args)
            return 'package:android' if 'packages' in args else 'mCurrentFocus=Window{abc u0 android/.ResolverActivity}'
        result = diag.capture(adb, lambda: [ET.Element('node', {'package': 'android'})],
                              lambda: 'android/android.ResolverActivity', {'owned.app'}, 43123)
        self.assertEqual(sum('window' in call for call in calls), 2)
        self.assertTrue(result['activityMatchesWindowBefore'])
        self.assertFalse(any('input' in call or 'start' in call for call in calls))

    def test_diagnostic_stops_after_product_open_before_any_chooser_or_approval(self):
        report = {'authForegroundDiagnosticOnly': True}
        with patch.object(dual, 'wait_named'), patch.object(dual, 'confirm_click') as opened, \
             patch.object(dual, 'capture_auth_foreground', return_value={'scope': 'test'}) as capture, \
             patch.object(dual, 'choose_auth_receiver') as choose, patch.object(dual, 'approve_auth_receiver') as approve:
            with self.assertRaisesRegex(dual.GuiFailure, 'dual_auth_foreground_diagnostic_only'):
                dual.authorize_ts(Mock(), Mock(), 'scope', 43123, report)
        self.assertEqual(opened.call_count, 2); capture.assert_called_once()
        choose.assert_not_called(); approve.assert_not_called()
        self.assertEqual(report['authorization']['foregroundDiagnostic'], {'scope': 'test'})

    def test_failed_tree_does_not_discard_verified_window_component(self):
        def adb(*args, **kwargs):
            return 'package:android' if 'packages' in args else 'mCurrentFocus=Window{abc u0 android/.ResolverActivity}'
        result = diag.capture(adb, Mock(side_effect=RuntimeError('private text')), lambda: None, {'owned.app'}, 43123)
        self.assertEqual(result['windowComponentAfterTree'], 'android/android.ResolverActivity')
        self.assertFalse(result['readsAvailable']['nativeTree'])
        self.assertNotIn('private text', json.dumps(result))


if __name__ == '__main__': unittest.main()
