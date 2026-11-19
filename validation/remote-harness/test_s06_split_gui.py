"""Portable S06 evidence gate tests; no personal SSH or external connections."""
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from s06_split_gui import (REQUIRED, STOCK_CLOSE_CHECK, acknowledge_stock_close,
                               checked_widget_result, failure_diagnostics, stock_peers_match, widget_failure, GuiFailure)
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    checked_widget_result = None


@unittest.skipIf(checked_widget_result is None, 'pairing requirements are installed in the GUI workflow')
class S06EvidenceTests(unittest.TestCase):
    def evidence(self, guarded=False):
        return {**{key: True for key in REQUIRED}, 'sides': [
            {'connectionCount': 1, 'frameCount': 8, 'deltaFrames': 5, 'inputAccepted': guarded}
            for _ in range(2)], **({STOCK_CLOSE_CHECK: True} if not guarded else {})}

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
        for key in (*REQUIRED, STOCK_CLOSE_CHECK):
            for bad in (None, False, 1, 'true'):
                value = self.evidence()
                value[key] = bad
                with self.subTest(key=key, bad=bad):
                    with self.assertRaises(GuiFailure):
                        checked_widget_result(value, False)

    def test_focused_close_is_required_and_published_only_for_flutter_stock(self):
        stock = self.evidence()
        self.assertIs(checked_widget_result(stock, False)[STOCK_CLOSE_CHECK], True)
        stock.pop(STOCK_CLOSE_CHECK)
        with self.assertRaisesRegex(GuiFailure, 's06_widget_checks_incomplete'):
            checked_widget_result(stock, False)
        guarded = self.evidence(guarded=True)
        self.assertNotIn(STOCK_CLOSE_CHECK, checked_widget_result(guarded, True))
        guarded[STOCK_CLOSE_CHECK] = True
        self.assertNotIn(STOCK_CLOSE_CHECK, checked_widget_result(guarded, True))

    def test_acknowledgement_requires_original_a_closed_and_original_b_still_open(self):
        def probe_once(probe, code, *, timeout):
            self.assertGreater(timeout, 0)
            if not probe():
                raise GuiFailure(code)

        def accept(port, fingerprint):
            return f'Accepted publickey for fixture from 127.0.0.1 port {port} ssh2: ED25519 {fingerprint}\n'

        def disconnect(port):
            return f'Disconnected from user fixture 127.0.0.1 port {port}\n'

        with tempfile.TemporaryDirectory() as temp, patch('s06_split_gui.wait_for', side_effect=probe_once):
            root = Path(temp)
            peers = [SimpleNamespace(root=root, config={'username': 'fixture'}, fingerprint=key)
                     for key in ('SHA256:fixture-a', 'SHA256:fixture-b')]
            log = root / 'sshd.log'
            connected = accept(2201, peers[0].fingerprint) + accept(2202, peers[1].fingerprint)
            ack = root / 'focused-close-ack'
            proc = SimpleNamespace(poll=lambda: None)
            deadline = time.monotonic() + 30
            with self.assertRaisesRegex(GuiFailure, 's06_focused_close_request_timeout'):
                acknowledge_stock_close(root, peers, proc, deadline)
            (root / 'focused-close-request').touch()
            closed_a = connected + disconnect(2201)
            for contents in (connected + disconnect(2210), closed_a + disconnect(2202),
                             closed_a + accept(2203, peers[1].fingerprint)):
                log.write_text(contents)
                with self.assertRaisesRegex(GuiFailure, 's06_focused_peer_close_unconfirmed'):
                    acknowledge_stock_close(root, peers, proc, deadline)
                self.assertFalse(ack.exists())
            log.write_text(closed_a)
            acknowledge_stock_close(root, peers, proc, deadline)
            self.assertTrue(ack.is_file())
            self.assertFalse(stock_peers_match(peers, both_closed=True))
            log.write_text(closed_a + disconnect(2202))
            self.assertTrue(stock_peers_match(peers, both_closed=True))
            log.write_text(closed_a + disconnect(2202) + accept(2203, peers[1].fingerprint) + disconnect(2203))
            self.assertFalse(stock_peers_match(peers, both_closed=True))

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

    def test_failure_stages_and_locations_never_export_messages_or_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'stage').write_text('s06_connect_0')
            self.assertEqual(str(widget_failure(root, 'failed')), 'failed_s06_connect_0')
            (root / 'stage').write_text('private-message')
            self.assertEqual(str(widget_failure(root, 'failed')), 'failed')
            (root / 'failure.json').write_text(json.dumps({'kind': 'TestFailure',
                'locations': ['s06_real_ssh_test.dart:123:4'], 'message': 'do-not-export'}))
            self.assertEqual(failure_diagnostics(root), {'kind': 'TestFailure',
                'locations': ['s06_real_ssh_test.dart:123:4']})
            for invalid in [{'kind': 'private message', 'locations': []},
                            {'kind': 'TestFailure', 'locations': ['/private/raw.log:1']}, []]:
                (root / 'failure.json').write_text(json.dumps(invalid))
                self.assertEqual(failure_diagnostics(root), {'valid': False})


if __name__ == '__main__':
    unittest.main()
