"""Native-driver contract and isolated real SSH; these are not iOS device proof."""
import base64
import copy
import hashlib
import io
import json
import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tauri_ios_direct_ssh as ios
from terminal_screenshot_gate import ScreenshotGateError
from screen_proof_token import token_lines


class ManualEncryptedKeyTests(unittest.TestCase):
    class Peer:
        marker = 'hp-check'

        def __init__(self):
            self.events = []
            self.screen_token = ''
            self.username = 'fixture'

        def snapshot(self):
            return {'connections': len(self.events), 'connectionsClosed': all(e['closed'] for e in self.events),
                    'connectionEvents': copy.deepcopy(self.events), 'shellRequested': len(self.events) == 3,
                    'markerReceived': any(e['markerReceived'] for e in self.events)}

        def wait_for_connections_closed(self, count, timeout):
            return len(self.events) == count and all(e['closed'] for e in self.events)

        def empty_event(self, index):
            return dict(id=index, hostKey='A', closed=True, handshakeCompleted=index > 1,
                        authAccepted=False, authAttempts=0, authSuccesses=0, ptyRequests=0, shellRequests=0,
                        inputBytes=0, outputBytes=0, sessionClosed=False, markerReceived=False, singleMarkerLineExact=False)

    def setUp(self):
        output = tempfile.TemporaryDirectory()
        self.addCleanup(output.cleanup)
        self.peer = self.Peer()
        self.result = {'cases': {'encryptedKey': {'status': 'not_run', 'credentialEntry': 'nativeTypeText'}}}
        self.state = ios.Checkpoints(None, None, output.name, self.result, encrypted=self.peer)

    def post(self, step, **extra):
        self.state.accept({'stage': 'encrypted_key_' + step, **extra})

    def through_wrong_submission(self):
        self.post('form')
        self.peer.events.append(self.peer.empty_event(1))
        for step in ('probe', 'reviewed', 'wrong_pem_entry', 'wrong_pem_verified', 'wrong_ready', 'wrong_submit'):
            self.post(step)

    def test_manual_flow_checks_distinct_wrong_and_correct_stages_and_live_close(self):
        self.through_wrong_submission()
        wrong = self.peer.empty_event(2)
        self.peer.events.append(wrong)
        wrong['authAttempts'] = 1
        with self.assertRaisesRegex(ios.Failure, 'pre_auth_not_empty'):
            self.post('wrong_rejected')
        wrong['authAttempts'] = 0
        for step in ('wrong_rejected', 'correct_pem_entry', 'correct_pem_verified', 'correct_ready', 'correct_submit'):
            self.post(step)
        session = self.peer.empty_event(3) | dict(closed=False, authAccepted=True, authAttempts=2, authSuccesses=1,
                                                   ptyRequests=1, shellRequests=1, outputBytes=25)
        self.peer.events.append(session)
        self.post('connected')
        session.update(markerReceived=True, singleMarkerLineExact=True, inputBytes=9, outputBytes=90)
        self.post('input')
        with patch.object(self.state, 'capture') as capture:
            self.post('terminal')
        capture.assert_called_once()
        self.post('disconnect_attempt')
        session.update(closed=True, sessionClosed=True)
        self.post('disconnected')
        self.post('returned_home')
        case = self.result['cases']['encryptedKey']
        self.assertEqual((case['status'], case['authenticationMethod']), ('passed', 'publickey'))
        self.assertEqual([case['initialProbe']['authAttempts'], case['wrongPassphrase']['peer']['authAttempts'],
                          case['acceptedSession']['authSuccesses']], [0, 0, 1])
        self.assertTrue(case['peerClosedBeforeDriverExit'])
        self.assertEqual(self.state.index, len(self.state.stages))

    def test_native_event_disallows_replay_cross_case_and_secret_payload(self):
        self.post('form')
        self.peer.events.append(self.peer.empty_event(1))
        self.post('probe')
        self.post('reviewed')
        with self.assertRaisesRegex(ios.Failure, 'checkpoint_payload_invalid'):
            self.post('wrong_pem_entry', private='fixture-secret')
        self.post('wrong_pem_entry')
        for stage in ('encrypted_key_wrong_pem_entry', 'encrypted_key_correct_pem_entry', 'ordinary_form'):
            with self.assertRaisesRegex(ios.Failure, 'checkpoint_order_invalid'):
                self.state.accept({'stage': stage})
        self.assertNotIn('fixture-secret', json.dumps(self.result))
        self.assertEqual(self.result['lastCompletedStage'], 'encrypted_key_wrong_pem_entry')

    def test_driver_types_only_once_per_verified_empty_pem_editor_and_uses_no_clipboard(self):
        source = (ios.HERE / 'tauri_ios_direct_ssh.swift').read_text()
        owner = source.split('private func typeEncryptedCredential', 1)[1].split('private func encryptedDraft', 1)[0]
        self.assertEqual(owner.count('.typeText(text)'), 1)
        self.assertIn('credentialEmpty(focused.live.snapshot)', owner)
        self.assertIn('scrolling: false', owner)
        draft = source.split('private func encryptedDraft', 1)[1].split('private func authMethodFact', 1)[0]
        self.assertLess(draft.index('"_pem_entry"'), draft.index('typeEncryptedCredential(before.pem'))
        self.assertLess(draft.index('entered.pem.live.snapshot.value as? String == pem'), draft.index('"_pem_verified"'))
        for forbidden in ('pbcopy', 'pbpaste', 'UIPasteboard', 'press(forDuration', 'evaluateJavaScript'):
            self.assertNotIn(forbidden, owner + draft)


class NativeGeometryTests(unittest.TestCase):
    def payload(self):
        return {'screenSize': [440, 956], 'safeFrame': [0, 60, 440, 850],
                'terminalFrame': [20.2, 210.2, 399.5, 300.5], 'targetFrame': [20, 160, 400, 30]}

    def test_native_points_map_inward_to_original_retina_png(self):
        value = ios.measured_bounds(self.payload(), (1320, 2868))
        self.assertEqual(value['terminalBounds'], [61, 631, 1198, 901])
        self.assertEqual(value['targetBounds'], [60, 480, 1200, 90])
        self.assertEqual(value['nativeScale'], 3)

    def test_unknown_zoom_nonfinite_and_outside_visible_frames_reject(self):
        for key, value in [('screenSize', [440, 900]), ('terminalFrame', [0, 0, 440, 300]),
                           ('targetFrame', [20, 160, 500, 30]), ('safeFrame', [0, -1, 440, 900]),
                           ('terminalFrame', [float('nan'), 210, 400, 300]),
                           ('targetFrame', [20, 200, 400, 30])]:
            with self.subTest(key=key, value=value):
                payload = self.payload()
                payload[key] = value
                with self.assertRaises(ios.Failure):
                    ios.measured_bounds(payload, (1320, 2868))

    def test_s10_requires_exactly_seven_fully_visible_native_regions(self):
        payload = {'screenSize': [440, 956], 'safeFrame': [0, 60, 440, 850],
                   'reviewFrames': [[20, 80 + i * 100, 400, 50] for i in range(7)]}
        self.assertEqual(len(ios.measured_bounds(payload, (1320, 2868))['reviewBounds']), 7)
        for frames in [payload['reviewFrames'][:-1], [[0, 0, 440, 100]] * 7,
                       [[20, float('inf'), 400, 20]] * 7]:
            with self.assertRaises(ios.Failure):
                ios.measured_bounds({**payload, 'reviewFrames': frames}, (1320, 2868))


class InputAndPrivacyTests(unittest.TestCase):
    def test_case_sensitive_ssh_identifiers_disable_native_autocorrection(self):
        from html.parser import HTMLParser
        class Inputs(HTMLParser):
            def __init__(self):
                super().__init__(); self.inputs = {}
            def handle_starttag(self, tag, attrs):
                if tag == 'input':
                    value = dict(attrs)
                    self.inputs[value.get('id')] = value
        parser = Inputs()
        parser.feed((ios.HERE.parent / 'tauri/index.html').read_text())
        for name in ('ssh-host', 'ssh-user'):
            self.assertEqual({k: parser.inputs[name].get(k) for k in ('autocapitalize', 'autocorrect', 'spellcheck')},
                             {'autocapitalize': 'none', 'autocorrect': 'off', 'spellcheck': 'false'})
    def build_inputs(self, root):
        project = root / 'generated/Product.xcodeproj'
        project.mkdir(parents=True)
        (project / 'project.pbxproj').write_text('generated source')
        app = root / 'Simulator.app'
        app.mkdir()
        (app / 'Product').write_bytes(b'compiled real product')
        (app / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': ios.BUNDLE_ID, 'CFBundleExecutable': 'Product',
            'CFBundleSupportedPlatforms': ['iPhoneSimulator']}))
        return project.parent, app

    def test_requires_actual_simulator_bundle_and_binds_source_project_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, app = self.build_inputs(root)
            evidence = ios.validate_inputs(project, app, 'a' * 40)
            self.assertEqual(evidence['executableSha256'], hashlib.sha256(b'compiled real product').hexdigest())
            for bad in ('', 'a' * 39, 'not-current'):
                with self.assertRaises(ios.Failure):
                    ios.validate_inputs(project, app, bad)
            info = plistlib.loads((app / 'Info.plist').read_bytes())
            for key, value in [('CFBundleSupportedPlatforms', ['iPhoneOS']),
                               ('CFBundleIdentifier', 'unrelated.app')]:
                bad = {**info, key: value}
                (app / 'Info.plist').write_bytes(plistlib.dumps(bad))
                with self.assertRaises(ios.Failure):
                    ios.validate_inputs(project, app, 'a' * 40)

    def test_non_ci_stops_before_any_device_command_and_exports_only_fixed_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, app = self.build_inputs(root)
            with patch.object(ios, 'command') as command:
                result = ios.run(project, app, root / 'public', source_sha='a' * 40, env={})
            command.assert_not_called()
            self.assertEqual(result['error'], 'tauri_ios_requires_macos_ci')
            self.assertEqual(result['artifacts'], {})
            self.assertEqual(list((root / 'public').iterdir()), [root / 'public/result.json'])

    def test_invalid_source_environment_never_enters_public_failure_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(ios, 'command') as command:
                result = ios.run(root, root, root / 'public', env={'GITHUB_SHA': 'PRIVATE-SYNTHETIC-VALUE'})
            command.assert_not_called()
            self.assertEqual(result['error'], 'tauri_ios_source_sha_invalid')
            self.assertIsNone(result['sourceSHA'])
            self.assertNotIn('PRIVATE-SYNTHETIC-VALUE', json.dumps(result))

    def test_only_private_runtime_resource_contains_config_and_no_auto_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {'syntheticPassword': 'PRIVATE-CREDENTIAL'}
            ios.prepare_driver(directory, config)
            source = (Path(directory) / 'UITests/Driver.swift').read_text()
            self.assertNotIn('PRIVATE-CREDENTIAL', source)
            self.assertNotIn('__HP_CONFIG_BASE64__', source)
            self.assertNotIn('NSStringFromCGRect', source)
            self.assertEqual(source, (ios.HERE / 'tauri_ios_direct_ssh.swift').read_text())
            resource = Path(directory) / 'UITests/Fixture.json'
            self.assertEqual(json.loads(resource.read_text()), config)
            self.assertEqual(resource.stat().st_mode & 0o777, 0o600)
            self.assertEqual(resource.parent.stat().st_mode & 0o777, 0o700)
            self.assertIn('XCUIApplication(bundleIdentifier:', source)
            self.assertEqual(source.count('app.typeText("hp-check\\n")'), 1)
            self.assertNotIn('evaluateJavaScript', source)
            self.assertNotIn('invoke(', source)
            self.assertNotIn('screen_token', source)
            spec = json.loads((Path(directory) / 'project.json').read_text())
            self.assertFalse(spec['schemes']['PocketUI']['test']['targets'][0]['parallelizable'])
            self.assertIn({'path': 'UITests/Fixture.json', 'buildPhase': 'resources'}, spec['targets']['PocketUITests']['sources'])
            self.assertNotIn('PRIVATE-CREDENTIAL', json.dumps(spec))
            self.assertNotIn(base64.b64encode(json.dumps(config).encode()).decode(), source)

    def test_runtime_selection_checks_encoded_minor_version_and_chooses_large_phone(self):
        runtime = {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-18-6',
                   'version': '18.6', 'isAvailable': True}
        types = [{'name': 'iPhone 16 Pro Max', 'identifier': 'phone16',
                  'minRuntimeVersion': (18 << 16) + (1 << 8)},
                 {'name': 'iPhone 17 Pro Max', 'identifier': 'phone17', 'minRuntimeVersion': 26 << 16}]
        self.assertEqual(ios.select_simulator([runtime], types), (runtime['identifier'], 'phone16'))

    def test_public_model_and_runtime_are_distinct_from_xcode_sdk(self):
        runtime = 'com.apple.CoreSimulator.SimRuntime.iOS-26-2'
        device = 'com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max'
        self.assertEqual(ios.simulator_evidence(runtime, device), {'runtime': runtime, 'deviceType': device})
        with patch.object(ios, 'command', side_effect=[b'Xcode 16.4\nBuild version 16F6\n', b'18.5\n']):
            self.assertEqual(ios.toolchain_evidence(), {'xcodeVersion': '16.4', 'xcodeBuild': '16F6', 'simulatorSDKVersion': '18.5'})
        for value in ('/private/runtime/secret', 'UUID-123', runtime + '\nPRIVATE'):
            with self.assertRaises(ios.Failure):
                ios.simulator_evidence(value, device)


class BuildDiagnosticsTests(unittest.TestCase):
    def test_runner_publishes_clean_build_location_and_environment_then_cleans_private_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, app = InputAndPrivacyTests().build_inputs(root)
            runtime = 'com.apple.CoreSimulator.SimRuntime.iOS-26-2'
            device_type = 'com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max'
            device_uuid = 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
            fixture_secrets, private_paths = [], []
            def command(arguments, *, log=None, **kwargs):
                if arguments == ['xcodebuild', '-version']:
                    return b'Xcode 16.4\nBuild version 16F6\n'
                if arguments == ['xcodebuild', '-version', '-sdk', 'iphonesimulator', 'SDKVersion']:
                    return b'18.5\n'
                if arguments[:4] == ['xcrun', 'simctl', 'list', 'runtimes']:
                    return json.dumps({'runtimes': [{'isAvailable': True, 'identifier': runtime, 'version': '26.2'}]}).encode()
                if arguments[:4] == ['xcrun', 'simctl', 'list', 'devicetypes']:
                    return json.dumps({'devicetypes': [{'name': 'iPhone 17 Pro Max', 'identifier': device_type}]}).encode()
                if arguments[:3] == ['xcrun', 'simctl', 'create']:
                    return device_uuid.encode()
                if arguments[-1] == 'build-for-testing':
                    private = Path(arguments[2]).parent
                    private_paths.append(private)
                    config = json.loads((private / 'UITests/Fixture.json').read_text())
                    fixture_secrets.extend([config['ordinaryPassword'], config['rotationPassword'], config['checkpointSecret']])
                    source = (private / 'UITests/Driver.swift').read_text()
                    self.assertEqual(source, (ios.HERE / 'tauri_ios_direct_ssh.swift').read_text())
                    log.write(f"{private}/UITests/Driver.swift:211:40: error: cannot find '{config['ordinaryPassword']}' in scope\n".encode())
                    raise ios.Failure('tauri_ios_command_failed')
                return b''
            with patch.object(ios, 'command', side_effect=command), patch.object(ios.shutil, 'which', return_value='/tools/present'):
                result = ios.run(project, app, root / 'public', source_sha='a' * 40,
                                 env={'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'macOS'})
            self.assertEqual(result['stage'], 'xctest_build')
            self.assertEqual(result['error'], 'tauri_ios_xctest_build_failed')
            self.assertEqual(result['buildDiagnostics'], [
                {'classification': 'swift_name_lookup', 'file': 'Driver.swift', 'line': 211, 'column': 40}])
            self.assertEqual(result['simulator'], {'runtime': runtime, 'deviceType': device_type})
            self.assertEqual(result['toolchain']['simulatorSDKVersion'], '18.5')
            self.assertTrue(all(result['cleanup'].values()))
            self.assertTrue(private_paths and all(not p.exists() for p in private_paths))
            encoded = (root / 'public/result.json').read_text()
            for private in [*fixture_secrets, device_uuid, *map(str, private_paths)]:
                self.assertNotIn(private, encoded)
            self.assertEqual(sorted(p.name for p in (root / 'public').iterdir()), ['result.json'])

    def test_compile_diagnostics_allow_only_categories_known_basenames_and_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'build-private.log'
            path.write_text('\n'.join([
                f"{root}/UITests/Driver.swift:211:40: error: cannot find 'PRIVATE-PASSWORD' in scope",
                "211 | let secret = PRIVATE-PASSWORD", "    |     ^ PRIVATE-PASSWORD",
                f"{root}/Host/Host.swift:2:1: error: 'main' attribute cannot apply without static main()",
                f"{root}/UITests/Driver.swift:250:13: error: operator can throw but expression is not marked with 'try'",
                f"{root}/UITests/Driver.swift:260:13: error: call to main actor-isolated method in nonisolated context",
                '/private/account/PRIVATE-PASSWORD.swift:12:2: error: cannot convert value of type PRIVATE-PASSWORD',
            ]))
            result = ios.build_diagnostics(path, root, phase='xctest_build')
            self.assertEqual(result[:4], [
                {'classification': 'swift_name_lookup', 'file': 'Driver.swift', 'line': 211, 'column': 40},
                {'classification': 'swift_entry_point', 'file': 'Host.swift', 'line': 2, 'column': 1},
                {'classification': 'swift_throwing_expression', 'file': 'Driver.swift', 'line': 250, 'column': 13},
                {'classification': 'swift_actor_isolation', 'file': 'Driver.swift', 'line': 260, 'column': 13}])
            self.assertEqual(result[-1], {'classification': 'swift_type_mismatch'})
            encoded = json.dumps(result)
            for private in ('PRIVATE-PASSWORD', directory, 'let secret', 'source', '/private/account'):
                self.assertNotIn(private, encoded)

    def test_bounded_diagnostics_drop_unknown_file_coordinates_and_template_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'private.log'
            path.write_text('\n'.join(f"{root}/UITests/Driver.swift:{line}:1: error: cannot find 'PRIVATE' in scope"
                                      for line in range(1, 40)))
            self.assertEqual(len(ios.build_diagnostics(path, root, phase='xctest_build')), 12)
            for text, phase, expected in [
                ('Spec validation error: PRIVATE-SECRET\n', 'xcodegen_generate', 'xcodegen_invalid_spec'),
                ('xcodebuild: error: Unable to find destination PRIVATE-UUID', 'xctest_build', 'xcode_destination_unavailable'),
                ('xcodebuild: error: SDK PRIVATE-SDK cannot be located', 'xctest_build', 'xcode_sdk_unavailable'),
                ('private arbitrary text', 'xctest_build', 'xcode_build_failed')]:
                path.write_text(text)
                self.assertEqual(ios.build_diagnostics(path, root, phase=phase), [{'classification': expected}])

    def test_generation_and_compilation_failures_have_separate_stages_and_private_logs(self):
        for failing_call, stage, code in [(1, 'xcodegen_generate', 'tauri_ios_xcodegen_failed'),
                                           (2, 'xctest_build', 'tauri_ios_xctest_build_failed')]:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                count = 0
                def fail(arguments, *, log, **kwargs):
                    nonlocal count
                    count += 1
                    if count == failing_call:
                        log.write(b'error: PRIVATE-COMPILE-DIAGNOSTIC\n')
                        raise ios.Failure('tauri_ios_command_failed')
                result = {}
                with patch.object(ios, 'command', side_effect=fail):
                    with self.assertRaisesRegex(ios.Failure, code):
                        ios.build_driver(directory, ['xcodebuild'], result)
                self.assertEqual(result['stage'], stage)
                self.assertEqual(count, failing_call)
                self.assertNotIn('PRIVATE-COMPILE-DIAGNOSTIC', json.dumps(result))
                self.assertTrue((Path(directory) / (stage + '-private.log')).is_file())


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_failure_categories_export_only_owned_basename_and_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'private.log'
            messages = [
                ('Failed to get matching snapshots: No matches found for PRIVATE-CREDENTIAL',
                 'xctest_element_absent_or_query_unresolved'),
                ('Failed to resolve query: PRIVATE-CREDENTIAL', 'xctest_element_absent_or_query_unresolved'),
                ('Failed to get matching snapshots: Multiple matching elements found for PRIVATE-CREDENTIAL',
                 'xctest_ambiguous_match'),
                ('Timed out waiting for PRIVATE-CREDENTIAL', 'xctest_timeout'),
                ('XCTAssertTrue failed: PRIVATE-CREDENTIAL', 'xctest_native_assertion'),
                ('Incorrect actor executor assumption PRIVATE-CREDENTIAL', 'xctest_actor_isolation'),
                ('Failed to launch app PRIVATE-CREDENTIAL', 'xctest_process_failure')]
            path.write_text('\n'.join(f'{root}/UITests/Driver.swift:{100 + i}:9: error: {message}'
                                      for i, (message, _) in enumerate(messages)))
            records = ios.runtime_diagnostics(path, root)
            self.assertEqual(records, [{'classification': code, 'file': 'Driver.swift', 'line': 100 + i}
                                       for i, (_, code) in enumerate(messages)])
            encoded = json.dumps(records)
            for private in ('PRIVATE-CREDENTIAL', str(root), 'column', 'Failed to'):
                self.assertNotIn(private, encoded)

    def test_unknown_paths_messages_application_output_and_large_logs_remain_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'private.log'
            path.write_text('\n'.join([
                '/unknown/Driver.swift:42: error: XCTAssertTrue failed PRIVATE-CREDENTIAL',
                '/invalid\x00/Driver.swift:42: error: XCTAssertTrue failed PRIVATE-CREDENTIAL',
                '../Host/Host.swift:43: error: Timed out waiting PRIVATE-CREDENTIAL',
                f'{root}/Host/Host.swift:44: error: XCTAssertEqual failed PRIVATE-CREDENTIAL',
                'No matches found for ordinary successful application output',
                'PRIVATE-CREDENTIAL ' + 'x' * 8192 + ': error: Timed out waiting',
                *[f'{root}/UITests/Driver.swift:{i}: error: XCTAssertTrue failed PRIVATE-CREDENTIAL'
                  for i in range(50, 80)]]))
            records = ios.runtime_diagnostics(path, root)
            self.assertEqual(records[:3], [{'classification': 'xctest_native_assertion'},
                {'classification': 'xctest_timeout'},
                {'classification': 'xctest_native_assertion', 'file': 'Host.swift', 'line': 44}])
            self.assertEqual(len(records), 12)
            self.assertNotIn('PRIVATE-CREDENTIAL', json.dumps(records))
            for content in ('** TEST EXECUTE FAILED **', 'error: PRIVATE-CREDENTIAL',
                            'No matches found for an ordinary app log', ''):
                path.write_text(content)
                self.assertEqual(ios.runtime_diagnostics(path, root), [{'classification': 'xctest_failed'}])
            self.assertEqual(ios.runtime_diagnostics(root / 'missing', root), [{'classification': 'xctest_failed'}])

    def test_runtime_failure_preserves_checkpoint_error_and_cleans_all_private_files(self):
        for checkpoint_failure, command_failed in ((None, True), ('tauri_ios_native_check_failed', True),
                                                   ('tauri_ios_native_check_failed', False)):
            with self.subTest(checkpoint_failure=checkpoint_failure, command_failed=command_failed), \
                    tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project, app = InputAndPrivacyTests().build_inputs(root)
                private_paths, states, secrets = [], [], []
                original_checkpoints = ios.Checkpoints
                def checkpoints(*args, **kwargs):
                    state = original_checkpoints(*args, **kwargs)
                    states.append(state)
                    return state
                def command(arguments, *, log=None, **kwargs):
                    if arguments == ['xcodebuild', '-version']:
                        return b'Xcode 16.4\nBuild version 16F6\n'
                    if arguments == ['xcodebuild', '-version', '-sdk', 'iphonesimulator', 'SDKVersion']:
                        return b'18.5\n'
                    if arguments[:4] == ['xcrun', 'simctl', 'list', 'runtimes']:
                        return json.dumps({'runtimes': [{'isAvailable': True, 'version': '26.2',
                            'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-26-2'}]}).encode()
                    if arguments[:4] == ['xcrun', 'simctl', 'list', 'devicetypes']:
                        return json.dumps({'devicetypes': [{'name': 'iPhone 17 Pro Max',
                            'identifier': 'com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max'}]}).encode()
                    if arguments[:3] == ['xcrun', 'simctl', 'create']:
                        return b'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
                    if 'test-without-building' in arguments:
                        private = Path(arguments[2]).parent
                        private_paths.append(private)
                        self.assertEqual(private.stat().st_mode & 0o777, 0o700)
                        self.assertEqual(Path(log.name).stat().st_mode & 0o777, 0o600)
                        result_bundle = Path(arguments[arguments.index('-resultBundlePath') + 1])
                        self.assertEqual(result_bundle.parent, private)
                        result_bundle.mkdir()
                        config = json.loads((private / 'UITests/Fixture.json').read_text())
                        secrets.extend([config['ordinaryPassword'], config['rotationPassword'], config['checkpointSecret']])
                        (result_bundle / 'private-data').write_text(json.dumps(config))
                        states[0].accept({'stage':'ordinary_form'})
                        states[0].failure = checkpoint_failure
                        log.write(f'{private}/UITests/Driver.swift:123: error: No matches found for {config["ordinaryPassword"]}\n'.encode())
                        if command_failed:
                            raise ios.Failure('tauri_ios_command_failed')
                    return b''
                with patch.object(ios, 'command', side_effect=command), \
                        patch.object(ios, 'Checkpoints', side_effect=checkpoints), \
                        patch.object(ios.shutil, 'which', return_value='/tools/present'):
                    result = ios.run(project, app, root / 'public', source_sha='a' * 40,
                                     env={'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'macOS'})
                self.assertEqual(result['error'], checkpoint_failure or 'tauri_ios_xctest_failed')
                self.assertEqual(result['runtimeDiagnostics'], [{'classification': 'xctest_element_absent_or_query_unresolved',
                                                                'file': 'Driver.swift', 'line': 123}])
                self.assertTrue(all(result['cleanup'].values()))
                self.assertTrue(private_paths and all(not p.exists() for p in private_paths))
                encoded = (root / 'public/result.json').read_text()
                observations = json.loads(encoded)['cases']['ordinary']['failurePeerObservations']
                self.assertEqual(observations['beforeCleanup']['connections'], 0)
                self.assertEqual(observations['afterCleanup']['connections'], 0)
                self.assertNotIn('failurePeerObservations', result['cases']['keyChange'])
                for private in [*secrets, *map(str, private_paths)]:
                    self.assertNotIn(private, encoded)
                self.assertEqual(sorted(p.name for p in (root / 'public').iterdir()), ['result.json'])


class ScreenshotContractTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.fixture = SimpleNamespace(username='fixture', port=12345, screen_token='CAVE DUSK FERN GLOW HILL JADE KITE LEAF')
        self.result = {'cases': {'ordinary': {}, 'keyChange': {}}, 'artifacts': {}}

    def screenshot(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (440, 956), '#101010').save(buffer, format='PNG')
        data = buffer.getvalue()
        return data, {'screenSize': [440, 956], 'safeFrame': [0, 60, 440, 850],
                      'terminalFrame': [20, 200, 400, 300], 'targetFrame': [20, 160, 400, 30],
                      'identityVerified': True, 'noCredentialsVisible': True,
                      'activeHeaderBounds': {'titleFrame':[16,70,160,30], 'disconnectFrame':[330,60,90,44],
                                             'statusBarFrames':[[0,0,440,54]], 'sameOwner':True,
                                             'disconnectHittable':True},
                      'pngBase64': base64.b64encode(data).decode(),
                      'nativeOwner': {'windowFrame': [0,0,440,956], 'webFrames': [[0,0,440,956]] * 3,
                                      'webWrapperCount': 3, 'uniqueWebBoundsCount': 1}}

    def test_same_exact_original_hash_binds_manifest_case_and_unchanged_gate_json(self):
        data, payload = self.screenshot()
        criteria = {'schemaVersion': 1, 'imageSha256': hashlib.sha256(data).hexdigest(),
                    'terminalBounds': [20, 200, 400, 300], 'markerVisible': True,
                    'tokenVisible': True, 'proofSequenceVisible': True,
                    'expectedToken': self.fixture.screen_token}
        with tempfile.TemporaryDirectory() as directory:
            state = ios.Checkpoints(None, None, directory, self.result)
            with patch.object(ios, 'verify_terminal_screenshot', return_value=criteria) as gate:
                state.capture('ordinary_terminal', payload, self.fixture)
            gate.assert_called_once_with(data, expected_token=self.fixture.screen_token,
                                         bounds=[20, 200, 400, 300])
            case = self.result['cases']['ordinary']['terminalScreenshot']
            self.assertEqual((Path(directory) / case['imageFile']).read_bytes(), data)
            self.assertEqual(case['imageSha256'], self.result['artifacts'][case['imageFile']])
            self.assertEqual(json.loads((Path(directory) / case['criteriaFile']).read_text()), criteria)
            self.assertEqual(case['criteriaSha256'], hashlib.sha256((Path(directory) / case['criteriaFile']).read_bytes()).hexdigest())
            with self.assertRaisesRegex(ios.Failure, 'replay'):
                state.capture('ordinary_terminal', payload, self.fixture)

    def test_unknown_identity_or_unsafe_geometry_saves_no_public_png(self):
        _, payload = self.screenshot()
        for change in ({'identityVerified': False}, {'noCredentialsVisible': False},
                       {'terminalFrame': [0, 0, 440, 300]}):
            with tempfile.TemporaryDirectory() as directory:
                state = ios.Checkpoints(None, None, directory, copy.deepcopy(self.result))
                with self.assertRaises(ios.Failure):
                    state.capture('ordinary_terminal', {**payload, **change}, self.fixture)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_terminal_header_required_and_occluded_or_unowned_rejected(self):
        _, payload = self.screenshot()
        for change in ('missing', 'old_header', 'missing_title', 'occluded_title', 'occluded_action', 'duplicate_bar',
                       'outside', 'unowned', 'unhittable', 'controls_overlap', 'controls_misaligned', 'target_overlap'):
            candidate = copy.deepcopy(payload)
            header = candidate['activeHeaderBounds']
            if change == 'missing': candidate.pop('activeHeaderBounds')
            elif change == 'old_header':
                candidate.pop('activeHeaderBounds')
                candidate['headerBounds'] = {'brandFrame':[16,60,100,40], 'addFrame':[300,60,100,40],
                                             'headingFrame':[16,112,200,28], 'headerBottom':106,
                                             'statusBarFrames':[[0,0,440,54]], 'sameOwner':True}
                self.assertIn('headerBounds', ios.measured_bounds(candidate, (440,956)))
            elif change == 'missing_title': header.pop('titleFrame')
            elif change == 'occluded_title': header['titleFrame'][1] = 40
            elif change == 'occluded_action': header['disconnectFrame'][1] = 40
            elif change == 'duplicate_bar': header['statusBarFrames'].append([0,0,440,54])
            elif change == 'outside': header['disconnectFrame'][0] = 400
            elif change == 'unowned': header['sameOwner'] = False
            elif change == 'unhittable': header['disconnectHittable'] = False
            elif change == 'controls_overlap': header['disconnectFrame'][0] = 100
            elif change == 'controls_misaligned': header['disconnectFrame'][1] = 105
            else: candidate['targetFrame'][1] = 95
            for stage in ('ordinary_terminal', 'key_change_terminal'):
                with self.subTest(change=change, stage=stage), tempfile.TemporaryDirectory() as directory:
                    state = ios.Checkpoints(None, None, directory, copy.deepcopy(self.result))
                    with self.assertRaisesRegex(ios.Failure, 'capture_header_invalid'):
                        state.capture(stage, candidate, self.fixture)
                    self.assertEqual(list(Path(directory).iterdir()), [])

    def test_ocr_failure_keeps_safe_original_and_gate_diagnostics_without_text(self):
        data, payload = self.screenshot()
        evidence = {'imageSha256': hashlib.sha256(data).hexdigest(), 'markerVisible': False}
        with tempfile.TemporaryDirectory() as directory:
            state = ios.Checkpoints(None, None, directory, self.result)
            with patch.object(ios, 'verify_terminal_screenshot', side_effect=ScreenshotGateError('failed', evidence)):
                with self.assertRaisesRegex(ios.Failure, 'terminal_ocr_failed'):
                    state.capture('ordinary_terminal', payload, self.fixture)
            self.assertIn('ordinary-terminal.png', self.result['artifacts'])
            self.assertEqual(json.loads((Path(directory) / 'ordinary-terminal-ocr.json').read_text()), evidence)

    def test_s10_retains_system_original_and_never_runs_terminal_ocr(self):
        data, payload = self.screenshot()
        payload.pop('terminalFrame')
        payload.pop('targetFrame')
        payload.pop('activeHeaderBounds')
        payload['reviewFrames'] = [[20, 80 + i * 100, 400, 50] for i in range(7)]
        with tempfile.TemporaryDirectory() as directory:
            state = ios.Checkpoints(None, None, directory, self.result)
            with patch.object(ios, 'verify_terminal_screenshot') as gate:
                state.capture('key_change_review', payload, self.fixture)
            gate.assert_not_called()
            self.assertEqual((Path(directory) / 'key-change-review.png').read_bytes(), data)
            self.assertIn('reviewScreenshot', self.result['cases']['keyChange'])


class GeometryReasonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.result = {}
        self.state = ios.Checkpoints(None, None, self.directory.name, self.result)

    def test_geometry_reason_trace_is_bounded_scoped_and_compatible(self):
        self.state.accept({'stage': 'native_progress', 'nativeCheckpoint': 'ordinary_host'})
        self.assertNotIn('geometryReasonTrace', self.result)
        encrypted = ios.Checkpoints(None, None, self.directory.name, self.result, encrypted=object())
        for phase in sorted(ios.GEOMETRY_PHASES):
            state = encrypted if phase.startswith('encrypted_key_') else self.state
            for reason in sorted(ios.GEOMETRY_REASONS):
                state.accept({'stage': 'native_progress', 'nativeCheckpoint': phase, 'geometryReason': reason})
            self.assertEqual(self.result['geometryReasonTrace'][phase], sorted(ios.GEOMETRY_REASONS))
        phase = 'ordinary_host'
        for _ in range(ios.MAX_GEOMETRY_REASONS_PER_CHECKPOINT - len(ios.GEOMETRY_REASONS)):
            self.state.accept({'stage': 'native_progress', 'nativeCheckpoint': phase, 'geometryReason': 'field_outside'})
        before = copy.deepcopy(self.result)
        with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
            self.state.accept({'stage': 'native_progress', 'nativeCheckpoint': phase, 'geometryReason': 'field_outside'})
        self.assertEqual(self.result, before)

    def test_input_readback_is_bounded_and_cannot_publish_text(self):
        payload = {'stage': 'native_progress', 'nativeCheckpoint': 'ordinary_host',
                   'inputReadback': {'state': 'empty', 'samples': 6}}
        self.state.accept(payload)
        self.assertEqual(self.result['inputReadbacks']['ordinary_host'], {'state': 'empty', 'samples': 6})
        for detail in ({'state': 'fixture-secret', 'samples': 1}, {'state': 'empty', 'samples': 7},
                       {'state': 'empty', 'samples': True}, {'state': 'empty', 'samples': 1, 'text': 'secret'}):
            with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
                self.state.accept(payload | {'inputReadback': detail})
        with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
            self.state.accept(payload | {'nativeCheckpoint': 'ordinary_password'})

    def test_secret_exposure_diagnostic_only_accepts_bounded_categories(self):
        state = ios.Checkpoints(None, None, self.directory.name, {}, encrypted=object())
        candidate = {'role': 'textView', 'scope': 'sameWeb', 'relation': 'ancestor',
                     'identifier': False, 'label': False, 'value': True,
                     'privateKeyHeader': True, 'passphrase': False}
        detail = {'count': 1, 'candidates': [candidate]}
        payload = {'stage': 'native_progress', 'nativeCheckpoint': 'encrypted_key_passphrase', 'secretDiagnostic': detail}
        state.accept(payload)
        self.assertEqual(state.result['secretDiagnostic'], detail)
        for bad in (detail | {'text': 'fixture-secret'}, {'count': 1, 'candidates': [candidate | {'role': 'secret'}]},
                    {'count': 1, 'candidates': [candidate | {'value': 'secret'}]}, {'count': 10001, 'candidates': []}):
            with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
                state.accept(payload | {'secretDiagnostic': bad})

    def test_key_change_password_preserves_both_attempts(self):
        phase = 'key_change_password'
        first = ['field_outside'] * 9
        second = ['field_unhittable'] * 10 + ['scroll_surface_unhittable']
        for reason in first + second:
            self.state.accept({'stage': 'native_progress', 'nativeCheckpoint': phase, 'geometryReason': reason})
        self.assertEqual(self.result['geometryReasonTrace'][phase], first + second)

    def test_password_failure_geometry_publication_and_bounds(self):
        detail = {'viewport': [0, 0, 440, 956], 'usable': [0, 50, 440, 700],
                  'owner': [0, 100, 440, 800], 'query': [10, 700, 400, 44], 'bound': None,
                  'queryEnabled': True, 'boundEnabled': True, 'queryHittable': False,
                  'boundHittable': False, 'scrollAttempted': True, 'scrollDirection': 'swipe_up'}
        payload = {'stage': 'native_progress', 'nativeCheckpoint': 'key_change_password',
                   'geometryReason': 'queried_unhittable', 'geometryDetail': detail}
        self.state.accept(payload)
        detail['query'][0] = 999
        published = json.loads(json.dumps(self.result))
        self.assertEqual(published['geometryFailureDetails']['key_change_password'][0]['query'][0], 10)
        self.assertEqual(published['geometryFailureDetails']['key_change_password'][0]['reason'], 'queried_unhittable')
        self.state.accept(payload)
        before = copy.deepcopy(self.result)
        with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
            self.state.accept(payload)
        self.assertEqual(self.result, before)

    def test_password_failure_geometry_rejects_unknown_text_invalid_values_and_scope(self):
        detail = {'viewport': [0, 0, 440, 956], 'usable': None, 'owner': None,
                  'query': None, 'bound': None, 'queryEnabled': True, 'boundEnabled': False,
                  'queryHittable': False, 'boundHittable': False, 'scrollAttempted': False,
                  'scrollDirection': 'none'}
        base = {'stage': 'native_progress', 'nativeCheckpoint': 'ordinary_password',
                'geometryReason': 'field_invalid', 'geometryDetail': detail}
        variants = [dict(detail, text='fixture-secret-must-not-escape'), dict(detail, query=[0, 0, True, 2]),
                    dict(detail, query=[0, 0, 10001, 2]), dict(detail, viewport=[0, float('nan'), 1, 2]),
                    dict(detail, scrollAttempted=True), dict(detail, scrollDirection='secret')]
        payloads = [dict(base, geometryDetail=value) for value in variants]
        payloads += [dict(base, nativeCheckpoint='ordinary_host'), dict(base, stage='native_failure'),
                     {k: v for k, v in base.items() if k != 'geometryReason'}]
        for payload in payloads:
            with self.subTest(payload=payload):
                state = ios.Checkpoints(None, None, self.directory.name, {})
                with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
                    state.accept(payload)
                self.assertEqual(state.result, {})

    def test_geometry_reason_rejects_secrets_invalid_types_phases_and_failure_events(self):
        for stage, phase, reason in [
            ('native_progress', 'ordinary_host', 'fixture-secret-must-not-escape'),
            ('native_progress', 'ordinary_host', None),
            ('native_progress', 'ordinary_host', ['field_invalid']),
            ('native_progress', 'ordinary_fingerprint', 'field_invalid'),
            ('native_progress', 'ordinary_reprobe', 'field_invalid'),
            ('native_failure', 'ordinary_host', 'field_invalid'),
        ]:
            with self.subTest(stage=stage, phase=phase, reason=reason):
                state = ios.Checkpoints(None, None, self.directory.name, {})
                with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
                    state.accept({'stage': stage, 'nativeCheckpoint': phase, 'geometryReason': reason})
                self.assertNotIn('fixture-secret-must-not-escape', json.dumps(state.result))
                self.assertNotIn('geometryReasonTrace', state.result)


class TerminalFallbackTests(unittest.TestCase):
    def payload(self, image):
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        return {'screenSize':[440,956], 'safeFrame':[0,54,440,850], 'targetFrame':[95,129,250,30],
                'terminalFrame':[0,170,440,430], 'identityVerified':True, 'noCredentialsVisible':True,
                'boundSource':'terminal_control_bounds',
                'activeHeaderBounds':{'titleFrame':[16,65,170,24], 'disconnectFrame':[330,59,90,44],
                                      'statusBarFrames':[[0,0,440,54]], 'sameOwner':True, 'disconnectHittable':True},
                'controlBounds':{'keyboardFrame':[350,120,74,50], 'helperFrames':[[20+i*55,600,50,44] for i in range(4)], 'sameOwner':True},
                'nativeOwner':{'windowFrame':[0,0,440,956], 'webFrames':[[0,0,440,956]],
                               'webWrapperCount':1, 'uniqueWebBoundsCount':1},
                'pngBase64':base64.b64encode(stream.getvalue()).decode()}

    def image(self, boxes):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (440,956), 'white')
        draw = ImageDraw.Draw(image)
        for box in boxes: draw.rectangle(box, fill=(11,15,23))
        return image

    def test_unique_terminal_background_is_inward_and_same_png_reaches_ocr(self):
        image = self.image([(20,190,419,549)])
        payload = self.payload(image)
        data = base64.b64decode(payload['pngBase64'])
        class Fixture:
            username='fixture'; port=1234; screen_token='synthetic'
        result={'cases':{'ordinary':{}},'artifacts':{}}
        criteria={'imageSha256':hashlib.sha256(data).hexdigest(), 'markerVisible':True,
                  'tokenVisible':True, 'proofSequenceVisible':True}
        with tempfile.TemporaryDirectory() as directory, patch.object(ios, 'verify_terminal_screenshot', return_value=criteria) as gate:
            ios.Checkpoints(None,None,directory,result).capture('ordinary_terminal',payload,Fixture())
            bounds=result['cases']['ordinary']['terminalScreenshot']['terminalBounds']
            self.assertEqual(bounds,[20,190,400,360])
            gate.assert_called_once_with(data,expected_token='synthetic',bounds=bounds)
            self.assertEqual(result['cases']['ordinary']['terminalScreenshot']['candidateTerminalBounds'],[0,170,440,430])

    def test_scaled_narrow_background_tolerates_text_and_antialiasing(self):
        from PIL import Image, ImageDraw
        image=Image.new('RGB',(960,1200),'white')
        draw=ImageDraw.Draw(image)
        draw.rectangle((30,0,929,999),fill=(14,17,26))
        for y in range(40,800,60):
            draw.rectangle((60,y,450,y+9),fill=(220,220,220))
            draw.rectangle((60,y+10,450,y+12),fill=(25,28,37))
        bounds=ios.terminal_background_bounds(image,[0,0,960,1100],3)
        self.assertEqual(bounds,[30,3,900,997])
        with self.assertRaisesRegex(ios.Failure,'terminal_background_invalid'):
            ios.terminal_background_bounds(image,[0,0,200,1100],3)

    def test_reject_missing_multiple_wrong_color_and_unbounded_background(self):
        cases = [[], [(20,190,419,299),(20,380,419,499)], [(0,170,439,599)]]
        for boxes in cases:
            with self.subTest(boxes=boxes), self.assertRaisesRegex(ios.Failure,'terminal_background_invalid'):
                ios.terminal_background_bounds(self.image(boxes),[0,170,440,430],1)
        image=self.image([])
        from PIL import ImageDraw
        ImageDraw.Draw(image).rectangle((20,190,419,549),fill=(80,80,80))
        with self.assertRaisesRegex(ios.Failure,'terminal_background_invalid'):
            ios.terminal_background_bounds(image,[0,170,440,430],1)

    def test_reject_false_or_overlapping_control_proofs(self):
        base=self.payload(self.image([(20,190,419,549)]))
        cases=[]
        for change in ('owner','order','candidate','target','target_not_in_keyboard_row'):
            payload=copy.deepcopy(base)
            if change == 'owner': payload['controlBounds']['sameOwner']=False
            elif change == 'order': payload['controlBounds']['helperFrames'][1][0]=25
            elif change == 'candidate': payload['terminalFrame']=[0,171,440,429]
            elif change == 'target': payload['targetFrame']=[20,180,400,30]
            else: payload['targetFrame']=[95,105,250,12]
            cases.append(payload)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ios.Failure): ios.measured_bounds(payload,(440,956))


class CaseLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.ordinary, self.rotation = object(), object()
        self.result = {'cases': {'ordinary': {'status': 'not_run'}, 'keyChange': {'status': 'not_run'}}, 'artifacts': {}}
        self.state = ios.Checkpoints(self.ordinary, self.rotation, '/tmp', self.result)

    def test_unstarted_and_started_cases_finalize_without_inventing_success(self):
        self.state.finalize_cases()
        self.assertEqual([c['status'] for c in self.result['cases'].values()], ['not_run', 'not_run'])
        self.state.accept({'stage': 'ordinary_form'})
        self.state.finalize_cases()
        self.assertEqual([c['status'] for c in self.result['cases'].values()], ['failed', 'not_run'])
        self.result['cases']['ordinary']['status'] = 'passed'
        self.state.index = ios.STAGES.index('key_change_form')
        self.state.accept({'stage': 'key_change_form'})
        self.state.finalize_cases()
        self.assertEqual([c['status'] for c in self.result['cases'].values()], ['passed', 'failed'])

    def test_input_then_capture_failure_keeps_only_confirmed_partial_evidence(self):
        for name, stage, count in [('ordinary', 'ordinary_input', 2), ('keyChange', 'key_change_input', 4)]:
            with self.subTest(name=name):
                result = {'cases': {'ordinary': {'status': 'not_run'}, 'keyChange': {'status': 'not_run'}}, 'artifacts': {}}
                state = ios.Checkpoints(self.ordinary, self.rotation, '/tmp', result)
                state.index = ios.STAGES.index('ordinary_form' if name == 'ordinary' else 'key_change_form')
                state.accept({'stage': ios.STAGES[state.index]})
                state.index = ios.STAGES.index(stage)
                facts = {'connections': count, 'connectionEvents': [{'markerReceived': False}] * (count-1) + [{'markerReceived': True}]}
                def verify_peer(fixture, predicate, code):
                    self.assertTrue(predicate(facts))
                    self.assertFalse(predicate({**facts, 'connectionEvents': [{'markerReceived': True}] +
                                                [{'markerReceived': False}] * (count-1)}))
                    return facts
                recorded = {}
                with patch.object(ios, 'wait_peer', side_effect=verify_peer), patch.object(ios, 'ordinary_evidence') as ordinary_peer:
                    if name == 'ordinary':
                        recorded['activeFlow'] = [{'step': step} for step in ios.ORDINARY_ACTIVE_STEPS]
                        result['cases'][name].update(recorded)
                    state.accept({'stage': stage})
                    if name == 'ordinary': ordinary_peer.assert_called_once_with(self.ordinary, closed=False)
                    else: ordinary_peer.assert_not_called()
                state.accept({'stage': 'native_failure', 'nativeCheckpoint': stage.replace('_input', '_terminal_capture'),
                              'nativeFailureCode': 'native_geometry_ambiguous'})
                state.finalize_cases()
                self.assertEqual(result['cases'][name], dict(recorded, status='failed', terminalInputReceived=True))
                self.assertNotIn('peer', result['cases'][name])


class FailurePeerSnapshotTests(unittest.TestCase):
    def test_fixed_observations_drop_sensitive_or_unknown_fields_and_bound_events(self):
        from types import SimpleNamespace
        event = {'id':4, 'hostKey':'B', 'phase':'await_channel', 'closeReason':'fixture_stopped',
                 'authAttempts':1, 'authSuccesses':1, 'ptyRequests':0, 'shellRequests':0,
                 'inputBytes':0, 'outputBytes':0, 'closed':True, 'sessionClosed':False,
                 'socketErrorKind':'secret', 'username':'secret', 'password':'secret',
                 'message':'secret', 'firstAuthMs':None}
        fixture=SimpleNamespace(snapshot=lambda: {'connections':20, 'connectionsClosed':True,
                                                    'connectionEvents':[event]*20, 'password':'secret'})
        result=ios.failure_peer_snapshot(fixture)
        self.assertEqual(result['connections'],20)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['events']),16)
        self.assertNotIn('secret',json.dumps(result))
        self.assertNotIn('firstAuthMs',result['events'][0])
        self.assertEqual(result['events'][0]['closeReason'],'fixture_stopped')
        self.assertEqual(result['events'][0]['authAttempts'],1)

    def test_unknown_values_not_invented_and_missing_snapshot_rejected(self):
        from types import SimpleNamespace
        fixture=SimpleNamespace(snapshot=lambda:{'connections':1,'connectionsClosed':False,
                       'connectionEvents':[{'id':1,'phase':'private text','authAttempts':None}]})
        result=ios.failure_peer_snapshot(fixture)
        self.assertEqual(result['events'],[{'id':1}])
        fixture.snapshot=lambda:{'connections':True,'connectionsClosed':False,'connectionEvents':[]}
        with self.assertRaisesRegex(ios.Failure,'failure_peer_snapshot_invalid'):
            ios.failure_peer_snapshot(fixture)


class ConnectDiagnosticTests(unittest.TestCase):
    def detail(self, attempt):
        sample = {'status':'connecting', 'keyboardVisible':False, 'submitFrame':[5,6,100,44],
                  'submitEnabled':True, 'submitHittable':True}
        return {'attempt':attempt, 'before':copy.deepcopy(sample), 'after':copy.deepcopy(sample),
                'statuses':['connecting','connection_failed']}

    def test_all_fixed_swift_connection_statuses_are_accepted(self):
        statuses=['unknown','ambiguous','idle','disconnected','connecting','connected','review_blocked',
                  'review_required','authentication_failed','start_failed','connection_failed','session_ended']
        detail=self.detail('ordinary')
        detail['statuses']=statuses
        for status in statuses:
            detail['before']['status']=status
            detail['after']['status']=status
            self.assertEqual(ios.public_connect_diagnostic(detail)['before']['status'],status)

    def test_exact_phase_attempt_and_peer_at_event_without_state_advancement(self):
        from types import SimpleNamespace
        fixture=SimpleNamespace(snapshot=lambda:{'connections':4, 'connectionsClosed':False,
                    'connectionEvents':[{'id':4,'hostKey':'B','authAttempts':1,'authSuccesses':0,
                                         'password':'never-export-this','phase':'await_channel'}]})
        for attempt,phase,next_stage in [('ordinary','ordinary_connect','ordinary_input'),
                                          ('rotation_refused','key_change_connect','key_change_review'),
                                          ('rotation_approved','key_change_connect','key_change_input')]:
            with self.subTest(attempt=attempt):
                state=ios.Checkpoints(fixture,fixture,'/tmp',{})
                state.index=ios.STAGES.index(next_stage)
                event={'stage':'native_connect_diagnostic','nativeCheckpoint':phase,'detail':self.detail(attempt)}
                state.accept(event)
                report=state.result['connectDiagnostics'][attempt]
                self.assertEqual(report['peerAtDiagnostic']['connections'],4)
                self.assertEqual(report['peerAtDiagnostic']['events'][0]['authAttempts'],1)
                self.assertNotIn('never-export-this',json.dumps(state.result))
                self.assertEqual(state.index,ios.STAGES.index(next_stage))
                with self.assertRaisesRegex(ios.Failure,'connect_diagnostic_invalid'): state.accept(event)

    def test_reject_private_text_invalid_types_replays_and_wrong_phase(self):
        good=self.detail('rotation_approved')
        samples=[dict(good, statuses=['connecting','secret']),dict(good, statuses=['idle','idle']),
                 dict(good, after=dict(good['after'], status='secret')),
                 dict(good, after=dict(good['after'], submitFrame=[1,2,float('nan'),4])),
                 dict(good, before=dict(good['before'], label='secret')),
                 dict(good, before=dict(good['before'], submitEnabled=1)), dict(good, attempt='secret')]
        for detail in samples:
            with self.subTest(detail=detail):
                state=ios.Checkpoints(None,None,'/tmp',{})
                state.index=ios.STAGES.index('key_change_input')
                with self.assertRaisesRegex(ios.Failure,'connect_diagnostic_invalid'):
                    state.accept({'stage':'native_connect_diagnostic','nativeCheckpoint':'key_change_connect','detail':detail})
                self.assertEqual(state.result,{})
        state=ios.Checkpoints(None,None,'/tmp',{})
        state.index=ios.STAGES.index('ordinary_input')
        with self.assertRaisesRegex(ios.Failure,'connect_diagnostic_invalid'):
            state.accept({'stage':'native_connect_diagnostic','nativeCheckpoint':'key_change_connect','detail':good})


class CaptureDiagnosticsTests(unittest.TestCase):
    def test_swift_failure_codes_are_all_allowlisted_and_header_failure_is_recorded(self):
        source = (ios.HERE / 'tauri_ios_direct_ssh.swift').read_text()
        emitted = set(re.findall(r'\b(?:try require\([\s\S]*?,\s*|NSError\(domain:\s*)"(native_[a-z_]+)"', source))
        self.assertIn('native_terminal_header_unproven', emitted)
        self.assertEqual(emitted - ios.NATIVE_FAILURES, set())
        state = ios.Checkpoints(None, None, '/tmp', {})
        state.accept({'stage':'native_failure', 'nativeCheckpoint':'ordinary_terminal_capture',
                      'nativeFailureCode':'native_terminal_header_unproven'})
        self.assertEqual(state.result['nativeFailureCode'], 'native_terminal_header_unproven')
        self.assertEqual(state.failure, 'tauri_ios_native_check_failed')

    def test_fixed_capture_diagnostics_export_and_bound(self):
        detail = {'anchor': 'terminal', 'matchCount': 2, 'reason': 'geometry_ambiguous',
                  'candidates': [{'role': 'other', 'frame': [10, 200, 400, 500],
                                  'ownerResolved': True, 'visible': True}], 'truncated': False}
        state = ios.Checkpoints(None, None, '/tmp', {})
        event = {'stage': 'native_capture_diagnostic', 'nativeCheckpoint': 'ordinary_terminal_capture', 'detail': detail}
        for _ in range(4): state.accept(event)
        detail['candidates'][0]['frame'][0] = 99
        result = json.loads(json.dumps(state.result))
        self.assertEqual(result['captureDiagnostics']['ordinary_terminal_capture'][0]['candidates'][0]['frame'][0], 10)
        with self.assertRaisesRegex(ios.Failure, 'capture_diagnostic_invalid'): state.accept(event)
        self.assertEqual(len(state.result['captureDiagnostics']['ordinary_terminal_capture']), 4)
        state.accept({'stage': 'native_failure', 'nativeCheckpoint': 'ordinary_terminal_capture',
                      'nativeFailureCode': 'native_terminal_keyboard_visible'})
        self.assertEqual(state.result['nativeFailureCode'], 'native_terminal_keyboard_visible')

    def test_header_diagnostics_are_accepted_at_both_terminal_stages(self):
        for phase in ('ordinary_terminal_capture','key_change_terminal_capture'):
            for anchor in ('header_brand','header_add','terminal_heading','status_bar'):
                for reason in ('not_found','frame_invalid','owner_unproven','outside_safe_frame','layout_unstable'):
                    state=ios.Checkpoints(None,None,'/tmp',{})
                    detail={'anchor':anchor,'matchCount':0,'reason':reason,'candidates':[],'truncated':False}
                    state.accept({'stage':'native_capture_diagnostic','nativeCheckpoint':phase,'detail':detail})
                    self.assertEqual(state.result['captureDiagnostics'][phase],[detail])

    def test_review_diagnostics_allow_only_seven_fixed_anchors_and_snapshot_phase(self):
        anchors = ('review_title', 'review_blocked', 'review_old_fingerprint', 'review_new_fingerprint',
                   'review_target', 'review_recheck', 'review_cancel')
        for anchor in anchors:
            for sample in ('before', 'after'):
                with self.subTest(anchor=anchor, sample=sample):
                    detail = {'anchor': anchor, 'sample': sample, 'matchCount': 1, 'reason': 'geometry_ambiguous',
                              'candidates': [{'role':'staticText', 'frame':[1,2,100,44],
                                              'ownerResolved':True, 'visible':False}], 'truncated':False}
                    state = ios.Checkpoints(None,None,'/tmp',{})
                    state.accept({'stage':'native_capture_diagnostic', 'nativeCheckpoint':'key_change_review_capture',
                                  'detail':detail})
                    self.assertEqual(state.result['captureDiagnostics']['key_change_review_capture'], [detail])

    def test_review_diagnostics_reject_text_cross_phase_bad_sample_and_extra_fields(self):
        detail = {'anchor':'review_old_fingerprint', 'sample':'before', 'matchCount':0,
                  'reason':'not_found', 'candidates':[], 'truncated':False}
        base = {'stage':'native_capture_diagnostic', 'nativeCheckpoint':'key_change_review_capture', 'detail':detail}
        bad = [dict(base, detail=dict(detail, anchor='SHA256:secret')), dict(base, detail=dict(detail, sample='secret')),
               dict(base, detail={k:v for k,v in detail.items() if k != 'sample'}),
               dict(base, detail=dict(detail, text='secret')), dict(base, nativeCheckpoint='ordinary_terminal_capture'),
               dict(base, detail=dict(detail, anchor='terminal'))]
        for payload in bad:
            state = ios.Checkpoints(None,None,'/tmp',{})
            with self.subTest(payload=payload), self.assertRaisesRegex(ios.Failure,'capture_diagnostic_invalid'):
                state.accept(payload)
            self.assertEqual(state.result,{})

    def test_failed_checkpoint_does_not_claim_completion(self):
        class Fixture:
            def wait_for_connections_closed(self, count, timeout): return False
        result={'cases':{'ordinary':{'status':'not_run'},'keyChange':{'status':'not_run'}},'artifacts':{}}
        state=ios.Checkpoints(Fixture(),None,'/tmp',result)
        state.accept({'stage':'ordinary_form'})
        with self.assertRaisesRegex(ios.Failure,'probe_not_closed'):
            state.accept({'stage':'ordinary_probe'})
        self.assertEqual(result['stage'],'ordinary_probe')
        self.assertEqual(result['lastCompletedStage'],'ordinary_form')
        self.assertEqual(state.index,ios.STAGES.index('ordinary_probe'))

    def test_capture_diagnostics_reject_unknown_text_bad_geometry_and_scope(self):
        detail = {'anchor': 'target', 'matchCount': 1, 'reason': 'not_found', 'candidates': [], 'truncated': False}
        event = {'stage': 'native_capture_diagnostic', 'nativeCheckpoint': 'key_change_terminal_capture', 'detail': detail}
        bad_candidate = {'role': 'other', 'frame': [0, 0, 1, 1], 'ownerResolved': True, 'visible': True}
        variants = [dict(detail, text='fixture-secret'), dict(detail, anchor='fixture-secret'),
                    dict(detail, matchCount=True), dict(detail, candidates=[dict(bad_candidate, text='fixture-secret')]),
                    dict(detail, candidates=[dict(bad_candidate, frame=[0, float('nan'), 1, 2])]),
                    dict(detail, candidates=[dict(bad_candidate, frame=[0, 0, -1, 2])]),
                    dict(detail, candidates=[bad_candidate]*9), dict(detail, reason='unknown')]
        for payload in [dict(event, detail=x) for x in variants] + [dict(event, nativeCheckpoint='ordinary_password')]:
            state = ios.Checkpoints(None, None, '/tmp', {})
            with self.subTest(payload=payload), self.assertRaisesRegex(ios.Failure, 'capture_diagnostic_invalid'):
                state.accept(payload)
            self.assertEqual(state.result, {})


class HomeDiagnosticsTests(unittest.TestCase):
    def test_compact_home_requires_owned_roles_and_two_real_navigation_actions(self):
        home = {**self.value(), 'compactEmptyHome': True}
        members = home['members']
        for name in ('homeHeading', 'zeroHosts', 'headerAdd'):
            members[name] = {'count': 0, 'roles': []}
        members['emptyDescription'] = {'count': 1, 'roles': ['staticText']}
        members['compactShortcut'] = {'count': 1, 'roles': ['button']}
        self.assertEqual(ios.public_home_diagnostic(home), home)
        for name in ('emptyDescription', 'compactShortcut', 'emptyAdd'):
            bad = {**home, 'members': {**members, name: {'count': 0, 'roles': []}}}
            with self.subTest(name=name), self.assertRaises(ios.Failure):
                ios.public_home_diagnostic(bad)
        readiness = {'outcome': 'ready', 'elapsedMs': 200, 'strictSampleMs': 200, 'strictSamples': 1,
                     'waitCalls': 0, 'samples': [{'state': 'ready', 'elapsedMs': 200}]}
        with tempfile.TemporaryDirectory() as directory:
            state = self.state_for_navigation(directory)
            state.accept({'stage': 'native_home', 'nativeCheckpoint': 'ordinary_open_add',
                          'home': home, 'readiness': readiness})
            first = self.navigation('emptyAdd', 'emptyHome', 'addChoice')
            first['geometry']['role'] = 'button'
            first['before']['compactEmptyHome'] = True
            first['after']['mobileAddChoice'] = True
            with self.assertRaisesRegex(ios.Failure, 'home_retry_unsafe'):
                state.accept({**first, 'member': 'headerAdd'})
            state.accept(first)
            second = self.navigation('sshChoice', 'addChoice', 'sshForm')
            second['geometry']['role'] = 'button'
            second['nativeCheckpoint'] = 'ordinary_open_ssh'
            with self.assertRaisesRegex(ios.Failure, 'home_retry_unsafe'):
                state.accept(second)
            with self.assertRaisesRegex(ios.Failure, 'ssh_form_unproven'):
                state.accept({'stage': 'native_navigation_arrival', 'nativeCheckpoint': 'ordinary_open_ssh',
                              'source': 'currentFormObservation', 'performed': False, 'state': second['after'],
                              'geometry': second['geometry']})
            second['before']['mobileAddChoice'] = True
            with self.assertRaisesRegex(ios.Failure, 'home_retry_unsafe'):
                state.accept({**second, 'before': {**second['before'], 'inputCount': 1}})
            state.accept(second)
            state.accept({'stage': 'native_home_entry', 'nativeCheckpoint': 'ordinary_open_ssh', 'member': 'emptyAdd',
                          'selection': 'buttonRole', 'role': 'button', 'enteredAddPage': True,
                          'enteredSSHForm': True, 'route': 'viaAdd'})
            self.assertEqual(state.result['homeEntry']['ordinary']['member'], 'emptyAdd')

    def test_unknown_initial_observation_never_authorizes_navigation(self):
        initial = {'state': 'unidentified_startup', 'elapsedMs': 317}
        trace = {'outcome': 'ready', 'elapsedMs': 1500, 'strictSampleMs': 500, 'strictSamples': 2,
                 'waitCalls': 1, 'samples': [initial, {'state': 'ready', 'elapsedMs': 1500}]}
        self.assertEqual(ios.public_home_readiness(trace, self.value()), trace)
        unresolved = {**trace, 'outcome': 'unexpected',
                      'samples': [initial, {'state': 'unexpected', 'elapsedMs': 1500}]}
        unknown = {**self.value(), 'knownEmptyHome': False, 'inputCount': 1}
        with tempfile.TemporaryDirectory() as directory:
            state = self.state_for_navigation(directory)
            state.accept({'stage': 'native_home', 'nativeCheckpoint': 'ordinary_open_add',
                          'home': unknown, 'readiness': unresolved})
            with self.assertRaisesRegex(ios.Failure, 'home_retry_unsafe'):
                self.replay_official_header(state)
            self.assertNotIn('navigationTrace', state.result)
        for samples in ([initial], [initial, initial], [{'state': 'shell', 'elapsedMs': 1}, initial]):
            with self.subTest(samples=samples), self.assertRaisesRegex(ios.Failure, 'home_diagnostic_invalid'):
                ios.public_home_readiness({**trace, 'samples': samples}, self.value())

    def test_cold_start_observations_do_not_open_pages_or_advance_the_fixture(self):
        ready = {'outcome': 'ready', 'elapsedMs': 44250, 'strictSampleMs': 42250, 'strictSamples': 2,
                 'waitCalls': 1, 'samples': [{'state': 'loading', 'elapsedMs': 42000}, {'state':'ready', 'elapsedMs':44250}]}
        for phase, scenario, next_stage in (('ordinary_open_add', 'ordinary', 'ordinary_probe'),
                                              ('key_change_open_add', 'keyChange', 'key_change_probe_a')):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                state = ios.Checkpoints(None, None, directory, {})
                state.index = ios.STAGES.index(next_stage)
                event = {'stage':'native_home', 'nativeCheckpoint':phase, 'home':self.value(), 'readiness':ready}
                state.accept(event)
                self.assertEqual(state.result['homeReadiness'], {scenario: ready})
                self.assertEqual(state.index, ios.STAGES.index(next_stage))
                self.assertNotIn('navigationTrace', state.result)
                with self.assertRaisesRegex(ios.Failure, 'home_diagnostic_phase_invalid'):
                    state.accept(event)
        loading = self.value()
        loading['knownEmptyHome'] = False
        loading['knownErrors']['loading'] = True
        for name in ('emptyHeading', 'zeroHosts'):
            loading['members'][name] = {'count':0, 'roles':[]}
        timed_out = {'outcome': 'loading', 'elapsedMs': 35100, 'strictSampleMs': 100, 'strictSamples': 10,
                     'waitCalls': 9, 'samples': [{'state':'loading', 'elapsedMs': 10}]}
        with tempfile.TemporaryDirectory() as directory:
            state = self.state_for_navigation(directory)
            state.accept({'stage':'native_home', 'nativeCheckpoint':'ordinary_open_add', 'home': loading, 'readiness': timed_out})
            self.assertEqual(state.result['homeReadiness']['ordinary'], timed_out)
            with self.assertRaisesRegex(ios.Failure, 'home_retry_unsafe'):
                self.replay_official_header(state)
            self.assertNotIn('navigationTrace', state.result)

    def test_cold_start_rejects_impossible_or_private_evidence(self):
        base = {'outcome':'ready', 'elapsedMs':4200, 'strictSampleMs':400, 'strictSamples':2, 'waitCalls':1,
                'samples':[{'state':'loading', 'elapsedMs':200}, {'state':'ready', 'elapsedMs':4200}]}
        invalid_samples = [[], [{'state':'unknown','elapsedMs':100}],
                           [{'state':'ready','elapsedMs':100}, {'state':'ready','elapsedMs':200}],
                           [{'state':'loading','elapsedMs':4000}, {'state':'ready','elapsedMs':10}],
                           [{'state':'ready','elapsedMs':100, 'label':'PRIVATE'}]]
        changes = [{'samples':samples} for samples in invalid_samples]
        changes += [{'strictSamples':13}, {'elapsedMs':-1}, {'waitCalls':2}, {'strictSampleMs':4201},
                    {'outcome':'error'}, {'credentials':'PRIVATE'}]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                state = self.state_for_navigation(directory)
                with self.assertRaisesRegex(ios.Failure, 'home_diagnostic_invalid'):
                    state.accept({'stage':'native_home', 'nativeCheckpoint':'ordinary_open_add', 'home':self.value(),
                                  'readiness':{**base, **change}})
                self.assertNotIn('PRIVATE', json.dumps(state.result))
                self.assertFalse(state.result.get('homeReadiness'))
        for home_change in ({'knownEmptyHome':False}, {'webViewCount':0}, {'appAlertCount':1},
                            {'knownErrors':{key:key == 'loading' for key in ios.HOME_ERRORS}}):
            home = {**self.value(), **home_change}
            with self.subTest(home_change=home_change), self.assertRaisesRegex(ios.Failure, 'home_diagnostic_invalid'):
                ios.public_home_readiness(base, home)

    def test_repeated_home_sampling_retains_latest_without_navigation_or_ssh_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.state_for_navigation(directory)
            initial = self.value()
            state.accept({'stage': 'native_home', 'nativeCheckpoint': 'ordinary_open_add', 'home': initial})
            latest = self.value()
            latest.update(windowCount=2, webViewCount=3, unknownVisibleTextCount=4)
            latest['members']['headerAdd'] = {'count': 0, 'roles': []}
            for _ in range(2):
                state.accept({'stage': 'native_home', 'nativeCheckpoint': 'ordinary_open_add', 'home': latest})
            self.assertEqual(state.result['homeDiagnostics']['ordinary'], latest)
            self.assertNotIn('navigationTrace', state.result)
            self.assertEqual(state.index, ios.STAGES.index('ordinary_probe'))
            self.assertIsNone(state.failure)
            self.assertEqual(list(Path(directory).iterdir()), [])
            state.index += 1
            with self.assertRaisesRegex(ios.Failure, 'home_diagnostic_phase_invalid'):
                state.accept({'stage': 'native_home', 'nativeCheckpoint': 'ordinary_open_add', 'home': latest})

    def official_r4_record(self):
        return json.loads((ios.HERE / 'testdata/tauri-ios-r4-header-add.json').read_text())['record']

    def state_for_navigation(self, directory, ordinary=None):
        state = ios.Checkpoints(ordinary, None, directory, {'artifacts': {}})
        state.index = ios.STAGES.index('ordinary_probe')
        return state

    def replay_official_header(self, state):
        # Only this row is official evidence. Subsequent synthetic unit states
        # are explicitly separate and are never appended to the evidence file.
        record = self.official_r4_record()
        state.accept({'stage': 'native_navigation', 'nativeCheckpoint': 'ordinary_open_add', **record})
        return record

    def test_first_navigation_binding_is_geometry_only_and_bounded(self):
        binding = {'witnessFrame': [17, 166, 163, 22], 'liveFrame': [17, 166, 163, 22],
                   'ownerFrame': [17, 166, 163, 22], 'windowFrame': [0, 0, 440, 956],
                   'webFrames': [[0, 0, 440, 956]]}
        with tempfile.TemporaryDirectory() as directory:
            state = self.state_for_navigation(directory)
            row = self.navigation('emptyAdd', 'emptyHome', 'emptyHome')
            row['binding'] = binding
            state.accept(row)
            self.assertEqual(state.result['navigationTrace']['ordinary'][0]['binding'], binding)
        for bad in (binding | {'text': 'secret'}, binding | {'webFrames': [[0, 0, 1, 1]] * 9},
                    binding | {'witnessFrame': [0, 0, 'secret', 2]}):
            with tempfile.TemporaryDirectory() as directory:
                state = self.state_for_navigation(directory)
                with self.assertRaisesRegex(ios.Failure, 'navigation_diagnostic_invalid'):
                    state.accept(self.navigation('emptyAdd', 'emptyHome', 'emptyHome') | {'binding': bad})

    def test_official_r4_one_to_two_window_record_is_preserved_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.state_for_navigation(directory)
            record = self.replay_official_header(state)
            self.assertEqual(state.result['navigationTrace']['ordinary'], [record])
            self.assertEqual(record['before']['windowCount'], 1)
            self.assertEqual(record['after']['windowCount'], 2)
            self.assertEqual(record['after']['page'], 'addChoice')
            self.assertEqual(record['geometry']['frame'], [334,78,91,44])

    def test_synthetic_one_two_three_window_layers_allow_owned_form_but_reject_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.state_for_navigation(directory)
            first = self.navigation('headerAdd', 'emptyHome', 'addChoice')
            first['after']['windowCount'] = 2
            state.accept(first)
            second = self.navigation('sshChoice', 'addChoice', 'sshForm')
            second['nativeCheckpoint'] = 'ordinary_open_ssh'
            second['before']['windowCount'] = 2
            second['after'].update(windowCount=3, formOwnerResolved=True)
            state.accept(second)
            state.accept({'stage':'native_home_entry', 'nativeCheckpoint':'ordinary_open_ssh', 'member':'headerAdd',
                          'selection':'buttonRole', 'role':'button', 'enteredAddPage':True,
                          'enteredSSHForm':True, 'route':'viaAdd'})
            self.assertEqual(state.result['navigationTrace']['ordinary'][-1]['after']['windowCount'], 3)
            with self.assertRaisesRegex(ios.Failure, 'replay'):
                state.accept(second)

    def test_current_form_observation_does_not_fabricate_a_click_or_historical_source_page(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.state_for_navigation(directory)
            official = self.replay_official_header(state)
            # This is a synthetic new observation, not an inferred official R4
            # second row. It preserves the sampled sshForm page verbatim.
            current = self.navigation_state('sshForm')
            current.update(windowCount=2, formOwnerResolved=True)
            state.accept({'stage':'native_navigation_arrival', 'nativeCheckpoint':'ordinary_open_ssh',
                          'source':'currentFormObservation', 'performed':False, 'state':current,
                          'geometry':self.navigation('sshChoice','addChoice','sshForm')['geometry']})
            self.assertEqual(state.result['navigationTrace']['ordinary'], [official])
            arrival = state.result['navigationArrivals']['ordinary']
            self.assertEqual(arrival['state'], current)
            self.assertFalse(arrival['performed'])
            state.accept({'stage':'native_home_entry', 'nativeCheckpoint':'ordinary_open_ssh', 'member':'headerAdd',
                          'selection':'buttonRole', 'role':'button', 'enteredAddPage':True,
                          'enteredSSHForm':True, 'route':'viaAdd'})

    def test_multi_window_does_not_allow_unknown_owner_alerts_or_navigation_after_ssh(self):
        for changed in ({'formOwnerResolved':False}, {'noAlerts':False}, {'appForeground':False}):
            with tempfile.TemporaryDirectory() as directory:
                state = self.state_for_navigation(directory)
                self.replay_official_header(state)
                current = self.navigation_state('sshForm')
                current.update({'windowCount':3, 'formOwnerResolved':True, **changed})
                with self.assertRaises(ios.Failure):
                    state.accept({'stage':'native_navigation_arrival','nativeCheckpoint':'ordinary_open_ssh',
                                  'source':'currentFormObservation','performed':False,'state':current,
                                  'geometry':self.navigation('sshChoice','addChoice','sshForm')['geometry']})
        with tempfile.TemporaryDirectory() as directory:
            from types import SimpleNamespace
            state = self.state_for_navigation(directory, SimpleNamespace(snapshot=lambda:{'connections':1}))
            with self.assertRaisesRegex(ios.Failure, 'navigation_after_ssh'):
                self.replay_official_header(state)
    def value(self):
        return {'appForeground': True, 'webViewCount': 1, 'windowCount': 1,
                'members': {k: {'count': 1, 'roles': ['button' if k in ('headerAdd', 'emptyAdd') else 'staticText']}
                            for k in ios.HOME_MEMBERS},
                'knownErrors': {k: False for k in ios.HOME_ERRORS},
                'appAlertCount': 0, 'systemAlertCount': 0,
                'alertMembers': {k: False for k in ios.HOME_ALERT_MEMBERS},
                'alertSnapshotFailed': False, 'inputCount': 0, 'unknownVisibleTextCount': 0,
                'knownEmptyHome': True}

    def test_only_fixed_members_roles_counts_and_flags_are_public(self):
        value = self.value()
        public = ios.public_home_diagnostic(value)
        self.assertEqual(public, value)
        value['members']['brand']['count'] = 200
        self.assertEqual(public['members']['brand']['count'], 1)
        for mutation in ({'rawTree': 'PRIVATE'}, {'pngBase64': 'PRIVATE'}, {'appForeground': 'PRIVATE'},
                         {'webViewCount': -1}, {'knownErrors': {'PRIVATE': True}}):
            with self.assertRaises(ios.Failure):
                ios.public_home_diagnostic({**self.value(), **mutation})
        for mutation in ({'count': 1, 'roles': ['PRIVATE']}, {'count': 1, 'roles': ['button'], 'label': 'PRIVATE'}):
            value = self.value(); value['members']['headerAdd'] = mutation
            with self.assertRaises(ios.Failure):
                ios.public_home_diagnostic(value)

    def navigation_state(self, page):
        state = {'page': page, 'appForeground': True, 'inputCount': 3 if page == 'sshForm' else 0,
                 'windowCount': 1, 'webViewCount': 3, 'noAlerts': True, 'noKnownErrors': True,
                 'emptyHomeIdentity': page == 'emptyHome', 'formByStructure': page == 'sshForm',
                 'formOwnerResolved': page == 'sshForm',
                 'sshTitleSeen': page == 'sshForm', 'addTitleSeen': page == 'addChoice', 'credentialsEmpty': True}
        if page == 'sshForm':
            state['formControls'] = self.form_controls()
        else:
            state['formControls'] = {name: {'role': 'none', 'matches': 0, 'owner': False,
                                            'reason': 'missing'}
                                     for name in ios.FORM_CONTROL_NAMES}
        return state

    def form_controls(self, **overrides):
        controls = {'host': {'role': 'textField', 'matches': 1, 'owner': True, 'reason': 'matched'},
                    'port': {'role': 'textField', 'matches': 1, 'owner': True, 'reason': 'matched'},
                    'user': {'role': 'textField', 'matches': 1, 'owner': True, 'reason': 'matched'},
                    'probe': {'role': 'button', 'matches': 1, 'owner': True, 'reason': 'matched'}}
        controls.update(overrides)
        return controls

    def navigation(self, member, before, after, performed=True):
        return {'stage':'native_navigation', 'nativeCheckpoint':'ordinary_open_add', 'member':member,
                'selection':'uniqueIdentifier', 'method':'elementCenter', 'performed':performed,
                'targetPresentAfter':False, 'afterGeometry':None, 'elapsedMs':200,
                'geometry': {'frame':[20,100,200,44], 'visibleFrame':[0,62,440,850], 'screenFrame':[0,0,440,956],
                             'statusBarFrames':[[0,0,440,62]], 'role':'other', 'enabled':True, 'hittable':True,
                             'ownerResolved':True, 'centerVisible':True, 'fullyVisible':True},
                'before':self.navigation_state(before), 'after':self.navigation_state(after),
                'outcome':('blocked' if not performed else {'emptyHome':'noProgress','addChoice':'addChoice','sshForm':'sshForm','unexpected':'unexpected'}[after])}

    def test_navigation_retries_only_after_proven_empty_home_and_records_original_role(self):
        with tempfile.TemporaryDirectory() as directory:
            result = {'artifacts': {}}
            state = ios.Checkpoints(None,None,directory,result);state.index=ios.STAGES.index('ordinary_probe')
            state.accept(self.navigation('headerAdd','emptyHome','emptyHome'))
            state.accept(self.navigation('emptyAdd','emptyHome','addChoice'))
            state.accept(self.navigation('sshChoice','addChoice','sshForm'))
            state.accept({'stage':'native_home_entry','nativeCheckpoint':'ordinary_open_ssh','member':'emptyAdd',
                          'selection':'uniqueIdentifier','role':'other','enteredAddPage':True,'enteredSSHForm':True,'route':'viaAdd'})
            self.assertEqual(result['homeEntry']['ordinary']['role'],'other')
            self.assertEqual(len(result['navigationTrace']['ordinary']),3)
            self.assertEqual(list(Path(directory).iterdir()),[])
            self.assertEqual(state.index,ios.STAGES.index('ordinary_probe'))

    def test_real_home_ssh_shortcut_needs_structural_form_and_no_title_assumption(self):
        with tempfile.TemporaryDirectory() as directory:
            state=ios.Checkpoints(None,None,directory,{'artifacts':{}});state.index=ios.STAGES.index('ordinary_probe')
            value=self.navigation('ordinaryShortcut','emptyHome','sshForm');value['after']['sshTitleSeen']=False
            state.accept(value)
            state.accept({'stage':'native_home_entry','nativeCheckpoint':'ordinary_open_add','member':'ordinaryShortcut',
                          'selection':'buttonRole','role':'button','enteredAddPage':False,'enteredSSHForm':True,'route':'directSSH'})
            self.assertEqual(state.result['homeEntry']['ordinary']['route'],'directSSH')

    def test_navigation_rejects_replayed_target_unknown_page_unsafe_center_and_raw_data(self):
        changes=[{'method':'guessedCoordinate'}, {'after':{**self.navigation_state('emptyHome'),'credentialsEmpty':False}},
                 {'geometry':{**self.navigation('headerAdd','emptyHome','emptyHome')['geometry'],'centerVisible':False}},
                 {'before':{**self.navigation_state('emptyHome'),'rawTree':'PRIVATE'}}]
        for change in changes:
            with tempfile.TemporaryDirectory() as directory:
                state=ios.Checkpoints(None,None,directory,{'artifacts':{}});state.index=ios.STAGES.index('ordinary_probe')
                with self.assertRaises(ios.Failure):state.accept({**self.navigation('headerAdd','emptyHome','emptyHome'),**change})
                self.assertNotIn('PRIVATE',json.dumps(state.result))

    def test_form_controls_whitelist_accepts_current_diagnostics_and_old_records(self):
        # Current driver record: sshForm proven with per-control evidence.
        state = self.navigation_state('sshForm')
        self.assertEqual(set(state['formControls']), set(ios.FORM_CONTROL_NAMES))
        self.assertEqual(state['formControls']['host'],
                         {'role': 'textField', 'matches': 1, 'owner': True, 'reason': 'matched'})
        # Ambiguity is reportable without claiming a target.
        off_form = self.navigation_state('unexpected')
        ambiguous = {name: {'role': 'none', 'matches': 0, 'owner': False, 'reason': 'missing'}
                     for name in ios.FORM_CONTROL_NAMES}
        ambiguous['port'] = {'role': 'none', 'matches': 2, 'owner': False, 'reason': 'ambiguous'}
        ios.public_navigation_state({**off_form, 'formControls': ambiguous})
        # One identity with several editable descendants keeps its role.
        wrong = dict(ambiguous)
        wrong['user'] = {'role': 'other', 'matches': 1, 'owner': False, 'reason': 'wrongRole'}
        ios.public_navigation_state({**off_form, 'formControls': wrong})
        # A matched control whose owner could not be resolved.
        unproven = dict(ambiguous)
        unproven['host'] = {'role': 'textField', 'matches': 1, 'owner': False, 'reason': 'ownerUnproven'}
        ios.public_navigation_state({**off_form, 'formControls': unproven})
        # Legacy R6 records carry no formControls at all and still replay.
        legacy = {k: v for k, v in state.items() if k != 'formControls'}
        self.assertEqual(ios.public_navigation_state(legacy)['page'], 'sshForm')

    def test_form_controls_keep_partial_and_uncommon_owner_evidence(self):
        # Three controls resolved, the port identity failed: the page is not
        # the proven form, so the partial evidence must survive verbatim.
        partial = self.navigation_state('unexpected')
        partial['formControls'] = self.form_controls(
            port={'role': 'none', 'matches': 0, 'owner': False, 'reason': 'missing'})
        saved = ios.public_navigation_state(partial)
        self.assertEqual(saved['formControls']['host']['reason'], 'matched')
        self.assertEqual(saved['formControls']['port']['reason'], 'missing')
        # All four controls own an owner but the common window is not proven:
        # formOwnerResolved is false, so the page stays unproven while the
        # per-control owners are still reported.
        split = self.navigation_state('unexpected')
        split['formByStructure'] = False
        split['formOwnerResolved'] = False
        split['formControls'] = self.form_controls()
        saved = ios.public_navigation_state(split)
        self.assertFalse(saved['formOwnerResolved'])
        self.assertTrue(all(item['owner'] for item in saved['formControls'].values()))

    def test_form_controls_reject_structural_and_privacy_violations(self):
        base = self.navigation_state('sshForm')
        bad_records = [
            # Extra key carrying a raw label or URL must not survive.
            {**base, 'formControls': {**self.form_controls(),
                                      'host': {'role': 'textField', 'matches': 1, 'owner': True,
                                               'reason': 'matched', 'label': 'PRIVATE ssh-host'}}},
            # Unknown name smuggles another control into the public record.
            {**base, 'formControls': {**self.form_controls(),
                                      'extra': {'role': 'button', 'matches': 1, 'owner': True, 'reason': 'matched'}}},
            # matched without a proven owner is fabrication.
            {**base, 'formControls': self.form_controls(
                host={'role': 'textField', 'matches': 1, 'owner': False, 'reason': 'matched'})},
            # ownerUnproven that still claims an owner.
            {**base, 'formControls': self.form_controls(
                port={'role': 'textField', 'matches': 1, 'owner': True, 'reason': 'ownerUnproven'})},
            # role none cannot be matched or wrongRole.
            {**base, 'formControls': self.form_controls(
                user={'role': 'none', 'matches': 1, 'owner': True, 'reason': 'matched'})},
            {**base, 'formControls': self.form_controls(
                user={'role': 'none', 'matches': 1, 'owner': False, 'reason': 'wrongRole'})},
            # Static text is not an editable target on the sshForm page.
            {**base, 'formControls': self.form_controls(
                host={'role': 'other', 'matches': 1, 'owner': True, 'reason': 'matched'})},
            # A plain-text probe button claim.
            {**base, 'formControls': self.form_controls(
                probe={'role': 'other', 'matches': 1, 'owner': True, 'reason': 'matched'})},
            # Unbounded / non-integer match counts.
            {**base, 'formControls': self.form_controls(
                host={'role': 'textField', 'matches': 10001, 'owner': True, 'reason': 'matched'})},
            {**base, 'formControls': self.form_controls(
                host={'role': 'textField', 'matches': -1, 'owner': True, 'reason': 'matched'})},
            {**base, 'formControls': self.form_controls(
                host={'role': 'textField', 'matches': '1', 'owner': True, 'reason': 'matched'})},
            # A matched control must have found at least one identity.
            {**base, 'formControls': self.form_controls(
                host={'role': 'textField', 'matches': 0, 'owner': True, 'reason': 'matched'})},
            # A missing control must not carry a match count or a role.
            {**base, 'formControls': self.form_controls(
                host={'role': 'none', 'matches': 1, 'owner': False, 'reason': 'missing'})},
            # An ambiguous identity needs at least one candidate.
            {**base, 'formControls': self.form_controls(
                host={'role': 'none', 'matches': 0, 'owner': False, 'reason': 'ambiguous'})},
            # Ambiguity always collapses to no role.
            {**base, 'formControls': self.form_controls(
                host={'role': 'textField', 'matches': 2, 'owner': False, 'reason': 'ambiguous'})},
            # The three inputs are never a button and the probe is never an input.
            {**base, 'formControls': self.form_controls(
                host={'role': 'button', 'matches': 1, 'owner': True, 'reason': 'matched'})},
            {**base, 'formControls': self.form_controls(
                probe={'role': 'textField', 'matches': 1, 'owner': True, 'reason': 'matched'})},
            # The host and user are never a wrapper; only the port can be.
            {**base, 'formControls': self.form_controls(
                user={'role': 'inputWrapper', 'matches': 1, 'owner': True, 'reason': 'matched'})},
            # Unknown enums and a raw value string must all fail.
            {**base, 'formControls': self.form_controls(
                host={'role': 'secureTextField', 'matches': 1, 'owner': True, 'reason': 'matched'})},
            {**base, 'formControls': self.form_controls(
                host={'role': 'textField', 'matches': 1, 'owner': True, 'reason': 'guessed'})},
            # Non-string enum members must fail with the fixed diagnostic code.
            {**base, 'formControls': self.form_controls(
                host={'role': ['textField'], 'matches': 1, 'owner': True, 'reason': 'matched'})},
            {**base, 'formControls': self.form_controls(
                host={'role': 'textField', 'matches': 1, 'owner': True, 'reason': {'matched': True}})},
            # The sshForm page needs all four controls matched.
            {**base, 'formControls': self.form_controls(
                port={'role': 'none', 'matches': 0, 'owner': False, 'reason': 'missing'})},
            {**base, 'formControls': {name: {'role': 'none', 'matches': 0, 'owner': False, 'reason': 'missing'}
                                      for name in ios.FORM_CONTROL_NAMES}},
        ]
        for record in bad_records:
            with self.assertRaises(ios.Failure):
                ios.public_navigation_state(record)

    def test_form_controls_checkpoint_flow_saves_diagnostics_and_keeps_privacy(self):
        with tempfile.TemporaryDirectory() as directory:
            result = {'artifacts': {}}
            state = ios.Checkpoints(None, None, directory, result)
            state.index = ios.STAGES.index('ordinary_probe')
            state.accept(self.navigation('headerAdd', 'emptyHome', 'emptyHome'))
            state.accept(self.navigation('emptyAdd', 'emptyHome', 'addChoice'))
            state.accept(self.navigation('sshChoice', 'addChoice', 'sshForm'))
            state.accept({'stage': 'native_home_entry', 'nativeCheckpoint': 'ordinary_open_ssh',
                          'member': 'emptyAdd', 'selection': 'uniqueIdentifier', 'role': 'other',
                          'enteredAddPage': True, 'enteredSSHForm': True, 'route': 'viaAdd'})
            saved = result['navigationTrace']['ordinary'][-1]['after']['formControls']
            self.assertEqual(set(saved), set(ios.FORM_CONTROL_NAMES))
            self.assertTrue(all(item['reason'] == 'matched' and item['owner'] for item in saved.values()))
            # The raw tree never reaches the persisted record.
            self.assertNotIn('PRIVATE', json.dumps(result))
        with tempfile.TemporaryDirectory() as directory:
            state=ios.Checkpoints(None,None,directory,{'artifacts':{}});state.index=ios.STAGES.index('ordinary_probe')
            state.accept(self.navigation('headerAdd','emptyHome','emptyHome'))
            with self.assertRaisesRegex(ios.Failure,'replay'):state.accept(self.navigation('headerAdd','emptyHome','emptyHome'))
            state.accept(self.navigation('emptyAdd','emptyHome','unexpected'))
            with self.assertRaises(ios.Failure):state.accept(self.navigation('ordinaryShortcut','emptyHome','sshForm'))


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), 'real Foundation/CoreGraphics Swift precheck requires macOS swiftc')
class NativeFramePolicyTests(unittest.TestCase):
    def test_real_production_geometry_handles_nested_wrappers_leaf_text_and_conflicts(self):
        source=(ios.HERE/'tauri_ios_direct_ssh.swift').read_text()
        policy=source[source.index('enum NativeFramePolicy {'):source.index('// END NATIVE FRAME POLICY')]
        program = r'''import Foundation
import CoreGraphics
func check(_ value: Bool) { if !value { fatalError("native geometry regression") } }
let screen = CGRect(x:0,y:0,width:440,height:956)
let inner = CGRect(x:0,y:59,width:440,height:897)
let visible = NativeFramePolicy.visible(window:screen,screen:screen,webAncestors:[screen,screen,inner],
    occlusions:[CGRect(x:0,y:0,width:440,height:62),CGRect(x:0,y:656,width:440,height:300)])!
check(visible == CGRect(x:0,y:62,width:440,height:594))
let statusBar = CGRect(x: 0, y: 0, width: 440, height: 62)
let docked = CGRect(x: 0, y: 656, width: 440, height: 266)
check(NativeFramePolicy.visible(window: screen, screen: screen, webAncestors: [inner],
                               occlusions: [statusBar, docked]) == nil)
func active(_ keyboards: [CGRect], web: CGRect = inner, bars: [CGRect] = [statusBar], shown: Bool = true)
                -> NativeFramePolicy.ActiveViewport {
    NativeFramePolicy.activeViewport(window: screen, screen: screen, webAncestors: [web],
                                    statusBars: bars, keyboardPresent: shown, keyboardFrames: keyboards)
}
check(active([docked, docked]).visible == visible)
check(active([docked], web: CGRect(x: 0, y: 59, width: 440, height: 590)).visible?.maxY == 649)
check(active([docked], web: CGRect(x: 0, y: 680, width: 440, height: 240)).reason == "keyboard_covers_viewport")
check(active([docked, docked.offsetBy(dx: 0, dy: 1)]).reason == "keyboard_frame_unproven")
check(active([docked], bars: [CGRect(x: 0, y: 120, width: 440, height: 62)]).reason == "status_bar_viewport_invalid")
check(active([docked], shown: false).reason == "keyboard_state_changed")
check(NativeFramePolicy.unique([screen,screen,inner]).count == 2)
check(NativeFramePolicy.visible(window:screen,screen:screen,webAncestors:[],occlusions:[]) == nil)
let parent=CGRect(x:10,y:100,width:420,height:100), leaf=CGRect(x:20,y:120,width:400,height:40)
check(NativeFramePolicy.semanticIndex(frames:[parent,leaf],preferred:[1],visible:visible,clippedControl:false) == 1)
check(NativeFramePolicy.semanticIndex(frames:[leaf,leaf],preferred:[1],visible:visible,clippedControl:false) == 1)
check(NativeFramePolicy.semanticIndex(frames:[leaf,CGRect(x:220,y:150,width:180,height:40)],preferred:[0],visible:visible,clippedControl:false) == nil)
check(NativeFramePolicy.semanticIndex(frames:[CGRect(x:20,y:40,width:400,height:40)],preferred:[0],visible:visible,clippedControl:false) == nil)
check(NativeFramePolicy.semanticIndex(frames:[CGRect(x:20,y:180,width:400,height:600)],preferred:[0],visible:visible,clippedControl:true) == 0)
check(NativeFramePolicy.sameOwner(windowPaths:[[0],[0]],webPaths:[[0,1,2],[0,1,2]]))
check(!NativeFramePolicy.sameOwner(windowPaths:[[0],[1]],webPaths:[[0,1],[1,1]]))
check(!NativeFramePolicy.sameOwner(windowPaths:[[0],[0]],webPaths:[[0,1],[0,2]]))
// An active owner may be under the second or third window; total count is not identity.
check(NativeFramePolicy.sameOwner(windowPaths:[[2],[2],[2],[2]],webPaths:[[2,0,0],[2,0,0],[2,0,0],[2,0,0]]))
check(NativeFramePolicy.compatibleOwner(windowPaths:[[2],[2]],webPaths:[[],[2,0,0]],nodePaths:[[2,0],[2,0,0,1]],selected:1))
check(!NativeFramePolicy.compatibleOwner(windowPaths:[[0],[2]],webPaths:[[0,0],[2,0]],nodePaths:[[0,0,1],[2,0,1]],selected:1))
check(!NativeFramePolicy.compatibleOwner(windowPaths:[[2],[2]],webPaths:[[2,0],[2,1]],nodePaths:[[2,0,1],[2,1,1]],selected:1))
check(!NativeViewPolicy.reached(member:"sshChoice",page:"addChoice"))
check(["addChoice","addChoice","sshForm"].firstIndex { NativeViewPolicy.reached(member:"sshChoice",page:$0) } == 2)
check(NativeViewPolicy.reached(member:"headerAdd",page:"addChoice"))
check(!NativeViewPolicy.unsafeCredential(nonempty:false,enabled:false,hittable:false,visible:false))
check(NativeViewPolicy.unsafeCredential(nonempty:false,enabled:false,hittable:true,visible:true))
check(NativeViewPolicy.unsafeCredential(nonempty:true,enabled:false,hittable:false,visible:false))
check(NativeViewPolicy.unsafeCredential(nonempty:false,enabled:true,hittable:true,visible:false))
check(NativeViewPolicy.scope(window:[2],web:[2,0],currentWindow:[2],currentWeb:[2,0,1]) == .current)
check(NativeViewPolicy.scope(window:[0],web:[0,0],currentWindow:[2],currentWeb:[2,0]) == .otherWindow)
check(NativeViewPolicy.scope(window:[2],web:[],currentWindow:[2],currentWeb:[2,0]) == .nativeSystem)
check(NativeViewPolicy.scope(window:[2],web:[2,1],currentWindow:[2],currentWeb:[2,0]) == .ambiguous)
let decisions: Set<String> = ["recheck","cancel"]
let actionFrame = CGRect(x:20,y:200,width:200,height:44)
let currentActions = [NativeViewPolicy.Action(scope:.current,label:"recheck",frame:actionFrame,enabled:true,hittable:true),
                     NativeViewPolicy.Action(scope:.current,label:"cancel",frame:actionFrame.offsetBy(dx:0,dy:60),enabled:true,hittable:true)]
let unrelated = [NativeViewPolicy.Action(scope:.nativeSystem,label:"keyboard",frame:actionFrame,enabled:true,hittable:true),
                 NativeViewPolicy.Action(scope:.otherWindow,label:"other",frame:actionFrame,enabled:true,hittable:true),
                 NativeViewPolicy.Action(scope:.current,label:"hidden",frame:actionFrame,enabled:false,hittable:false)]
check(NativeViewPolicy.reviewValid(currentActions + unrelated,expected:decisions,visible:visible))
check(!NativeViewPolicy.reviewValid(currentActions + [NativeViewPolicy.Action(scope:.current,label:"escape",frame:actionFrame,enabled:true,hittable:true)],expected:decisions,visible:visible))
print("native geometry cases passed")
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'Policy.swift').write_text('import Foundation\nimport CoreGraphics\n'+policy)
            (root/'main.swift').write_text(program)
            build=subprocess.run(['swiftc','-swift-version','5',str(root/'Policy.swift'),str(root/'main.swift'),'-o',str(root/'geometry')],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(root/'geometry')],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertIn('native geometry cases passed',run.stdout)


class NativeDiagnosticPublishingTests(unittest.TestCase):
    def test_active_geometry_failure_publishes_only_fixed_phase_and_bounded_shapes(self):
        from ios_direct_ssh_batch import publish_evidence
        phase = 'ordinary_active_flow'
        detail = {'context': 'keyboard_open_after', 'page': 'terminal', 'reason': 'keyboard_frame_unproven',
                  'keyboardVisible': True, 'screen': [0, 0, 440, 956], 'viewport': [0, 59, 440, 897],
                  'visible': None, 'statusBars': [[0, 0, 440, 62]], 'keyboards': [[60, 646, 320, 276]],
                  'frames': [[372, 130, 44, 44]]}
        payload = {'stage': 'native_active_diagnostic', 'nativeCheckpoint': phase, 'detail': detail}
        sha = 'a' * 40
        with tempfile.TemporaryDirectory() as output:
            work = Path(output)
            def checkpoint(index='ordinary_input', native_phase=phase):
                report = {'status': 'failed', 'sourceSHA': sha, 'artifacts': {}}
                state = ios.Checkpoints(None, None, output, report)
                state.index = ios.STAGES.index(index)
                state.accept({'stage': 'native_progress', 'nativeCheckpoint': native_phase})
                return state, report

            state, report = checkpoint()
            state.accept(payload)
            with self.assertRaisesRegex(ios.Failure, 'active_diagnostic_invalid'):
                state.accept(payload)
            state.accept({'stage': 'native_failure', 'nativeCheckpoint': phase,
                          'nativeFailureCode': 'native_visible_frame_invalid'})
            self.assertEqual(report['activeDiagnostic'], {'nativeCheckpoint': phase, **detail})
            public = work / 'public'
            public.mkdir()
            ios.write_json(public / 'result.json', report)
            self.assertEqual(publish_evidence(public, work / 'verified', shell='tauri', source_sha=sha), {'result.json'})
            self.assertEqual(json.loads((work / 'verified/result.json').read_text()), report)

            for change in ({'text': 'synthetic secret'}, {'reason': 'synthetic secret'}, {'context': []},
                           {'page': 'network'}, {'keyboardVisible': 1}, {'screen': [0, 0, 440, True]},
                           {'viewport': [0, 0, 440, -1]}, {'keyboards': [[10001, 0, 440, 200]]},
                           {'frames': [{'rawLabel': 'synthetic secret'}]}, {'statusBars': [None] * 5}):
                with self.subTest(change=change), self.assertRaisesRegex(ios.Failure, 'active_diagnostic_invalid'):
                    checkpoint()[0].accept({**payload, 'detail': {**detail, **change}})
            for state, value in (
                (checkpoint(index='ordinary_password')[0], payload),
                (checkpoint(native_phase='ordinary_port')[0], {**payload, 'nativeCheckpoint': 'ordinary_port'}),
                (checkpoint()[0], {**payload, 'arbitrary': 'synthetic secret'}),
                (checkpoint()[0], {**payload, 'nativeCheckpoint': 'key_change_terminal_focus'}),
            ):
                with self.assertRaisesRegex(ios.Failure, 'active_diagnostic_invalid'):
                    state.accept(value)
                self.assertNotIn('activeDiagnostic', state.result)

    def test_password_observation_redacts_and_survives_ci_publication(self):
        from ios_direct_ssh_batch import publish_evidence
        raw = {'role': 'secureTextField', 'owner': 'sameWeb', 'idKind': 'empty', 'labelKind': 'spaced',
               'frameKind': 'inside', 'enabled': True, 'hit': 'unknown'}
        live = raw | {'hit': 'yes'}
        detail = {'rawCount': 1, 'raw': [raw], 'scopedSecureCount': 1, 'scopedSecure': [live]}
        payload = {'stage': 'native_failure', 'nativeCheckpoint': 'ordinary_fingerprint',
                   'nativeFailureCode': 'native_mobile_password_identity_missing', 'passwordObservation': detail}
        sha = 'a' * 40
        with tempfile.TemporaryDirectory() as output:
            work = Path(output)
            report = {'status': 'failed', 'sourceSHA': sha, 'artifacts': {}}
            ios.Checkpoints(None, None, output, report).accept(payload)
            self.assertEqual(report['passwordObservation'], detail)
            public = work / 'public'
            public.mkdir()
            ios.write_json(public / 'result.json', report)
            self.assertEqual(publish_evidence(public, work / 'verified', shell='tauri', source_sha=sha), {'result.json'})
            self.assertEqual(json.loads((work / 'verified/result.json').read_text()), report)

            explicit_leaks = ({'label': 'private-label'}, {'identifier': 'private-id'}, {'value': 'private-value'},
                              {'frame': [0, 0, 100, 100]}, {'placeholder': 'private-placeholder'})
            changes = [detail | {'raw': [raw | extra]} for extra in explicit_leaks]
            changes += [detail | {'text': 'private'}, detail | {'rawCount': True}, detail | {'raw': [raw] * 13, 'rawCount': 13},
                        detail | {'raw': [raw | {'labelKind': ['private']}]}, detail | {'raw': [raw | {'idKind': 'private'}]},
                        detail | {'scopedSecure': [live | {'owner': 'otherWindow'}]}, detail | {'scopedSecureCount': -1}]
            for changed in [payload | {'passwordObservation': change} for change in changes] + [
                    payload | {'nativeCheckpoint': 'ordinary_port'}, payload | {'stage': 'native_progress'},
                    payload | {'nativeFailureCode': 'native_control_disabled'}, payload | {'private': 'private'}]:
                state = ios.Checkpoints(None, None, output, {})
                with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
                    state.accept(changed)
                self.assertNotIn('passwordObservation', state.result)
                self.assertNotIn('private', json.dumps(state.result))

    def test_mobile_password_failure_codes_are_source_bound_and_export_nothing_else(self):
        source = (ios.HERE / 'tauri_ios_direct_ssh.swift').read_text()
        codes = source.split('enum MobilePasswordIssue:', 1)[1].split('var pending:', 1)[0]
        self.assertEqual(set(re.findall(r'"(native_mobile_password_[a-z_]+)"', codes)), ios.MOBILE_PASSWORD_FAILURES)
        with tempfile.TemporaryDirectory() as output:
            for phase in ios.MOBILE_PASSWORD_PHASES:
                for code in ios.MOBILE_PASSWORD_FAILURES:
                    payload = {'stage': 'native_failure', 'nativeCheckpoint': phase, 'nativeFailureCode': code}
                    fixture = object() if phase.startswith('encrypted_key_') else None
                    state = ios.Checkpoints(None, None, output, {}, encrypted=fixture)
                    state.accept(payload)
                    self.assertEqual(state.result, {'nativeCheckpoint': phase, 'nativeFailureCode': code})
            payload = {'stage': 'native_failure', 'nativeCheckpoint': 'ordinary_fingerprint',
                       'nativeFailureCode': 'native_mobile_password_frame_unsettled'}
            for changed in ({'nativeCheckpoint': 'ordinary_port'}, {'nativeFailureCode': payload['nativeFailureCode'] + ': private'},
                            {'nativeFailureCode': ['private']}, {'label': 'private'}, {'frame': [0, 0, 10, 10]}):
                state = ios.Checkpoints(None, None, output, {})
                with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
                    state.accept(payload | changed)
                self.assertNotIn('nativeFailureCode', state.result)
                self.assertNotIn('private', json.dumps(state.result))

    def test_swift_form_owner_and_geometry_failures_publish_through_real_http(self):
        source = (ios.HERE / 'tauri_ios_direct_ssh.swift').read_text()
        emitted = set(re.findall(r'\btry require\([\s\S]*?,\s*"(native_[a-z_]+)"\)', source))
        prefixes = ('native_form_', 'native_control_', 'native_scroll_', 'native_owner_',
                    'native_geometry_', 'native_window_', 'native_webview_', 'native_visible_',
                    'native_target_', 'native_screen_', 'native_capture_', 'native_terminal_')
        codes = sorted(code for code in emitted if code.startswith(prefixes))
        self.assertTrue({'native_form_control_changed', 'native_form_control_unproven',
                         'native_control_owner_unproven', 'native_terminal_header_unproven'} <= set(codes))
        with tempfile.TemporaryDirectory() as directory:
            state = ios.Checkpoints(None, None, directory, {})
            server, thread = ios.start_checkpoints(state)
            self.addCleanup(thread.join, 2)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            url = f'http://127.0.0.1:{server.server_port}/checkpoint'
            private = 'synthetic-user-data'
            for code in codes + ['native_control_unknown', private, codes[0] + ':' + private]:
                with self.subTest(code=code):
                    state.failure = None
                    state.result.clear()
                    payload = {'stage': 'native_failure', 'nativeCheckpoint': 'ordinary_port',
                               'nativeFailureCode': code}
                    request = Request(url, data=json.dumps(payload).encode(),
                                      headers={'Authorization': state.secret})
                    try:
                        response = urlopen(request, timeout=2)
                    except HTTPError as error:
                        response = error
                    with response:
                        self.assertEqual(response.code, 200 if code in codes else 409)
                        self.assertEqual(json.load(response), {'ok': code in codes})
                    if code in codes:
                        self.assertEqual(state.result, {'nativeCheckpoint': 'ordinary_port', 'nativeFailureCode': code})
                        self.assertEqual(state.failure, 'tauri_ios_native_check_failed')
                    else:
                        self.assertEqual(state.failure, 'tauri_ios_native_diagnostic_invalid')
                        self.assertNotIn('nativeFailureCode', state.result)
                    self.assertNotIn(private, json.dumps(state.result))


class FixtureReplyHandshakeTests(unittest.TestCase):
    def test_repeated_last_word_and_fragmented_reply_require_whole_sequence_and_new_output(self):
        from types import SimpleNamespace
        fixture = SimpleNamespace(screen_token='ARCH ARCH ARCH ARCH ARCH ARCH ARCH ARCH', echo_marker='ECHO')
        expected = b'\r\n\x1b[32mECHO\x1b[0m\r\nARCH ARCH ARCH ARCH\r\nARCH ARCH ARCH ARCH\r\n$ '
        class FragmentedChannel:
            chunks = [expected[:20], expected[20:40], expected[40:-2], expected[-2:]]
            def recv(self, _): return self.chunks.pop(0)
        channel = FragmentedChannel()
        def check_counter(_fixture, predicate, _code, timeout):
            self.assertFalse(predicate({'connectionEvents':[{'outputBytes': 100 + len(expected) - 1}]}))
            self.assertTrue(predicate({'connectionEvents':[{'outputBytes': 100 + len(expected)}]}))
        with patch.object(ios, 'wait_peer', side_effect=check_counter):
            RealLoopbackCheckpointsTests.wait_for_reply(self, fixture, channel, 100)
        self.assertFalse(channel.chunks)

    read_until = lambda self, channel, expected: RealLoopbackCheckpointsTests.read_until(self, channel, expected)


class RealLoopbackCheckpointsTests(unittest.TestCase):
    def setUp(self):
        logging.getLogger('paramiko').setLevel(logging.CRITICAL)
        deadline = time.monotonic() + 60
        self.ordinary = ios.SingleCommandFixture(screen_proof=True, channel_deadline=deadline).__enter__()
        self.rotation = ios.SingleCommandFixture(rotate_after_probe=True, screen_proof=True, channel_deadline=deadline).__enter__()
        self.addCleanup(self.ordinary.close)
        self.addCleanup(self.rotation.close)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.result = {'cases': {'ordinary': {}, 'keyChange': {}}, 'artifacts': {}}
        self.state = ios.Checkpoints(self.ordinary, self.rotation, self.directory.name, self.result)

    def probe(self, fixture):
        import paramiko
        count = fixture.snapshot()['connections'] + 1
        with paramiko.Transport(('127.0.0.1', fixture.port)) as peer:
            peer.start_client(timeout=5)
            key = peer.get_remote_server_key()
        # The client can close before the fixture publishes its server-side close.
        self.assertTrue(fixture.wait_for_connections_closed(count, timeout=5))
        self.assertEqual(fixture.snapshot()['connections'], count)
        return key

    def session(self, fixture, *, marker=True):
        import paramiko
        peer = paramiko.Transport(('127.0.0.1', fixture.port))
        self.addCleanup(peer.close)
        peer.start_client(timeout=5)
        peer.auth_password(fixture.username, fixture.password)
        channel = peer.open_session(timeout=5)
        channel.get_pty(term='xterm-256color', width=40, height=10)
        channel.invoke_shell()
        channel.settimeout(5)
        self.wait_for_initial_prompt(fixture, channel)
        if marker:
            before = fixture.snapshot()['connectionEvents'][-1]['outputBytes']
            channel.sendall((fixture.marker + '\r').encode())
            self.wait_for_reply(fixture, channel, before)
        return peer, channel

    def read_until(self, channel, expected):
        received = b''
        while expected not in received:
            chunk = channel.recv(4096)
            self.assertTrue(chunk, 'fixture closed before completing its reply')
            received += chunk
            self.assertLessEqual(len(received), 65536, 'unexpectedly long fixture reply')
        return received

    def wait_for_initial_prompt(self, fixture, channel):
        received = self.read_until(channel, b'$ ')
        ios.wait_peer(fixture, lambda f: f['connectionEvents'][-1]['outputBytes'] >= len(received),
                      'fixture_prompt_not_recorded', timeout=5)

    def wait_for_reply(self, fixture, channel, output_before):
        # Match all proof lines and the final prompt even when bytes are fragmented.
        proof = '\r\n'.join(token_lines(fixture.screen_token))
        expected = ('\r\n\x1b[32m' + fixture.echo_marker + '\x1b[0m\r\n' + proof + '\r\n$ ').encode()
        self.read_until(channel, expected)
        ios.wait_peer(fixture, lambda f: f['connectionEvents'][-1]['outputBytes'] >= output_before + len(expected),
                      'fixture_reply_not_recorded', timeout=5)

    def accept(self, stage):
        self.state.accept({'stage': stage})

    def close_protocol(self, fixture, peer, channel):
        count = fixture.snapshot()['connections']
        try:
            # The fixture ends the session on SSH EOF. Keep the client's
            # transport open until the fixture has published the peer close.
            channel.shutdown_write()
            self.assertTrue(fixture.wait_for_connections_closed(count, timeout=5),
                            'test SSH peer did not finish closing after channel EOF')
        finally:
            peer.close()

    def test_failure_peer_snapshot_distinguishes_open_from_fixture_cleanup(self):
        self.probe(self.rotation)
        self.assertTrue(self.rotation.wait_for_connections_closed(1,timeout=5))
        peer, channel = self.session(self.rotation, marker=False)
        before = ios.failure_peer_snapshot(self.rotation)
        self.assertFalse(before['connectionsClosed'])
        self.assertEqual(before['events'][-1]['authSuccesses'],1)
        self.assertFalse(before['events'][-1]['closed'])
        self.rotation.close()
        after = ios.failure_peer_snapshot(self.rotation)
        self.assertTrue(after['connectionsClosed'])
        self.assertTrue(after['events'][-1]['closed'])
        self.assertEqual(after['events'][-1]['closeReason'],'fixture_stopped')
        self.assertFalse(after['events'][-1]['sessionClosed'])
        self.assertNotIn(self.ordinary.password,json.dumps({'before':before,'after':after}))
        peer.close()

    def test_protocol_teardown_waits_for_peer_after_sending_channel_eof(self):
        self.probe(self.ordinary)
        peer, channel = self.session(self.ordinary)
        finishing = threading.Event()
        release = threading.Event()
        record = self.ordinary._connection_record
        wait_closed = self.ordinary.wait_for_connections_closed
        close_peer = peer.close

        def pause_before_close(transport, field, value=True):
            if field == 'closeReason':
                finishing.set()
                release.wait(5)
            record(transport, field, value)

        def release_after_channel_eof(minimum, timeout):
            self.assertTrue(finishing.wait(5), 'server did not observe channel EOF')
            release.set()
            return wait_closed(minimum, timeout)

        def check_final_cleanup():
            try:
                self.assertTrue(self.ordinary.snapshot()['connectionsClosed'],
                                'client closed its transport before the server could finish')
            finally:
                close_peer()

        with patch.object(self.ordinary, '_connection_record', side_effect=pause_before_close), \
                patch.object(self.ordinary, 'wait_for_connections_closed', side_effect=release_after_channel_eof), \
                patch.object(peer, 'close', side_effect=check_final_cleanup) as close:
            try:
                self.close_protocol(self.ordinary, peer, channel)
            finally:
                release.set()
            close.assert_called_once()
        self.assertTrue(self.ordinary.wait_for_connections_closed(2, timeout=5))
        ios.ordinary_evidence(self.ordinary, closed=True)
        self.assertEqual(self.ordinary.snapshot()['connectionEvents'][-1]['closeReason'], 'peer_eof')

    @staticmethod
    def active_step(step):
        action = {'frame': [15, 90, 90, 50], 'visibleFrame': [0, 54, 440, 600], 'screenFrame': [0, 0, 440, 956],
                  'statusBarFrames': [[0, 0, 440, 54]], 'role': 'button', 'enabled': True, 'hittable': True,
                  'ownerResolved': True, 'centerVisible': True, 'fullyVisible': True}
        return dict(stage='ordinary_active', step=step, keyboardVisible=step == 'keyboard_opened', action=action)

    def ordinary_ready(self):
        self.accept('ordinary_form')
        self.probe(self.ordinary)
        self.accept('ordinary_probe')
        self.accept('ordinary_password')
        self.state.accept({'stage': 'native_progress', 'nativeCheckpoint': 'ordinary_connect'})
        return self.session(self.ordinary, marker=False)

    def test_complete_native_checkpoint_order_against_real_aabb_and_abbb_peers(self):
        peer, channel = self.ordinary_ready()
        steps = ('keyboard_opened', 'keyboard_closed', 'board', 'terminal_from_board',
                 'network', 'terminal_from_network', 'settings', 'terminal_from_settings')
        for step in steps:
            self.state.accept(self.active_step(step))
        trace = self.result['cases']['ordinary']['activeFlow']
        self.assertEqual(tuple(step['step'] for step in trace), steps)
        expected_peer = {'id': 2, 'hostKey': 'A', 'authAttempts': 1, 'authSuccesses': 1, 'ptyRequests': 1,
                         'shellRequests': 1, 'inputBytes': 0, 'closed': False}
        self.assertTrue(all(step['peer'] == expected_peer for step in trace))
        before = self.ordinary.snapshot()['connectionEvents'][-1]['outputBytes']
        channel.sendall((self.ordinary.marker + '\r').encode())
        self.wait_for_reply(self.ordinary, channel, before)
        self.accept('ordinary_input')
        # Images in this protocol test are deliberately mocked, not device proof.
        with patch.object(self.state, 'capture'):
            self.accept('ordinary_terminal')
        self.accept('ordinary_disconnect_attempt')
        self.close_protocol(self.ordinary, peer, channel)
        self.accept('ordinary_disconnected')
        self.assertNotEqual(self.result['cases']['ordinary'].get('status'), 'passed')
        with self.assertRaisesRegex(ios.Failure, 'checkpoint_order_invalid'):
            self.accept('key_change_form')
        self.accept('ordinary_returned_home')
        self.accept('key_change_form')
        key_a = self.probe(self.rotation)
        self.accept('key_change_probe_a')
        self.accept('key_change_password_a')
        self.state.accept({'stage': 'native_progress', 'nativeCheckpoint': 'key_change_connect'})
        key_b = self.probe(self.rotation)
        self.assertNotEqual(key_a, key_b)
        with patch.object(self.state, 'capture'):
            self.accept('key_change_review')
        self.accept('key_change_cancelled')
        self.assertEqual(self.rotation.snapshot()['connections'], 2)
        self.assertEqual(self.probe(self.rotation), key_b)
        self.accept('key_change_probe_b')
        self.accept('key_change_password_b')
        self.state.accept({'stage': 'native_progress', 'nativeCheckpoint': 'key_change_connect'})
        peer, channel = self.session(self.rotation)
        self.accept('key_change_input')
        with patch.object(self.state, 'capture'):
            self.accept('key_change_terminal')
        self.accept('key_change_disconnect_attempt')
        self.close_protocol(self.rotation, peer, channel)
        self.accept('key_change_disconnected')
        self.accept('complete')
        self.assertEqual(self.state.index, len(ios.STAGES))
        self.state.finalize_cases()
        for case_result in self.result['cases'].values():
            self.assertEqual(case_result['status'], 'passed')
            self.assertTrue(case_result['terminalInputReceived'])
        case = self.result['cases']['keyChange']
        self.assertEqual([e['stage'] for e in case['rotationEvidence']], [2, 3, 4])
        self.assertEqual([e['hostKey'] for e in case['peer']['connectionEvents']], ['A', 'B', 'B', 'B'])
        self.assertTrue(case['freshFingerprintConfirmed'])
        encoded = json.dumps(self.result)
        for secret in [self.ordinary.password, self.rotation.password,
                       self.rotation.public_key, self.rotation.rotated_public_key]:
            self.assertNotIn(secret, encoded)

    def test_active_steps_reject_order_keyboard_geometry_and_unexpected_fields(self):
        self.ordinary_ready()
        with self.assertRaisesRegex(ios.Failure, 'active_flow_incomplete'):
            self.accept('ordinary_input')
        first = self.active_step('keyboard_opened')
        for update, error in (
            ({'step':'keyboard_closed'}, 'active_order_invalid'),
            ({'keyboardVisible':False}, 'active_order_invalid'),
            ({'keyboardVisible':1}, 'active_order_invalid'),
            ({'unexpected':'private'}, 'active_order_invalid'),
            ({'action':dict(first['action'], frame=[15, 30, 90, 50])}, 'active_action_invalid'),
            ({'action':dict(first['action'], frame=[400, 90, 90, 50])}, 'active_action_invalid'),
            ({'action':dict(first['action'], ownerResolved=False)}, 'active_action_invalid'),
            ({'action':dict(first['action'], role='otherNative')}, 'active_action_invalid'),
            ({'action':dict(first['action'], hittable=False)}, 'active_action_invalid'),
            ({'action':dict(first['action'], extra='private')}, 'navigation_diagnostic_invalid'),
        ):
            with self.subTest(update=update), self.assertRaisesRegex(ios.Failure, error):
                self.state.accept(dict(first, **update))
            self.assertNotIn('activeFlow', self.result['cases']['ordinary'])
        self.state.accept(first)
        with self.assertRaisesRegex(ios.Failure, 'active_order_invalid'):
            self.state.accept(first)
        self.assertEqual(len(self.result['cases']['ordinary']['activeFlow']), 1)

    def test_real_early_channel_byte_disqualifies_the_active_step(self):
        _, channel = self.ordinary_ready()
        channel.sendall(b'x')
        ios.wait_peer(self.ordinary, lambda f: f['connectionEvents'][-1]['inputBytes'] == 1,
                      'fixture_byte_not_recorded', timeout=5)
        with self.assertRaisesRegex(ios.Failure, 'active_peer_changed'):
            self.state.accept(self.active_step('keyboard_opened'))
        self.assertNotIn('activeFlow', self.result['cases']['ordinary'])

    def test_replacement_transport_disqualifies_the_active_step(self):
        peer, channel = self.ordinary_ready()
        self.state.accept(self.active_step('keyboard_opened'))
        self.close_protocol(self.ordinary, peer, channel)
        with self.assertRaisesRegex(ios.Failure, 'active_peer_changed'):
            self.state.accept(self.active_step('keyboard_closed'))
        self.session(self.ordinary, marker=False)
        with self.assertRaisesRegex(ios.Failure, 'ordinary_connection_count_invalid'):
            self.state.accept(self.active_step('keyboard_closed'))

    def test_crlf_is_not_the_original_nine_byte_marker(self):
        _, channel = self.ordinary_ready()
        for step in ios.ORDINARY_ACTIVE_STEPS:
            self.state.accept(self.active_step(step))
        channel.sendall((self.ordinary.marker + '\r\n').encode())
        ios.wait_peer(self.ordinary, lambda f: f['connectionEvents'][-1]['inputBytes'] == 10,
                      'fixture_bytes_not_recorded', timeout=5)
        with self.assertRaisesRegex(ios.Failure, 'ordinary_session_incomplete'):
            self.accept('ordinary_input')

    def test_authenticated_early_peer_cannot_pass_refusal_or_cancel_checkpoint(self):
        self.state.index = ios.STAGES.index('key_change_review')
        self.probe(self.rotation)
        peer, channel = self.session(self.rotation, marker=False)
        self.close_protocol(self.rotation, peer, channel)
        with self.assertRaisesRegex(ios.Failure, 'rotation_evidence_invalid'):
            self.accept('key_change_review')

    def test_before_native_submit_rejects_an_early_authenticated_peer(self):
        self.probe(self.ordinary)
        self.accept('ordinary_form')
        self.accept('ordinary_probe')
        self.accept('ordinary_password')
        peer, channel = self.session(self.ordinary, marker=False)
        self.close_protocol(self.ordinary, peer, channel)
        with self.assertRaisesRegex(ios.Failure, 'probe_not_empty'):
            self.state.accept({'stage': 'native_progress', 'nativeCheckpoint': 'ordinary_connect'})

    def test_ordinary_return_rejects_reauthentication_and_replayed_input(self):
        self.probe(self.ordinary)
        peer, channel = self.session(self.ordinary)
        self.state.index = ios.STAGES.index('ordinary_disconnect_attempt')
        self.accept('ordinary_disconnect_attempt')
        self.close_protocol(self.ordinary, peer, channel)
        self.accept('ordinary_disconnected')
        peer, channel = self.session(self.ordinary)
        self.close_protocol(self.ordinary, peer, channel)
        with self.assertRaisesRegex(ios.Failure, 'ordinary_connection_count_invalid'):
            self.accept('ordinary_returned_home')
        self.assertNotEqual(self.result['cases']['ordinary'].get('status'), 'passed')

    def test_duplicate_terminal_input_and_peer_close_before_ui_disconnect_reject(self):
        self.probe(self.ordinary)
        peer, channel = self.session(self.ordinary)
        ios.wait_peer(self.ordinary, lambda f: f['markerReceived'], 'missing', timeout=5)
        ios.ordinary_evidence(self.ordinary, closed=False)
        channel.sendall((self.ordinary.marker + '\r').encode())
        ios.wait_peer(self.ordinary, lambda f: f['connectionEvents'][-1]['inputBytes'] > 10, 'missing', timeout=5)
        with self.assertRaises(ios.Failure):
            ios.ordinary_evidence(self.ordinary, closed=False)
        self.close_protocol(self.ordinary, peer, channel)

    def test_http_secret_and_stage_order_are_enforced_without_raw_failure_export(self):
        server, thread = ios.start_checkpoints(self.state)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/checkpoint'
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(url, data=b'{}', headers={'Authorization': 'wrong'}), timeout=2)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()
        self.assertEqual(self.state.index, 0)
        with self.assertRaises(HTTPError) as invalid:
            urlopen(Request(url, data=json.dumps({'stage': 'password=' + self.rotation.password}).encode(),
                            headers={'Authorization': self.state.secret}), timeout=2)
        invalid.exception.close()
        self.assertEqual(self.state.failure, 'tauri_ios_checkpoint_order_invalid')
        self.assertNotIn(self.rotation.password, json.dumps(self.result))

    def test_equal_byte_count_extra_leading_newline_cannot_pass_as_one_complete_command(self):
        self.probe(self.ordinary)
        peer, channel = self.session(self.ordinary, marker=False)
        channel.sendall(('\n' + self.ordinary.marker + '\r').encode())
        ios.wait_peer(self.ordinary, lambda f: f['markerReceived'], 'missing', timeout=5)
        event = self.ordinary.snapshot()['connectionEvents'][-1]
        self.assertEqual(event['inputBytes'], len(self.ordinary.marker) + 2)
        self.assertFalse(event['singleMarkerLineExact'])
        with self.assertRaisesRegex(ios.Failure, 'ordinary_session_incomplete'):
            ios.ordinary_evidence(self.ordinary, closed=False)
        self.close_protocol(self.ordinary, peer, channel)

    def test_second_authentication_attempt_cannot_pass_final_rotation_gate(self):
        import paramiko
        for _ in range(3):
            self.probe(self.rotation)
        self.assertTrue(self.rotation.wait_for_connections_closed(3, timeout=5))
        peer = paramiko.Transport(('127.0.0.1', self.rotation.port))
        self.addCleanup(peer.close)
        peer.start_client(timeout=5)
        with self.assertRaises(paramiko.AuthenticationException):
            peer.auth_password(self.rotation.username, 'wrong')
        peer.auth_password(self.rotation.username, self.rotation.password)
        channel = peer.open_session(timeout=5)
        channel.get_pty()
        channel.invoke_shell()
        channel.settimeout(5)
        self.wait_for_initial_prompt(self.rotation, channel)
        before = self.rotation.snapshot()['connectionEvents'][-1]['outputBytes']
        channel.sendall((self.rotation.marker + '\r').encode())
        self.wait_for_reply(self.rotation, channel, before)
        with self.assertRaisesRegex(ios.Failure, 'single_command_or_auth_invalid'):
            ios.rotation_session_evidence(self.rotation, closed=False)
        self.close_protocol(self.rotation, peer, channel)
        self.assertTrue(self.rotation.wait_for_connections_closed(4, timeout=5))
        # Shared gate accepts >=1 attempts; the Tauri-specific gate must still fail.
        self.rotation.rotation_evidence(4)
        with self.assertRaisesRegex(ios.Failure, 'single_command_or_auth_invalid'):
            ios.rotation_session_evidence(self.rotation, closed=True)

    def test_peer_close_before_ui_action_cannot_be_claimed_as_active_disconnect(self):
        self.probe(self.ordinary)
        peer, channel = self.session(self.ordinary)
        ios.wait_peer(self.ordinary, lambda f: f['markerReceived'], 'missing', timeout=5)
        ios.ordinary_evidence(self.ordinary, closed=False)
        self.close_protocol(self.ordinary, peer, channel)
        self.assertTrue(self.ordinary.wait_for_connections_closed(2, timeout=5))
        self.state.index = ios.STAGES.index('ordinary_disconnect_attempt')
        with self.assertRaisesRegex(ios.Failure, 'close_order_invalid'):
            self.accept('ordinary_disconnect_attempt')
        self.assertEqual(self.state.disconnects, set())
        for _ in range(3):
            self.probe(self.rotation)
        self.assertTrue(self.rotation.wait_for_connections_closed(3, timeout=5))
        peer, channel = self.session(self.rotation)
        ios.wait_peer(self.rotation, lambda f: f['markerReceived'], 'missing', timeout=5)
        ios.rotation_session_evidence(self.rotation, closed=False)
        self.close_protocol(self.rotation, peer, channel)
        self.assertTrue(self.rotation.wait_for_connections_closed(4, timeout=5))
        self.state.index = ios.STAGES.index('key_change_disconnect_attempt')
        with self.assertRaisesRegex(ios.Failure, 'close_order_invalid'):
            self.accept('key_change_disconnect_attempt')
        self.assertEqual(self.state.disconnects, set())

    def test_repeated_command_cannot_pass_final_rotation_gate_after_peer_close(self):
        for _ in range(3):
            self.probe(self.rotation)
        self.assertTrue(self.rotation.wait_for_connections_closed(3, timeout=5))
        peer, channel = self.session(self.rotation)
        ios.wait_peer(self.rotation, lambda f: f['markerReceived'], 'missing', timeout=5)
        before = self.rotation.snapshot()['connectionEvents'][-1]['outputBytes']
        channel.sendall((self.rotation.marker + '\r').encode())
        self.wait_for_reply(self.rotation, channel, before)
        self.close_protocol(self.rotation, peer, channel)
        self.assertTrue(self.rotation.wait_for_connections_closed(4, timeout=5))
        self.rotation.rotation_evidence(4)
        with self.assertRaisesRegex(ios.Failure, 'single_command_or_auth_invalid'):
            ios.rotation_session_evidence(self.rotation, closed=True)

    def test_native_failure_retains_only_fixed_phase_and_allowlisted_code(self):
        self.state.accept({'stage': 'native_progress', 'nativeCheckpoint': 'ordinary_password'})
        self.state.accept({'stage': 'native_failure', 'nativeCheckpoint': 'ordinary_password',
                           'nativeFailureCode': 'native_control_not_visible'})
        self.assertEqual(self.result['nativeCheckpoint'], 'ordinary_password')
        self.assertEqual(self.result['nativeFailureCode'], 'native_control_not_visible')
        self.assertEqual(self.state.failure, 'tauri_ios_native_check_failed')
        for phase, control in (('ordinary_fingerprint', 'confirmation'), ('ordinary_fingerprint', 'password'),
                               ('key_change_new_fingerprint', 'submit'), ('ordinary_return_home', 'return')):
            state = ios.Checkpoints(None, None, self.directory.name, {})
            code = f'native_mobile_{control}_owner_unproven'
            state.accept({'stage': 'native_failure', 'nativeCheckpoint': phase, 'nativeFailureCode': code})
            self.assertEqual(state.result, {'nativeCheckpoint': phase, 'nativeFailureCode': code})
        for bad in ({'nativeCheckpoint': self.ordinary.password, 'nativeFailureCode': 'native_control_missing'},
                    {'nativeCheckpoint': 'ordinary_password', 'nativeFailureCode': self.ordinary.password}):
            state = ios.Checkpoints(None, None, self.directory.name, {})
            with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
                state.accept({'stage': 'native_failure', **bad})
            self.assertNotIn(self.ordinary.password, json.dumps(state.result))


if __name__ == '__main__':
    unittest.main()
