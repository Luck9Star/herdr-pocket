"""Local tests only exercise evidence/isolation guards, never SSH or a host."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('remote_harness', Path(__file__).with_name('run-ci.py'))
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def result(case='positive', **changes):
    value = {'status': 'passed', 'case': case, 'hostKeyChecked': True, 'hostKeyMatched': True,
             'authStarted': True, 'snapshotReceived': True, 'fullFrameReceived': True,
             'generation': 1, 'lateEventsIgnored': 0, 'errorCode': None}
    value.update(changes)
    return value


class HarnessGuards(unittest.TestCase):
    def test_local_or_wrong_branch_never_enters_fixture_setup(self):
        for env in ({}, {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '123', 'GITHUB_REF': 'refs/heads/main'},
                    {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '../secret', 'GITHUB_REF': 'refs/heads/codex/test'}):
            with self.assertRaises(harness.ProbeFailure):
                harness.require_runner(env)
        harness.require_runner({'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '123', 'GITHUB_REF': 'refs/heads/codex/test'})

    def test_report_allowlist_drops_config_and_remote_output(self):
        raw = result(privateKeyPem='PRIVATE FIXTURE', stdout='REMOTE DATA', config={'password': 'never-copy'})
        safe = harness.safe_report(raw, 'positive')
        self.assertNotIn('privateKeyPem', safe)
        self.assertNotIn('config', safe)
        self.assertNotIn('stdout', safe)
        self.assertEqual(safe, result())

    def test_report_types_and_codes_cannot_smuggle_data(self):
        for changes in ({'authStarted': 1}, {'generation': True}, {'lateEventsIgnored': -1},
                        {'errorCode': 'private key: material'}, {'case': 'wrong-pin'}, {'status': 'success'}):
            with self.assertRaises(harness.ProbeFailure):
                harness.safe_report(result(**changes), 'positive')

    def test_wrong_pin_cannot_pass_for_tcp_failure_or_authentication(self):
        good = result('wrong-pin', hostKeyMatched=False, authStarted=False,
                      snapshotReceived=False, fullFrameReceived=False, errorCode='host_key_mismatch')
        harness.validate_evidence(good, 'wrong-pin')
        for changes in ({'hostKeyChecked': False}, {'authStarted': True}, {'hostKeyMatched': True}):
            with self.assertRaises(harness.ProbeFailure):
                harness.validate_evidence(dict(good, **changes), 'wrong-pin')

    def test_missing_session_requires_a_real_authenticated_snapshot(self):
        good = result('missing-session', fullFrameReceived=False, errorCode='session_mismatch')
        harness.validate_evidence(good, 'missing-session')
        for changes in ({'authStarted': False}, {'snapshotReceived': False}, {'fullFrameReceived': True}):
            with self.assertRaises(harness.ProbeFailure):
                harness.validate_evidence(dict(good, **changes), 'missing-session')

    def test_cancel_requires_actual_ssh_not_only_preconnect_model(self):
        good = result('cancel', fullFrameReceived=False, errorCode='cancelled')
        harness.validate_evidence(good, 'cancel')
        for changes in ({'authStarted': False}, {'snapshotReceived': False},
                        {'fullFrameReceived': True}, {'errorCode': 'timeout'}):
            with self.assertRaises(harness.ProbeFailure):
                harness.validate_evidence(dict(good, **changes), 'cancel')

    def test_positive_requires_complete_evidence(self):
        harness.validate_evidence(result(), 'positive')
        for field in harness.BOOL_FIELDS:
            with self.assertRaises(harness.ProbeFailure):
                harness.validate_evidence(result(**{field: False}), 'positive')

    def test_observe_requires_real_frames_and_active_cancel(self):
        good = result('observe-positive', errorCode='cancelled', paneCount=2,
                      frameCount=3, deltaFrames=2, lastSeq=3, connectionCount=1,
                      bufferHighWaterBytes=512)
        clean = harness.safe_report(dict(good, terminalText='never publish'), 'observe-positive')
        self.assertNotIn('terminalText', clean)
        harness.validate_evidence(clean, 'observe-positive')
        for changes in ({'fullFrameReceived': False}, {'snapshotReceived': False},
                        {'frameCount': 1}, {'deltaFrames': 0}, {'connectionCount': 2},
                        {'paneCount': 0}, {'errorCode': None}, {'lastSeq': None},
                        {'bufferHighWaterBytes': 0}, {'deltaFrames': 3}):
            with self.assertRaises(harness.ProbeFailure):
                harness.validate_evidence(dict(clean, **changes), 'observe-positive')
        for changes in ({'frameCount': True}, {'paneCount': 257}, {'deltaFrames': -1},
                        {'lastSeq': 'private'}, {'lastSeq': True}, {'bufferHighWaterBytes': 65_537}):
            with self.assertRaises(harness.ProbeFailure):
                harness.safe_report(dict(good, **changes), 'observe-positive')

    def test_observe_reconnect_is_two_explicit_connections(self):
        good = result('observe-reconnect', errorCode='cancelled', paneCount=1,
                      frameCount=4, deltaFrames=2, lastSeq=2, connectionCount=2,
                      bufferHighWaterBytes=512)
        harness.validate_evidence(good, 'observe-reconnect')
        for changes in ({'connectionCount': 1}, {'frameCount': 3}, {'deltaFrames': 1}):
            with self.assertRaises(harness.ProbeFailure):
                harness.validate_evidence(dict(good, **changes), 'observe-reconnect')
        first_full = dict(good, case='observe-cancel', frameCount=1, deltaFrames=0, connectionCount=1)
        harness.validate_evidence(first_full, 'observe-cancel')
        with self.assertRaises(harness.ProbeFailure):
            harness.validate_evidence(dict(first_full, frameCount=2), 'observe-cancel')

    def test_protocol_diagnostics_exclude_remote_content_and_arbitrary_fields(self):
        data = {'version': '0.9.5+build-1', 'protocol': 22, 'panes': [{'private': 'never'}],
                'privateKeyPem': 'never'}
        safe = harness.protocol_diagnostics(data)
        self.assertEqual(set(safe), {'version', 'protocol'})
        self.assertEqual(safe['protocol']['value'], 22)
        self.assertNotIn('value', harness.protocol_diagnostics({'version': 'line\nsecret'})['version'])
        self.assertFalse(harness.protocol_diagnostics({})['protocol']['present'])
        nested = harness.protocol_diagnostics({'protocol': {'version': 22, 'arbitrary': 'never'}})
        self.assertEqual(nested['protocol']['nestedKnownFields']['version']['value'], 22)
        self.assertNotIn('arbitrary', str(nested))
        wrapper = harness.snapshot_diagnostics({'type':'session_snapshot', 'snapshot':data})
        self.assertEqual(wrapper['resultType'], 'session_snapshot')
        self.assertTrue(wrapper['snapshotPresent'])
        self.assertEqual(wrapper['nestedKnownFields']['protocol']['value'], 22)
        self.assertNotIn('panes', str(wrapper))
        self.assertFalse(wrapper['flatKnownFields']['protocol']['present'])


if __name__ == '__main__':
    unittest.main()
