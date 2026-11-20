from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from flutter_linux_stock_ui import StockWindow, ancestor_labels, geometry, unique_match
from paired_gui import GuiFailure

if os.name != 'nt':
    from flutter_linux_stock_pairing import (
        DENIAL_NOTICES, PAIR_CONNECT, catalog_reference, connection_profile, denial_screens, observed_tick, reopen,
    )


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

    def test_disabled_button_requires_the_live_owned_role_state_and_no_tap(self):
        ui = StockWindow.__new__(StockWindow)
        ui.atspi = SimpleNamespace(Role=SimpleNamespace(PUSH_BUTTON='button'),
                                   StateType=SimpleNamespace(ENABLED='enabled', SENSITIVE='sensitive'))
        ui.glib = SimpleNamespace(Error=ValueError)
        ui.find, ui.check_focus = Mock(), Mock()
        node = Mock()
        node.get_interfaces.return_value = ['Action']
        ui.visible = Mock(return_value=[(node, 'Connect')])
        for role, states, actions in (('button', ('sensitive',), ()), ('button', (), ()),
                                      ('button', ('sensitive', 'enabled'), ()), ('button', ('sensitive',), ('Tap',)),
                                      ('label', ('sensitive',), ())):
            with self.subTest(role=role, states=states, actions=actions):
                node.get_role.return_value = role
                node.get_state_set.return_value = SimpleNamespace(contains=states.__contains__)
                node.get_n_actions.return_value = len(actions)
                node.get_action_name.side_effect = lambda i: actions[i]
                if role == 'button' and states == ('sensitive',) and not actions:
                    ui.disabled_button('fixture_missing', 'Connect')
                else:
                    with self.assertRaisesRegex(GuiFailure, 'fixture_missing_not_disabled'):
                        ui.disabled_button('fixture_missing', 'Connect')
        node.do_action.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'POSIX fixture and Linux pairing verifier')
    def test_denial_capture_requires_each_specific_notice_and_disabled_action(self):
        self.assertNotEqual(DENIAL_NOTICES['locked'], DENIAL_NOTICES['unavailable'])
        for mode, notice in DENIAL_NOTICES.items():
            with self.subTest(mode=mode):
                ui = Mock()
                with patch('flutter_linux_stock_pairing.capture_window', side_effect=[(None, b'notice'), (None, b'button')]):
                    self.assertEqual(denial_screens(ui, mode), {'stock-second-denial-notice.png': b'notice',
                                                               'stock-second-denial-connect.png': b'button'})
                self.assertEqual(ui.find.call_args_list, [call('stock_flutter_denial_notice_missing', notice),
                                                          call('stock_flutter_denial_notice_changed', notice)])
                self.assertEqual(ui.disabled_button.call_args_list, [call('stock_flutter_denial_connect_missing', PAIR_CONNECT, scroll='down'),
                                                                     call('stock_flutter_denial_connect_changed', PAIR_CONNECT)])
                ui.tap.assert_not_called()


@unittest.skipIf(os.name == 'nt', 'POSIX fixture and Linux pairing verifier')
class StockPairingTests(unittest.TestCase):
    config = {'host': '127.0.0.1', 'port': 2222, 'username': 'fixture', 'session': 'pocket-probe',
              'socketPath': '/tmp/fixture/herdr/sessions/pocket-probe/herdr.sock', 'herdrPath': '/tmp/fixture/herdr',
              'expectedHostKey': 'ssh-ed25519 parser-only', 'privateKeyPem': 'irrelevant secret fixture'}

    def test_denied_reopen_never_runs_second_ssh_and_requires_the_first_peer_closed(self):
        prefix = 'flutter_linux_stock_pairing.'
        first = SimpleNamespace(returncode=0, pid=1)
        second = SimpleNamespace(pid=2)
        ui = Mock()
        approval = Mock()
        with (patch(prefix+'owned_process', return_value=nullcontext(second)),
              patch(prefix+'StockWindow', return_value=ui), patch(prefix+'denial_screens', return_value={'proof':b'png'}),
              patch(prefix+'observe') as connect, patch(prefix+'stop') as stop, patch(prefix+'require_peers') as peers):
            args = (Path('/synthetic/probe'), Path('/synthetic'), {}, None, None, first, self.config,
                    ('original-id','opaque-handle','original-label'), approval, 'synthetic-pane')
            peers.return_value = False
            with self.assertRaisesRegex(GuiFailure, 'stock_flutter_denial_original_peer_unproven'):
                reopen(*args, mode='locked')
            peers.return_value = True
            self.assertEqual(reopen(*args, mode='unavailable'), {'proof':b'png'})
            self.assertEqual(peers.call_args_list, [call(approval, 1, all_closed=True)]*2)
            connect.assert_not_called()
            stop.assert_not_called()
            ui.close.assert_called_once()

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
