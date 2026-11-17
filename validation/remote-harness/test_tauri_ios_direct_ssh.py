"""Native-driver contract and isolated real SSH; these are not iOS device proof."""
import base64
import copy
import hashlib
import io
import json
import logging
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
            self.assertIn('matches.allSatisfy { $0.frame == first.frame }', source)
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
                      'pngBase64': base64.b64encode(data).decode()}

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
        payload['reviewFrames'] = [[20, 80 + i * 100, 400, 50] for i in range(7)]
        with tempfile.TemporaryDirectory() as directory:
            state = ios.Checkpoints(None, None, directory, self.result)
            with patch.object(ios, 'verify_terminal_screenshot') as gate:
                state.capture('key_change_review', payload, self.fixture)
            gate.assert_not_called()
            self.assertEqual((Path(directory) / 'key-change-review.png').read_bytes(), data)
            self.assertIn('reviewScreenshot', self.result['cases']['keyChange'])


class RealLoopbackCheckpointsTests(unittest.TestCase):
    def setUp(self):
        logging.getLogger('paramiko').setLevel(logging.CRITICAL)
        self.ordinary = ios.SingleCommandFixture(screen_proof=True).__enter__()
        self.rotation = ios.SingleCommandFixture(rotate_after_probe=True, screen_proof=True).__enter__()
        self.addCleanup(self.ordinary.close)
        self.addCleanup(self.rotation.close)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.result = {'cases': {'ordinary': {}, 'keyChange': {}}, 'artifacts': {}}
        self.state = ios.Checkpoints(self.ordinary, self.rotation, self.directory.name, self.result)

    def probe(self, fixture):
        import paramiko
        peer = paramiko.Transport(('127.0.0.1', fixture.port))
        peer.start_client(timeout=5)
        key = peer.get_remote_server_key()
        peer.close()
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
        if marker:
            channel.sendall((fixture.marker + '\r').encode())
            received = b''
            while fixture.screen_token.split()[7].encode() not in received:
                received += channel.recv(4096)
            self.assertIn(fixture.echo_marker.encode(), received)
        return peer, channel

    def accept(self, stage):
        self.state.accept({'stage': stage})

    @staticmethod
    def close_protocol(peer, channel):
        # The real fixture may close after receiving channel EOF before Paramiko
        # sends its final CHANNEL_CLOSE. Only teardown EOF is idempotent; the
        # production gate still checked the session alive before the UI action.
        try:
            channel.close()
        except EOFError:
            pass
        finally:
            peer.close()

    def test_complete_native_checkpoint_order_against_real_aabb_and_abbb_peers(self):
        self.accept('ordinary_form')
        self.probe(self.ordinary)
        self.accept('ordinary_probe')
        self.accept('ordinary_password')
        peer, channel = self.session(self.ordinary)
        self.accept('ordinary_input')
        # Images in this protocol test are deliberately mocked, not device proof.
        with patch.object(self.state, 'capture'):
            self.accept('ordinary_terminal')
        self.accept('ordinary_disconnect_attempt')
        self.close_protocol(peer, channel)
        self.accept('ordinary_disconnected')
        self.accept('key_change_form')
        key_a = self.probe(self.rotation)
        self.accept('key_change_probe_a')
        self.accept('key_change_password_a')
        key_b = self.probe(self.rotation)
        self.assertNotEqual(key_a, key_b)
        with patch.object(self.state, 'capture'):
            self.accept('key_change_review')
        self.accept('key_change_cancelled')
        self.assertEqual(self.rotation.snapshot()['connections'], 2)
        self.assertEqual(self.probe(self.rotation), key_b)
        self.accept('key_change_probe_b')
        self.accept('key_change_password_b')
        peer, channel = self.session(self.rotation)
        self.accept('key_change_input')
        with patch.object(self.state, 'capture'):
            self.accept('key_change_terminal')
        self.accept('key_change_disconnect_attempt')
        self.close_protocol(peer, channel)
        self.accept('key_change_disconnected')
        self.accept('complete')
        self.assertEqual(self.state.index, len(ios.STAGES))
        case = self.result['cases']['keyChange']
        self.assertEqual([e['stage'] for e in case['rotationEvidence']], [2, 3, 4])
        self.assertEqual([e['hostKey'] for e in case['peer']['connectionEvents']], ['A', 'B', 'B', 'B'])
        self.assertTrue(case['freshFingerprintConfirmed'])
        encoded = json.dumps(self.result)
        for secret in [self.ordinary.password, self.rotation.password,
                       self.rotation.public_key, self.rotation.rotated_public_key]:
            self.assertNotIn(secret, encoded)

    def test_authenticated_early_peer_cannot_pass_refusal_or_cancel_checkpoint(self):
        self.state.index = ios.STAGES.index('key_change_review')
        self.probe(self.rotation)
        peer, channel = self.session(self.rotation, marker=False)
        self.close_protocol(peer, channel)
        with self.assertRaisesRegex(ios.Failure, 'rotation_evidence_invalid'):
            self.accept('key_change_review')

    def test_duplicate_terminal_input_and_peer_close_before_ui_disconnect_reject(self):
        self.probe(self.ordinary)
        peer, channel = self.session(self.ordinary)
        ios.wait_peer(self.ordinary, lambda f: f['markerReceived'], 'missing', timeout=5)
        ios.ordinary_evidence(self.ordinary, closed=False)
        channel.sendall((self.ordinary.marker + '\r').encode())
        ios.wait_peer(self.ordinary, lambda f: f['connectionEvents'][-1]['inputBytes'] > 10, 'missing', timeout=5)
        with self.assertRaises(ios.Failure):
            ios.ordinary_evidence(self.ordinary, closed=False)
        self.close_protocol(peer, channel)

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
        self.close_protocol(peer, channel)

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
        channel.sendall((self.rotation.marker + '\r').encode())
        ios.wait_peer(self.rotation, lambda f: f['markerReceived'], 'missing', timeout=5)
        with self.assertRaisesRegex(ios.Failure, 'single_command_or_auth_invalid'):
            ios.rotation_session_evidence(self.rotation, closed=False)
        self.close_protocol(peer, channel)
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
        self.close_protocol(peer, channel)
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
        self.close_protocol(peer, channel)
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
        channel.sendall((self.rotation.marker + '\r').encode())
        ios.wait_peer(self.rotation, lambda f: f['connectionEvents'][-1]['inputBytes'] > 10, 'missing', timeout=5)
        self.close_protocol(peer, channel)
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
        for bad in ({'nativeCheckpoint': self.ordinary.password, 'nativeFailureCode': 'native_control_missing'},
                    {'nativeCheckpoint': 'ordinary_password', 'nativeFailureCode': self.ordinary.password}):
            state = ios.Checkpoints(None, None, self.directory.name, {})
            with self.assertRaisesRegex(ios.Failure, 'native_diagnostic_invalid'):
                state.accept({'stage': 'native_failure', **bad})
            self.assertNotIn(self.ordinary.password, json.dumps(state.result))


if __name__ == '__main__':
    unittest.main()
