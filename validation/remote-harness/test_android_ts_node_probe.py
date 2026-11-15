import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

import android_ts_node_probe as probe


class ProbeGuardsTests(unittest.TestCase):
    def test_only_fixed_metadata_can_be_exported(self):
        value = {'schemaVersion': 1, 'loginInvoked': False, 'dialInvoked': False, 'passed': False,
            'states': ['starting', 'needs-login'], 'startError': 'identity_unavailable', 'lastStage': 'native-status'}
        self.assertEqual(probe.safe_probe(value), value)
        for changed in ({**value, 'url': 'private-value'}, {**value, 'startError': 'private-value'},
                        {**value, 'states': ['private-value']}, {**value, 'loginInvoked': True},
                        {**value, 'passed': 1}):
            with self.assertRaises(ValueError): probe.safe_probe(changed)

    def test_directory_export_contains_only_owned_mode_booleans(self):
        directories = {'coreDirectoryPrepared': True, 'productDirectoryCallbackSucceeded': False,
            **{key: {'exists': True, 'directory': True, 'ownerMatches': True, 'permissionBits0700': True,
                     'fullMode0700': False, 'setgid': True} for key in ('root', 'runtime', 'identity')}}
        value = {'schemaVersion': 1, 'loginInvoked': False, 'dialInvoked': False, 'directories': directories}
        self.assertEqual(probe.safe_probe(value), value)
        changed = copy.deepcopy(value); changed['directories']['identity']['path'] = 'private-value'
        with self.assertRaises(ValueError): probe.safe_probe(changed)

    def test_netmon_diagnose_and_java_interfaces_are_exportable(self):
        value = {'schemaVersion': 1, 'loginInvoked': False, 'dialInvoked': False, 'passed': False,
            'states': ['starting', 'needs-login'], 'startError': 'identity_unavailable', 'lastStage': 'native-status'}
        # Real Go marshal shape: stateBuilt=true leaves stateErrClass at the
        # zero value "" (netmon.go sets it only on failure).
        diagnose = {'event': 'netmon_diagnose', 'getterRegistered': True, 'getterCalls': 1,
            'paths': [{'path': 'goNet', 'ok': True, 'errClass': 'none', 'interfaces': 3, 'addresses': 5},
                      {'path': 'getifaddrs', 'ok': False, 'errClass': '', 'interfaces': 0, 'addresses': 0}],
            'selected': 'goNet', 'stateBuilt': True, 'stateErrClass': '',
            'haveV4': True, 'haveV6': False, 'anyUp': True}
        accepted = {**value, 'javaInterfaces': {'ok': True, 'interfaces': 3, 'addresses': 5, 'errClass': ''},
            'netmonDiagnose': diagnose}
        self.assertEqual(probe.safe_probe(accepted), accepted)
        for sentinel in ({'fileMissing': True}, {'parseError': True}):
            self.assertEqual(probe.safe_probe({**value, 'netmonDiagnose': sentinel})['netmonDiagnose'], sentinel)
        for rejected in ({**value, 'javaInterfaces': 'private-value'},
                         {**value, 'netmonDiagnose': 'private-value'},
                         {**value, 'javaInterfaces': {'ok': True, 'interfaces': -1, 'addresses': 0, 'errClass': ''}},
                         {**value, 'netmonDiagnose': {'event': 'netmon_diagnose', 'fileMissing': True}},
                         {**value, 'netmonDiagnose': {'fileMissing': False}},
                         {**value, 'netmonOptIn': 'yes'}):
            with self.assertRaises(ValueError): probe.safe_probe(rejected)
        for accepted in ({**value, 'netmonOptIn': True}, {**value, 'netmonOptIn': False}):
            self.assertEqual(probe.safe_probe(accepted), accepted)

    def test_missing_or_rejected_report_preserves_only_safe_metadata(self):
        self.assertEqual(probe.probe_report(b'cat: private-path: No such file or directory'),
            {'probeReport': 'not-json', 'reportFileMissing': True})
        import json
        value = {'schemaVersion': 1, 'loginInvoked': False, 'dialInvoked': False,
            'lastStage': 'native-start', 'contextBound': True, 'secret': 'private-value'}
        result = probe.probe_report(json.dumps(value).encode())
        self.assertEqual(result['probeReport'], 'schema-rejected')
        self.assertEqual(result['probePartial']['lastStage'], 'native-start')
        self.assertTrue(result['probePartial']['contextBound'])
        self.assertNotIn('private-value', repr(result)); self.assertNotIn('secret', repr(result))
        from types import SimpleNamespace
        result = probe.instrument_summary(SimpleNamespace(returncode=0,
            stdout=b'INSTRUMENTATION_RESULT: shortMsg=Process crashed.\nINSTRUMENTATION_CODE: 0\n'))
        self.assertEqual(result['returnCode'], '0'); self.assertTrue(result['processCrash'])
        self.assertTrue(result['finished'])

    def test_apk_contains_exact_fixed_libraries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); apk = root / 'probe.apk'
            for name in probe.LIBRARIES: (root / name).write_bytes(b'synthetic-' + name.encode())
            with zipfile.ZipFile(apk, 'w') as archive:
                for name in probe.LIBRARIES: archive.write(root / name, 'lib/x86_64/' + name)
            self.assertEqual(set(probe.verify_apk(apk, root)), set(probe.LIBRARIES))
            (root / probe.LIBRARIES[0]).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'native_mismatch'): probe.verify_apk(apk, root)

    def test_probe_never_requests_login_or_application_dial(self):
        source = (Path(__file__).parent / 'android-ts-node-probe/ProbeInstrumentation.java').read_text()
        self.assertNotIn('"nodeBeginLogin"', source)
        self.assertNotIn('"nodeLoginStatus"', source)
        self.assertNotIn('"streamOpen"', source)
        self.assertIn('"nodeStart"', source)
        self.assertIn('"nodeStop"', source)


    def test_netmon_diagnose_collected_requires_both_variants(self):
        with_ok = [{'probe': {'netmonDiagnose': {'event': 'netmon_diagnose'}}},
                   {'probe': {'netmonDiagnose': {'fileMissing': True}}}]
        self.assertTrue(probe.netmon_diagnose_collected(with_ok))
        self.assertFalse(probe.netmon_diagnose_collected(
            [{'probe': {'netmonDiagnose': {'event': 'netmon_diagnose'}}}, {'probe': {}}]))
        self.assertFalse(probe.netmon_diagnose_collected([]))

    def test_netmon_diagnose_schema_mirrors_committed_go(self):
        def diagnose(**over):
            base = {'event': 'netmon_diagnose', 'getterRegistered': True, 'getterCalls': 2,
                'paths': [{'path': 'goNet', 'ok': False, 'errClass': 'permission', 'interfaces': 0, 'addresses': 0},
                          {'path': 'getifaddrs', 'ok': True, 'errClass': 'none', 'interfaces': 3, 'addresses': 5}],
                'selected': 'getifaddrs', 'stateBuilt': True, 'stateErrClass': '',
                'haveV4': True, 'haveV6': False, 'anyUp': True}
            base.update(over)
            return base
        def accepted(item):
            try:
                probe.safe_probe(dict(schemaVersion=1, loginInvoked=False, dialInvoked=False, netmonDiagnose=item))
                return True
            except ValueError:
                return False
        self.assertTrue(accepted(diagnose()))
        self.assertTrue(accepted(diagnose(paths=[{'path': 'goNet', 'ok': True, 'errClass': 'none',
            'interfaces': 2, 'addresses': 4}], selected='goNet')))
        # A path that never executed is legal: ok=false with errClass "".
        self.assertTrue(accepted(diagnose(paths=[{'path': 'goNet', 'ok': True, 'errClass': 'none',
            'interfaces': 2, 'addresses': 4}, {'path': 'getifaddrs', 'ok': False, 'errClass': '',
            'interfaces': 0, 'addresses': 0}], selected='goNet')))
        # stateBuilt=true must keep the zero-value "" stateErrClass (Go sets
        # it only on failure); stateBuilt=false must carry a real class.
        self.assertFalse(accepted(diagnose(stateErrClass='none')))
        self.assertTrue(accepted(diagnose(stateBuilt=False, stateErrClass='permission')))
        self.assertFalse(accepted(diagnose(stateBuilt=False, stateErrClass='')))
        self.assertFalse(accepted(diagnose(event='other_event')))
        self.assertFalse(accepted(diagnose(getterCalls=-1)))
        self.assertFalse(accepted(diagnose(getterCalls='two')))
        self.assertFalse(accepted(diagnose(selected='java')))
        self.assertFalse(accepted(diagnose(stateErrClass='EPERM netlink raw-secret')))
        self.assertFalse(accepted(diagnose(paths=[{'path': 'goNet', 'ok': True, 'errClass': 'none',
            'interfaces': 1, 'addresses': 1, 'extra': 1}])))
        self.assertFalse(accepted(diagnose(paths=[{'path': 'java', 'ok': True, 'errClass': 'none',
            'interfaces': 1, 'addresses': 1}])))
        self.assertFalse(accepted(diagnose(paths=[{'path': 'goNet', 'ok': True, 'errClass': 'other',
            'interfaces': 1, 'addresses': 1}])))
        self.assertFalse(accepted(diagnose(paths=[{'path': 'goNet', 'ok': False, 'errClass': 'none',
            'interfaces': 0, 'addresses': 0}])))
        self.assertFalse(accepted(diagnose(secretKey='raw-interface-name')))

    def test_java_interfaces_errclass_is_real_enum(self):
        def accepted(item):
            try:
                probe.safe_probe(dict(schemaVersion=1, loginInvoked=False, dialInvoked=False, javaInterfaces=item))
                return True
            except ValueError:
                return False
        self.assertTrue(accepted({'ok': True, 'interfaces': 4, 'addresses': 6, 'errClass': ''}))
        self.assertTrue(accepted({'ok': False, 'interfaces': 0, 'addresses': 0, 'errClass': 'SocketException'}))
        self.assertFalse(accepted({'ok': True, 'interfaces': 0, 'addresses': 0, 'errClass': ''}))
        self.assertFalse(accepted({'ok': True, 'interfaces': 2, 'addresses': 2, 'errClass': 'other'}))
        self.assertFalse(accepted({'ok': True, 'interfaces': 2, 'addresses': 2, 'errClass': 'x' * 65}))
if __name__ == '__main__': unittest.main()
