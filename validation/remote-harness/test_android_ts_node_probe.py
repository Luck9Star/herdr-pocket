import copy
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
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
        directories = {'coreDirectoryPrepared': True, 'productDirectoryCallbackSucceeded': True,
            **{key: {'exists': True, 'directory': True, 'ownerMatches': True, 'permissionBits0700': True,
                     'fullMode0700': False, 'setgid': True} for key in ('root', 'runtime', 'identity')}}
        value = {'schemaVersion': 1, 'loginInvoked': False, 'dialInvoked': False, 'passed': False,
            'states': ['starting', 'needs-login'], 'startError': 'identity_unavailable', 'lastStage': 'native-status',
            'directories': directories}
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

    def test_start_returned_and_previous_exit_shapes(self):
        base = {'schemaVersion': 1, 'loginInvoked': False, 'dialInvoked': False, 'passed': False,
            'states': ['starting', 'needs-login'], 'startError': 'identity_unavailable', 'lastStage': 'native-start-returned'}
        def accepted(extra):
            try:
                probe.safe_probe({**base, **extra})
                return True
            except ValueError:
                return False
        self.assertTrue(accepted({'startReturnedAfterMs': 1200}))
        self.assertFalse(accepted({'startReturnedAfterMs': -1}))
        self.assertFalse(accepted({'startReturnedAfterMs': 'fast'}))
        self.assertTrue(accepted({'previousExit': {'available': True, 'reason': 2,
            'status': 6, 'timestamp': 1760000000000, 'importance': 100}}))
        self.assertTrue(accepted({'previousExit': {'available': False}}))
        self.assertTrue(accepted({'previousExit': {'available': False, 'errClass': 'SecurityException'}}))
        self.assertFalse(accepted({'previousExit': {'available': True, 'reason': 99,
            'status': 6, 'timestamp': 1, 'importance': 1}}))
        self.assertFalse(accepted({'previousExit': {'available': True, 'reason': 2,
            'status': 6, 'timestamp': 1, 'importance': 1, 'trace': 'raw-text'}}))
        self.assertFalse(accepted({'previousExit': {'available': False, 'errClass': 'x' * 65}}))

    def test_missing_or_rejected_report_preserves_only_safe_metadata(self):
        self.assertEqual(probe.probe_report(b'cat: private-path: No such file or directory'),
            {'probeReport': 'not-json', 'reportFileMissing': True})
        import json
        value = {'schemaVersion': 1, 'loginInvoked': False, 'dialInvoked': False,
            'lastStage': 'native-start', 'contextBound': True, 'secret': 'private-value'}
        result = probe.probe_report(json.dumps(value).encode())
        self.assertNotIn('private-value', repr(result)); self.assertNotIn('secret', repr(result))
        from types import SimpleNamespace
        result = probe.instrument_summary(SimpleNamespace(returncode=0,
            stdout=b'INSTRUMENTATION_FAILED: private-value', stderr=b''))
        self.assertNotIn('private-value', repr(result)); self.assertNotIn('secret', repr(result))

    def test_crash_forensics_redacted_and_bounded(self):
        from types import SimpleNamespace
        raw = (b'INSTRUMENTATION_STATUS: Error\n'
               b'Process crashed.\n'
               b'Fatal signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0xdeadbeef\n'
               b'panic: runtime error: invalid memory address\n'
               b'# pc 00000000004a1b2c /data/app/libhp_tailscale.so\n'
               b'herdr.local/tailscale-runtime.netmonInterfaceGetter(...)\n'
               b'herdr.local/tailscale-runtime.toNetmonInterfaces(...)\n'
               b'INSTRUMENTATION_CODE: 0\n')
        summary = probe.instrument_summary(SimpleNamespace(returncode=0, stdout=raw))
        self.assertTrue(summary['processCrash'])
        self.assertEqual(summary['crashSignals'], [11])
        # Panic lines are classified, never stored as raw text.
        self.assertEqual(summary['panicTypes'], ['invalid-memory-address'])
        self.assertEqual(sorted(summary['goFrames']),
                         ['netmonInterfaceGetter', 'toNetmonInterfaces'])
        dumped = repr(summary)
        self.assertNotIn('deadbeef', dumped)
        self.assertNotIn('hp_tailscale.so', dumped)
        self.assertNotIn('invalid memory address', dumped)
        # Quiet run: no crash markers, no forensics block at all.
        quiet = probe.instrument_summary(SimpleNamespace(returncode=0,
            stdout=b'INSTRUMENTATION_CODE: -1\n'))
        self.assertNotIn('crashSignals', quiet)
        self.assertNotIn('panicTypes', quiet)
        self.assertNotIn('goFrames', quiet)

    def test_tombstone_record_attributed_whole(self):
        # A standard crash-buffer tombstone: debuggerd PID on the header,
        # package bound by the Cmdline line, signal and Go frames inside.
        blob = (b'09-16 00:04:35.123  1234  1235 E crash_dump64: \n'
                b'*** *** *** \n'
                b'Build fingerprint: \x27generic\x27\n'
                b'Cmdline: dev.herdr.herdr_flutter_probe\n'
                b'signal 6 (SIGABRT), code -1 (SI_QUEUE), fault addr --------\n'
                b'Abort message: \x27panic: runtime error: nil pointer dereference\x27\n'
                b'#00 pc 00000000004a1b2c /data/app/libhp_tailscale.so\n'
                b'    at herdr.local/tailscale-runtime.netmonInterfaceGetter(...)\n'
                b'    at tailscale.com/net/netmon.(*Monitor).pump(...)\n'
                b'*** *** *** \n'
                b'Cmdline: com.android.other_app\n'
                b'signal 5 (SIGTRAP)\n')
        parts = __import__('re').split(rb'\*\*\* \*\*\* \*\*\*', blob)
        ours = [r for r in parts
                if b'dev.herdr.herdr_flutter_probe' in r or b'>>> dev.herdr' in r]
        self.assertEqual(len(ours), 1)
        merged = probe._redacted_forensics(ours[0])
        self.assertEqual(merged['crashSignals'], [6])
        self.assertEqual(merged['panicTypes'], ['nil-dereference'])
        self.assertEqual(merged['goFrames'], ['netmonInterfaceGetter'])
        self.assertEqual(merged['upstreamFrames'], ['net/netmon'])
        dumped = repr(merged)
        self.assertNotIn('deadbeef', dumped)
        self.assertNotIn('0x00000000004a1b2c', dumped)
        self.assertNotIn('other_app', dumped)
        self.assertEqual(probe._abort_class(ours[0]), 'go-panic')
        self.assertEqual(probe._module_basenames(ours[0]), ['libhp_tailscale.so'])
        # Rust panic abort: empty tombstone abort message, "panicked at" on stderr.
        self.assertEqual(probe._abort_class(b'Abort message: \x27\x27\n'), 'other')
        self.assertEqual(probe._abort_class(b'thread panicked at src/lib.rs:12\n'), 'rust-panic')
        # fd ownership abort is the probe's own stderr redirection showing up.
        self.assertEqual(probe._abort_class(
            b'Abort message: \x27failed to check ownership of fd 2\x27\n'), 'fd-ownership')
        # Unknown panic text falls back to a fixed class, never raw text.
        unknown = probe._redacted_forensics(b'Abort message: \x27panic: segmentation fault\x27')
        self.assertEqual(unknown['panicTypes'], ['other'])
        self.assertNotIn('segmentation', repr(unknown))

    def test_abort_class_and_module_basenames(self):
        record = (b'Cmdline: dev.herdr.herdr_flutter_probe\n'
                  b'signal 6 (SIGABRT), code -1 (SI_QUEUE)\n'
                  b'Abort message: \x27art::Thread::AssertNoPendingException CheckJNI\x27\n'
                  b'#00 pc 0000000000617b48 /apex/com.android.art/lib64/libart.so (offset)\n'
                  b'#01 pc 00000000004a1b2c /data/app/libhp_tailscale.so\n'
                  b'#02 pc 00000000000bcd8e /system/lib64/libc.so\n')
        self.assertEqual(probe._abort_class(record), 'jni-checkjni')
        self.assertEqual(probe._module_basenames(record),
                         ['libart.so', 'libhp_tailscale.so', 'libc.so'])
        go_abort = (b'Abort message: \x27panic: runtime error: nil pointer dereference\x27\n')
        self.assertEqual(probe._abort_class(go_abort), 'go-panic')
        unknown = b'Abort message: \x27something entirely novel\x27\n'
        self.assertEqual(probe._abort_class(unknown), 'other')
        dumped = repr(probe._module_basenames(record))
        self.assertNotIn('/apex', dumped)
        self.assertNotIn('/data/app', dumped)
        self.assertNotIn('0x0000000000617b48', dumped)

    def test_probe_never_requests_login_or_application_dial(self):
        source = (Path(__file__).resolve().parent / 'android-ts-node-probe/ProbeInstrumentation.java').read_text()
        for forbidden in ('beginLogin', 'begin_login', 'UserDial', 'user_dial', '"dial"'):
            self.assertNotIn(forbidden, source)

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


class ProbeJavaCompileTests(unittest.TestCase):
    """Compile the probe sources the way the CI build step does.

    Two probe runs died on a javac error before touching a device, so the
    checked-exception boundary of the probe Java is now a local gate. The
    compile needs the android-35 platform jar; skip when it is absent.
    """

    ANDROID_JAR = Path(os.environ.get('ANDROID_HOME', '')) / 'platforms/android-35/android.jar'

    def test_probe_sources_compile_against_android_jar(self):
        if not shutil.which('javac') or not self.ANDROID_JAR.is_file():
            self.skipTest('javac or android-35 platform jar unavailable')
        root = Path(__file__).resolve().parents[2]
        probe_dir = root / 'validation/remote-harness/android-ts-node-probe'
        java_dir = root / 'validation/network-profiles/native/android'
        sources = [probe_dir / name for name in (
            'NetworkRuntimeChannel.java', 'DirectoryProbe.java', 'ProbeInstrumentation.java')]
        sources += [java_dir / name for name in (
            'AndroidTailscaleConfig.java', 'AndroidTailscaleStateStore.java',
            'AndroidTailscaleEnvelope.java', 'TailscaleStateStoreCore.java')]
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ['javac', '-source', '11', '-target', '11', '-Xlint:-options',
                 '-classpath', str(self.ANDROID_JAR), '-d', tmp]
                + [str(p) for p in sources],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0,
                f'probe javac failed:\n{result.stdout}\n{result.stderr}')
            produced = {p.name for p in Path(tmp).rglob('*.class')}
        self.assertIn('ProbeInstrumentation.class', produced)
        self.assertIn('DirectoryProbe.class', produced)


if __name__ == '__main__': unittest.main()
