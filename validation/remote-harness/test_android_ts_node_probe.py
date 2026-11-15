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


if __name__ == '__main__': unittest.main()
