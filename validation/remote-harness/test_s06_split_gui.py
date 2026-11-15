"""Portable S06 evidence gate tests; no personal SSH or external connections."""
import copy
import unittest

try:
    from s06_split_gui import REQUIRED, checked_widget_result, GuiFailure
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    checked_widget_result = None


@unittest.skipIf(checked_widget_result is None, 'pairing requirements are installed in the GUI workflow')
class S06EvidenceTests(unittest.TestCase):
    def evidence(self, guarded=False):
        return {**{key: True for key in REQUIRED}, 'sides': [
            {'connectionCount': 1, 'frameCount': 8, 'deltaFrames': 5, 'inputAccepted': guarded}
            for _ in range(2)]}

    def test_both_sides_must_independently_receive_real_full_and_delta_frames(self):
        for guarded in (False, True):
            valid = self.evidence(guarded)
            self.assertEqual(len(checked_widget_result(valid, guarded)['sides']), 2)
            for index in range(2):
                for key, bad in [('connectionCount', 2), ('connectionCount', True),
                                 ('frameCount', 1), ('deltaFrames', 0), ('deltaFrames', True),
                                 ('inputAccepted', not guarded)]:
                    value = copy.deepcopy(valid)
                    value['sides'][index][key] = bad
                    with self.subTest(guarded=guarded, side=index, field=key, bad=bad):
                        with self.assertRaises(GuiFailure):
                            checked_widget_result(value, guarded)

    def test_every_named_safety_checkpoint_is_mandatory_and_not_truthy(self):
        for key in REQUIRED:
            for bad in (None, False, 1, 'true'):
                value = self.evidence()
                value[key] = bad
                with self.subTest(key=key, bad=bad):
                    with self.assertRaises(GuiFailure):
                        checked_widget_result(value, False)

    def test_only_public_boolean_and_numeric_fields_can_be_published(self):
        value = self.evidence()
        value['privateKeyPem'] = 'must-never-export'
        value['sides'][0]['rawTerminalBytes'] = 'must-never-export'
        clean = checked_widget_result(value, False)
        self.assertNotIn('privateKeyPem', clean)
        self.assertNotIn('rawTerminalBytes', clean['sides'][0])
        for value in (None, [], {}, {'sides': []}, {**self.evidence(), 'sides': [None, None]}):
            with self.assertRaises(GuiFailure):
                checked_widget_result(value, False)


if __name__ == '__main__':
    unittest.main()
