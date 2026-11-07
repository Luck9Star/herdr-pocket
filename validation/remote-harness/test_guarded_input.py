"""No AVD, real host or credentials; exercise the independent evidence gates."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from guarded_input import (EvidenceError, TUI_KEY_LENGTHS, TUI_SCREEN_CHECKS, expected_bytes,
                           mobile_receipts, mobile_tui_evidence, validate_mode)

spec = importlib.util.spec_from_file_location('guarded_runner', Path(__file__).with_name('run-ci.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class GuardedInputTests(unittest.TestCase):
    def test_tui_requires_a_guarded_android_target(self):
        for route in ('flutter-android', 'tauri-android'):
            validate_mode(route, True, True, True)
            with self.assertRaises(EvidenceError):
                validate_mode(route, True, False, True)
        with self.assertRaises(EvidenceError):
            validate_mode('flutter', True, True, True)

    def test_tui_requires_fresh_screen_steps_and_all_twelve_distinct_receipts(self):
        def receipt(i, size):
            return dict(requestId=f'{i:032x}', paneId='w1:p1', terminalId='term_ab', acceptedBytes=size)

        prior = [receipt(0, 1), receipt(1, 9)]
        keys = [receipt(i, size) for i, size in enumerate(TUI_KEY_LENGTHS, 2)]
        evidence = dict(receipts=keys, observedInitialFull=True, screenChecks=list(TUI_SCREEN_CHECKS))
        self.assertEqual(mobile_tui_evidence(evidence, prior, 'w1:p1', 'term_ab'), evidence)
        with self.assertRaises(EvidenceError):
            mobile_tui_evidence(evidence, prior, 'w1:p1', 'term_cd')
        for change in (
                dict(observedInitialFull=1), dict(screenChecks=list(reversed(TUI_SCREEN_CHECKS))),
                dict(screenChecks=['initial'] * 10), dict(receipts=keys[:-1]), dict(receipts=keys[::-1]),
                dict(receipts=[dict(keys[0], requestId=prior[0]['requestId']), *keys[1:]]),
                dict(receipts=[dict(keys[0], paneId='w2:p1'), *keys[1:]]),
                dict(receipts=keys[:-1] + [dict(keys[-1], terminalId='term_cd')]), dict(clipboard='raw')):
            with self.subTest(fields=list(change)), self.assertRaises(EvidenceError):
                mobile_tui_evidence({**evidence, **change}, prior)

    def test_candidate_mode_report_is_bound_to_the_binary_and_observed_transitions(self):
        digest = 'a' * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'observer-input-modes.json'
            with self.assertRaises(runner.ProbeFailure):
                runner.checked_observer_modes(path, digest)
            step = dict(modeOnlyFrameObserved=True, freshVisualObserved=True)
            record = dict(status='passed', expectation='candidate', binarySha256=digest,
                          version='herdr 0.9.5', canvas=dict(cols=120, rows=40),
                          capabilityVerified=True, initialFull=True, initialVisible=True,
                          initialModeSynchronized=True, sequenceContiguous=True,
                          sharedPtySizeUnchanged=True, ptySampleCount=25, steps=[step] * 4)
            path.write_text(json.dumps(record))
            self.assertEqual(runner.checked_observer_modes(path, digest)['modeTransitions'], 4)
            for change in (dict(status='failed'), dict(expectation='stock'), dict(binarySha256='b' * 64),
                           dict(initialModeSynchronized=1), dict(ptySampleCount=True),
                           dict(steps=[step] * 3), dict(steps=[{**step, 'freshVisualObserved': False}] * 4)):
                with self.subTest(fields=list(change)), self.assertRaises(runner.ProbeFailure):
                    path.write_text(json.dumps({**record, **change}))
                    runner.checked_observer_modes(path, digest)

    def test_stock_is_empty_and_android_requires_explicit_opt_in(self):
        for route in ('tauri-android', 'flutter-android'):
            validate_mode(route, False, False)
            self.assertEqual(expected_bytes(route, False), b'')
            validate_mode(route, True, True)
            self.assertEqual(expected_bytes(route, True), 'kPocket测'.encode())
            for options in ((False, True), (True, False)):
                with self.assertRaises(EvidenceError):
                    validate_mode(route, *options)
        for route in ('flutter', 'tauri'):
            validate_mode(route, True, False)
            self.assertEqual(expected_bytes(route, True), 'Pocket测'.encode())
            with self.assertRaises(EvidenceError):
                validate_mode(route, True, True)
        with self.assertRaises(EvidenceError):
            validate_mode(None, True, False)

    def test_receipts_must_be_distinct_ordered_and_bound_to_the_real_snapshot(self):
        first = {'requestId': '0' * 32, 'paneId': 'w1:p1', 'terminalId': 'term_ab', 'acceptedBytes': 1}
        second = dict(first, requestId='1' * 32, acceptedBytes=9)
        self.assertEqual(mobile_receipts([first, second], 'w1:p1', 'term_ab'), [first, second])
        for raw in (None, [first], [second, first], [first, dict(second, acceptedBytes=True)],
                    [dict(first, paneId='w1:p2'), second], [first, dict(second, terminalId='term_cd')],
                    [first, dict(second, requestId=first['requestId'])], [first, dict(second, body='secret')]):
            with self.assertRaises(EvidenceError):
                mobile_receipts(raw, 'w1:p1', 'term_ab')

    def test_only_a_verified_binary_from_this_build_reaches_the_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / 'input-fixture'
            root.mkdir()
            env = {'RUNNER_TEMP': tmp, 'GITHUB_SHA': '1' * 40}
            binary = b'synthetic executable bytes'
            patch = runner.REPO / 'validation/herdr-input-extension/herdr-0.9.5-pocket-input.patch'
            (root / patch.name).write_bytes(patch.read_bytes())
            metadata = {'sourceSHA': env['GITHUB_SHA'], 'upstreamSHA': runner.HERDR_COMMIT,
                        'patchSHA256': hashlib.sha256(patch.read_bytes()).hexdigest(),
                        'binarySHA256': hashlib.sha256(binary).hexdigest(), 'buildProfile': 'dev',
                        'configDirectory': 'herdr', 'readinessAndCapabilitySmokePassed': True,
                        'binaryDebugAssertions': False, 'scope': 'isolated validation fixture'}
            (root / 'herdr').write_bytes(binary)
            (root / 'manifest.json').write_text(json.dumps(dict(metadata, arbitrary='private')))
            self.assertEqual(runner.load_input_fixture(root, env), (binary, metadata))
            for field, wrong in (('sourceSHA', '2' * 40), ('upstreamSHA', ''), ('patchSHA256', ''),
                                 ('readinessAndCapabilitySmokePassed', 1), ('binaryDebugAssertions', 0),
                                 ('binarySHA256', '0' * 64)):
                (root / 'manifest.json').write_text(json.dumps(dict(metadata, **{field: wrong})))
                with self.assertRaises(runner.ProbeFailure):
                    runner.load_input_fixture(root, env)
            (root / patch.name).write_bytes(b'different patch')
            with self.assertRaisesRegex(runner.ProbeFailure, 'input_fixture_patch_mismatch'):
                runner.load_input_fixture(root, env)
