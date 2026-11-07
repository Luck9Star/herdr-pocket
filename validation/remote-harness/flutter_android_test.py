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
        **{name: True for name in gui.BOOL_FIELDS}, 'profileCreationActionsBeforeReview': 0, 'identityCreationActions': 1,
        'localFontMarkerColumns': [15] * 8, 'observerCanvas': {'cols':120,'rows':40,'wideMarkerMatched':True,'wideMarkerVisible':True,'readingPositionRestored':True},
        'localThemePromptCursors': gui.theme_prompt_expectations(),
        'firstSequence': 5, 'deltaSequence': 7, 'frameCountLowerBound': 2, 'deltaCountLowerBound': 1}
    value.update(changes)
    return value


def tui_resume_report(**changes):
    value = {'schemaVersion':1,'actionsCompleted':3,'boardCount':1,'tabCount':1,'resumeCount':0,
        'viewCount':1,'terminalReplaced':True,'sequencePresent':True,'sequence':5,
        'cols':80,'rows':24,'bufferRows':24,'cursorKeysMode':True,'directCount':1,'directEnabled':True,
        'rowsChecked':24,'rowMatchMask':0xffffff,'firstMismatchRow':-1,'tailRowsBlank':True,'titleRowMask':1}
    value.update(changes)
    return value


def checkpoint_payload(label):
    return {'checkpoint': label, **({'viewInsetBottom': 300 if label.endswith(('-shown', '-reopened', '-request')) else 0,
        'editorFocused': True, 'modeReselected': False} if label not in gui.CLIPBOARD_CHECKPOINTS else {})}


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
        pubspec = 'name: synthetic\ndependencies:\n  terminal_view: 0.5.0\ndev_dependencies:\n  flutter_test:\n    sdk: flutter\n'
        (self.source / 'pubspec.yaml').write_text(pubspec)
        (self.app / 'pubspec.yaml').write_text(tool.terminal_view_ime.reference_pubspec(pubspec))
        (self.app / 'pubspec_overrides.yaml').write_text('dependency_overrides:\n  terminal_view:\n    path: candidate/terminal_view\n')
        (self.app / 'candidate/terminal_view').mkdir(parents=True)
        shutil.copytree(self.source / 'lib', self.app / 'lib')
        native = self.app / 'android/app/src/main/kotlin/dev/herdr/herdr_flutter_probe'
        shutil.copytree(self.source / 'native/android', native)
        self.gradle = self.app / 'android/app/build.gradle.kts'
        self.gradle.write_text('namespace = "dev.herdr.herdr_flutter_probe"\napplicationId = "dev.herdr.herdr_flutter_probe"\n'
            'compileOptions { sourceCompatibility = JavaVersion.VERSION_17 }\nkotlinOptions { jvmTarget = "17" }\n')
        self.baseline = 'packages:\n' + ''.join(block(name) for name in ('flutter', 'flutter_test', 'terminal_view', 'dartssh2'))
        (self.source / 'pubspec.lock').write_text(self.baseline)
        self.baseline = self.baseline.replace(block('terminal_view'), '  terminal_view:\n    dependency: "direct main"\n    description:\n      path: "candidate/terminal_view"\n      relative: true\n    source: path\n    version: "0.5.0"\n')
        self.footer = 'sdks:\n  dart: ">=3.11.0 <4.0.0"\n'
        (self.app / 'pubspec.lock').write_text(self.baseline + self.footer)
        (self.app / '.herdr-generated-probe.json').write_text(json.dumps({'kind': 'herdr-flutter-validation', 'sourceCommit': self.env['GITHUB_SHA']}))
        (self.app / 'candidate-manifest.json').write_text(json.dumps({'sourceCommit': self.env['GITHUB_SHA'],
            'variant': 'experimental-patched', 'candidateLockSha256': tool.digest(self.app / 'pubspec.lock')}))
        root_temp = tempfile.TemporaryDirectory(prefix='hp-mobile-123-', dir='/tmp')
        self.addCleanup(root_temp.cleanup)
        self.fixture_root = Path(root_temp.name).resolve()
        self.config = {'schemaVersion': 1, 'host': '127.0.0.1', 'port': 2222, 'username': 'fixture',
            'expectedHostKey': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINdamAGCsQq31Uv+08lkBzoO4XLz2qYjJa8CGmj3B1Ea', 'socketPath': str(self.fixture_root / 'config/herdr/sessions/pocket-probe/herdr.sock'),
            'herdrPath': str(self.fixture_root / 'herdr'), 'session': 'pocket-probe', 'paneId': 'w1:p1', 'reviewConfirmed': True}

    def prepared(self):
        tool.prepare(self.app, self.env)
        (self.app / 'pubspec.lock').write_text(self.baseline + ''.join(block(name) for name in sorted(tool.SDK_ADDITIONS)) + self.footer)
        return tool.verify_lock(self.app, self.env)

    def args(self):
        output = self.runner / 'output'; output.mkdir(exist_ok=True)
        return type('Args', (), {'flutter_app': self.app, 'input_fixture': None, 'output': output})()


class ScaffoldGuards(PreparedFixture):
    def test_preparation_cli_reports_static_guard_and_omits_external_errors(self):
        for error, reason in (
            (tool.DevicePreparationFailure('android_device_pubspec_source_mismatch'), 'android_device_pubspec_source_mismatch'),
            (OSError('private fixture path'), None),
        ):
            with self.subTest(reason=reason), patch.object(tool, 'prepare', side_effect=error), \
                    patch('sys.argv', ['probe', 'prepare', '--destination', str(self.app)]), patch('builtins.print') as output:
                self.assertEqual(tool.main(), 1)
                report = json.loads(output.call_args.args[0])
                expected = {'status': 'failed', 'step': 'prepare', 'errorCode': 'android_device_preparation_failed'}
                if reason is not None:
                    expected['reason'] = reason
                self.assertEqual(report, expected)

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

    def test_unapproved_pubspec_and_override_are_rejected_before_and_after_prepare(self):
        spec = self.app / 'pubspec.yaml'
        expected = spec.read_text()
        spec.write_text(expected.replace('candidate/reference_terminal_view', '../other'))
        with self.assertRaises(tool.DevicePreparationFailure): tool.prepare(self.app, self.env)
        spec.write_text(expected)
        override = self.app / 'pubspec_overrides.yaml'
        correct = override.read_text()
        override.write_text(correct.replace('candidate/terminal_view', '../other'))
        with self.assertRaises(tool.DevicePreparationFailure): tool.prepare(self.app, self.env)
        override.write_text(correct)
        tool.prepare(self.app, self.env)
        (self.app / 'pubspec.lock').write_text(self.baseline + ''.join(block(name) for name in sorted(tool.SDK_ADDITIONS)) + self.footer)
        override.write_text(correct.replace('candidate/terminal_view', '../other'))
        with self.assertRaises(tool.DevicePreparationFailure): tool.verify_lock(self.app, self.env)

    def test_wrong_candidate_lock_rejected_even_with_matching_manifest_hash(self):
        lock = self.app / 'pubspec.lock'
        lock.write_text(lock.read_text().replace('candidate/terminal_view', '../other'))
        manifest = self.app / 'candidate-manifest.json'
        value = json.loads(manifest.read_text())
        value['candidateLockSha256'] = tool.digest(lock)
        manifest.write_text(json.dumps(value))
        with self.assertRaises(tool.DevicePreparationFailure): tool.prepare(self.app, self.env)
        self.assertFalse((self.app / tool.MARKER).exists())

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
    def test_public_profile_wire_is_exact_allowlist_without_local_identity_or_private_material(self):
        raw = gui.public_profile_json(self.config)
        data = json.loads(raw)
        self.assertEqual(set(data), {'version', 'type', 'host', 'port', 'username', 'provider',
                                     'session', 'socketPath', 'herdrPath', 'expectedHostKey'})
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['type'], 'herdr-connection-profile')
        self.assertEqual(data['provider'], 'direct')
        for name in ('host', 'port', 'username', 'session', 'socketPath', 'herdrPath', 'expectedHostKey'):
            self.assertEqual(data[name], self.config[name])
        self.assertLessEqual(len(raw.encode('utf-8')), 2048)
        self.assertEqual(gui.public_host_fingerprint(data['expectedHostKey']),
                         'SHA256:bbXpuKG6zhzdmnxq256TlqzFBzRl2f6OOg722cYNbU8')
        self.assertNotIn('paneId', raw)
        self.assertNotIn('reviewConfirmed', raw)
        for bad in ({**self.config, 'privateKeyPem':'NEVER'}, {**self.config, 'port':True},
                    {**self.config, 'host':'x'*2049}, {**self.config, 'expectedHostKey':'invalid'}):
            with self.subTest(bad=list(bad)), self.assertRaises(gui.DeviceFailure):
                gui.public_profile_json(bad)

    def test_public_fingerprint_rejects_noncanonical_and_malformed_blobs(self):
        valid = self.config['expectedHostKey']
        for value in (valid + ' comment', valid + '=', 'ssh-rsa ' + valid.split(' ')[1],
                      'ssh-ed25519 AAAA', None):
            with self.subTest(value=value), self.assertRaises(gui.DeviceFailure):
                gui.public_host_fingerprint(value)

    def test_profile_evidence_requires_true_observations_and_zero_pre_review_actions(self):
        for field in ('profilePreviewShown', 'profileFieldsMatched', 'profileFingerprintMatched',
                      'profileTargetUnreviewed', 'profileNoCreationIntent'):
            with self.subTest(field=field), self.assertRaises(gui.DeviceFailure):
                gui.safe_device_result(device_report(**{field: False}))
        for bad in (1, True, None, '0'):
            with self.subTest(count=bad), self.assertRaises(gui.DeviceFailure):
                gui.safe_device_result(device_report(profileCreationActionsBeforeReview=bad))

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
        report = device_report(case=gui.GUARDED_CASE, acceptedByteCounts=[1, 9], restoredViewportLogicalPixels=[96,96],
                               inputReceipts=[first, second], **dict.fromkeys(gui.GUARDED_FIELDS, True),
                               **gui.CLIPBOARD_COUNTS)
        self.assertEqual(gui.safe_device_result(report, guarded=True)['inputReceipts'], [first, second])
        with self.assertRaises(gui.DeviceFailure):
            gui.safe_device_result(report)
        with self.assertRaises(gui.DeviceFailure):
            gui.safe_device_result(device_report(), guarded=True)
        for changes in ({'acceptedByteCounts': [True, 9]}, {'unsentDraftRestored': False},
                        {'restoredViewportLogicalPixels': [96, 0]}, {'restoredViewportLogicalPixels': [12, True]},
                        {'inputReceipts': [first, dict(second, requestId=first['requestId'])]}):
            with self.assertRaises(gui.DeviceFailure):
                gui.safe_device_result(dict(report, **changes), guarded=True)

    def test_guarded_clipboard_evidence_is_required_bounded_and_never_copies_clipboard_contents(self):
        first = {'requestId': 'a' * 32, 'terminalId': 'term_ab', 'paneId': 'w1:p1', 'acceptedBytes': 1}
        second = dict(first, requestId='b' * 32, acceptedBytes=9)
        report = device_report(case=gui.GUARDED_CASE, acceptedByteCounts=[1, 9], restoredViewportLogicalPixels=[96,96],
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

    def test_tui_requires_guarded_before_any_device_or_launch_operation(self):
        self.prepared();args=self.args();args.android_tui=True
        with patch.object(gui,'text') as text,patch.object(gui,'adb') as adb:
            launch=Mock();approval=Mock()
            with self.assertRaisesRegex(gui.DeviceFailure,'android_tui_requires_guarded_input'):
                gui._run(args,self.fixture_root,self.env,self.config,approval,launch)
            text.assert_not_called();adb.assert_not_called();launch.assert_not_called();approval.start_tui.assert_not_called()
            self.assertFalse((self.fixture_root/'flutter-android-public-defines.json').exists())

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

    def test_preserve_measured_marker_positions_and_reject_malformed_sample_values(self):
        measured = [15, 15, 16, 15, 15, 15, 0, 15]
        clean = gui.safe_device_result(device_report(localFontMarkerColumns=measured))
        self.assertEqual(clean['localFontMarkerColumns'], measured)
        for columns in (None, measured[:7], [True] * 8, [2] * 8, [17] * 8, ['15'] * 8):
            with self.subTest(columns=columns), self.assertRaises(gui.DeviceFailure):
                gui.safe_device_result(device_report(localFontMarkerColumns=columns))

    def test_theme_cursors_require_both_locked_samples_exact_integer_fields(self):
        expected = gui.theme_prompt_expectations()
        self.assertEqual(gui.safe_device_result(device_report())['localThemePromptCursors'],expected)
        malformed = [None, [], {}, {**expected,'unknown':expected['powerlevel10k']},
                     {'powerlevel10k':expected['powerlevel10k']}]
        for field in expected['powerlevel10k']:
            for value in (None, True, False, '0', 0.0, -1, 40, 999):
                if type(value) is int and value == expected['powerlevel10k'][field]:
                    continue
                malformed.append({**expected,'powerlevel10k':{**expected['powerlevel10k'],field:value}})
        malformed.append({**expected,'powerlevel10k':{**expected['powerlevel10k'],'terminalText':'PRIVATE'}})
        malformed.append({**expected,'oh-my-posh':expected['powerlevel10k']})
        for measured in malformed:
            with self.subTest(measured=measured),self.assertRaises(gui.DeviceFailure):
                gui.safe_device_result(device_report(localThemePromptCursors=measured))

    def test_old_device_result_without_theme_probe_cannot_pass_current_contract(self):
        old = device_report()
        del old['localThemePromptCursors']
        with self.assertRaises(gui.DeviceFailure):
            gui.safe_device_result(old)

    def test_theme_expectations_reject_a_fixture_not_matching_its_lock(self):
        with patch.object(gui.hashlib,'sha256') as hashed:
            hashed.return_value.hexdigest.return_value = '0' * 64
            with self.assertRaises(gui.DeviceFailure):
                gui.theme_prompt_expectations()

    def test_android_theme_instrumentation_reads_real_views_after_each_normal_choice(self):
        source=(REPO/'validation/flutter/integration_test/android_pairing_observe_test.dart').read_text()
        flow=source[source.index('Future<({List<int> markers,'):source.index('/// Observe the real view after')]
        for expected in ("rootBundle.loadString('assets/shared/theme-prompt-samples-v1.json')",
                         "await tapKey(tester,'terminal-font-sample-$id')",
                         "ValueKey('terminal-theme-view-$id')",'terminal.buffer.cursorX',
                         'terminal.buffer.cursorY','expect(themeView.readOnly,isTrue)',
                         'expect(themeView.autoResize,isFalse)','expect(x,expected.cursorColumn)',
                         'expect(y,expected.cursorRow)'):
            self.assertIn(expected,flow)
        self.assertNotIn('cursorColumn:14',flow)
        self.assertNotIn('cursorColumn:15',flow)
        self.assertLess(flow.index('markers[row] ='),flow.index('for (final id in const'))
        self.assertIn("'localThemePromptCursors':fontDiagnostics.themes",source)

    def test_stock_observer_canvas_requires_measured_geometry_and_marker(self):
        expected = {'cols': 120, 'rows': 40, 'wideMarkerMatched': True,
                    'wideMarkerVisible': True, 'readingPositionRestored': True}
        raw = device_report(observerCanvas=dict(expected, terminalText='synthetic'))
        self.assertEqual(gui.safe_device_result(raw)['observerCanvas'], expected)
        missing = device_report()
        del missing['observerCanvas']
        invalid = (None, {}, dict(expected, cols=80), dict(expected, rows=24),
                   dict(expected, cols=True), dict(expected, rows=40.0),
                   dict(expected, wideMarkerMatched=1), dict(expected, wideMarkerMatched=False),
                   dict(expected, wideMarkerVisible=1), dict(expected, wideMarkerVisible=False),
                   dict(expected, readingPositionRestored=1), dict(expected, readingPositionRestored=False),
                   {k:v for k,v in expected.items() if k != 'wideMarkerVisible'},
                   {k:v for k,v in expected.items() if k != 'readingPositionRestored'})
        for item in [missing, *(device_report(observerCanvas=canvas) for canvas in invalid)]:
            with self.subTest(item=item.get('observerCanvas')), self.assertRaisesRegex(
                    gui.DeviceFailure, '^flutter_android_observer_canvas_unconfirmed$'):
                gui.safe_device_result(item)

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
        blocked = [{'paneId': 'w2:p1', 'terminalId': 'term_abc'},
                   {'paneId': 'w3:p1', 'terminalId': 'term_def'}]
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
            self.assertEqual(defines['HERDR_ANDROID_API35_KEYBOARD_FIXTURE'], 'true')
            self.assertEqual(json.loads(defines['HERDR_ANDROID_BLOCKED_TARGETS']), [] if guarded else blocked)
            self.assertEqual(defines['HERDR_ANDROID_PROFILE_JSON'], gui.public_profile_json(self.config))
            self.assertNotIn('privateKeyPem', defines['HERDR_ANDROID_PROFILE_JSON'])
            self.assertEqual(defines['HERDR_ANDROID_HOST_FINGERPRINT'], gui.public_host_fingerprint(self.config['expectedHostKey']))
            state['installed'] = True; forwards.add(owned)
            try:
                yield Process()
            finally:
                if fail_checkpoint == 'ime':
                    self.assertTrue((args.output/'flutter-android-system-ime-failure.json').is_file())
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
            if parts == ('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard'): return '1'
            if parts == ('reverse', '--list'):
                return gui.SERIAL + ' tcp:2222 tcp:2222' if state['reverse'] else ''
            return ''
        approval = Mock(); approval.approve.return_value = b'{"public":"response"}'
        approval.blocked_targets = blocked
        approval.verify_blocked_targets.return_value = blocked
        if fail_checkpoint == 'receiver':
            approval.verify_ssh.side_effect = gui.DeviceFailure('synthetic_checkpoint_receiver_failure')
        report = device_report()
        if guarded:
            first = {'requestId': 'a' * 32, 'terminalId': 'term_ab', 'paneId': 'w1:p1', 'acceptedBytes': 1}
            report.update(case=gui.GUARDED_CASE, acceptedByteCounts=[1, 9], restoredViewportLogicalPixels=[96, 96],
                inputReceipts=[first, dict(first, requestId='b' * 32, acceptedBytes=9)],
                **dict.fromkeys(gui.GUARDED_FIELDS, True), **gui.CLIPBOARD_COUNTS)
        else:
            report['blockedTargetEvidence'] = dict(blocked[1], listedRows=2, reviewRequired=True,
                observing=True, markerMatched=True, otherMarkerAbsent=True)
        public = iter((b'{"public":"signer"}', b'{"public":"request"}', json.dumps(report).encode()))
        def wait_public(*args, checkpoints=None, **kwargs):
            if checkpoints is not None:
                payloads = [checkpoint_payload(label) for label in checkpoints.expected]
                def system(_read, _package, visible):
                    if fail_checkpoint == 'ime':
                        raise gui.SystemImeFailure('android_system_ime_target_mismatch',
                            {'reason':'focus_foreign','focusOwner':'foreign','attempts':1,'raw':'PRIVATE'})
                    return {'visible':visible,'ownedTarget':True}
                with patch.object(gui, 'read_public', side_effect=[
                        json.dumps(value).encode() for value in payloads]), \
                        patch.object(gui, 'wait_system_ime', side_effect=system):
                    for _ in payloads: checkpoints.poll()
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
                expected = 'flutter_android_signer_verification_failed' if fail_signer else 'flutter_android_cleanup_failed'
                with self.assertRaisesRegex(gui.DeviceFailure, '^' + expected + '$'):
                    gui._run(args, self.fixture_root, self.env, self.config, approval, process)
                result = None
            elif fail_signer:
                with self.assertRaisesRegex(gui.DeviceFailure, 'flutter_android_signer_verification_failed'):
                    gui._run(args, self.fixture_root, self.env, self.config, approval, process)
                approval.approve.assert_not_called()
                result = None
            elif fail_checkpoint:
                expected_error = 'android_system_ime_target_mismatch' if fail_checkpoint == 'ime' else 'synthetic_checkpoint_' + fail_checkpoint + '_failure'
                with self.assertRaisesRegex(gui.DeviceFailure, '^'+expected_error+'$'):
                    gui._run(args, self.fixture_root, self.env, self.config, approval, process)
                self.assertEqual(approval.verify_ssh.call_count, 0 if fail_checkpoint == 'ime' else 1)
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

    def test_finally_collects_only_validated_resume_diagnostics_in_existing_failure_artifact(self):
        record={'stage':'tui_resume_full','errorClass':'TestFailure','line':68,'tuiResume':tui_resume_report()}
        with patch.object(gui,'read_public',return_value=json.dumps(record).encode()):
            self.exercise(fail_checkpoint='receiver')
        output=json.loads((self.runner/'output/flutter-android-test-failure.json').read_text())
        self.assertEqual(output,{'sourceSHA':self.env['GITHUB_SHA'],'failure':record})

    def test_finally_rejects_a_resume_failure_with_unapproved_payload(self):
        payload={'stage':'tui_resume_full','errorClass':'TestFailure','line':68,
                 'tuiResume':tui_resume_report(),'message':'PRIVATE'}
        with patch.object(gui,'read_public',return_value=json.dumps(payload).encode()):
            self.exercise(fail_checkpoint='receiver')
        output=json.loads((self.runner/'output/flutter-android-test-failure.json').read_text())
        self.assertEqual(output,{'sourceSHA':self.env['GITHUB_SHA'],'failure':None})
        self.assertNotIn('PRIVATE',json.dumps(output))

    def test_failed_cleanup_is_recorded_and_cannot_return_passed(self):
        result, cleanup = self.exercise(fail_reverse_cleanup=True)
        self.assertIsNone(result)
        self.assertEqual(cleanup['status'], 'failed')
        self.assertFalse(cleanup['reverseRemoved'])
        self.assertTrue(cleanup['ownedPackageAbsent'])

    def test_primary_failure_survives_failed_cleanup(self):
        result, cleanup = self.exercise(fail_reverse_cleanup=True, fail_signer=True)
        self.assertIsNone(result)
        self.assertEqual(cleanup['status'], 'failed')
        self.assertEqual(cleanup['primaryFailure'], 'flutter_android_signer_verification_failed')
        self.assertTrue(cleanup['ownedPackageAbsent'])
        self.assertFalse(cleanup['reverseRemoved'])

    def test_caller_handling_an_unrelated_error_does_not_become_driver_primary_failure(self):
        try:
            raise RuntimeError('PRIVATE OUTER ERROR')
        except RuntimeError:
            _, cleanup = self.exercise(fail_reverse_cleanup=True)
        self.assertNotIn('primaryFailure', cleanup)
        self.assertEqual(cleanup['status'], 'failed')

    def test_unknown_primary_error_is_redacted(self):
        self.assertEqual(gui._safe_primary_failure(gui.DeviceFailure('PRIVATE')), 'flutter_android_primary_failure')
        self.assertEqual(gui._safe_primary_failure(ValueError('PRIVATE')), 'flutter_android_primary_failure')

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

    def test_ime_failure_is_written_before_cleanup_and_keeps_original_failure(self):
        result, cleanup = self.exercise(guarded=True, fail_checkpoint='ime')
        self.assertIsNone(result);self.assertEqual(cleanup['status'],'passed')
        raw=(self.runner/'output/flutter-android-system-ime-failure.json').read_text()
        evidence=json.loads(raw)
        self.assertEqual(evidence['checkpoint'],'keyboard-direct-shown')
        self.assertEqual(evidence['systemRead'],'requested_state')
        self.assertEqual(evidence['diagnostic'],{'reason':'focus_foreign','focusOwner':'foreign','attempts':1})
        self.assertEqual(evidence['completedCheckpoints'],[])
        self.assertNotIn('PRIVATE',raw)


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
                'expectedHostKey': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINdamAGCsQq31Uv+08lkBzoO4XLz2qYjJa8CGmj3B1Ea'}
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
            self.assertEqual(host_factory.call_args.args[1:], ('fixture', config['expectedHostKey']))
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

    def test_legacy_wait_can_omit_checkpoints_but_explicit_new_checks_cannot_be_bypassed(self):
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


class TuiResumeDiagnosticGuards(unittest.TestCase):
    def test_resume_v2_reports_only_bounded_page_and_adapter_state(self):
        diagnostic=tui_resume_report(schemaVersion=2,pageCount=1,pageBusy=True,pagePaused=False,
            pageLive=False,evidenceFull=False,boardFreshness='refreshing',adapterPhase='snapshot',adapterError='none')
        record={'stage':'tui_resume_full','errorClass':'TestFailure','line':131,'tuiResume':diagnostic}
        raw=json.dumps(record,separators=(',',':')).encode()
        self.assertLessEqual(len(raw),gui.PUBLIC_LIMITS['failure.json'])
        self.assertEqual(gui.safe_test_failure(record),record)
        self.assertEqual(gui.checked_public_payload(raw,'failure.json'),raw)
        for field,value in [('adapterPhase','private'),('adapterError','private'),('boardFreshness','private'),
                            ('pageCount',3),('pageLive',1),('private','secret')]:
            with self.subTest(field=field),self.assertRaises(gui.DeviceFailure):
                gui.safe_tui_resume({**diagnostic,field:value})
        with self.assertRaises(gui.DeviceFailure):
            gui.safe_tui_resume({**diagnostic,'pageCount':0})

    def test_all_resume_substages_roundtrip_bounded_false_predicates_without_text(self):
        for stage in gui.TUI_RESUME_STAGES:
            diagnostic=tui_resume_report(cursorKeysMode=False,rowMatchMask=0xffffef,firstMismatchRow=4)
            record={'stage':stage,'errorClass':'TestFailure','line':68,'tuiResume':diagnostic}
            raw=json.dumps(record,separators=(',',':')).encode()
            self.assertLessEqual(len(raw),gui.PUBLIC_LIMITS['failure.json'])
            self.assertEqual(gui.safe_test_failure(record),record)
            self.assertEqual(gui.checked_public_payload(raw,'failure.json'),raw)
            self.assertFalse(gui.safe_test_failure(record)['tuiResume']['cursorKeysMode'])
        # Legacy three-field failures stay byte-for-byte compatible.
        old={'stage':'tui_resume_full','errorClass':'TestFailure','line':68}
        self.assertEqual(gui.safe_test_failure(old),old)
        worst={'stage':'tui_find_resume','errorClass':'TimeoutException','line':10000,
            'tuiResume':tui_resume_report(boardCount=2,tabCount=2,resumeCount=2,directCount=2,
                directEnabled=False,cursorKeysMode=False,sequence=9_007_199_254_740_991)}
        self.assertEqual(gui.safe_test_failure(worst),worst)
        self.assertLessEqual(len(json.dumps(worst,separators=(',',':')).encode()),512)

    def test_reject_unknown_identity_path_text_and_wrong_typed_or_unbounded_values(self):
        for field,value in (('terminalText','PRIVATE'),('path','PRIVATE'),('terminalId','PRIVATE'),
                            ('rowMatchMask',True),('rowMatchMask',1<<24),('schemaVersion',True),
                            ('cols',513),('sequence',9_007_199_254_740_992),('directEnabled',1),
                            ('boardCount',3),('firstMismatchRow',24),('rowsChecked',1),('actionsCompleted',4)):
            record={'stage':'tui_resume_full','errorClass':'TestFailure','line':68,
                    'tuiResume':tui_resume_report(**{field:value})}
            with self.subTest(field=field,value=value),self.assertRaises(gui.DeviceFailure):gui.safe_test_failure(record)
        for diagnostic in (None,[],{},dict(tui_resume_report(),titleRowMask='PRIVATE')):
            with self.subTest(diagnostic=diagnostic),self.assertRaises(gui.DeviceFailure):
                gui.safe_test_failure({'stage':'tui_resume_full','errorClass':'TestFailure','line':68,'tuiResume':diagnostic})
        with self.assertRaises(gui.DeviceFailure):
            gui.safe_test_failure({'stage':'guarded_direct','errorClass':'TestFailure','line':68,'tuiResume':tui_resume_report()})

    def test_reject_inconsistent_masks_geometry_missing_views_and_sequence_presence(self):
        for changes in ({'rowMatchMask':0xffffef}, {'tailRowsBlank':False}, {'cols':120},
                        {'viewCount':0}, {'directCount':0}, {'sequencePresent':False},
                        {'sequence':-1}, {'rowsChecked':0}, {'firstMismatchRow':7}):
            with self.subTest(changes=changes),self.assertRaises(gui.DeviceFailure):gui.safe_tui_resume(tui_resume_report(**changes))
        missing=tui_resume_report(viewCount=0,terminalReplaced=False,sequencePresent=False,sequence=-1,
            cols=0,rows=0,bufferRows=0,cursorKeysMode=False,directEnabled=False,
            rowsChecked=0,rowMatchMask=0,firstMismatchRow=-1,tailRowsBlank=False,titleRowMask=0)
        self.assertEqual(gui.safe_tui_resume(missing),missing)
        wrong_geometry={**missing,'viewCount':1,'cols':120,'rows':40,'bufferRows':40,'cursorKeysMode':True}
        self.assertEqual(gui.safe_tui_resume(wrong_geometry),wrong_geometry)

    def test_same_failure_public_reader_limit_is_bounded_and_extra_fields_are_not_exported(self):
        record={'stage':'tui_resume_full','errorClass':'TestFailure','line':68,'tuiResume':tui_resume_report()}
        raw=json.dumps(record,separators=(',',':')).encode()
        relative='cache/herdr-flutter-android-123/failure.json'
        with patch.object(gui,'adb',return_value=subprocess.CompletedProcess([],0,raw,b'')) as adb:
            self.assertEqual(gui.read_public(relative,gui.PUBLIC_LIMITS['failure.json']),raw)
            self.assertIn(str(gui.PUBLIC_LIMITS['failure.json']+1),adb.call_args.args)
        with patch.object(gui,'adb',return_value=subprocess.CompletedProcess([],0,b'x'*(gui.PUBLIC_LIMITS['failure.json']+1),b'')):
            with self.assertRaisesRegex(gui.DeviceFailure,'oversize'):gui.read_public(relative,gui.PUBLIC_LIMITS['failure.json'])
        with self.assertRaises(gui.DeviceFailure):
            gui.checked_public_payload(json.dumps({**record,'message':'PRIVATE'}).encode(),'failure.json')

    def test_resume_instrumentation_retains_acceptance_and_one_click_without_replay_or_extra_time(self):
        source=(REPO/'validation/flutter/integration_test/android_pairing_observe_test.dart').read_text()
        flow=source[source.index("  stage('tui_find_board');"):source.index("  stage('tui_initial');")]
        self.assertEqual(flow.count('await tap('),3)
        self.assertEqual(flow.count('onPoll:sample'),3)
        self.assertNotIn('seconds:',flow)
        for predicate in ('!identical(tester.widget<TerminalView>',"currentTuiScreen(tester,'initial')",'onSelected != null'):
            self.assertIn(predicate,flow)
        self.assertLess(flow.index("stage('tui_find_board')"),flow.index("stage('tui_return_tab')"))
        self.assertLess(flow.index("stage('tui_find_resume')"),flow.index("stage('tui_resume_full')"))
        snapshot=source[source.index('Map<String,Object> tuiResumeSnapshot'):source.index('Future<void> visibleTuiScreen')]
        self.assertNotIn('publish(',snapshot);self.assertNotIn('write(',snapshot)
        self.assertIn("actual == 'Pocket TUI'",snapshot)
        fields=set(re.findall(r"'([A-Za-z]+)':",snapshot))
        expected=tui_resume_report(schemaVersion=2,pageCount=1,pageBusy=True,pagePaused=False,
            pageLive=False,evidenceFull=False,boardFreshness='refreshing',adapterPhase='snapshot',adapterError='none')
        self.assertEqual(fields,set(gui.safe_tui_resume(expected)))
        self.assertIn("'tuiResume':tuiResume",source)
        self.assertIn("'failure.json',jsonEncode(boundedFailure",source)


class TuiGuards(unittest.TestCase):
    """Protocol/once-only tests; all host/adb collaborators here are fakes."""
    relative = 'cache/herdr-flutter-android-123'
    terminal = 'term_abcd'

    def report(self):
        from guarded_input import TUI_SCREEN_CHECKS, TUI_KEY_LENGTHS
        receipts = [{'requestId': format(i, '032x'), 'paneId':'w1:p1',
                     'terminalId':self.terminal, 'acceptedBytes':size} for i,size in enumerate((1,9),1)]
        return device_report(case=gui.GUARDED_CASE, **{name:True for name in gui.GUARDED_FIELDS},
            **gui.CLIPBOARD_COUNTS, restoredViewportLogicalPixels=[24,24], inputReceipts=receipts,
            acceptedByteCounts=[1,9], tui={'observedInitialFull':True,'screenChecks':list(TUI_SCREEN_CHECKS),
                'receipts':[{'requestId':format(i,'032x'),'paneId':'w1:p1','terminalId':self.terminal,
                             'acceptedBytes':size} for i,size in enumerate(TUI_KEY_LENGTHS,3)]})

    def state(self):
        approval=Mock();approval.start_tui.return_value={'ready':True,'sameTarget':True,'initialInputMatched':True}
        state=gui.ClipboardCheckpoints(self.relative,approval,keyboard=True,tui=True,config={'synthetic':True})
        state.completed=list(state.expected[:-1])
        return state,approval

    def test_opt_in_tui_retains_old_receipts_and_strict_shared_whitelist(self):
        raw=self.report();clean=gui.safe_device_result(raw,guarded=True,tui=True)
        self.assertEqual(len(clean['inputReceipts']),2);self.assertEqual(len(clean['tui']['receipts']),10)
        raw['private']='PRIVATE';raw['observerCanvas']['private']='PRIVATE'
        self.assertNotIn('PRIVATE',json.dumps(gui.safe_device_result(raw,guarded=True,tui=True)))
        with self.assertRaisesRegex(gui.DeviceFailure,'tui_unexpected'):gui.safe_device_result(raw,guarded=True)
        with self.assertRaisesRegex(gui.DeviceFailure,'requires_guarded'):gui.safe_device_result(raw,tui=True)
        for change in ('missing','full','stale','replay','target','size','extra'):
            raw=self.report()
            if change=='missing':raw.pop('tui')
            if change=='full':raw['tui']['observedInitialFull']=False
            if change=='stale':raw['tui']['screenChecks'][7]='close-help'
            if change=='replay':raw['tui']['receipts'][0]['requestId']=raw['inputReceipts'][0]['requestId']
            if change=='target':raw['tui']['receipts'][0]['terminalId']='term_1234'
            if change=='size':raw['tui']['receipts'][0]['acceptedBytes']=1
            if change=='extra':raw['tui']['private']='PRIVATE'
            with self.subTest(change=change),self.assertRaises(gui.DeviceFailure):gui.safe_device_result(raw,guarded=True,tui=True)

    def test_start_checkpoint_is_bounded_and_contains_no_command(self):
        good={'checkpoint':gui.TUI_CHECKPOINT,'terminalId':self.terminal}
        raw=json.dumps(good).encode();self.assertLess(len(raw),gui.PUBLIC_LIMITS['checkpoint.json'])
        self.assertEqual(gui.checked_public_payload(raw,'checkpoint.json'),raw)
        for change in ({'terminalId':'PRIVATE'},{'terminalId':None},{'command':'PRIVATE'}):
            with self.subTest(change=change),self.assertRaises(gui.DeviceFailure):
                gui.checked_public_payload(json.dumps({**good,**change}).encode(),'checkpoint.json')
        with self.assertRaises(gui.DeviceFailure):gui.ClipboardCheckpoints(self.relative,Mock(),tui=True,guarded=False,config={})
        state=gui.ClipboardCheckpoints(self.relative,Mock(),keyboard=True)
        with patch.object(gui,'read_public',return_value=raw),patch.object(gui,'adb') as adb:
            with self.assertRaisesRegex(gui.DeviceFailure,'checkpoint_order_invalid'):state.poll()
            state.approval.start_tui.assert_not_called();adb.assert_not_called()

    def test_start_once_verifies_independent_target_and_duplicate_poll_never_relaunches(self):
        state,approval=self.state();lookup=Mock(return_value=self.terminal)
        raw=json.dumps({'checkpoint':gui.TUI_CHECKPOINT,'terminalId':self.terminal}).encode()
        with patch.dict('sys.modules',{'paired_gui':SimpleNamespace(fixture_terminal_id=lookup)}), \
                patch.object(gui,'read_public',return_value=raw),patch.object(gui,'adb') as adb:
            state.poll();state.poll();state.require_complete()
            lookup.assert_called_once_with({'synthetic':True})
            approval.start_tui.assert_called_once_with(terminal_id=self.terminal)
            approval.verify_ssh.assert_not_called();self.assertEqual(adb.call_count,2)
            self.assertEqual(json.loads(adb.call_args_list[0].kwargs['data']),{'checkpoint':gui.TUI_CHECKPOINT})

    def test_failed_start_target_or_ack_is_never_replayed(self):
        for failure in ('target','launch','unconfirmed','ack'):
            state,approval=self.state();lookup=Mock(return_value='term_1234' if failure=='target' else self.terminal)
            if failure=='launch':approval.start_tui.side_effect=gui.DeviceFailure('synthetic_start_failure')
            if failure=='unconfirmed':approval.start_tui.return_value={'ready':False}
            raw=json.dumps({'checkpoint':gui.TUI_CHECKPOINT,'terminalId':self.terminal}).encode()
            with self.subTest(failure=failure),patch.dict('sys.modules',{'paired_gui':SimpleNamespace(fixture_terminal_id=lookup)}), \
                    patch.object(gui,'read_public',return_value=raw), \
                    patch.object(gui,'adb',side_effect=gui.DeviceFailure('flutter_android_adb_failed') if failure=='ack' else None) as adb:
                before=state.completed.copy()
                with self.assertRaises(gui.DeviceFailure):state.poll()
                with self.assertRaisesRegex(gui.DeviceFailure,'already_attempted'):state.poll()
                self.assertEqual(state.completed,before)
                self.assertEqual(approval.start_tui.call_count,0 if failure=='target' else 1)
                if failure!='ack':adb.assert_not_called()

    def test_integration_source_uses_current_screen_fresh_full_real_taps_and_retains_legacy_phase(self):
        source=(REPO/'validation/flutter/integration_test/android_pairing_observe_test.dart').read_text()
        self.assertNotIn("contains('固定 80×24')",source)
        self.assertIn("contains('观察画布 ')",source)
        self.assertIn("'HERDR_ANDROID_GUARDED_TUI'",source)
        self.assertIn('terminal.buffer.height != terminal.viewHeight',source)
        self.assertIn('actual != (y < rows.length ? rows[y]',source)
        self.assertIn('visibleRemoteScreenCells(terminal,render,',source)
        self.assertIn('!identical(tester.widget<TerminalView>',source)
        self.assertIn('(displayedSequence(tester) ?? -1) > sequence',source)
        self.assertIn('await tap(tester,button); await accepted',source)
        self.assertLess(source.index("inputReceipts.add(visibleReceipt(tester,target['paneId'] as String,9))"),source.index('tuiEvidence = await exerciseTui'))
        self.assertIn("'acceptedByteCounts':[1,9]",source)
        for key in ('remote-key-↓','remote-key-Tab',*('remote-function-key-'+name for name in ('backspace','shift-tab','insert','delete','f1','f5','f10'))):
            self.assertIn(key,source)


class SystemKeyboardGuards(unittest.TestCase):
    def test_ime_diagnostic_export_is_bounded_and_checkpoints_are_not_acknowledged(self):
        for label in (gui.KEYBOARD_OBSERVE_CHECKPOINT,'keyboard-direct-shown','keyboard-draft-back-request'):
            with self.subTest(label=label),tempfile.TemporaryDirectory() as temporary:
                output=Path(temporary)/'flutter-android-system-ime-failure.json'
                state=gui.ClipboardCheckpoints('cache/herdr-flutter-android-123',Mock(),keyboard=True,
                    guarded=label!=gui.KEYBOARD_OBSERVE_CHECKPOINT,ime_failure_output=output)
                state.completed=list(state.expected[:state.expected.index(label)])
                before=state.completed.copy()
                failure=gui.SystemImeFailure('android_system_ime_hide_unconfirmed' if label.endswith('request') else 'android_system_ime_target_mismatch',
                    {'reason':'focus_null','focusOwner':'none','attempts':100,'expectedVisible':False,'timedOut':True,
                     'rawDump':'PRIVATE','editorPackageCount':1000,'visibility':'PRIVATE'})
                samples=[{'visible':True,'ownedTarget':True},failure] if label.endswith('request') else [failure]
                with patch.object(gui,'read_public',return_value=json.dumps(checkpoint_payload(label)).encode()), \
                        patch.object(gui,'wait_system_ime',side_effect=samples),patch.object(gui,'adb') as adb:
                    with self.assertRaises(gui.SystemImeFailure) as caught:state.poll()
                self.assertIs(caught.exception,failure)
                self.assertEqual(state.completed,before);state.approval.verify_ssh.assert_not_called()
                raw=output.read_text();report=json.loads(raw)
                self.assertLess(len(raw),4096);self.assertNotIn('PRIVATE',raw)
                self.assertEqual(report['checkpoint'],label)
                self.assertEqual(report['completedCheckpoints'],before)
                self.assertEqual(report['systemRead'],'after_system_back' if label.endswith('request') else 'requested_state')
                self.assertEqual(report['systemBackSent'],label.endswith('request'))
                self.assertEqual(output.stat().st_mode & 0o777,0o600)
                self.assertEqual(len(adb.call_args_list),1 if label.endswith('request') else 0)
                if label.endswith('request'):adb.assert_called_once_with('shell','input','keyevent','KEYCODE_BACK')
                # Existing evidence is never overwritten; a write failure must
                # preserve the original IME exception and never ACK the request.
                with patch.object(gui,'wait_system_ime',side_effect=failure):
                    with self.assertRaises(gui.SystemImeFailure) as caught:state.system_ime(label,True)
                self.assertIs(caught.exception,failure);self.assertEqual(output.read_text(),raw)

    def test_public_ime_diagnostic_drops_unknown_values_and_wrong_types(self):
        for reason in ('PRIVATE',[],{},None):
            error=gui.SystemImeFailure('android_system_ime_target_mismatch',
                {'reason':reason,'attempts':True,'focusCount':-1,'raw':'PRIVATE'})
            self.assertEqual(error.public_diagnostic(),{})

    @staticmethod
    def dumps(*, window=True, decor=True, input_view=True, package=gui.PACKAGE, editor=None):
        editor = package if editor is None else editor
        method = ('Current Input Method Manager state:\n  mInputShown=true\n'
            '  mStartInputHistory: PRIVATE_HISTORY\n'
            'Input method service state for synthetic-ime:\n'
            f'  mWindowVisible={str(window).lower()} mDecorViewVisible={str(decor).lower()}\n'
            f'  mIsInputViewShown={str(input_view).lower()}\n'
            f'  mInputEditorInfo:\n    packageName={editor}\n')
        windows = (f'WINDOW MANAGER DISPLAY CONTENTS\n  Display: mDisplayId=0\n  mCurrentFocus=Window{{abc u0 {package}/.MainActivity}}\n'
            f'  InsetsSource id=3 type=ime frame=[0,900][500,1000] visible={str(window and decor and input_view).lower()} flags= sideHint=BOTTOM\n')
        return method, windows

    def test_actual_window_flags_are_required_focus_or_show_request_never_proves_visible(self):
        shown = gui.parse_system_ime(*self.dumps(), gui.PACKAGE)
        self.assertTrue(shown['visible']); self.assertFalse(shown['hidden'])
        hidden = gui.parse_system_ime(*self.dumps(window=False, decor=False), gui.PACKAGE)
        self.assertFalse(hidden['visible']); self.assertTrue(hidden['hidden'])
        # InputViewShown may be retained after hiding; actual window flags win.
        self.assertTrue(hidden['inputViewShown'])
        transient = gui.parse_system_ime(*self.dumps(window=True, decor=False), gui.PACKAGE)
        self.assertFalse(transient['visible']); self.assertFalse(transient['hidden'])
        self.assertNotIn('PRIVATE', json.dumps(shown))

    def test_missing_duplicate_historical_or_foreign_state_is_not_accepted(self):
        method, windows = self.dumps()
        invalid = [(method.replace('mWindowVisible=true', 'requestShow=true'), windows),
            (method + ' mWindowVisible=false', windows), (method + method, windows),
            (method, windows + windows), (method, windows.replace(gui.PACKAGE, 'other.application')),
            (method, windows.replace('type=ime', 'type=navigationBars')),
            (method.replace('packageName=' + gui.PACKAGE, 'packageName=other.application'), windows),
            ('mInputShown=true mShowRequested=true', windows)]
        for raw, focus in invalid:
            with self.subTest(raw=raw[:35]), self.assertRaises(gui.DeviceFailure):
                gui.parse_system_ime(raw, focus, gui.PACKAGE)

    def test_wait_requires_two_actual_stable_samples_and_propagates_read_failure(self):
        read = Mock(side_effect=[self.dumps(window=False, decor=False), self.dumps(), self.dumps()])
        with patch.object(gui.time, 'sleep'):
            result = gui.wait_system_ime(read, gui.PACKAGE, True)
        self.assertEqual(result['stableSamples'], 2); self.assertEqual(read.call_count, 3)
        with patch.object(gui.time, 'monotonic', side_effect=[0, 0, 1, 13]), patch.object(gui.time, 'sleep'):
            with self.assertRaisesRegex(gui.DeviceFailure, '^android_system_ime_show_unconfirmed$'):
                gui.wait_system_ime(lambda: self.dumps(window=False, decor=False), gui.PACKAGE, True)
        with self.assertRaisesRegex(gui.DeviceFailure, '^bounded_adb_failure$'):
            gui.wait_system_ime(Mock(side_effect=gui.DeviceFailure('bounded_adb_failure')), gui.PACKAGE, True)

    def test_keyboard_checkpoint_shape_insets_system_and_receiver_are_all_required(self):
        relative = 'cache/herdr-flutter-android-123'
        for label in (*gui.KEYBOARD_CHECKPOINTS, gui.KEYBOARD_OBSERVE_CHECKPOINT):
            value = checkpoint_payload(label)
            raw = json.dumps(value).encode()
            self.assertLessEqual(len(raw), gui.PUBLIC_LIMITS['checkpoint.json'])
            self.assertEqual(gui.checked_public_payload(raw, 'checkpoint.json'), raw)
            for change in ({'viewInsetBottom': True}, {'viewInsetBottom': -1}, {'privateText': 'PRIVATE'}):
                with self.assertRaises(gui.DeviceFailure):
                    gui.checked_public_payload(json.dumps(dict(value, **change)).encode(), 'checkpoint.json')
        state = gui.ClipboardCheckpoints(relative, Mock(), keyboard=True, guarded=True)
        payloads = [checkpoint_payload(label) for label in state.expected]
        with patch.object(gui, 'read_public', side_effect=[json.dumps(x).encode() for x in payloads]), \
                patch.object(gui, 'wait_system_ime', side_effect=lambda _read, _package, visible: {'visible': visible, 'ownedTarget': True}) as system, \
                patch.object(gui, 'adb'):
            for _ in payloads: state.poll()
            state.require_complete()
        self.assertEqual(system.call_count, len(gui.KEYBOARD_CHECKPOINTS) + 1)
        self.assertEqual([c.args for c in state.approval.verify_ssh.call_args_list], [(b'',)] * 3 + [(b'k',)] * (len(state.expected) - 3))
        self.assertEqual(len(state.keyboard_evidence), len(gui.KEYBOARD_CHECKPOINTS))
        state = gui.ClipboardCheckpoints(relative, Mock(), keyboard=True, guarded=False)
        payload = dict(checkpoint_payload(gui.KEYBOARD_OBSERVE_CHECKPOINT), viewInsetBottom=1)
        with patch.object(gui, 'read_public', return_value=json.dumps(payload).encode()), \
                patch.object(gui, 'wait_system_ime') as system, patch.object(gui, 'adb') as adb:
            with self.assertRaisesRegex(gui.DeviceFailure, 'keyboard_insets_mismatch'): state.poll()
            system.assert_not_called(); adb.assert_not_called(); state.approval.verify_ssh.assert_not_called()

    def test_system_back_is_once_only_after_owned_visible_window_and_not_replayed_after_failure(self):
        relative = 'cache/herdr-flutter-android-123'
        label = 'keyboard-draft-back-request'
        payload = json.dumps(checkpoint_payload(label)).encode()
        before = list(gui.KEYBOARD_CHECKPOINTS[:gui.KEYBOARD_CHECKPOINTS.index(label)])
        for failure in (None, 'not-owned', 'hide-unconfirmed'):
            state = gui.ClipboardCheckpoints(relative, Mock(), keyboard=True)
            state.completed = before.copy()
            samples = [{'visible': True, 'ownedTarget': failure != 'not-owned'},
                gui.DeviceFailure('android_system_ime_hide_unconfirmed') if failure == 'hide-unconfirmed' else {'visible': False, 'ownedTarget': True}]
            with patch.object(gui, 'read_public', return_value=payload), \
                    patch.object(gui, 'wait_system_ime', side_effect=samples), patch.object(gui, 'adb') as adb:
                if failure:
                    with self.assertRaises(gui.DeviceFailure): state.poll()
                    self.assertEqual(state.completed, before)
                else:
                    state.poll(); state.poll()  # Atomic request can remain; never send Back twice.
                    self.assertTrue(state.keyboard_evidence[-1]['systemBackSent'])
                    state.approval.verify_ssh.assert_called_once_with(b'k')
                back = [c for c in adb.call_args_list if c.args == ('shell', 'input', 'keyevent', 'KEYCODE_BACK')]
                self.assertEqual(len(back), 0 if failure == 'not-owned' else 1)
                if failure:
                    self.assertEqual(len(adb.call_args_list), len(back))  # No ACK on unconfirmed hide.


if __name__ == '__main__':
    unittest.main()
