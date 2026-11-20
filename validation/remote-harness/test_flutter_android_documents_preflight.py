import subprocess
import unittest
from unittest.mock import patch
import flutter_android_documents_preflight as probe


def tree(label='设置', clickable='true', bounds='[10,20][110,120]'):
    return (f'<hierarchy><node package="{probe.PACKAGE}" clickable="{clickable}" enabled="true" bounds="{bounds}">'
            f'<node package="{probe.PACKAGE}" text="{label}" /></node></hierarchy>').encode()


class PreflightTest(unittest.TestCase):
    def test_only_fixed_labels_and_unique_clickable_ancestor_are_exposed(self):
        result = probe.inventory(tree())
        self.assertEqual(result['设置'], {'matches': 1, 'clickableAncestors': 1, 'bounds': [10, 20, 110, 120]})
        self.assertEqual(result['终端字号']['matches'], 0)
        self.assertNotIn('secret', str(probe.inventory(tree('secret'))))

    def test_home_merged_settings_semantics_is_allowlisted_but_not_substrings(self):
        self.assertEqual(probe.inventory(tree('设置&#10;设置'))['设置']['matches'], 1)
        self.assertEqual(probe.inventory(tree('设置 something'))['设置']['matches'], 0)

    def test_duplicate_label_and_invalid_bounds_do_not_authorize_tap(self):
        self.assertNotIn('bounds', probe.inventory(tree(bounds='[0,0][9999,3]'))['设置'])
        duplicate = tree().replace(b'</hierarchy>', tree()[11:-12] + b'</hierarchy>')
        self.assertEqual(probe.inventory(duplicate)['设置']['matches'], 2)
        with self.assertRaisesRegex(probe.Failure, 'target_unconfirmed'):
            probe.tap_unique(probe.inventory(duplicate), '设置')

    def test_changed_target_never_taps(self):
        state = probe.inventory(tree())
        with patch.object(probe, 'hierarchy', return_value=probe.inventory(tree(bounds='[11,20][110,120]'))), \
             patch.object(probe, 'adb') as adb:
            with self.assertRaisesRegex(probe.Failure, 'target_unstable'):
                probe.tap_unique(state, '设置')
            adb.assert_not_called()

    def test_single_observed_target_tapped_once(self):
        state = probe.inventory(tree())
        with patch.object(probe, 'hierarchy', return_value=state), patch.object(probe, 'adb') as adb:
            probe.tap_unique(state, '设置')
            adb.assert_called_once_with('shell', 'input', 'tap', '60', '70')

    def test_diagnostics_are_fixed_and_do_not_contain_command_arguments(self):
        with patch.object(probe.subprocess, 'run', side_effect=subprocess.TimeoutExpired('secret', 1)):
            with self.assertRaises(probe.Failure) as caught:
                probe.adb('shell', 'uiautomator', 'dump', 'secret')
        self.assertEqual((caught.exception.operation, caught.exception.outcome), ('hierarchy_dump', 'timeout'))
        self.assertNotIn('secret', str(caught.exception))
        with patch.object(probe.subprocess, 'run', side_effect=OSError('secret')):
            with self.assertRaises(probe.Failure) as caught:
                probe.adb('shell', 'input', 'tap', '100', '200')
        self.assertEqual((caught.exception.operation, caught.exception.outcome), ('tap', 'os_error'))

    def test_invalid_xml_is_rejected(self):
        with self.assertRaisesRegex(probe.Failure, 'hierarchy_invalid'):
            probe.inventory(b'<hierarchy>')


if __name__ == '__main__':
    unittest.main()
