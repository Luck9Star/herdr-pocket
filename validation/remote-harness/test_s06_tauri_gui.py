import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

try:
    from s06_tauri_gui import (SplitDriver, exercise_window_resize, layout_matches, observed_tick,
                               peer_connection_evidence, require_same_positions, require_side_by_side,
                               window_dimensions, exercise_direct_resize, exercise_peer_close, peer_close_sample,
                               owned_xvfb, park_xvfb_pointer, GuiFailure)
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    observed_tick = None


@unittest.skipIf(observed_tick is None, 'pairing requirements are installed in the native GUI workflow')
class TauriSplitEvidenceTests(unittest.TestCase):
    def test_first_key_requires_same_ready_editor_and_records_both_peer_byte_counts(self):
        ready = {'originalTargetsActive': True, 'selectedB': True, 'originalEditorB': True,
                 'aReadOnly': True, 'documentFocused': True, 'bEditorFocused': True,
                 'bModeReady': True, 'bEditorWritable': True, 'bMode': 'direct',
                 'bReceipt': 'absent', 'armed': True, 'keyDowns': 0}
        before = {**ready, 'bModeReady': False, 'bEditorFocused': False, 'bMode': 'observe',
                  'bEditorWritable': False, 'bReadOnly': True, 'armed': False}
        after = {**ready, 'bReceipt': 'matched', 'keyDowns': 1, 'trustedKeyOnOriginalB': True,
                 'events': {'keydown': {'atDocument': 1, 'trustedOriginal': 1, 'fixtureCharacter': 1,
                                       'usableLegacyCode': 1, 'composed': 1, 'preventedAtDocument': 0,
                                       'atEditorAfterHandlers': 1, 'preventedAtEditor': 1,
                                       'text': 'private-key-event'},
                            'beforeinput': {'atDocument': 65, 'trustedOriginal': True},
                            'private-event-kind': {'atDocument': 1}},
                 'ipcTiming': {'calibrated': True, 'completedSendResources': 1, 'url': 'private-ipc-url'}}

        def one_poll(probe, code, **kwargs):
            value = probe()
            if not value:
                raise GuiFailure(code)
            return value

        for states, received, error, sends in (
            ([before, ready, after, after], (b'', b'b'), None, 1),
            *[([before, {**ready, changed: False}, before], (b'', b''),
               'direct_key_not_ready', 0) for changed in (
                   'documentFocused', 'originalTargetsActive', 'originalEditorB', 'selectedB',
                   'aReadOnly', 'bEditorFocused', 'bModeReady', 'bEditorWritable', 'armed')],
            ([before, ready, after], (b'', b''), 'direct_input_missing', 1),
            ([before, ready, after], (b'', b'private-payload'), 'direct_peer_bytes_mismatch', 1),
            ([before, ready, after], (b'b', b'b'), 'direct_peer_bytes_mismatch', 1),
            ([before, ready, ready], None, 'webdriver_actions_unknown_error', 1),
            *[([before, ready, {**after, **changed}, {**after, **changed}],
               (b'', b'b'), 'direct_key_delivery_unconfirmed', 1) for changed in (
                   {'keyDowns': 0}, {'keyDowns': 2}, {'keyDowns': True},
                   {'trustedKeyOnOriginalB': False}, {'bReceipt': 'other'},
               )],
        ):
            with self.subTest(error=error, ready=states[1]), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                wires = tuple(output / side for side in ('a', 'b'))
                for wire in wires:
                    wire.write_bytes(b'')

                def key(value):
                    self.assertEqual(value, 'b')
                    if received is None:
                        raise GuiFailure('webdriver_actions_unknown_error')
                    for wire, data in zip(wires, received):
                        wire.write_bytes(data)

                ui = SplitDriver(SimpleNamespace(), output)
                with (patch.object(ui, 'read', side_effect=states) as read,
                      patch.object(ui, 'named') as named, patch.object(ui, 'keyboard', side_effect=key) as keys,
                      patch('s06_tauri_gui.wait_for', side_effect=one_poll)):
                    if error:
                        code = error if error.startswith('webdriver_') else 's06_tauri_' + error
                        with self.assertRaisesRegex(GuiFailure, '^' + code + '$'):
                            ui.first_direct_key(['a', 'b'], [('p', 'a'), ('p', 'b')], wires)
                    else:
                        ui.first_direct_key(['a', 'b'], [('p', 'a'), ('p', 'b')], wires)
                named.assert_called_once_with('逐键输入', 'b .tab-mode-actions')
                self.assertEqual(keys.call_count, sends)
                self.assertEqual(read.call_args_list[-1].args[-1], 'finish')
                artifact = (output / 's06-tauri-first-direct-key.json').read_text()
                self.assertNotIn('private-payload', artifact)
                self.assertNotIn('private-', artifact)
                evidence = json.loads(artifact)
                self.assertEqual(evidence['keyboardAttempted'], bool(sends))
                self.assertEqual(evidence['peerBefore'], [
                    {'byteCount': 0, 'match': 'empty'}, {'byteCount': 0, 'match': 'empty'}])
                self.assertEqual([peer['byteCount'] for peer in evidence['peerAfter']],
                                 [len(data) for data in (received or (b'', b''))])
                if sends:
                    self.assertEqual(evidence['beforeKey']['keyDowns'], 0)
                    self.assertEqual(evidence['beforeKey']['ipcTiming'], {
                        'calibrated': False, 'status': 'unavailable', 'completedSendResources': None})
                else:
                    self.assertEqual(evidence['stage'], 'before_key')
                if error is None:
                    sample = evidence['afterKey']
                    self.assertEqual(sample['events']['keydown']['preventedAtEditor'], 1)
                    self.assertIsNone(sample['events']['beforeinput']['atDocument'])
                    self.assertIsNone(sample['events']['beforeinput']['trustedOriginal'])
                    self.assertEqual(sample['ipcTiming'], {
                        'calibrated': True, 'status': 'observed', 'completedSendResources': 1})

    def test_only_the_matching_ancestor_owned_xvfb_can_be_prepared(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            env = {'DISPLAY': ':103', 'XAUTHORITY': '/tmp/xvfb-run.fixture/Xauthority'}
            wrapper, server, session = (proc / str(pid) for pid in (100, 101, 102))
            for process in (wrapper, server, session):
                process.mkdir()
            (session / 'cmdline').write_bytes(b'dbus-run-session\0')
            (session / 'status').write_text('PPid:\t100\n')
            (wrapper / 'cmdline').write_bytes(b'/bin/sh\0/usr/bin/xvfb-run\0-a\0')
            children = wrapper / 'task/100/children'
            children.parent.mkdir(parents=True)
            children.write_text('101 102 ')
            argv = server / 'cmdline'
            matching = b'Xvfb\0:103\0-nolisten\0tcp\0-auth\0/tmp/xvfb-run.fixture/Xauthority\0'
            argv.write_bytes(matching)
            self.assertTrue(owned_xvfb(env, proc=proc, parent=102))
            self.assertFalse(owned_xvfb({**env, 'DISPLAY': 'localhost:103'}, proc=proc, parent=102))
            self.assertFalse(owned_xvfb({**env, 'DISPLAY': ':104'}, proc=proc, parent=102))
            self.assertFalse(owned_xvfb({**env, 'XAUTHORITY': '/tmp/another'}, proc=proc, parent=102))
            argv.write_bytes(matching.replace(b'\0tcp\0', b'\0unix\0'))
            self.assertFalse(owned_xvfb(env, proc=proc, parent=102))

    def test_owned_xvfb_parks_pointer_without_clicking_or_changing_focus(self):
        lib = MagicMock()
        lib.XOpenDisplay.return_value = 1
        lib.XDefaultRootWindow.return_value = 2
        lib.XWarpPointer.return_value = 1

        def input_focus(_, focus, __):
            focus._obj.value = 1  # X11 PointerRoot

        lib.XGetInputFocus.side_effect = input_focus
        with (patch('s06_tauri_gui.owned_xvfb', return_value=True),
              patch('s06_tauri_gui.ctypes.CDLL', return_value=lib)):
            with park_xvfb_pointer({'DISPLAY': ':103'}) as parked:
                self.assertTrue(parked)
                lib.XCloseDisplay.assert_not_called()
            lib.XWarpPointer.assert_called_once_with(1, 0, 2, 0, 0, 0, 0, 300, 100)
            lib.XSetInputFocus.assert_not_called()
            lib.XSync.assert_called_once_with(1, 0)
            lib.XCloseDisplay.assert_called_once_with(1)

        with (patch('s06_tauri_gui.owned_xvfb', return_value=False),
              patch('s06_tauri_gui.ctypes.CDLL') as loader):
            with park_xvfb_pointer({'DISPLAY': ':103'}) as parked:
                self.assertFalse(parked)
            loader.assert_not_called()

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

    def test_direct_escape_uses_one_native_chord_and_waits_for_consumed_key(self):
        calls = []
        def call(method, path, body):
            calls.append((method, path, body))

        def one_poll(probe, code, **kwargs):
            result = probe()
            if not result:
                raise GuiFailure(code)
            return result

        ui = SplitDriver(SimpleNamespace(session='/session/test', call=call))
        before = {'originalTargetsActive': True, 'selectedB': True, 'directXterm': True,
                  'bReceiptMatched': True, 'aFocusButtonReady': True}
        after = {'originalTargetsActive': True, 'selectedB': True, 'aFocusButtonFocused': True,
                 'bothReadOnly': True, 'keyCount': 1, 'trustedConsumedChord': True}
        with (patch.object(ui, 'read', side_effect=[before, {**before, 'armed': True}, after]) as read,
              patch('s06_tauri_gui.wait_for', side_effect=one_poll)):
            self.assertEqual(ui.escape_direct_input(['a', 'b'], [('pane-a', 'terminal-a'), ('pane-b', 'terminal-b')]), after)
        self.assertEqual([call.args[-1] for call in read.call_args_list], [False, True, False])
        self.assertEqual(calls, [('POST', '/session/test/actions', {'actions': [{
            'type': 'key', 'id': 's06-native-keyboard', 'actions': [
                {'type': 'keyDown', 'value': '\ue009'}, {'type': 'keyDown', 'value': '\ue008'},
                {'type': 'keyDown', 'value': '\ue036'}, {'type': 'keyUp', 'value': '\ue036'},
                {'type': 'keyUp', 'value': '\ue008'}, {'type': 'keyUp', 'value': '\ue009'},
            ],
        }]})])

    def test_direct_escape_fails_closed_without_resending_key_actions(self):
        before = {'originalTargetsActive': True, 'selectedB': True, 'directXterm': True,
                  'bReceiptMatched': True, 'aFocusButtonReady': True}
        after = {'originalTargetsActive': True, 'selectedB': True, 'aFocusButtonFocused': True,
                 'bothReadOnly': True, 'keyCount': 1, 'trustedConsumedChord': True}

        def one_poll(probe, code, **kwargs):
            result = probe()
            if result is not True:
                raise GuiFailure(code)
            return result

        cases = [
            ([{**before, 'directXterm': False}], 'direct_escape_not_ready', 0),
            ([{**before, 'bReceiptMatched': False}], 'direct_escape_not_ready', 0),
            ([before, {**before, 'armed': False}], 'direct_escape_not_armed', 0),
            *[([before, {**before, 'armed': True}, {**after, **changed}],
               'direct_escape_unconfirmed', 1) for changed in (
                   {'keyCount': 0}, {'keyCount': 2}, {'keyCount': True},
                   {'trustedConsumedChord': False}, {'aFocusButtonFocused': False},
                   {'bothReadOnly': False}, {'selectedB': False}, {'originalTargetsActive': False},
               )],
        ]
        for samples, error, expected_calls in cases:
            with self.subTest(samples=samples):
                calls = []
                def call(method, path, body):
                    calls.append((method, path, body))

                ui = SplitDriver(SimpleNamespace(session='/session/test', call=call))
                with (patch.object(ui, 'read', side_effect=samples),
                      patch('s06_tauri_gui.wait_for', side_effect=one_poll)):
                    with self.assertRaisesRegex(GuiFailure, '^s06_tauri_' + error + '$'):
                        ui.escape_direct_input(['a', 'b'], [('pane-a', 'terminal-a'), ('pane-b', 'terminal-b')])
                self.assertEqual([(method, path) for method, path, _ in calls],
                                 [('POST', '/session/test/actions')] * expected_calls)

    def test_webdriver_action_error_never_resends_chord_or_claims_observation(self):
        calls = []
        def call(method, path, body):
            calls.append((method, path))
            raise GuiFailure('webdriver_actions_unknown_error')

        ui = SplitDriver(SimpleNamespace(session='/session/test', call=call))
        before = {'originalTargetsActive': True, 'selectedB': True, 'directXterm': True,
                  'bReceiptMatched': True, 'aFocusButtonReady': True}
        with patch.object(ui, 'read', side_effect=[before, {**before, 'armed': True}]) as read:
            with self.assertRaisesRegex(GuiFailure, '^webdriver_actions_unknown_error$'):
                ui.escape_direct_input(['a', 'b'], [('pane-a', 'terminal-a'), ('pane-b', 'terminal-b')])
        self.assertEqual(calls, [('POST', '/session/test/actions')])
        self.assertEqual(read.call_count, 2)

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

    def test_guarded_resize_keeps_the_original_input_or_stops_without_further_actions(self):
        targets = [('w1:p1', 'term_a001'), ('w1:p1', 'term_b001')]
        a_rect = dict(left=20, right=120, top=20, width=100, height=400)
        b_rect = {**a_rect, 'left': 134, 'right': 234}
        a = {'target': list(targets[0]), 'phase': 'active', 'focused': False,
             'currentFrame': True, 'inputControls': True, 'rect': a_rect}
        b = {**a, 'target': list(targets[1]), 'focused': True, 'rect': b_rect}
        wide = {'views': [a, b], 'split': '2', 'mounted': 2, 'splitVisible': True,
                'stashNotice': False, 'returnVisible': True, 'domFocusOwner': 'panel-b'}
        narrow = {**wide, 'views': [None, b], 'split': '1', 'mounted': 1,
                  'splitVisible': False, 'stashNotice': True}

        def one_poll(probe, code, **kwargs):
            observed = probe()
            if not observed:
                raise GuiFailure(code)
            return observed

        def fixture(changed=None, *, tick_restored=31, scoped_peer=True):
            widths, commands, checked_bytes = [], [], []
            armed = False

            def read(_, __, ___, action):
                nonlocal armed
                commands.append(action)
                if action == 'arm':
                    armed = True
                narrow_state = widths == [700]
                sample = {key: True for key in ('selectedB', 'targetB', 'directB', 'receiptB',
                                              'originalEditor', 'originalInputState', 'neverBlurred')} | {
                    'armed': armed, 'aPaused': narrow_state, 'aObserves': not narrow_state,
                }
                if narrow_state and changed:
                    sample.update(changed)
                return sample

            def window(width):
                widths.append(width)
                return {'window': width}

            def read_tick(panel, side, *, scroll):
                self.assertEqual((panel, side, scroll), ('a', 0, False))
                return tick_restored if widths else 30

            def peer(_):
                return {'authenticationCount': 2 if not scoped_peer and widths else 1, 'closed': False}

            driver = SimpleNamespace(output=None, read=read, wait_window=lambda width: {'window': width}, window=window,
                                     read_layout=lambda _: narrow if widths == [700] else wide, rendered_tick=read_tick)
            return (driver, widths, commands, checked_bytes, peer)

        for changed, error, resized in (
            (None, None, [700, 1440]),
            ({'neverBlurred': False}, 'input_focus_lost_narrow', [700]),
            ({'originalEditor': False}, 'input_focus_lost_narrow', [700]),
            ({'selectedB': False}, 'input_focus_lost_narrow', [700]),
            ({'originalInputState': False}, 'input_focus_lost_narrow', [700]),
            ({'receiptB': False}, 'input_focus_lost_narrow', [700]),
            ({'aPaused': False}, 'layout_narrow', [700]),
        ):
            with self.subTest(changed=changed):
                driver, widths, commands, checked, peer = fixture(changed)
                with (patch('s06_tauri_gui.wait_for', side_effect=one_poll),
                      patch('s06_tauri_gui.peer_connection_evidence', side_effect=peer)):
                    if error:
                        with self.assertRaisesRegex(GuiFailure, '^s06_tauri_direct_resize_' + error + '$'):
                            exercise_direct_resize(driver, ['a', 'b'], targets, [object(), object()], checked.append)
                        self.assertNotIn('finish', commands)
                    else:
                        proof = exercise_direct_resize(driver, ['a', 'b'], targets, [object(), object()], checked.append)
                        self.assertEqual(proof['aFixtureTicks'], [30, 31])
                        self.assertEqual(proof['domFocusOwnerSamples'], ['panel-b'] * 3)
                        self.assertEqual(proof['peerInputBytesBeforeEscape'], [0, 1])
                        self.assertEqual(checked, [(b'', b'b')] * 3)
                        self.assertEqual(commands[-1], 'finish')
                self.assertEqual(widths, resized)
                self.assertEqual(commands.count('arm'), 1)

        for options, error in (({'tick_restored': 30}, 'a_tick_wide_restored'),
                               ({'scoped_peer': False}, 'peer_changed_narrow')):
            driver, _, _, checked, peer = fixture(**options)
            with (patch('s06_tauri_gui.wait_for', side_effect=one_poll),
                  patch('s06_tauri_gui.peer_connection_evidence', side_effect=peer),
                  self.assertRaisesRegex(GuiFailure, '^s06_tauri_direct_resize_' + error + '$')):
                exercise_direct_resize(driver, ['a', 'b'], targets, [object(), object()], checked.append)

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

    def test_return_to_manual_pause_requires_the_terminal_before_touching_pairing(self):
        targets = [('w1:p1', 'term_a001'), ('w1:p1', 'term_b001')]
        views = [{'target': list(target), 'phase': 'paused', 'focused': side == 1,
                  'currentFrame': False, 'inputControls': False} for side, target in enumerate(targets)]
        layout = {'views': views, 'split': '2', 'mounted': 2, 'splitVisible': True,
                  'stashNotice': False, 'returnVisible': True, 'domFocusOwner': 'outside-panels'}
        terminal = {**layout, 'page': 'terminal', 'pairing': 'closed'}
        open_pairing = {**terminal, 'pairing': 'open'}
        board = {**open_pairing, 'page': 'dashboard'}
        wrong_focus = {**terminal, 'views': [views[0], {**views[1], 'focused': False}]}
        for snapshots, pairing_click, error in (
            ([board, open_pairing, terminal], True, None),
            ([terminal, terminal], False, None),
            ([board], False, 's06_tauri_manual_return_route_unconfirmed'),
            ([{**terminal, 'pairing': 'unproven'}], False, 's06_tauri_manual_return_pairing_unproven'),
            ([open_pairing, open_pairing], True, 's06_tauri_layout_manual_paused'),
            ([terminal, wrong_focus], False, 's06_tauri_layout_manual_paused'),
        ):
            with self.subTest(error=error, pairing_click=pairing_click):
                pending = iter(snapshots)
                events = []
                def read(panels):
                    self.assertEqual(panels, ['a', 'b'])
                    events.append('observe')
                    return next(pending, snapshots[-1])

                def bounded_poll(probe, code, **kwargs):
                    for _ in range(2):
                        if result := probe():
                            return result
                    raise GuiFailure(code)

                driver = SimpleNamespace(click=lambda selector: events.append(selector))
                ui = SplitDriver(driver)
                with (patch.object(ui, 'read_layout', side_effect=read),
                      patch.object(ui, 'named', side_effect=lambda *args: events.append('summary')) as named,
                      patch('s06_tauri_gui.wait_for', side_effect=bounded_poll)):
                    if error is None:
                        ui.return_to_paused_split(['a', 'b'], targets, 1)
                    else:
                        with self.assertRaisesRegex(GuiFailure, '^' + error + '$'):
                            ui.return_to_paused_split(['a', 'b'], targets, 1)

                self.assertEqual(events[0], '#nav-terminal')
                self.assertEqual(events.count('#nav-terminal'), 1)
                if pairing_click:
                    named.assert_called_once_with('配对与连接资料', '#remote-page #remote-setup', '> summary')
                    self.assertEqual(events[events.index('summary') - 1], 'observe')
                else:
                    named.assert_not_called()

    def test_manual_return_failure_exports_only_known_values_and_requires_safe_capture(self):
        secret = 'do-not-publish-ax-or-target'
        sample = {'page': 'terminal', 'pairing': 'open', 'domFocusOwner': secret,
                  'views': [{'target': [secret, secret], 'phase': secret, 'focused': False,
                             'currentFrame': False, 'inputControls': False, 'rect': secret},
                            {'target': ['pane-b', 'term-b'], 'phase': 'paused', 'focused': True,
                             'currentFrame': False, 'inputControls': False}]}
        def one_poll(probe, code, **kwargs):
            if result := probe():
                return result
            raise GuiFailure(code)

        for safe in (False, True):
            with self.subTest(safe=safe), tempfile.TemporaryDirectory() as directory:
                clicks = []
                ui = SplitDriver(SimpleNamespace(click=clicks.append), Path(directory))
                # A one-shot click can lose its result. A later read cannot authorize a replay.
                with (patch.object(ui, 'read_layout', return_value=sample),
                      patch.object(ui, 'named', side_effect=GuiFailure('webdriver_click_unknown_error')) as named,
                      patch.object(ui, 'read', return_value={'safeScreenshot': safe}),
                      patch.object(ui, 'screenshot') as shot,
                      patch('s06_tauri_gui.wait_for', side_effect=one_poll)):
                    with self.assertRaisesRegex(GuiFailure, '^webdriver_click_unknown_error$'):
                        ui.return_to_paused_split(['a', 'b'], [('pane-a', 'term-a'), ('pane-b', 'term-b')], 1)
                named.assert_called_once()
                self.assertEqual(clicks, ['#nav-terminal'])
                if safe:
                    shot.assert_called_once_with('manual-return-failure')
                else:
                    shot.assert_not_called()
                raw = (Path(directory) / 's06-tauri-manual-return-failure.json').read_text()
                self.assertNotIn(secret, raw)
                self.assertNotIn('term-b', raw)
                self.assertEqual(json.loads(raw), {
                    'page': 'terminal', 'pairing': 'open', 'domFocusOwner': 'other',
                    'sides': [{'targetMatches': False, 'phase': 'other', 'focused': False,
                               'currentFrame': False, 'inputControls': False},
                              {'targetMatches': True, 'phase': 'paused', 'focused': True,
                               'currentFrame': False, 'inputControls': False}],
                    'screenshotSaved': safe})

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
                    (accepted + 'Connection closed by 127.0.0.1 port 40123 [preauth]\n', 1, False),
                    (accepted + other.replace('40124', '40123') + closed, 1, False),
                    (accepted + 'Disconnected from user stranger 127.0.0.1 port 40123\n', 1, False),
                    (accepted + accepted, 2, False)]:
                (root / 'sshd.log').write_text(log)
                self.assertEqual(peer_connection_evidence(approval), {'authenticationCount': count, 'closed': done})

    def test_auth_bound_reset_and_socket_state_are_diagnostics_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            approval = SimpleNamespace(root=root, config={'username': 'fixture', 'port': 30333}, fingerprint='SHA256:reviewed')
            log = root / 'sshd.log'
            log.write_text('Accepted publickey for fixture from 127.0.0.1 port 40123 ssh2: ED25519 SHA256:reviewed\n')
            with patch('s06_tauri_gui.loopback_tcp_states', return_value={(30333, 40123): '01', (30333, 40124): '06'}):
                self.assertEqual(peer_close_sample([approval]), [
                    {'authenticationCount': 1, 'recognizedCloseCount': 0, 'resetCount': 0, 'socketState': 'established'}])
            with log.open('ab') as handle:
                handle.write(b'Read error from remote host 127.0.0.1 port 40123: Connection reset by peer\r\n')
            with patch('s06_tauri_gui.loopback_tcp_states', return_value={}):
                self.assertEqual(peer_close_sample([approval]), [
                    {'authenticationCount': 1, 'recognizedCloseCount': 0, 'resetCount': 1, 'socketState': 'absent'}])
            self.assertEqual(peer_connection_evidence(approval), {'authenticationCount': 1, 'closed': False})
            with log.open('ab') as handle:
                handle.write(b'Disconnected from user fixture 127.0.0.1 port 40123\r\n')
            with patch('s06_tauri_gui.loopback_tcp_states', return_value={}):
                self.assertEqual(peer_close_sample([approval]), [
                    {'authenticationCount': 1, 'recognizedCloseCount': 1, 'resetCount': 1, 'socketState': 'absent'}])

    def test_close_reports_both_clicks_and_peers_before_driver_exit(self):
        active = {'authenticationCount': 1, 'recognizedCloseCount': 0, 'resetCount': 0, 'socketState': 'established'}
        closed = {**active, 'recognizedCloseCount': 1, 'socketState': 'absent'}
        reset = {**active, 'resetCount': 1, 'socketState': 'absent'}

        def one_poll(probe, code, **kwargs):
            if code.endswith('peer_close_unconfirmed'):
                self.assertEqual(kwargs['timeout'], 12)
            if not probe():
                raise GuiFailure(code)
            return True

        for end, error in (([closed, closed], None), ([closed, reset], 'peer_close_unconfirmed'),
                           ([closed, {**closed, 'resetCount': 1}], 'peer_close_unconfirmed'),
                           ([closed, {**active, 'socketState': 'absent'}], 'peer_close_unconfirmed'),
                           ([closed, {**closed, 'authenticationCount': 2}], 'peer_close_unconfirmed')):
            with self.subTest(end=end), tempfile.TemporaryDirectory() as temp:
                ui = SimpleNamespace(output=Path(temp), focus=MagicMock(), named=MagicMock(), read=MagicMock(return_value=True))
                samples = [[active, active], [active, active], [closed, active], [closed, active], end, end]
                with (patch('s06_tauri_gui.peer_close_sample', side_effect=samples),
                      patch('s06_tauri_gui.wait_for', side_effect=one_poll)):
                    if error:
                        with self.assertRaisesRegex(GuiFailure, '^s06_tauri_' + error + '$'):
                            exercise_peer_close(ui, ['a', 'b'], ['unused-a', 'unused-b'])
                    else:
                        self.assertEqual(exercise_peer_close(ui, ['a', 'b'], ['unused-a', 'unused-b']), [1, 1])
                self.assertEqual([call.args for call in ui.named.call_args_list], [
                    ('关闭此标签', 'a .tab-connection-actions'), ('关闭此标签', 'b .tab-connection-actions')])
                report = json.loads((ui.output / 's06-tauri-peer-close.json').read_text())
                self.assertEqual(report['final'], end)
                self.assertTrue(report['workspaceHidden'])
                self.assertTrue(all(step['panelRemoved'] for step in report['steps']))


if __name__ == '__main__':
    unittest.main()
