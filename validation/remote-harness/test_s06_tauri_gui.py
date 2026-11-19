import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from s06_tauri_gui import (SplitDriver, exercise_window_resize, layout_matches, observed_tick,
                               peer_connection_evidence, require_same_positions, require_side_by_side,
                               window_dimensions, GuiFailure)
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    observed_tick = None


@unittest.skipIf(observed_tick is None, 'pairing requirements are installed in the native GUI workflow')
class TauriSplitEvidenceTests(unittest.TestCase):
    def test_two_dom_panels_must_actually_share_a_row_without_overlap(self):
        a = dict(left=0, right=100, top=20, width=100, height=400)
        b = dict(left=114, right=214, top=20, width=100, height=500)
        require_side_by_side([a, b]); require_side_by_side([b, a])
        for rectangles in [[a, {**b, 'top': 420}], [a, {**b, 'left': 80}],
                           [a], [a, {**b, 'width': 0}]]:
            with self.assertRaises(GuiFailure):
                require_side_by_side(rectangles)

    def test_window_command_is_sent_once_and_waits_for_real_rect_and_viewport(self):
        calls = []
        viewports = iter(({'width': 1440, 'height': 1168}, {'width': 700, 'height': 1168}))
        def call(method, path, data=None):
            calls.append((method, path, data))
            if path.endswith('/execute/sync'):
                self.assertEqual(data, {'script': 'return {width:innerWidth,height:innerHeight};', 'args': []})
                return next(viewports)
            return {'width': 700, 'height': 1200, 'x': 20, 'y': 30}

        ui = SplitDriver(SimpleNamespace(session='/session/test', call=call))
        self.assertEqual(ui.window(700), {'window': {'width': 700, 'height': 1200},
                                          'viewport': {'width': 700, 'height': 1168}})
        self.assertEqual(calls, [
            ('POST', '/session/test/window/rect', {'width': 700, 'height': 1200}),
            ('GET', '/session/test/window/rect', None),
            ('POST', '/session/test/execute/sync', {'script': 'return {width:innerWidth,height:innerHeight};', 'args': []}),
            ('GET', '/session/test/window/rect', None),
            ('POST', '/session/test/execute/sync', {'script': 'return {width:innerWidth,height:innerHeight};', 'args': []}),
        ])

    def test_unconfirmed_native_resize_fails_without_replaying(self):
        calls = []
        def call(method, path, data=None):
            calls.append((method, path, data))
            return {'width': 1440, 'height': 1200}

        with self.assertRaisesRegex(GuiFailure, '^s06_tauri_window_size_unconfirmed$'):
            SplitDriver(SimpleNamespace(session='/session/test', call=call)).window(700)
        self.assertEqual(len(calls), 1)
        for rectangle in (None, {'width': True, 'height': 1200}, {'width': 700, 'height': 0}):
            with self.assertRaises(GuiFailure):
                window_dimensions(rectangle)

    def test_layout_requires_original_target_focus_and_current_frame(self):
        targets = [('w1:p1', 'term_a001'), ('w1:p1', 'term_b001')]
        a = {'target': list(targets[0]), 'phase': 'active', 'focused': False,
             'currentFrame': True, 'inputControls': False}
        b = {**a, 'target': list(targets[1]), 'focused': True}
        wide = {'views': [a, b], 'split': '2', 'mounted': 2, 'splitVisible': True,
                'stashNotice': False, 'returnVisible': True}
        self.assertTrue(layout_matches(wide, targets, ('active', 'active'), 1))
        for changed in ({'target': list(targets[1])}, {'focused': True}, {'currentFrame': False},
                        {'phase': 'resuming'}, {'inputControls': True}):
            with self.subTest(changed=changed):
                self.assertFalse(layout_matches({**wide, 'views': [{**a, **changed}, b]},
                                                targets, ('active', 'active'), 1))
        narrow = {**wide, 'views': [None, b], 'split': '1', 'mounted': 1,
                  'splitVisible': False, 'stashNotice': True}
        self.assertTrue(layout_matches(narrow, targets, (None, 'active'), 1))
        self.assertFalse(layout_matches({**narrow, 'views': [a, b]}, targets, (None, 'active'), 1))
        self.assertFalse(layout_matches({**narrow, 'stashNotice': None}, targets, (None, 'active'), 1))
        stopped = {**a, 'phase': 'paused', 'currentFrame': False}
        paused_wide = {**wide, 'views': [stopped, {**b, 'phase': 'paused', 'currentFrame': False}]}
        self.assertTrue(layout_matches(paused_wide, targets, ('paused', 'paused'), 1))
        self.assertFalse(layout_matches({**paused_wide, 'views': [a, paused_wide['views'][1]]},
                                        targets, ('paused', 'paused'), 1))

    def test_returned_wide_geometry_cannot_swap_the_two_targets(self):
        a = dict(left=20, right=120, top=20, width=100, height=400)
        b = dict(left=134, right=234, top=20, width=100, height=500)
        before = {'views': [{'rect': a}, {'rect': b}]}
        require_same_positions(before, before)
        with self.assertRaisesRegex(GuiFailure, '^s06_tauri_split_position_changed$'):
            require_same_positions(before, {'views': [{'rect': b}, {'rect': a}]})

    def test_advance_requires_strictly_new_ticks_on_every_requested_side(self):
        ui = SplitDriver(SimpleNamespace())
        samples = iter((20, 30, 21, 30, 21, 31))
        with patch.object(ui, 'collapse_details'), patch.object(ui, 'rendered_tick', side_effect=samples) as tick:
            self.assertEqual(ui.ticks(['a', 'b'], (0, 1), (20, 30)), [21, 31])
            self.assertEqual(tick.call_count, 6)

    def test_tick_failure_exports_only_the_stage_and_hit_geometry(self):
        layout = {'reason': 'row-hit', 'final': {'rowY': 930, 'points': [
            {'x': x, 'y': 930, 'inClient': True, 'target': 'terminal'} for x in (53.2, 137.2, 296.8)]}}
        row = {'text': 'S06 B tick 000041', 'layout': layout}

        def one_poll(probe, code, timeout):
            self.assertIsNone(probe())  # A readable row with the old tick still fails.
            self.assertEqual(timeout, 12)
            raise GuiFailure(code)

        with tempfile.TemporaryDirectory() as directory:
            ui = SplitDriver(SimpleNamespace(), Path(directory))
            with (patch.object(ui, 'collapse_details'), patch.object(ui, 'read', return_value=row),
                  patch('s06_tauri_gui.wait_for', side_effect=one_poll)):
                with self.assertRaisesRegex(GuiFailure, '^s06_tauri_viewport_ticks_unconfirmed_narrow_active$'):
                    ui.ticks(['a', 'b'], (1,), (41,), 'narrow_active')
            report = json.loads((Path(directory) / 's06-tauri-tick-failure.json').read_text())
            self.assertEqual(report, {'stage': 'narrow_active', 'sides': {'1': layout}})

    def test_tick_rejects_obscured_sample_even_with_matching_row_text(self):
        ui = SplitDriver(SimpleNamespace())
        sample = {'text': 'S06 B tick 000041', 'layout': {'reason': 'row-clipped'}}
        with patch.object(ui, 'read', return_value=sample):
            self.assertIsNone(ui.rendered_tick('panel', 1))

    def test_tick_rejects_scroll_that_moves_dom_or_selected_focus(self):
        ui = SplitDriver(SimpleNamespace())
        with patch.object(ui, 'read', return_value={'text': None, 'layout': {'reason': 'focus-changed'}}):
            with self.assertRaisesRegex(GuiFailure, '^s06_tauri_tick_scroll_changed_focus$'):
                ui.rendered_tick('panel', 1)

    def test_replacement_connection_stops_resize_evidence_before_first_capture(self):
        ui = SimpleNamespace(window=lambda width: {'window': {'width': width}}, wait_layout=lambda *args: {},
                             ticks=lambda *args, **kwargs: [10, 20])
        evidence = ({'authenticationCount': 1, 'closed': False}, {'authenticationCount': 2, 'closed': False})
        with patch('s06_tauri_gui.peer_connection_evidence', side_effect=evidence):
            with self.assertRaisesRegex(GuiFailure, '^s06_tauri_resize_did_not_keep_two_original_ssh_connections$'):
                exercise_window_resize(ui, ['a', 'b'], [], [object(), object()], lambda _: None)

    def test_stale_read_relocates_before_the_only_native_click(self):
        for read in ('textContent', 'displayed', 'enabled'):
            calls, lookups = [], []
            def call(method, path, data=None):
                calls.append((method, path))
                if path.endswith('/elements'):
                    lookups.append(1)
                    return [{'element-6066-11e4-a52e-4f735466cecf': 'old' if len(lookups) == 1 else 'new'}]
                if '/old/' in path and path.endswith('/' + read):
                    raise GuiFailure('webdriver_' + read + '_stale_element_reference')
                if path.endswith('/property/textContent'):
                    return '管理'
                return True
            SplitDriver(SimpleNamespace(session='/session/test', call=call)).named('管理')
            self.assertEqual([p for m, p in calls if p.endswith('/click')], ['/session/test/element/new/click'])
            self.assertEqual(len(lookups), 2)

    def test_native_click_failure_is_never_replayed(self):
        clicks = []
        def call(method, path, data=None):
            if path.endswith('/elements'):
                return [{'element-6066-11e4-a52e-4f735466cecf': 'one'}]
            if path.endswith('/property/textContent'):
                return '管理'
            if path.endswith('/click'):
                clicks.append(path)
                raise GuiFailure('webdriver_click_stale_element_reference')
            return True
        with self.assertRaises(GuiFailure):
            SplitDriver(SimpleNamespace(session='/session/test', call=call)).named('管理')
        self.assertEqual(len(clicks), 1)

    def test_manual_pause_requires_the_real_board_and_both_original_paused_panels(self):
        for route, phases, count, accepted in (
            ('dashboard', ['paused', 'paused'], 2, True),
            ('workspace', ['paused', 'paused'], 2, False),
            ('dashboard', ['paused', 'pausing'], 2, False),
            ('dashboard', ['paused', 'unbound'], 2, False),
            ('dashboard', ['paused', 'paused'], 3, False),
        ):
            with self.subTest(route=route, phases=phases, count=count):
                clicks = []
                def call(method, path, data=None):
                    if path.endswith('/elements'):
                        return [{'element-6066-11e4-a52e-4f735466cecf': 'original'}]
                    if path.endswith('/click'):
                        clicks.append((method, path, data))
                        return None
                    raise AssertionError(path)

                def one_poll(probe, code, **kwargs):
                    result = probe()
                    if not result:
                        raise GuiFailure(code)
                    return result

                ui = SplitDriver(SimpleNamespace(session='/session/test', call=call))
                before = {'page': 'workspace', 'phases': ['active', 'active'], 'buttonReady': True}
                after = {'page': route, 'phases': phases, 'viewCount': count, 'buttonReady': False}
                with (patch.object(ui, 'read', side_effect=[before, after]),
                      patch('s06_tauri_gui.wait_for', side_effect=one_poll)):
                    if accepted:
                        ui.pause_on_board(['a', 'b'], [[], []])
                    else:
                        with self.assertRaisesRegex(GuiFailure, '^s06_tauri_manual_pause_unconfirmed$'):
                            ui.pause_on_board(['a', 'b'], [[], []])
                self.assertEqual(clicks, [('POST', '/session/test/element/original/click', {})])

    def test_manual_pause_never_clicks_an_occluded_control_or_replays_click_error(self):
        for button_ready, safe, expected_clicks in ((False, False, 0), (True, False, 1), (True, True, 1)):
            with self.subTest(button_ready=button_ready, safe=safe), tempfile.TemporaryDirectory() as directory:
                clicks = []
                def call(method, path, data=None):
                    if path.endswith('/elements'):
                        return [{'element-6066-11e4-a52e-4f735466cecf': 'original'}]
                    if path.endswith('/click'):
                        clicks.append(path)
                        raise GuiFailure('webdriver_click_unknown_error')
                    raise AssertionError(path)

                def one_poll(probe, code, **kwargs):
                    result = probe()
                    if not result:
                        raise GuiFailure(code)
                    return result

                state = {'page': 'workspace', 'phases': ['active', 'active'], 'buttonReady': button_ready,
                         'safeScreenshot': safe}
                ui = SplitDriver(SimpleNamespace(session='/session/test', call=call), Path(directory))
                with (patch.object(ui, 'read', return_value=state), patch.object(ui, 'screenshot') as shot,
                      patch('s06_tauri_gui.wait_for', side_effect=one_poll)):
                    with self.assertRaises(GuiFailure):
                        ui.pause_on_board(['a', 'b'], [[], []])
                self.assertEqual(len(clicks), expected_clicks)
                if safe:
                    shot.assert_called_once_with('manual-pause-failure')
                else:
                    shot.assert_not_called()
                report = json.loads((Path(directory) / 's06-tauri-manual-pause-failure.json').read_text())
                self.assertEqual(report['clickSent'], button_ready)
                self.assertFalse(report['clickReturned'])
                self.assertIs(report['screenshotSaved'], safe)

    def test_visible_snapshots_require_the_correct_independent_peer_marker(self):
        self.assertEqual(observed_tick('Synthetic observe tick 000123', 0), 123)
        self.assertEqual(observed_tick('S06 B tick 000124', 1), 124)
        for text, side in [('S06 B tick 000124', 0), ('Synthetic observe tick 000123', 1),
                           ('Synthetic observe tick 1', 0), ('', 1),
                           ('S06 B tick 000001 S06 B tick 000002', 1), ('x' * 65537, 0)]:
            with self.subTest(side=side):
                with self.assertRaises(GuiFailure):
                    observed_tick(text, side)

    def test_authentication_and_close_are_for_the_reviewed_key_and_same_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            approval = SimpleNamespace(root=root, config={'username': 'fixture'}, fingerprint='SHA256:reviewed')
            accepted = 'Accepted publickey for fixture from 127.0.0.1 port 40123 ssh2: ED25519 SHA256:reviewed\n'
            other = 'Accepted publickey for fixture from 127.0.0.1 port 40124 ssh2: ED25519 SHA256:other\n'
            closed = 'Received disconnect from 127.0.0.1 port 40123:11: explicit close\n'
            for log, count, done in [(other, 0, False), (accepted, 1, False),
                    (closed + accepted, 1, False), (accepted + closed.replace('40123', '40124'), 1, False),
                    (accepted + closed, 1, True), (accepted + 'Connection closed by 127.0.0.1 port 40123\n', 1, True),
                    (accepted + accepted, 2, False)]:
                (root / 'sshd.log').write_text(log)
                self.assertEqual(peer_connection_evidence(approval), {'authenticationCount': count, 'closed': done})


if __name__ == '__main__':
    unittest.main()
