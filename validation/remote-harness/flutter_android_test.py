"""Local isolation/evidence tests only. No Flutter, adb, AVD, SSH or real keys."""
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import flutter_android_gui as gui

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('flutter_android_preparation',
    REPO / 'validation/flutter/tool/android_device_test.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

runner_spec = importlib.util.spec_from_file_location('flutter_android_shared_runner',
    REPO / 'validation/remote-harness/run-ci.py')
runner = importlib.util.module_from_spec(runner_spec)
runner_spec.loader.exec_module(runner)

try:
    import paired_gui
except ModuleNotFoundError as error:
    if error.name != 'cryptography':
        raise
    paired_gui = None


def block(name, source='sdk', version='0.0.0'):
    description = ('    description: flutter\n' if source == 'sdk' else
        '    description:\n      name: ' + name + '\n      sha256: "' + '1' * 64 + '"\n      url: "https://pub.dev"\n')
    return f'  {name}:\n    dependency: transitive\n' + description + f'    source: {source}\n    version: "{version}"\n'


def device_report(**changes):
    value = {'case': 'android-native-pairing-observe', 'buildMode': 'debug',
        **{name: True for name in gui.BOOL_FIELDS}, 'identityCreationActions': 1,
        'firstSequence': 5, 'deltaSequence': 7, 'frameCountLowerBound': 2, 'deltaCountLowerBound': 1}
    value.update(changes)
    return value


class PreparedFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.source, self.runner = base / 'source', base / 'runner'
        self.app = self.runner / 'app'
        self.source.mkdir(); self.app.mkdir(parents=True)
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '123',
            'GITHUB_REF': 'refs/heads/codex/unit', 'GITHUB_SHA': 'a' * 40,
            'RUNNER_TEMP': str(self.runner), 'ANDROID_SERIAL': gui.SERIAL}
        self.patch = patch.object(tool, 'SOURCE', self.source)
        self.patch.start(); self.addCleanup(self.patch.stop)
        for folder in ('lib', 'native/android', 'integration_test'):
            (self.source / folder).mkdir(parents=True)
        for name in ('main.dart', 'device_keys.dart', 'host_catalog.dart', 'pairing_page.dart', 'remote_adapter.dart'):
            (self.source / 'lib' / name).write_text('// synthetic source integrity fixture\n')
        for name in ('MainActivity.kt', 'PairScanChannel.kt', 'HostCatalogFile.kt', 'InputJournalFile.kt'):
            (self.source / 'native/android' / name).write_text('// synthetic native source fixture\n')
        (self.source / 'integration_test/android_pairing_observe_test.dart').write_text('// integration fixture\n')
        pubspec = 'name: synthetic\ndev_dependencies:\n  flutter_test:\n    sdk: flutter\n'
        (self.source / 'pubspec.yaml').write_text(pubspec)
        (self.app / 'pubspec.yaml').write_text(pubspec)
        shutil.copytree(self.source / 'lib', self.app / 'lib')
        native = self.app / 'android/app/src/main/kotlin/dev/herdr/herdr_flutter_probe'
        shutil.copytree(self.source / 'native/android', native)
        self.gradle = self.app / 'android/app/build.gradle.kts'
        self.gradle.write_text('namespace = "dev.herdr.herdr_flutter_probe"\napplicationId = "dev.herdr.herdr_flutter_probe"\n'
            'compileOptions { sourceCompatibility = JavaVersion.VERSION_17 }\nkotlinOptions { jvmTarget = "17" }\n')
        self.baseline = 'packages:\n' + ''.join(block(name) for name in ('flutter', 'flutter_test', 'terminal_view', 'dartssh2'))
        self.footer = 'sdks:\n  dart: ">=3.11.0 <4.0.0"\n'
        (self.app / 'pubspec.lock').write_text(self.baseline + self.footer)
        (self.app / '.herdr-generated-probe.json').write_text(json.dumps({'kind': 'herdr-flutter-validation', 'sourceCommit': self.env['GITHUB_SHA']}))
        (self.app / 'candidate-manifest.json').write_text(json.dumps({'sourceCommit': self.env['GITHUB_SHA'],
            'variant': 'experimental-patched', 'candidateLockSha256': tool.digest(self.app / 'pubspec.lock')}))
        root_temp = tempfile.TemporaryDirectory(prefix='hp-mobile-123-', dir='/tmp')
        self.addCleanup(root_temp.cleanup)
        self.fixture_root = Path(root_temp.name).resolve()
        self.config = {'schemaVersion': 1, 'host': '127.0.0.1', 'port': 2222, 'username': 'fixture',
            'expectedHostKey': 'public-fixture-only', 'socketPath': str(self.fixture_root / 'config/herdr/sessions/pocket-probe/herdr.sock'),
            'herdrPath': str(self.fixture_root / 'herdr'), 'session': 'pocket-probe', 'paneId': 'w1:p1', 'reviewConfirmed': True}

    def prepared(self):
        tool.prepare(self.app, self.env)
        (self.app / 'pubspec.lock').write_text(self.baseline + ''.join(block(name) for name in sorted(tool.SDK_ADDITIONS)) + self.footer)
        return tool.verify_lock(self.app, self.env)

    def args(self):
        output = self.runner / 'output'; output.mkdir(exist_ok=True)
        return type('Args', (), {'flutter_app': self.app, 'input_fixture': None, 'output': output})()


class ScaffoldGuards(PreparedFixture):
    def test_only_generated_app_gains_sdk_test_dependency_and_jvm_targets_stay_identical(self):
        pubspec = (self.source / 'pubspec.yaml').read_bytes(); gradle = self.gradle.read_bytes()
        proof = self.prepared()
        self.assertTrue(proof['lockVerified'])
        self.assertEqual((self.source / 'pubspec.yaml').read_bytes(), pubspec)
        self.assertEqual(self.gradle.read_bytes(), gradle)
        self.assertIn('  integration_test:\n    sdk: flutter', (self.app / 'pubspec.yaml').read_text())
        self.assertEqual(set(proof['addedPackages']), tool.SDK_ADDITIONS)
        self.assertEqual(len(proof['productionAndroidChannels']), 4)

    def test_local_wrong_branch_wrong_source_and_source_checkout_are_refused_before_mutation(self):
        for changes in ({'GITHUB_ACTIONS': 'false'}, {'GITHUB_REF': 'refs/heads/main'},
                        {'GITHUB_SHA': 'b' * 40}, {'GITHUB_RUN_ID': '../escape'}):
            with self.assertRaises(tool.DevicePreparationFailure):
                tool.prepare(self.app, dict(self.env, **changes))
        with self.assertRaises(tool.DevicePreparationFailure):
            tool.prepare(self.source, self.env)
        self.assertFalse((self.app / tool.MARKER).exists())

    def test_source_tamper_or_pubspec_symlink_cannot_write_outside_scaffold(self):
        target = self.app / 'lib/device_keys.dart'
        target.write_text('// changed implementation\n')
        with self.assertRaises(tool.DevicePreparationFailure):
            tool.prepare(self.app, self.env)
        shutil.copy2(self.source / 'lib/device_keys.dart', target)
        (self.app / 'pubspec.yaml').unlink()
        (self.app / 'pubspec.yaml').symlink_to(self.source / 'pubspec.yaml')
        original = (self.source / 'pubspec.yaml').read_bytes()
        with self.assertRaises(tool.DevicePreparationFailure):
            tool.prepare(self.app, self.env)
        self.assertEqual((self.source / 'pubspec.yaml').read_bytes(), original)

    def test_existing_dependency_drift_and_non_sdk_integration_package_are_rejected(self):
        tool.prepare(self.app, self.env)
        sdk = ''.join(block(name) for name in sorted(tool.SDK_ADDITIONS))
        for changed in (self.baseline.replace('version: "0.0.0"', 'version: "9.0.0"', 1) + sdk,
                        self.baseline + sdk.replace('source: sdk', 'source: hosted', 1)):
            (self.app / 'pubspec.lock').write_text(changed + self.footer)
            with self.assertRaises(tool.DevicePreparationFailure): tool.verify_lock(self.app, self.env)

    def test_only_allowlisted_new_hosted_packages_with_pinned_digests_are_accepted(self):
        tool.prepare(self.app, self.env)
        sdk = ''.join(block(name) for name in sorted(tool.SDK_ADDITIONS))
        for extra in (block('unexpected', 'hosted', '1.0.0'), block('file', 'hosted', '1.0.0').replace('1' * 64, 'not-a-digest')):
            (self.app / 'pubspec.lock').write_text(self.baseline + sdk + extra + self.footer)
            with self.assertRaises(tool.DevicePreparationFailure): tool.verify_lock(self.app, self.env)
        (self.app / 'pubspec.lock').write_text(self.baseline + sdk + block('file', 'hosted', '1.0.0') + self.footer)
        self.assertTrue(tool.verify_lock(self.app, self.env)['lockVerified'])


class RunnerGuards(PreparedFixture):
    def test_unprepared_or_changed_production_app_never_reaches_adb(self):
        with self.assertRaises(gui.DeviceFailure): gui.require_cloud(self.env, self.fixture_root, self.app, self.config)
        self.prepared()
        self.assertEqual(gui.require_cloud(self.env, self.fixture_root, self.app, self.config), self.app)
        (self.app / 'lib/device_keys.dart').write_text('// substituted signer\n')
        with self.assertRaises(gui.DeviceFailure): gui.require_cloud(self.env, self.fixture_root, self.app, self.config)

    def test_real_devices_extra_credentials_and_non_ci_are_rejected(self):
        self.prepared()
        for env, config in ((dict(self.env, ANDROID_SERIAL='physical-device'), self.config),
                            (dict(self.env, GITHUB_ACTIONS='false'), self.config),
                            (self.env, dict(self.config, privateKeyPem='never-use')),
                            (self.env, dict(self.config, host='192.0.2.1'))):
            with self.assertRaises(gui.DeviceFailure): gui.require_cloud(env, self.fixture_root, self.app, config)

    def test_input_candidate_is_refused_before_any_device_action(self):
        self.prepared(); args = self.args(); args.input_fixture = self.runner / 'input-fixture'
        with patch.object(gui, 'adb') as adb:
            with self.assertRaises(gui.DeviceFailure): gui._run(args, self.fixture_root, self.env, self.config, Mock(), Mock())
            adb.assert_not_called()

    def test_existing_package_and_additional_device_are_never_removed_or_used(self):
        self.prepared(); args = self.args(); launch = Mock()
        def output(*parts, **kwargs):
            if parts == ('devices',): return 'List of devices attached\nemulator-5554\tdevice'
            if parts[-1:] == ('ro.kernel.qemu',): return '1'
            if parts[-1:] == ('ro.build.version.sdk',): return '35'
            if parts[-1:] == ('get-current-user',): return '0'
            return ''
        with patch.object(gui, 'text', side_effect=output), patch.object(gui, 'package_present', return_value=True), patch.object(gui, 'adb') as adb:
            with self.assertRaises(gui.DeviceFailure): gui._run(args, self.fixture_root, self.env, self.config, Mock(), launch)
            launch.assert_not_called(); adb.assert_not_called()
        with patch.object(gui, 'text', return_value='List of devices attached\nemulator-5554\tdevice\nphone\tdevice'):
            with self.assertRaises(gui.DeviceFailure): gui._run(args, self.fixture_root, self.env, self.config, Mock(), launch)


class WireGuards(unittest.TestCase):
    def test_actual_flutter_version_must_match_the_pinned_sdk(self):
        version = {'frameworkVersion': '3.47.9', 'frameworkRevision': tool.FLUTTER_COMMIT, 'private': 'never-copy'}
        with patch.object(gui.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(version).encode(), b'')):
            self.assertEqual(set(gui.checked_flutter_version()), {'frameworkVersion', 'frameworkRevision'})
        for change in ({'frameworkVersion': '3.48.0'}, {'frameworkRevision': 'b' * 40}):
            with patch.object(gui.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(dict(version, **change)).encode(), b'')):
                with self.assertRaises(gui.DeviceFailure): gui.checked_flutter_version()
    def test_evidence_allowlist_never_publishes_key_config_or_terminal_text(self):
        clean = gui.safe_device_result(device_report(privateKeyPem='NEVER', config={'password': 'NEVER'}, terminalText='NEVER'))
        self.assertNotIn('NEVER', json.dumps(clean))
        self.assertEqual(set(clean), set(device_report()))

    def test_failed_native_or_frame_evidence_cannot_be_treated_as_success(self):
        for changes in ({'uninjectedNativeDeviceKeys': False}, {'localIdentityDeleted': False}, {'fullRendered': 1},
                        {'firstSequence': True}, {'deltaSequence': 5}, {'identityCreationActions': 2},
                        {'frameCountLowerBound': 1}, {'buildMode': 'release'}, {'case': 'mock'}):
            with self.assertRaises(gui.DeviceFailure): gui.safe_device_result(device_report(**changes))

    def test_public_exchange_only_uses_fixed_cache_paths_and_bounds(self):
        with patch.object(gui, 'adb', return_value=subprocess.CompletedProcess([], 0, b'x' * 2049, b'')) as adb:
            with self.assertRaises(gui.DeviceFailure): gui.read_public('cache/herdr-flutter-android-123/request.json', 2048)
            self.assertEqual(adb.call_args.args[:5], ('shell', '-T', 'run-as', gui.PACKAGE, 'head'))
            self.assertEqual(adb.call_args.args[-3:], ('-c', '2049', 'cache/herdr-flutter-android-123/request.json'))
            with self.assertRaises(gui.DeviceFailure): gui.read_public('files/device-identity', 2048)

    def test_response_is_stdin_not_shell_source_and_rename_is_atomic(self):
        response = b'{"public":"$(never-execute)"}'
        with patch.object(gui, 'adb') as adb:
            gui.write_response('cache/herdr-flutter-android-123', response)
            first, second = adb.call_args_list
            self.assertEqual(first.args[:5], ('shell', '-T', 'run-as', gui.PACKAGE, 'tee'))
            self.assertEqual(first.kwargs['data'], response)
            self.assertNotIn('$(never-execute)', ' '.join(first.args))
            self.assertEqual(second.args[:4], ('shell', 'run-as', gui.PACKAGE, 'mv'))
            with self.assertRaises(gui.DeviceFailure): gui.write_response('../escape', response)


class PublicExchangeGuards(unittest.TestCase):
    relative = 'cache/herdr-flutter-android-123'

    def request(self):
        # Shape-only public fixture: cryptographic key and TTL review belongs
        # to Host.review, not this reader test or its approval spy.
        return json.dumps({'version': 2, 'type': 'pairing-public-key-request',
            'request_id': 'a' * 32, 'account': 'fixture', 'host_key': 'SHA256:' + 'A' * 43,
            'device': 'Test phone', 'public_key': 'public-fixture-not-a-real-key',
            'issued_at': 1000, 'expires_at': 1600}, indent=2).encode()

    def read(self, stdout=b'', stderr=b'', code=0, name='request.json', limit=None):
        if limit is None:
            limit = {'request.json': 2048, 'result.json': 8192, 'stage': 40}[name]
        reply = subprocess.CompletedProcess([], code, stdout, stderr)
        with patch.object(gui, 'adb', return_value=reply) as adb:
            value = gui.read_public(self.relative + '/' + name, limit)
        adb.assert_called_once_with('shell', '-T', 'run-as', gui.PACKAGE,
            'head', '-c', str(limit + 1), self.relative + '/' + name, check=False)
        return value

    def test_known_package_and_current_file_not_ready_diagnostics_wait_even_with_legacy_zero_status(self):
        diagnostics = [
            ('run-as: unknown package: ' + gui.PACKAGE + '\n').encode(),
            ('head: ' + self.relative + '/request.json: No such file or directory\n').encode(),
        ]
        for diagnostic in diagnostics:
            for stdout, stderr, code in ((diagnostic, b'', 0), (b'', diagnostic, 1)):
                with self.subTest(diagnostic=diagnostic, code=code):
                    self.assertIsNone(self.read(stdout, stderr, code))
        # Diagnostics are longer than stage's 40-byte payload bound. They are
        # still a missing file/package, including when failure_stage polls it.
        for diagnostic in (diagnostics[0],
                           ('head: ' + self.relative + '/stage: No such file or directory\n').encode()):
            with self.subTest(stage_diagnostic=diagnostic):
                self.assertIsNone(self.read(stderr=diagnostic, code=1, name='stage'))

    def test_empty_whitespace_and_incomplete_json_wait_instead_of_reaching_approval(self):
        for raw in (b'', b' \r\n\t ', b'{', b'{"version":', self.request()[:-1], b'{"device":"\xe4\xb8'):
            with self.subTest(raw=raw):
                self.assertIsNone(self.read(raw))

    def test_unknown_shell_failures_use_static_file_specific_errors(self):
        for name in ('request.json', 'result.json', 'stage'):
            kind = name.split('.')[0]
            for stdout, stderr, code in ((b'', b'PRIVATE_DIAGNOSTIC', 1),
                                         (b'', b'PRIVATE_DIAGNOSTIC', 0),
                                         (b'PRIVATE_DIAGNOSTIC', b'', 1)):
                with self.subTest(name=name, code=code):
                    with self.assertRaises(gui.DeviceFailure) as failure:
                        self.read(stdout, stderr, code, name=name)
                    self.assertEqual(str(failure.exception), 'flutter_android_public_' + kind + '_read_failed')

    def test_unrelated_missing_files_and_other_packages_are_fatal_not_retried(self):
        for diagnostic in (b'head: files/private-record: No such file or directory\n',
                           b'run-as: unknown package: other.application\n',
                           ('head: ' + self.relative + '/request.json: Permission denied\n').encode()):
            with self.subTest(diagnostic=diagnostic):
                with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_public_request_read_failed$'):
                    self.read(stderr=diagnostic, code=1)

    def test_complete_wrong_request_schema_and_non_json_never_leave_static_errors(self):
        original = json.loads(self.request())
        invalid = [b'PRIVATE_NON_JSON', b'[]', b'null', b'"PRIVATE_JSON_STRING"']
        invalid.append(self.request().replace(b'{', b'{"version":2,', 1))
        for changes in ({'version': True}, {'version': 1}, {'type': 'pairing-binding-response'},
                        {'issued_at': True}, {'expires_at': '1600'}, {'account': {'private': 'nested'}},
                        {'extra': 'PRIVATE_FIELD'}):
            invalid.append(json.dumps(dict(original, **changes)).encode())
        missing = dict(original); del missing['device']
        invalid.append(json.dumps(missing).encode())
        for raw in invalid:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_public_request_invalid$'):
                    self.read(raw)

    def test_fixed_limits_are_required_before_adb_and_stderr_is_bounded(self):
        for name, limit in (('request.json', 8192), ('result.json', 2048), ('stage', 2048), ('request.json', True)):
            with self.subTest(name=name, limit=limit), patch.object(gui, 'adb') as adb:
                with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_public_limit_invalid$'):
                    gui.read_public(self.relative + '/' + name, limit)
                adb.assert_not_called()
        with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_public_exchange_oversize$'):
            self.read(stderr=b'PRIVATE_DIAGNOSTIC' * 129, code=1)

    def test_valid_request_and_result_bytes_are_preserved_and_result_checks_stay_strict(self):
        request = self.request()
        result = json.dumps(device_report(), indent=2).encode()
        self.assertEqual(self.read(request), request)
        self.assertEqual(self.read(result, name='result.json', limit=8192), result)
        with self.assertRaises(gui.DeviceFailure):
            self.read(json.dumps(device_report(localIdentityDeleted=False)).encode(), name='result.json', limit=8192)

    def test_only_fixed_stages_are_accepted_and_reported_as_failure_phase(self):
        self.assertEqual(self.read(b'host_authorization', name='stage', limit=40), b'host_authorization')
        with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_public_stage_invalid$'):
            self.read(b'PRIVATE_STAGE', name='stage', limit=40)
        proc = Mock(); proc.poll.return_value = 1
        replies = [subprocess.CompletedProcess([], 1, b'',
            ('head: ' + self.relative + '/request.json: No such file or directory\n').encode()),
            subprocess.CompletedProcess([], 0, b'public_request', b'')]
        with patch.object(gui, 'adb', side_effect=replies):
            with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_test_exited_public_request$'):
                gui.wait_public(proc, self.relative, 'request.json', 2048, timeout=1)

    def test_wait_only_delivers_final_json_to_approval_spy_after_diagnostics_and_partial_data(self):
        request = self.request()
        replies = [subprocess.CompletedProcess([], 0,
            ('run-as: unknown package: ' + gui.PACKAGE + '\n').encode(), b''),
            subprocess.CompletedProcess([], 1, b'',
                ('head: ' + self.relative + '/request.json: No such file or directory\n').encode()),
            subprocess.CompletedProcess([], 0, b' \n', b''),
            subprocess.CompletedProcess([], 0, b'{"version":', b''),
            subprocess.CompletedProcess([], 0, request, b'')]
        proc = Mock(); proc.poll.return_value = None
        approval = Mock(spec=['approve'])
        def sleep(_):
            approval.approve.assert_not_called()
        with patch.object(gui, 'adb', side_effect=replies) as adb, patch.object(gui.time, 'sleep', side_effect=sleep):
            approval.approve(gui.wait_public(proc, self.relative, 'request.json', 2048, timeout=1))
        self.assertEqual(adb.call_count, 5)
        approval.approve.assert_called_once_with(request)


class CleanupGuards(PreparedFixture):
    def exercise(self, fail_reverse_cleanup=False):
        self.prepared(); args = self.args()
        state = {'installed': False, 'reverse': False}
        original = (gui.SERIAL, 'tcp:55000', 'tcp:55001')
        owned = (gui.SERIAL, 'tcp:56000', 'tcp:56001')
        forwards = {original}
        calls = []
        class Process:
            def poll(self): return 0
            def wait(self, timeout): return 0
        @contextmanager
        def process(command, **kwargs):
            self.assertIn('--no-uninstall', command); self.assertIn('--no-pub', command)
            self.assertNotIn('--release', command); self.assertNotIn('--profile', command)
            self.assertEqual(command[-1], 'integration_test/android_pairing_observe_test.dart')
            self.assertEqual(command[command.index('-d') + 1], gui.SERIAL)
            state['installed'] = True; forwards.add(owned)
            yield Process()
        def adb(*parts, **kwargs):
            calls.append(parts)
            if parts[:2] == ('reverse', '--remove'):
                if fail_reverse_cleanup: raise gui.DeviceFailure('synthetic_cleanup_failure')
                state['reverse'] = False
            elif parts[0] == 'reverse': state['reverse'] = True
            elif parts[0] == 'uninstall': state['installed'] = False
            elif parts[:2] == ('forward', '--remove'):
                forwards.difference_update({item for item in forwards if item[1] == parts[2]})
            return subprocess.CompletedProcess([], 0, b'', b'')
        def text(*parts, **kwargs):
            if parts == ('devices',): return 'List of devices attached\nemulator-5554\tdevice'
            if parts[-1:] == ('ro.kernel.qemu',): return '1'
            if parts[-1:] == ('ro.build.version.sdk',): return '35'
            if parts[-1:] == ('get-current-user',): return '0'
            if parts == ('reverse', '--list'):
                return gui.SERIAL + ' tcp:2222 tcp:2222' if state['reverse'] else ''
            return ''
        approval = Mock(); approval.approve.return_value = b'{"public":"response"}'
        with patch.object(gui, 'adb', side_effect=adb), patch.object(gui, 'text', side_effect=text), \
                patch.object(gui, 'package_present', side_effect=lambda: state['installed']), \
                patch.object(gui, 'forward_set', side_effect=lambda: set(forwards)), \
                patch.object(gui, 'write_response'), \
                patch.object(gui, 'checked_flutter_version', return_value={'frameworkVersion': tool.FLUTTER_VERSION, 'frameworkRevision': tool.FLUTTER_COMMIT}), \
                patch.object(gui, 'wait_public', side_effect=[b'{"public":"request"}', json.dumps(device_report()).encode()]):
            if fail_reverse_cleanup:
                with self.assertRaisesRegex(gui.DeviceFailure, 'flutter_android_cleanup_failed'):
                    gui._run(args, self.fixture_root, self.env, self.config, approval, process)
                result = None
            else:
                result = gui._run(args, self.fixture_root, self.env, self.config, approval, process)
        self.assertEqual(forwards, {original})
        self.assertFalse(state['installed'])
        self.assertIn(('uninstall', gui.PACKAGE), calls)
        self.assertNotIn(('forward', '--remove', original[1]), calls)
        self.assertFalse((self.fixture_root / 'flutter-android-public-defines.json').exists())
        cleanup = json.loads((args.output / 'flutter-android-device-cleanup.json').read_text())
        return result, cleanup

    def test_only_owned_package_reverse_and_new_vm_forward_are_cleaned(self):
        result, cleanup = self.exercise()
        self.assertEqual(cleanup['status'], 'passed')
        self.assertTrue(result['deviceCleanup']['ownedPackageAbsent'])
        self.assertFalse(result['storageMocked'])  # This label is from the real runner; this test is not device evidence.
        self.assertFalse(cleanup['rawLogsUploaded'])

    def test_failed_cleanup_is_recorded_and_cannot_return_passed(self):
        result, cleanup = self.exercise(fail_reverse_cleanup=True)
        self.assertIsNone(result)
        self.assertEqual(cleanup['status'], 'failed')
        self.assertFalse(cleanup['reverseRemoved'])
        self.assertTrue(cleanup['ownedPackageAbsent'])


class SharedReportGuards(unittest.TestCase):
    def native_result(self, **changes):
        result = {'status': 'passed', 'uninjectedNativeDeviceKeys': True,
            'storageMocked': False, 'signerInjected': False, 'framesInjected': False}
        result.update(changes)
        return result

    def test_system_store_runtime_requires_passed_and_all_native_evidence(self):
        report = runner.gui_report_fields('flutter-android', self.native_result())
        self.assertNotIn('protected system-store runtime', report['unverified'])
        for status in ('failed', None):
            with self.subTest(status=status):
                report = runner.gui_report_fields('flutter-android', self.native_result(status=status))
                self.assertIn('protected system-store runtime', report['unverified'])

    def test_missing_or_contradictory_native_evidence_keeps_runtime_unverified(self):
        evidence = {'uninjectedNativeDeviceKeys': True, 'storageMocked': False,
            'signerInjected': False, 'framesInjected': False}
        for field, expected in evidence.items():
            for value in (None, not expected, int(expected)):
                with self.subTest(field=field, value=value):
                    result = self.native_result(**{field: value})
                    report = runner.gui_report_fields('flutter-android', result)
                    self.assertIn('protected system-store runtime', report['unverified'])
            with self.subTest(field=field, missing=True):
                result = self.native_result()
                del result[field]
                report = runner.gui_report_fields('flutter-android', result)
                self.assertIn('protected system-store runtime', report['unverified'])

    def test_readonly_native_success_does_not_claim_other_acceptance(self):
        for status in ('passed', 'failed'):
            with self.subTest(status=status):
                report = runner.gui_report_fields('flutter-android', self.native_result(status=status))
                self.assertIn('remote input from this GUI', report['unverified'])
                for gap in ('physical phone', 'camera', 'real IME', 'overlay networks',
                            'pixel rendering', 'hardware key protection', 'production deployment'):
                    self.assertIn(gap, report['unverified'])
                self.assertTrue(any('Flutter' in gap and 'release' in gap and 'profile' in gap
                                    for gap in report['unverified']))

    def test_native_frame_and_platform_labels_describe_flutter_debug_terminal(self):
        report = runner.gui_report_fields('flutter-android', self.native_result())
        self.assertIn('Terminal', report['frameEvidence'])
        self.assertNotIn('xterm', report['frameEvidence'].lower())
        self.assertNotIn('widget', report['frameEvidence'].lower())
        self.assertIn('API35', report['scope'])
        self.assertIn('Flutter', report['scope'])
        self.assertIn('debug', report['scope'])
        self.assertIn('API35', report['platform'])
        self.assertIn('Flutter', report['platform'])
        self.assertIn('debug', report['platform'])


@unittest.skipIf(paired_gui is None, 'shared pairing helper requires optional cryptography')
class SharedRouteGuards(unittest.TestCase):
    def exercise(self, failure=None):
        with tempfile.TemporaryDirectory(prefix='hp-mobile-123-', dir='/tmp') as directory:
            # Keep /tmp spelling: run_gui's existing fixture guard checks it.
            root = Path(directory)
            (root / 'authorized_keys').write_bytes(b'')
            env = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '123',
                'GITHUB_REF': 'refs/heads/codex/unit'}
            config = {'host': '127.0.0.1', 'username': 'fixture',
                'expectedHostKey': 'public-fixture-only'}
            args = SimpleNamespace(paired_gui='flutter-android', input_fixture=None)
            host = object()
            approval = Mock(spec=['verify_ssh', 'revoke'])
            if failure == 'verification':
                approval.verify_ssh.side_effect = paired_gui.GuiFailure('synthetic_verification_failure')
            exercise = Mock(return_value={'paired': True})
            if failure == 'device':
                exercise.side_effect = paired_gui.GuiFailure('synthetic_device_failure')
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(paired_gui, 'Host', return_value=host) as host_factory, \
                    patch.object(paired_gui, 'FixtureApproval', return_value=approval) as approval_factory, \
                    patch.object(gui, 'run_flutter_android', exercise), \
                    patch.object(paired_gui, 'run_flutter', side_effect=AssertionError('wrong Flutter route')), \
                    patch.object(paired_gui, 'run_tauri', side_effect=AssertionError('wrong Tauri route')), \
                    patch.object(gui, 'adb', side_effect=AssertionError('unexpected adb')), \
                    patch.object(subprocess, 'run', side_effect=AssertionError('unexpected process')):
                result = paired_gui.run_gui(args, root, env, config)
            host_factory.assert_called_once()
            self.assertEqual(host_factory.call_args.args[1:], ('fixture', 'public-fixture-only'))
            self.assertEqual(host_factory.call_args.args[0].parent, root)
            approval_factory.assert_called_once_with(root, config, host)
            exercise.assert_called_once_with(args, root, env, config, approval)
            approval.revoke.assert_called_once_with()
            return result, approval

    def test_native_route_verifies_zero_input_then_revokes(self):
        result, approval = self.exercise()
        approval.verify_ssh.assert_called_once_with(b'')
        self.assertEqual(approval.method_calls, [('verify_ssh', (b'',), {}), ('revoke', (), {})])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['adapter'], 'flutter-android')
        self.assertEqual(result['receivedInputBytes'], 0)
        self.assertTrue(result['matchedDeviceKeyInSshd'])
        self.assertTrue(result['revokedFixtureKey'])

    def test_native_route_device_failure_still_revokes_without_claiming_success(self):
        result, approval = self.exercise('device')
        approval.verify_ssh.assert_not_called()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errorCode'], 'synthetic_device_failure')
        self.assertNotIn('matchedDeviceKeyInSshd', result)

    def test_native_route_verification_failure_still_revokes(self):
        result, approval = self.exercise('verification')
        approval.verify_ssh.assert_called_once_with(b'')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errorCode'], 'synthetic_verification_failure')
        self.assertNotIn('revokedFixtureKey', result)


if __name__ == '__main__':
    unittest.main()
