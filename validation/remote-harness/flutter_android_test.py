"""Local isolation/evidence tests only. No Flutter, adb, AVD, SSH or real keys."""
from contextlib import contextmanager
import importlib.util
import json
import os
import re
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
        for name in tool.PRODUCTION_CHANNELS:
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
        self.assertEqual(len(proof['productionAndroidChannels']), 5)

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
    def test_first_target_review_failures_are_bounded_and_distinguish_consent_from_disabled_creation(self):
        for stage in ('target_finish_edit', 'target_review_ready', 'target_review_unchecked', 'target_create_unavailable'):
            record = {'stage': stage, 'errorClass': 'TestFailure', 'line': 240}
            encoded = json.dumps(record).encode()
            self.assertEqual(gui.safe_test_failure(record), record)
            self.assertEqual(gui.checked_public_payload(encoded, 'failure.json'), encoded)
            with self.assertRaises(gui.DeviceFailure):
                gui.safe_test_failure(dict(record, target='private target is not evidence'))

    def test_fixed_integration_stages_fit_the_public_driver_allowlist(self):
        source = (REPO / 'validation/flutter/integration_test/android_pairing_observe_test.dart').read_text()
        stages = set(re.findall(r"stage\('([a-z_]+)'\)", source))
        self.assertTrue(stages)
        self.assertLessEqual(stages, gui.STAGES)
        for stage in stages:
            self.assertLessEqual(len(stage.encode()), gui.PUBLIC_LIMITS['stage'])

    def test_failure_metadata_has_no_message_stack_or_payload_channel(self):
        record = {'stage': 'guarded_direct_commit', 'errorClass': 'TestFailure', 'line': 240}
        self.assertEqual(gui.safe_test_failure(record), record)
        self.assertEqual(gui.checked_public_payload(json.dumps(record).encode(), 'failure.json'),
                         json.dumps(record).encode())
        for changes in ({'message': 'remote text'}, {'stage': 'user_supplied_text'},
                        {'stage': []}, {'errorClass': {}}, {'errorClass': 'unbounded failure'},
                        {'line': True}, {'line': 10001}):
            with self.assertRaises(gui.DeviceFailure):
                gui.safe_test_failure(dict(record, **changes))

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

    def test_stock_and_guarded_device_reports_cannot_substitute_for_each_other(self):
        first = {'requestId': 'a' * 32, 'terminalId': 'term_ab', 'paneId': 'w1:p1', 'acceptedBytes': 1}
        second = dict(first, requestId='b' * 32, acceptedBytes=9)
        report = device_report(case=gui.GUARDED_CASE, acceptedByteCounts=[1, 9],
                               inputReceipts=[first, second], **dict.fromkeys(gui.GUARDED_FIELDS, True),
                               **gui.CLIPBOARD_COUNTS)
        self.assertEqual(gui.safe_device_result(report, guarded=True)['inputReceipts'], [first, second])
        with self.assertRaises(gui.DeviceFailure):
            gui.safe_device_result(report)
        with self.assertRaises(gui.DeviceFailure):
            gui.safe_device_result(device_report(), guarded=True)
        for changes in ({'acceptedByteCounts': [True, 9]}, {'unsentDraftRestored': False},
                        {'inputReceipts': [first, dict(second, requestId=first['requestId'])]}):
            with self.assertRaises(gui.DeviceFailure):
                gui.safe_device_result(dict(report, **changes), guarded=True)

    def test_guarded_clipboard_evidence_is_required_bounded_and_never_copies_clipboard_contents(self):
        first = {'requestId': 'a' * 32, 'terminalId': 'term_ab', 'paneId': 'w1:p1', 'acceptedBytes': 1}
        second = dict(first, requestId='b' * 32, acceptedBytes=9)
        report = device_report(case=gui.GUARDED_CASE, acceptedByteCounts=[1, 9],
            inputReceipts=[first, second], **dict.fromkeys(gui.GUARDED_FIELDS, True), **gui.CLIPBOARD_COUNTS)
        for field in (*gui.CLIPBOARD_FIELDS, *gui.CLIPBOARD_COUNTS):
            missing = dict(report); missing.pop(field)
            with self.subTest(field=field, missing=True), self.assertRaises(gui.DeviceFailure):
                gui.safe_device_result(missing, guarded=True)
            for bad in (False, 1, 'private clipboard') if field in gui.CLIPBOARD_FIELDS else (False, 0, 999999):
                with self.subTest(field=field, value=bad), self.assertRaises(gui.DeviceFailure):
                    gui.safe_device_result(dict(report, **{field: bad}), guarded=True)
        clean = gui.safe_device_result(dict(report, clipboardText='PRIVATE', originalClipboard='PRIVATE'), guarded=True)
        self.assertNotIn('PRIVATE', json.dumps(clean))
        self.assertEqual(clean['inputReceipts'], [first, second])
        for field in (*gui.CLIPBOARD_FIELDS, *gui.CLIPBOARD_COUNTS):
            with self.subTest(stockField=field), self.assertRaises(gui.DeviceFailure):
                gui.safe_device_result(device_report(**{field: report[field]}))

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

    def test_clipboard_fixture_is_not_enabled_before_disposable_api35_device_checks(self):
        self.prepared(); args = self.args(); args.android_guarded_input = True
        args.input_fixture = 'owned-mobile-fixture'
        for prop, bad in (('ro.kernel.qemu', '0'), ('ro.build.version.sdk', '34'), ('get-current-user', '10')):
            def output(*parts, **kwargs):
                if parts == ('devices',): return 'List of devices attached\nemulator-5554\tdevice'
                values = {'ro.kernel.qemu': '1', 'ro.build.version.sdk': '35', 'get-current-user': '0'}
                return bad if parts[-1] == prop else values.get(parts[-1], '')
            with self.subTest(property=prop), patch.object(gui, 'text', side_effect=output), \
                    patch.object(gui, 'adb') as adb, patch.object(gui, 'package_present', return_value=False):
                launch = Mock()
                with self.assertRaisesRegex(gui.DeviceFailure, 'flutter_android_avd_api_or_user_mismatch'):
                    gui._run(args, self.fixture_root, self.env, self.config, Mock(), launch)
                launch.assert_not_called(); adb.assert_not_called()
                self.assertFalse((self.fixture_root / 'flutter-android-public-defines.json').exists())


class WireGuards(unittest.TestCase):
    @unittest.skipIf(paired_gui is None, 'signature verification requires cryptography')
    def test_independent_signer_verification_and_tampering(self):
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        key = Ed25519PrivateKey.generate()
        value = {'publicKey': key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode(),
                 'signature': base64.b64encode(key.sign(gui.SIGNER_CHALLENGE)).decode(),
                 'deleteReturned': True, 'readRejected': True}
        clean = gui.verify_signer(json.dumps(value).encode())
        self.assertEqual(clean, {'stage':'complete', 'signatureVerified':True, 'deleteReturned':True, 'readRejected':True})
        self.assertNotIn(value['publicKey'], json.dumps(clean))
        for change in ({'signature': base64.b64encode(bytes(64)).decode()}, {'readRejected': False},
                       {'signature': 'invalid!'}, {'handle': 'never-accepted'}):
            with self.subTest(change=change), self.assertRaises(gui.DeviceFailure):
                gui.verify_signer(json.dumps(dict(value, **change)).encode())

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
        for stage in ('response_finish_edit', 'response_rejected', 'response_save_unconfirmed',
                      'response_review_invalidated'):
            encoded = stage.encode('ascii')
            self.assertEqual(self.read(encoded, name='stage', limit=40), encoded)
        with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_public_stage_invalid$'):
            self.read(b'PRIVATE_STAGE', name='stage', limit=40)
        proc = Mock(); proc.poll.return_value = 1
        replies = [subprocess.CompletedProcess([], 1, b'',
            ('head: ' + self.relative + '/request.json: No such file or directory\n').encode()),
            subprocess.CompletedProcess([], 0, b'public_request', b'')]
        with patch.object(gui, 'package_present', return_value=True), patch.object(gui, 'adb', side_effect=replies):
            with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_test_exited_public_request$'):
                gui.wait_public(proc, self.relative, 'request.json', 2048, timeout=1)

    def test_wait_does_not_read_public_files_until_owned_package_appears(self):
        proc = Mock(); proc.poll.return_value = None
        package_states = iter((False, False, True))
        events = []
        def package_present():
            state = next(package_states)
            events.append(('package', state))
            return state
        def read_public(relative, limit):
            events.append(('read', relative.rsplit('/', 1)[1]))
            return b'{"public":"synthetic"}'
        with patch.object(gui, 'package_present', side_effect=package_present), \
             patch.object(gui, 'read_public', side_effect=read_public), \
             patch.object(gui.time, 'sleep') as sleep:
            result = gui.wait_public(proc, self.relative, 'signer.json', 1024, timeout=1)
        self.assertEqual(result, b'{"public":"synthetic"}')
        self.assertEqual(events, [('package', False), ('package', False),
                                  ('package', True), ('read', 'signer.json')])
        self.assertEqual(sleep.call_count, 2)

    def test_process_exit_before_install_does_not_read_stage_or_public_files(self):
        proc = Mock(); proc.poll.return_value = 1
        with patch.object(gui, 'package_present', return_value=False), \
             patch.object(gui, 'read_public') as read_public, \
             patch.object(gui, 'failure_stage') as failure_stage:
            with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_test_exited_before_install$'):
                gui.wait_public(proc, self.relative, 'signer.json', 1024, timeout=1)
        read_public.assert_not_called()
        failure_stage.assert_not_called()

    def test_package_install_wait_remains_bounded_without_reading_public_files(self):
        proc = Mock(); proc.poll.return_value = None
        with patch.object(gui.time, 'monotonic', side_effect=(0, 2)), \
             patch.object(gui, 'package_present', return_value=False), \
             patch.object(gui, 'read_public') as read_public, \
             patch.object(gui, 'failure_stage') as failure_stage:
            with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_package_install_timeout$'):
                gui.wait_public(proc, self.relative, 'signer.json', 1024, timeout=1)
        read_public.assert_not_called()
        failure_stage.assert_not_called()

    def test_read_failure_after_owned_package_appears_remains_fatal(self):
        proc = Mock(); proc.poll.return_value = None
        failure = gui.DeviceFailure('flutter_android_public_signer_read_failed')
        with patch.object(gui, 'package_present', return_value=True), \
             patch.object(gui, 'read_public', side_effect=failure) as read_public:
            with self.assertRaisesRegex(gui.DeviceFailure, '^flutter_android_public_signer_read_failed$'):
                gui.wait_public(proc, self.relative, 'signer.json', 1024, timeout=1)
        read_public.assert_called_once_with(self.relative + '/signer.json', 1024)

    def test_wait_only_delivers_final_json_to_approval_spy_after_diagnostics_and_partial_data(self):
        request = self.request()
        replies = [subprocess.CompletedProcess([], 1, b'',
                ('head: ' + self.relative + '/request.json: No such file or directory\n').encode()),
            subprocess.CompletedProcess([], 0, b' \n', b''),
            subprocess.CompletedProcess([], 0, b'{"version":', b''),
            subprocess.CompletedProcess([], 0, request, b'')]
        proc = Mock(); proc.poll.return_value = None
        approval = Mock(spec=['approve'])
        def sleep(_):
            approval.approve.assert_not_called()
        with patch.object(gui, 'package_present', return_value=True), \
             patch.object(gui, 'adb', side_effect=replies) as adb, \
             patch.object(gui.time, 'sleep', side_effect=sleep):
            approval.approve(gui.wait_public(proc, self.relative, 'request.json', 2048, timeout=1))
        self.assertEqual(adb.call_count, 4)
        approval.approve.assert_called_once_with(request)


class CleanupGuards(PreparedFixture):
    def exercise(self, fail_reverse_cleanup=False, fail_signer=False, guarded=False, fail_checkpoint=None):
        self.prepared(); args = self.args()
        args.android_guarded_input = guarded
        if guarded: args.input_fixture = 'owned-mobile-fixture'
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
            defines = json.loads((self.fixture_root / 'flutter-android-public-defines.json').read_text())
            self.assertEqual(defines['HERDR_ANDROID_API35_CLIPBOARD_FIXTURE'], 'true' if guarded else 'false')
            state['installed'] = True; forwards.add(owned)
            yield Process()
        def adb(*parts, **kwargs):
            calls.append(parts)
            if fail_checkpoint == 'ack' and parts[-1:] == ('cache/herdr-flutter-android-123/checkpoint-ack.new',):
                raise gui.DeviceFailure('synthetic_checkpoint_ack_failure')
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
        if fail_checkpoint == 'receiver':
            approval.verify_ssh.side_effect = gui.DeviceFailure('synthetic_checkpoint_receiver_failure')
        report = device_report()
        if guarded:
            first = {'requestId': 'a' * 32, 'terminalId': 'term_ab', 'paneId': 'w1:p1', 'acceptedBytes': 1}
            report.update(case=gui.GUARDED_CASE, acceptedByteCounts=[1, 9],
                inputReceipts=[first, dict(first, requestId='b' * 32, acceptedBytes=9)],
                **dict.fromkeys(gui.GUARDED_FIELDS, True), **gui.CLIPBOARD_COUNTS)
        public = iter((b'{"public":"signer"}', b'{"public":"request"}', json.dumps(report).encode()))
        def wait_public(*args, checkpoints=None, **kwargs):
            if checkpoints is not None:
                with patch.object(gui, 'read_public', side_effect=[
                        json.dumps({'checkpoint': label}).encode() for label in gui.CLIPBOARD_CHECKPOINTS]):
                    checkpoints.poll(); checkpoints.poll()
            return next(public)
        with patch.object(gui, 'adb', side_effect=adb), patch.object(gui, 'text', side_effect=text), \
                patch.object(gui, 'package_present', side_effect=lambda: state['installed']), \
                patch.object(gui, 'forward_set', side_effect=lambda: set(forwards)), \
                patch.object(gui, 'write_response'), \
                patch.object(gui, 'checked_flutter_version', return_value={'frameworkVersion': tool.FLUTTER_VERSION, 'frameworkRevision': tool.FLUTTER_COMMIT}), \
                patch.object(gui, 'wait_public', side_effect=wait_public), \
                patch.object(gui, 'verify_signer', side_effect=gui.DeviceFailure('flutter_android_signer_verification_failed') if fail_signer else None,
                    return_value={'stage':'complete','signatureVerified':True,'deleteReturned':True,'readRejected':True}):
            if fail_reverse_cleanup:
                with self.assertRaisesRegex(gui.DeviceFailure, 'flutter_android_cleanup_failed'):
                    gui._run(args, self.fixture_root, self.env, self.config, approval, process)
                result = None
            elif fail_signer:
                with self.assertRaisesRegex(gui.DeviceFailure, 'flutter_android_signer_verification_failed'):
                    gui._run(args, self.fixture_root, self.env, self.config, approval, process)
                approval.approve.assert_not_called()
                result = None
            elif fail_checkpoint:
                with self.assertRaisesRegex(gui.DeviceFailure, 'synthetic_checkpoint_' + fail_checkpoint + '_failure'):
                    gui._run(args, self.fixture_root, self.env, self.config, approval, process)
                self.assertEqual(approval.verify_ssh.call_count, 1)
                self.assertLessEqual(sum(parts[-1:] == ('cache/herdr-flutter-android-123/checkpoint-ack.new',) for parts in calls), 1)
                result = None
            else:
                result = gui._run(args, self.fixture_root, self.env, self.config, approval, process)
        self.assertEqual(forwards, {original})
        self.assertFalse(state['installed'])
        self.assertIn(('uninstall', gui.PACKAGE), calls)
        self.assertEqual(calls.count(('uninstall', gui.PACKAGE)), 1)
        self.assertNotIn(('forward', '--remove', original[1]), calls)
        self.assertFalse((self.fixture_root / 'flutter-android-public-defines.json').exists())
        cleanup = json.loads((args.output / 'flutter-android-device-cleanup.json').read_text())
        evidence = json.loads((args.output / 'flutter-android-signer-probe.json').read_text())
        self.assertEqual(evidence['signatureVerified'], not fail_signer)
        self.assertEqual(evidence['stage'], 'verification_failed' if fail_signer else 'complete')
        return result, cleanup

    def test_only_owned_package_reverse_and_new_vm_forward_are_cleaned(self):
        result, cleanup = self.exercise()
        self.assertEqual(cleanup['status'], 'passed')
        self.assertTrue(result['deviceCleanup']['ownedPackageAbsent'])
        self.assertFalse(result['storageMocked'])  # This label is from the real runner; this test is not device evidence.
        self.assertFalse(cleanup['rawLogsUploaded'])

    def test_guarded_run_requires_clipboard_contract_but_keeps_the_original_two_receipts(self):
        result, cleanup = self.exercise(guarded=True)
        self.assertEqual(cleanup['status'], 'passed')
        self.assertEqual(result['acceptedByteCounts'], [1, 9])
        self.assertEqual(len(result['inputReceipts']), 2)
        self.assertIs(result['pasteOperationsNoExtraSshBytes'], True)
        for field in gui.CLIPBOARD_FIELDS:
            self.assertIs(result[field], True)
        for field, expected in gui.CLIPBOARD_COUNTS.items():
            self.assertEqual(result[field], expected)

    def test_failed_cleanup_is_recorded_and_cannot_return_passed(self):
        result, cleanup = self.exercise(fail_reverse_cleanup=True)
        self.assertIsNone(result)
        self.assertEqual(cleanup['status'], 'failed')
        self.assertFalse(cleanup['reverseRemoved'])
        self.assertTrue(cleanup['ownedPackageAbsent'])

    def test_failed_signer_verification_stops_before_host_approval(self):
        result, cleanup = self.exercise(fail_signer=True)
        self.assertIsNone(result)
        self.assertEqual(cleanup['status'], 'passed')

    def test_failed_clipboard_receiver_cleans_owned_resources_without_returning_success(self):
        result, cleanup = self.exercise(guarded=True, fail_checkpoint='receiver')
        self.assertIsNone(result)
        self.assertEqual(cleanup['status'], 'passed')

    def test_failed_clipboard_ack_cleans_owned_resources_without_replaying_unknown_write(self):
        result, cleanup = self.exercise(guarded=True, fail_checkpoint='ack')
        self.assertIsNone(result)
        self.assertEqual(cleanup['status'], 'passed')


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
            approval = Mock(spec=['verify_ssh', 'revoke', 'applied', 'fingerprint_authenticated'])
            approval.applied = failure != 'device'
            approval.fingerprint_authenticated.return_value = failure is None
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
        self.assertEqual(approval.method_calls, [('verify_ssh', (b'',), {}),
            ('fingerprint_authenticated', (), {}), ('revoke', (), {})])
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
        self.assertFalse(result['matchedDeviceKeyInSshd'])
        self.assertFalse(result['temporaryHostApprovedRequest'])

    def test_native_route_verification_failure_still_revokes(self):
        result, approval = self.exercise('verification')
        approval.verify_ssh.assert_called_once_with(b'')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errorCode'], 'synthetic_verification_failure')
        self.assertTrue(result['revokedFixtureKey'])
        self.assertFalse(result['matchedDeviceKeyInSshd'])


class ClipboardCheckpointGuards(unittest.TestCase):
    relative = 'cache/herdr-flutter-android-123'

    def test_only_exact_bounded_checkpoint_requests_are_accepted(self):
        for label in gui.CLIPBOARD_CHECKPOINTS:
            raw = json.dumps({'checkpoint': label}).encode()
            self.assertEqual(gui.checked_public_payload(raw, 'checkpoint.json'), raw)
        for value in ({'checkpoint': 'PRIVATE'}, {'checkpoint': 1}, {'checkpoint': []},
                      {'checkpoint': gui.CLIPBOARD_CHECKPOINTS[0], 'clipboard': 'PRIVATE'}):
            with self.subTest(value=value), self.assertRaises(gui.DeviceFailure):
                gui.checked_public_payload(json.dumps(value).encode(), 'checkpoint.json')

    def test_two_checkpoints_verify_real_receiver_before_atomic_ack_and_ignore_duplicate_poll(self):
        approval = Mock()
        state = gui.ClipboardCheckpoints(self.relative, approval)
        events = []
        approval.verify_ssh.side_effect = lambda expected: events.append(('verify', expected))
        def adb(*args, **kwargs):
            events.append(('ack', args, kwargs))
        labels = (gui.CLIPBOARD_CHECKPOINTS[0], gui.CLIPBOARD_CHECKPOINTS[0], gui.CLIPBOARD_CHECKPOINTS[1])
        with patch.object(gui, 'read_public', side_effect=[json.dumps({'checkpoint': item}).encode() for item in labels]), \
                patch.object(gui, 'adb', side_effect=adb):
            state.poll(); state.poll(); state.poll(); state.require_complete()
        self.assertEqual(approval.verify_ssh.call_args_list, [((b'k',), {}), ((b'k',), {})])
        self.assertEqual([event[0] for event in events], ['verify', 'ack', 'ack', 'verify', 'ack', 'ack'])
        for index, label in ((1, labels[0]), (4, labels[2])):
            self.assertEqual(events[index][1], ('shell', '-T', 'run-as', gui.PACKAGE, 'tee', self.relative + '/checkpoint-ack.new'))
            self.assertEqual(json.loads(events[index][2]['data']), {'checkpoint': label})
        self.assertEqual(state.completed, list(gui.CLIPBOARD_CHECKPOINTS))

    def test_out_of_order_old_or_missing_checkpoint_is_fatal(self):
        for completed, label in (([], gui.CLIPBOARD_CHECKPOINTS[1]),
                                 (list(gui.CLIPBOARD_CHECKPOINTS), gui.CLIPBOARD_CHECKPOINTS[0])):
            state = gui.ClipboardCheckpoints(self.relative, Mock()); state.completed = completed
            with patch.object(gui, 'read_public', return_value=json.dumps({'checkpoint': label}).encode()), \
                    patch.object(gui, 'adb') as adb:
                with self.assertRaisesRegex(gui.DeviceFailure, 'checkpoint_order_invalid'):
                    state.poll()
                adb.assert_not_called(); state.approval.verify_ssh.assert_not_called()
        for completed in ([], [gui.CLIPBOARD_CHECKPOINTS[0]]):
            state = gui.ClipboardCheckpoints(self.relative, Mock()); state.completed = completed
            with self.assertRaisesRegex(gui.DeviceFailure, 'checkpoints_missing'):
                state.require_complete()

    def test_receiver_or_ack_failure_does_not_mark_checkpoint_complete(self):
        for bad in ('receiver', 'ack'):
            approval = Mock(); state = gui.ClipboardCheckpoints(self.relative, approval)
            if bad == 'receiver': approval.verify_ssh.side_effect = gui.DeviceFailure('unexpected_remote_input')
            with patch.object(gui, 'read_public', return_value=json.dumps({'checkpoint': gui.CLIPBOARD_CHECKPOINTS[0]}).encode()), \
                    patch.object(gui, 'adb', side_effect=gui.DeviceFailure('flutter_android_adb_failed') if bad == 'ack' else None) as adb:
                with self.assertRaises(gui.DeviceFailure): state.poll()
                self.assertEqual(state.completed, [])
                if bad == 'receiver': adb.assert_not_called()

    def test_stock_wait_never_reads_checkpoints_and_guarded_result_cannot_bypass_them(self):
        proc = Mock(); proc.poll.return_value = None
        with patch.object(gui, 'package_present', return_value=True), \
                patch.object(gui, 'read_public', return_value=b'{}') as read:
            self.assertEqual(gui.wait_public(proc, self.relative, 'result.json', 8192, timeout=1), b'{}')
            read.assert_called_once_with(self.relative + '/result.json', 8192)
        state = gui.ClipboardCheckpoints(self.relative, Mock())
        with patch.object(gui, 'package_present', return_value=True), \
                patch.object(gui, 'read_public', side_effect=[None, b'{}']):
            with self.assertRaisesRegex(gui.DeviceFailure, 'checkpoints_missing'):
                gui.wait_public(proc, self.relative, 'result.json', 8192, timeout=1, checkpoints=state)

    def test_guarded_checkpoint_wait_has_bounded_timeout_and_checks_process_exit(self):
        for exited in (False, True):
            proc = Mock(); proc.poll.return_value = 1 if exited else None
            state = gui.ClipboardCheckpoints(self.relative, Mock())
            ticks = (0, 0, 2) if not exited else (0, 0)
            with patch.object(gui.time, 'monotonic', side_effect=ticks), patch.object(gui.time, 'sleep'), \
                    patch.object(gui, 'package_present', return_value=True), \
                    patch.object(gui, 'read_public', return_value=None), \
                    patch.object(gui, 'failure_stage', return_value='bounded_failure'), patch.object(gui, 'adb') as adb:
                with self.assertRaisesRegex(gui.DeviceFailure, '^bounded_failure$'):
                    gui.wait_public(proc, self.relative, 'result.json', 8192, timeout=1, checkpoints=state)
                state.approval.verify_ssh.assert_not_called(); adb.assert_not_called()


if __name__ == '__main__':
    unittest.main()
