import json
import os
from pathlib import Path
import tempfile
import unittest

from flutter_linux_stock_ui import ancestor_labels, geometry, unique_match
from paired_gui import GuiFailure

if os.name != 'nt':
    from flutter_linux_stock_pairing import catalog_reference, connection_profile, observed_tick


class StockWindowTests(unittest.TestCase):
    def test_geometry_requires_the_owned_visible_window_id(self):
        raw = 'WINDOW=123\nX=15\nY=20\nWIDTH=1280\nHEIGHT=720\nSCREEN=0\n'
        self.assertEqual(geometry(raw, 123).region, (15, 20, 1295, 740))
        for invalid, window in [(raw, 124), (raw + 'X=20\n', 123), (raw.replace('X=15','X=-15'), 123),
                                (raw.replace('HEIGHT=720', 'HEIGHT=20'), 123)]:
            with self.assertRaisesRegex(GuiFailure, 'stock_flutter_window_geometry_invalid'):
                geometry(invalid, window)

    def test_controls_match_exact_label_and_reject_duplicates(self):
        self.assertEqual(unique_match([(1, 'Open'), (2, 'Open another')], 'Open'), 1)
        self.assertIsNone(unique_match([(1, 'Open another')], 'Open'))
        self.assertEqual(unique_match([(1, 'Open\nSecondary description')], 'Open', prefixes=True), 1)
        with self.assertRaisesRegex(GuiFailure, 'stock_flutter_control_not_unique'):
            unique_match([(1, 'Open'), (2, 'Open\nSecondary description')], 'Open', prefixes=True)

    def test_saved_host_action_requires_both_labels_on_the_same_ancestor(self):
        class Node:
            def __init__(self, name, parent=None):
                self.name, self.parent = name, parent

            def get_name(self):
                return self.name

            def get_parent(self):
                return self.parent

        self.assertTrue(ancestor_labels(Node('Review', Node('Original\nSession A')), ('Original', 'Session A')))
        self.assertFalse(ancestor_labels(Node('Review', Node('Original', Node('Session A'))), ('Original', 'Session A')))
        self.assertFalse(ancestor_labels(Node('Review', Node('Original\nSession A2')), ('Original', 'Session A')))


@unittest.skipIf(os.name == 'nt', 'POSIX fixture and Linux pairing verifier')
class StockPairingTests(unittest.TestCase):
    config = {'host': '127.0.0.1', 'port': 2222, 'username': 'fixture', 'session': 'pocket-probe',
              'socketPath': '/tmp/fixture/herdr/sessions/pocket-probe/herdr.sock', 'herdrPath': '/tmp/fixture/herdr',
              'expectedHostKey': 'ssh-ed25519 parser-only', 'privateKeyPem': 'irrelevant secret fixture'}

    def test_public_import_only_uses_allowed_target_fields(self):
        data = json.loads(connection_profile(self.config))
        self.assertEqual(data['type'], 'herdr-connection-profile')
        self.assertEqual(data['provider'], 'direct')
        self.assertEqual(data['host'], '127.0.0.1')
        self.assertNotIn('privateKeyPem', data)

    def test_catalog_must_keep_the_same_request_opaque_handle_and_target(self):
        request = {'request_id': 'synthetic', 'public_key': 'ssh-ed25519 generated'}
        target = {k: v for k, v in self.config.items() if k != 'privateKeyPem'}
        record = {'id': '1'*32, 'label': 'fixture original', 'enabled': True, 'retired': False,
                  'target': {**target, 'paneId': ''}, 'pairing': {'handle': 'a'*32, 'request': request}}
        data = {'schemaVersion': 4, 'pendingCreation': None, 'profiles': [record]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.json'
            path.write_text(json.dumps(data))
            self.assertEqual(catalog_reference(path, self.config, request), ('1'*32, 'a'*32, 'fixture original'))
            for invalid in ({**data, 'pendingCreation': {'handle':'b'*32}},
                            {**data, 'profiles':[record, record]},
                            {**data, 'profiles':[{**record, 'target':{**target, 'paneId':'w1:p1'}}]}):
                path.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(GuiFailure, 'stock_flutter_catalog_binding_unverified'):
                    catalog_reference(path, self.config, request)

    def test_ocr_requires_one_remote_marker_and_tick(self):
        marker = 'Isolated SSH fixture. Remote input must remain empty.'
        tick = 'SYNTHETIC OBSERVE TICK 000047'
        self.assertEqual(observed_tick(marker+'\n'+tick), 47)
        self.assertIsNone(observed_tick('similar app\n'+tick))
        self.assertIsNone(observed_tick(marker+'\n'+tick+'\n'+tick))
        self.assertIsNone(observed_tick(marker+'\n'+marker+'\n'+tick))
        self.assertIsNone(observed_tick(marker+'\n'+tick+'0'))
