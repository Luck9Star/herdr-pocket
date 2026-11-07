import unittest
from mobile_blocked_result import checked_receipt, checked_targets


class MobileBlockedResultTests(unittest.TestCase):
    targets = [{'paneId': 'w2:p1', 'terminalId': 'term_a'}, {'paneId': 'w3:p1', 'terminalId': 'term_b'}]

    def receipt(self):
        return dict(self.targets[1], listedRows=2, reviewRequired=True, observing=True,
                    markerMatched=True, otherMarkerAbsent=True)

    def test_receipt_selects_the_second_exact_binding(self):
        raw = self.receipt()
        self.assertEqual(checked_receipt(raw, self.targets), raw)
        for edits in [self.targets[0], {'paneId': 'w2:p1'}, {'otherMarkerAbsent': False},
                      {'observing': 1}, {'listedRows': True}, {'listedRows': 2.0},
                      {'listedRows': 3}, {'terminalText': 'private'}]:
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                checked_receipt(raw | edits, self.targets)
        for key in raw:
            with self.subTest(missing=key), self.assertRaises(ValueError):
                checked_receipt({k: v for k, v in raw.items() if k != key}, self.targets)

    def test_targets_must_be_two_distinct_bounded_pairs(self):
        a, b = self.targets
        for rows in [[], [b], [b, b], [a, b | {'paneId': a['paneId']}],
                     [a, b | {'terminalId': a['terminalId']}], [a, b | {'terminalId': None}],
                     [a, b | {'debug': True}], [a, b | {'paneId': 'bad\nselector'}]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                checked_targets(rows)
