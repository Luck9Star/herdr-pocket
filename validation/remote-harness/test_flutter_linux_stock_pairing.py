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
    from PIL import Image, ImageDraw
    from flutter_linux_stock_pairing import (
        CANVAS_HEIGHT, CANVAS_WIDTH, DENIAL_NOTICES, OBSERVE_MODE, PAIR_CONNECT, TERM_BG, catalog_reference,
        connection_profile, denial_screens, observe_pixels, observed_tick, reopen, terminal_region,
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
                    ('original-id','opaque-handle','original-label'), approval, 'synthetic-pane', Path('/synthetic/out'))
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
        self.assertIsNone(observed_tick(marker+'\n'+tick.replace('000047','000O47')))

    def test_shifted_terminal_excludes_the_wider_header_and_survives_glyphs(self):
        for left, top in ((304, 335), (416, 235), (192, 270)):
            with self.subTest(left=left, top=top):
                image = Image.new('RGB', (1280, 720), 'white')
                draw = ImageDraw.Draw(image)
                draw.rectangle((left - 144, top - 39, left + CANVAS_WIDTH + 143, top - 1), fill=TERM_BG)
                self.assertIsNone(terminal_region(image))
                draw.rounded_rectangle((left, top, left + CANVAS_WIDTH - 1, top + CANVAS_HEIGHT - 1), 12, fill=TERM_BG)
                # Cover all three old sample columns with foreground at two rows.
                for y in (top + 95, top + 230):
                    for x in (480, 640, 800):
                        draw.rectangle((x - 3, y, x + 3, y + 5), fill='white')
                self.assertEqual(terminal_region(image), (left, top, left + CANVAS_WIDTH, top + CANVAS_HEIGHT))

    def test_terminal_region_rejects_the_broken_crop_and_more_than_one_canvas(self):
        for size, boxes in [((1280, 720), [(416, 429, 1088, 553)]),
                            ((672, 124), [(0, 0, 672, 124)]),
                            ((1280, 820), [(304, 40, 976, 400), (304, 420, 976, 780)]),
                            ((1500, 720), [(50, 240, 722, 600), (760, 240, 1432, 600)])]:
            with self.subTest(size=size, boxes=boxes):
                image = Image.new('RGB', size, 'white')
                draw = ImageDraw.Draw(image)
                for left, top, right, bottom in boxes:
                    draw.rectangle((left, top, right - 1, bottom - 1), fill=TERM_BG)
                self.assertIsNone(terminal_region(image, allow_bottom_clip=True))

    def test_bottom_crop_requests_outer_scroll_before_any_ocr(self):
        config = dict(self.config, paneId='w1:p1')
        ui = Mock()
        ui.visible.return_value = [(1,'pocket-probe · 远端终端'),(2,'pocket-probe / w1:p1'),(3,OBSERVE_MODE)]
        ui.window.return_value = SimpleNamespace(width=1280, height=650)
        image = Image.new('RGB', (1280, 650), 'white')
        ImageDraw.Draw(image).rectangle((304, 335, 975, 649), fill=TERM_BG)
        self.assertIsNone(terminal_region(image))
        self.assertEqual(terminal_region(image, allow_bottom_clip=True), (304, 335, 976, 650))

        def one_sample(probe, code, *, timeout):
            self.assertIsNone(probe())
            raise GuiFailure(code)

        with (tempfile.TemporaryDirectory() as path,
              patch('flutter_linux_stock_pairing.wait_for', side_effect=one_sample),
              patch('flutter_linux_stock_pairing.capture_window', return_value=(image,b'window')),
              patch('flutter_linux_stock_pairing.terminal_ocr') as ocr):
            with self.assertRaisesRegex(GuiFailure, 'stock_flutter_observation_pixels_missing'):
                observe_pixels(ui, config, 1, Path(path))
            ocr.assert_not_called()
            ui.scroll.assert_called_once_with('down', outer=True, steps=1)
            diagnostic = json.loads((Path(path)/'stock-peer-1-observation.json').read_text())
            self.assertTrue(diagnostic['terminalRegionClipped'])

    def test_capture_requires_owned_terminal_and_advancing_exact_tick(self):
        config = dict(self.config, paneId='w1:p1')
        ui = Mock()
        visible = [(1,'pocket-probe · 远端终端'),(2,'pocket-probe / w1:p1'),(3,OBSERVE_MODE)]
        ui.visible.side_effect = [[], visible, visible, visible]
        image = Image.new('RGB',(1000,720),'white')
        ImageDraw.Draw(image).rectangle((185, 280, 856, 639), fill=TERM_BG)
        marker = 'Isolated SSH fixture. Remote input must remain empty.'
        with (tempfile.TemporaryDirectory() as path,
              patch('flutter_linux_stock_pairing.capture_window', side_effect=[(image,b'one'),(image,b'same'),(image,b'two')]),
              patch('flutter_linux_stock_pairing.terminal_ocr', side_effect=[marker+'\nSynthetic observe tick '+tick
                                                                           for tick in ['000041','000041','000042']])):
            self.assertEqual(observe_pixels(ui, config, 1, Path(path)), (b'one',b'two'))
            self.assertEqual(list(Path(path).iterdir()), [])
            ui.scroll.assert_called_once_with('up', outer=True)

    def test_only_owned_terminal_crop_and_fixed_diagnostics_are_written_on_failure(self):
        config = dict(self.config, paneId='w1:p1')
        ui = Mock()
        ui.window.return_value = SimpleNamespace(width=1000, height=720)
        image = Image.new('RGB', (1000, 720), 'white')
        ImageDraw.Draw(image).rectangle((185, 280, 856, 639), fill=TERM_BG)

        def one_sample(probe, code, *, timeout):
            self.assertIsNone(probe())
            raise GuiFailure(code)

        for bound in (False, True):
            with (self.subTest(bound=bound), tempfile.TemporaryDirectory() as path,
                  patch('flutter_linux_stock_pairing.wait_for', side_effect=one_sample),
                  patch('flutter_linux_stock_pairing.capture_window', return_value=(image,b'whole window')) as capture,
                  patch('flutter_linux_stock_pairing.terminal_ocr', return_value='non-artifact OCR text')):
                header = 'pocket-probe / w1:p1' if bound else 'pocket-probe / other-pane'
                ui.visible.return_value = [(1,'pocket-probe · 远端终端'),(2,header),(3,OBSERVE_MODE)]
                output = Path(path)
                with self.assertRaisesRegex(GuiFailure, 'stock_flutter_observation_pixels_missing'):
                    observe_pixels(ui, config, 1, output)
                diagnostic = (output/'stock-peer-1-observation.json').read_text()
                self.assertNotIn('non-artifact OCR text', diagnostic)
                self.assertEqual(json.loads(diagnostic)['terminalHeaderVisible'], bound)
                crop = output/'stock-peer-1-terminal-crop.png'
                if bound:
                    with Image.open(crop) as captured:
                        self.assertEqual(captured.size, (CANVAS_WIDTH,CANVAS_HEIGHT))
                else:
                    capture.assert_not_called()
                    self.assertFalse(crop.exists())
