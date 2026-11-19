"""Safety and scaffold contract; actual XCUITest requires macOS and Xcode."""
import json
import base64
import ast
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
import xml.etree.ElementTree as ET

import macos_secure_xcuitest as runner

PROJECT = '''productType = "com.apple.product-type.bundle.unit-test";
''' + ('''\t\t\t\tBUNDLE_LOADER = "$(TEST_HOST)";
\t\t\t\tTEST_HOST = "$(BUILT_PRODUCTS_DIR)/herdr_flutter_probe.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/herdr_flutter_probe";
''' * 3)

class ScaffoldTests(unittest.TestCase):
    def scaffold(self, root):
        (root / 'macos/Runner.xcodeproj/xcshareddata/xcschemes').mkdir(parents=True)
        (root / 'macos/RunnerTests').mkdir(parents=True)
        (root / 'macos/Runner').mkdir(parents=True)
        (root / 'lib').mkdir()
        form = "    return entryList(desktop: desktop, key: const ValueKey('direct-form'), children: [\n"
        (root / 'lib/direct_ssh_page.dart').write_text(
            "  Future<void> connect() async {\n      final localSocket = await SSHSocket.connect(\n"
            + form * 2
            + "      Align(alignment: Alignment.topLeft, child: SizedBox(width: width, child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [\n"
            + "      if (keyAuth) ...[const SizedBox(height: 10), SizedBox(height: mobileButtonHeight, child: OutlinedButton(key: const ValueKey('direct-paste-key'),"
        )
        (root / '.herdr-generated-probe.json').write_text(json.dumps({'kind':'herdr-flutter-validation'}))
        (root / 'macos/Runner.xcodeproj/project.pbxproj').write_text(PROJECT)
        (root / 'macos/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme').write_text('<Scheme><TestAction><Testables><Testable parallelizable = "YES"/></Testables></TestAction></Scheme>')
        (root / 'macos/RunnerTests/RunnerTests.swift').write_text('unit test')
        (root / 'macos/Runner/MainFlutterWindow.swift').write_text('class Window {\n    super.awakeFromNib()\n}\n')

    def test_embedder_notification_hook_is_disposable_and_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.scaffold(root);runner.install_test_semantics_hook(root)
            text=(root/'macos/Runner/MainFlutterWindow.swift').read_text()
            self.assertIn('CommandLine.arguments.contains("--herdr-xcui-embedder-semantics")',text)
            self.assertIn('NSApplicationDidChangeAccessibilityEnhancedUserInterfaceNotification',text)
            self.assertIn('"AXEnhancedUserInterface": true',text)
            with self.assertRaises(ValueError):runner.install_test_semantics_hook(root)

    def test_only_expected_disposable_scaffold_is_converted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.scaffold(root);runner.prepare(root)
            project=(root / 'macos/Runner.xcodeproj/project.pbxproj').read_text()
            self.assertIn('com.apple.product-type.bundle.ui-testing',project)
            self.assertEqual(project.count('TEST_TARGET_NAME = Runner;'),3)
            self.assertNotIn('TEST_HOST',project)
            self.assertIn('secureTextFields', (root / 'macos/RunnerTests/RunnerTests.swift').read_text())
            with self.assertRaises(ValueError):runner.prepare(root)

    def test_fixture_embedded_only_in_disposable_test_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.scaffold(root)
            fixture=root / 'fixture&config.json';fixture.write_text(json.dumps({'port':2222,'username':'fixture','password':'a'*32,'fingerprint':'SHA256:'+'B'*43,'keyPort':2223,'keyFingerprint':'SHA256:'+'C'*43,'privateKey':'-----BEGIN OPENSSH PRIVATE KEY-----\nYWJj\n-----END OPENSSH PRIVATE KEY-----\n','passphrase':'b'*32}))
            runner.prepare(root,fixture)
            scheme=ET.parse(root / 'macos/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme')
            self.assertIsNone(scheme.find('.//EnvironmentVariable'))
            source=(root / 'macos/RunnerTests/RunnerTests.swift').read_text()
            self.assertNotIn('__HP_FIXTURE_BASE64__',source)
            self.assertNotIn('a'*32,source)
            dart=(root/'lib/direct_ssh_page.dart').read_text()
            self.assertNotIn('qaPemFocus', dart)
            self.assertIn('HPAX:H',dart);self.assertNotIn('a'*32,dart);self.assertNotIn('b'*32,dart)
            self.assertEqual(dart.count("if (desktop) Text('HPAX:H"),2)
            self.assertEqual(dart.count("Text('HPCLEAR:K${secret.text.isEmpty ? 1 : 0}P${passphrase.text.isEmpty ? 1 : 0}"),3)
            self.assertIn('HPKEY:K${secret.text == utf8.decode(base64.decode(',dart)
            self.assertIn(base64.b64encode(b'b'*32).decode(),dart)
            self.assertIn(base64.b64encode(json.loads(fixture.read_text())['privateKey'].encode()).decode(),dart)

    def test_current_product_template_accepts_disposable_injection(self):
        product = Path(__file__).resolve().parents[1] / 'flutter/lib/direct_ssh_page.dart'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); self.scaffold(root)
            (root/'lib/direct_ssh_page.dart').write_text(product.read_text())
            fixture=root/'fixture.json'
            fixture.write_text(json.dumps({'port':2222,'username':'fixture','password':'a'*32,'fingerprint':'SHA256:'+'B'*43,'keyPort':2223,'keyFingerprint':'SHA256:'+'C'*43,'privateKey':'-----BEGIN OPENSSH PRIVATE KEY-----\nYWJj\n-----END OPENSSH PRIVATE KEY-----\n','passphrase':'b'*32}))
            runner.prepare(root,fixture)
            dart=(root/'lib/direct_ssh_page.dart').read_text()
            self.assertNotIn('qaPemFocus',dart)
            self.assertIn('HP_XCUI_STAGE=keyPemParsed',dart)
            self.assertIn("ValueKey('direct-paste-key')",dart)
            self.assertEqual(dart.count("if (desktop) Text('HPAX:H"),2)
            self.assertEqual(dart.count("if (desktop && keyAuth) Text('HPKEY:K"),1)
            self.assertEqual(dart.count("Text('HPCLEAR:K"),3)
            self.assertEqual(dart.count("Text('HPCLOSE:L${closeLocalConfirmed ? 1 : 0}F${closeCleanupFailed ? 1 : 0}"),1)

    def test_unknown_project_or_missing_marker_is_not_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(ValueError):runner.prepare(root)
            self.scaffold(root)
            project=root / 'macos/Runner.xcodeproj/project.pbxproj';project.write_text('unrecognized')
            with self.assertRaises(ValueError):runner.prepare(root)
            self.assertEqual(project.read_text(),'unrecognized')

    def test_workflow_report_requires_case_progress_and_peer(self):
        workflow=(Path(__file__).resolve().parents[2] / '.github/workflows/flutter-macos-secure-xcui.yml').read_text()
        start=workflow.index("          python3 - \"$RUNNER_TEMP/macos-secure-evidence/result.json\" \"$result\" <<'PY'\n")
        body=workflow[start:].split("\n          PY\n",1)[0].split("<<'PY'\n",1)[1]
        script=textwrap.dedent(body)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture=root/'macos-secure-fixture';fixture.mkdir()
            allowed=['fixtureReadable','appLaunched','homepage','maskingHomepage','passwordHomepage','keyHomepage','returnHomepage','passwordFreshVerified','passwordAddressTyped','passwordPortCleared','passwordPortTyped','passwordUsernameTyped','keyFreshVerified','keyAddressTyped','keyPortCleared','keyPortTyped','keyUsernameTyped','ordinaryInputReadable','ordinarySentinelObserved','passwordSecureField','passwordHiddenFocused','passwordHiddenBlurred','maskingScanCompleted','passwordValuePresent','passphraseValuePresent',
                     'passwordProbeTapped','passwordFingerprintDialog','fingerprintVerified','passwordConfirmAttempt','passwordConfirmed','passwordCredentialAttempt','passwordCredentialEntered','passwordConnectAttempt','sshConnected','disconnectedAndCleared','passphraseSecureField','encryptedKeyProbeTapped','encryptedKeyFingerprintDialog','encryptedKeyFingerprintVerified','keyConfirmAttempt','keyConfirmed','keyCredentialAttempt','pemPasteButtonTapped','keyCredentialEntered','keyConnectAttempt','encryptedKeyConnected','encryptedKeyDisconnectedAndCleared',
                     'passphraseHiddenAfterFocusChanges','modeSwitchCleared','returnAndReopenCleared']
            good_peer={k:True for k in ('authAccepted','ptyRequested','shellRequested','sessionClosed','connectionsClosed')}
            (fixture/'facts.json').write_text(json.dumps({'password':good_peer,'encryptedKey':good_peer}))
            live=root/'macos-secure-private-live.json'
            live.write_text(json.dumps({'password':True,'key':True}))
            progress={k:True for k in allowed}
            methods=('testSystemMasking','testPasswordSSH','testEncryptedKeySSH','testReturnAndReopen')
            cases=''.join('Test Case '+name+' passed\n' for name in methods)
            good_log=cases+''.join('HP_XCUI_STAGE='+k+'\n' for k in progress)
            (root/'macos-secure-private-summary.json').write_text(json.dumps({'totalTestCount':4,'passedTests':4,'failedTests':0,'skippedTests':0}))
            log=root/'macos-secure-private.log';log.write_text(good_log)
            output=root/'result.json';env={**os.environ,'RUNNER_TEMP':temp,'GITHUB_SHA':'a'*40}
            def execute():
                return subprocess.run([sys.executable,'-',str(output),'0'],input=script,text=True,env=env,capture_output=True)
            self.assertEqual(execute().returncode,0);self.assertEqual(json.loads(output.read_text())['status'],'passed')
            for peer in ('password','key'):
                live.write_text(json.dumps({'password':peer!='password','key':peer!='key'}))
                self.assertNotEqual(execute().returncode,0)
                self.assertFalse(json.loads(output.read_text())['peerCloseObservedDuringDisconnectWindows'])
            live.unlink()
            self.assertNotEqual(execute().returncode,0)
            live.write_text(json.dumps({'password':True,'key':True}))
            log.write_text('Executed 0 tests')
            self.assertNotEqual(execute().returncode,0);self.assertFalse(json.loads(output.read_text())['testExecuted'])
            log.write_text('Test Case testSystemMasking failed')
            self.assertNotEqual(execute().returncode,0);self.assertTrue(json.loads(output.read_text())['cases']['testSystemMasking']['executed']);self.assertFalse(json.loads(output.read_text())['testPassed'])
            mask=['fixtureReadable','appLaunched','homepage','maskingHomepage','passwordSecureField',
                  'passwordHiddenFocused','passwordHiddenBlurred','passphraseSecureField',
                  'passphraseHiddenAfterFocusChanges','modeSwitchCleared','maskingScanCompleted','passwordValuePresent','passphraseValuePresent']
            log.write_text('Test Case testSystemMasking passed\n'+''.join('HP_XCUI_STAGE='+k+'\n' for k in mask))
            self.assertNotEqual(execute().returncode,0)
            report=json.loads(output.read_text());self.assertTrue(report['systemTreeAndSecureFieldsVerified'])
            self.assertTrue(report['cases']['testSystemMasking']['passed']);self.assertFalse(report['cases']['testPasswordSSH']['executed'])
            log.write_text('Test Case testSystemMasking failed\nHP_XCUI_METRIC=windows:1,nodes:10,buttons:2,exact:1,label:1\nprivate fixture material')
            self.assertNotEqual(execute().returncode,0)
            report=json.loads(output.read_text());self.assertEqual(report['homeMetrics']['nodes'],10)
            self.assertNotIn('private fixture material',output.read_text())
            log.write_text('Test Case testPasswordSSH failed\nHP_XCUI_FINGERPRINT=phase:password,nodes:12,prefix:1,exact:0\nprivate fingerprint material')
            self.assertNotEqual(execute().returncode,0)
            report=json.loads(output.read_text());self.assertEqual(report['fingerprintMetrics'][0]['expectedExactCount'],0)
            self.assertNotIn('private fingerprint material',output.read_text())
            log.write_text('Test Case testPasswordSSH failed\nHP_XCUI_TARGET=phase:passwordBefore,bits:1011101010101\nprivate target material')
            self.assertNotEqual(execute().returncode,0)
            report=json.loads(output.read_text());self.assertTrue(report['targetMetrics'][0]['hostMatches']);self.assertFalse(report['targetMetrics'][0]['passwordPortMatches'])
            self.assertNotIn('private target material',output.read_text())
            focus = 'HP_XCUI_FOCUS=phase:tap,owner:verified,ax:ok,trusted:1,role:textfield,match:yes,exists:1,enabled:1,hittable:1,stable:1,retained:match'
            invalid = ['HP_XCUI_FOCUS=phase:drag,owner:verified,ax:ok,trusted:1,role:private-secret,match:yes,exists:1,enabled:1,hittable:1,stable:1,retained:match',
                       focus + ',value:private-secret', focus.replace('enabled:1', 'enabled:2'),
                       focus.replace('phase:tap', 'phase:other')]
            invalid.append(focus.replace('ax:ok', 'ax:denied'))
            invalid.append(focus.replace('owner:verified', 'owner:unknown'))
            invalid.append(focus.replace('owner:verified', 'owner:private-secret'))
            drag = 'HP_XCUI_FOCUS=phase:drag,owner:verified,ax:denied,trusted:0,role:unknown,match:unknown,exists:1,enabled:1,hittable:1,stable:1,retained:unavailable'
            log.write_text('Test Case testSystemMasking failed\n' + focus + '\n' + '\n'.join(invalid) + '\n' + drag + '\n')
            self.assertNotEqual(execute().returncode,0)
            report=json.loads(output.read_text())
            self.assertEqual(report['ordinaryFocus'], [{'phase':'tap','owner':'verified','ax':'ok','trusted':True,'role':'textfield','frameMatch':'yes',
                'exists':True,'enabled':True,'hittable':True,'frameStable':True,'retained':'match'},
                {'phase':'drag','owner':'verified','ax':'denied','trusted':False,'role':'unknown','frameMatch':'unknown',
                 'exists':True,'enabled':True,'hittable':True,'frameStable':True,'retained':'unavailable'}])
            self.assertNotIn('private-secret',output.read_text())
            unknown = 'HP_XCUI_FOCUS=phase:drag,owner:unknown,ax:unavailable,trusted:0,role:unknown,match:unknown,exists:1,enabled:1,hittable:1,stable:1,retained:unavailable'
            log.write_text('Test Case testSystemMasking failed\n' + unknown + '\n')
            self.assertNotEqual(execute().returncode,0)
            report=json.loads(output.read_text())
            self.assertEqual(report['ordinaryFocus'][0]['owner'], 'unknown')
            self.assertEqual(report['ordinaryFocus'][0]['ax'], 'unavailable')
            self.assertFalse(report['systemTreeAndSecureFieldsVerified'])
            (root/'macos-secure-private-details.json').write_text(json.dumps({'message':'test timed out','private':'synthetic credential'}))
            self.assertNotEqual(execute().returncode,0)
            report=json.loads(output.read_text());self.assertIn('timeout',report['failureCategories']);self.assertTrue(report['xcresultDetailsAvailable'])
            self.assertNotIn('synthetic credential',output.read_text())
            del progress['returnAndReopenCleared'];log.write_text(cases+''.join('HP_XCUI_STAGE='+k+'\n' for k in progress))
            self.assertNotEqual(execute().returncode,0);self.assertEqual(json.loads(output.read_text())['status'],'failed')
            log.write_text(good_log)
            (fixture/'facts.json').write_text(json.dumps({'password':{'authAccepted':False},'encryptedKey':good_peer}))
            self.assertNotEqual(execute().returncode,0);self.assertFalse(json.loads(output.read_text())['peerAuthenticationPtyShellAndClose'])
            (fixture/'facts.json').write_text(json.dumps({'password':good_peer,'encryptedKey':{'authAccepted':False}}))
            log.write_text(good_log.replace('HP_XCUI_STAGE=passphraseValuePresent','HP_XCUI_STAGE=passphraseValueUnavailable'))
            self.assertNotEqual(execute().returncode,0)
            result=json.loads(output.read_text());self.assertFalse(result['systemTreeAndSecureFieldsVerified']);self.assertEqual(result['errorCode'],'secure_input_unproven')
            (fixture/'facts.json').write_text(json.dumps({'password':good_peer,'encryptedKey':good_peer}))
            self.assertEqual(execute().returncode,0)

    def test_clean_package_precedes_fixture_and_test_hook_and_is_success_gated(self):
        workflow=(Path(__file__).resolve().parents[2] / '.github/workflows/flutter-macos-secure-xcui.yml').read_text()
        self.assertLess(workflow.index('candidate.py" verify-lock'),workflow.index('flutter build macos --debug'))
        self.assertLess(workflow.index('flutter build macos --debug'),workflow.index('ci.py" package'))
        self.assertLess(workflow.index('ci.py" package'),workflow.index('--install-hook'))
        self.assertIn("if: success() && github.ref == 'refs/heads/codex/acceptance/macos-secure-design-parity'",workflow)

    def test_owned_fixture_outlives_job_and_has_explicit_cleanup(self):
        root=Path(__file__).resolve().parents[2]
        source=(root/'validation/remote-harness/macos_secure_xcui_fixture.py').read_text()
        tree=ast.parse(source)
        limit=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                   and any(isinstance(target,ast.Name) and target.id=='MAX_LIFETIME_SECONDS' for target in node.targets))
        workflow=(root/'.github/workflows/flutter-macos-secure-xcui.yml').read_text()
        self.assertIn('timeout-minutes: 45',workflow)
        self.assertGreater(limit,45*60)
        self.assertIn('touch "$RUNNER_TEMP/macos-secure-fixture/stop"',workflow)
        self.assertIn('wait "$fixture_pid"',workflow)

    def test_secure_queries_scroll_with_bounded_real_hits_and_dual_peer_guards(self):
        swift=(Path(__file__).parent/'macos_secure_xcuitest.swift').read_text()
        self.assertIn('target.scroll(byDeltaX: 0, deltaY: amount)',swift)
        self.assertIn('first == element.frame && element.isHittable',swift)
        self.assertIn('element.coordinate(withNormalizedOffset:',swift)
        self.assertIn('passwordValueUnavailable',swift)
        self.assertIn('passphraseValueUnavailable',swift)
        self.assertIn('encryptedKeyConnected',swift)
        self.assertIn('clickFormButton(app, label: "粘贴私钥")',swift)
        self.assertIn('XCUIKeyboardKey.end',swift)
        port = swift[swift.index('private func enterTarget'):swift.index('private func clickEntryBack')]
        self.assertEqual(port.count('app.typeKey(XCUIKeyboardKey.delete, modifierFlags: [])'),2)
        self.assertIn('cleared?[11] == true',swift)
        scanner=swift[swift.index('private func snapshotNodes'):swift.index('private func stableHit')]
        self.assertIn('try app.snapshot()',scanner)
        self.assertIn('pending.append(contentsOf: node.children)',scanner)
        self.assertNotIn('allElementsBoundByIndex',scanner)

    def test_disconnect_observation_window_and_key_order(self):
        swift=(Path(__file__).parent/'macos_secure_xcuitest.swift').read_text()
        connected=swift[swift.index('private func connectedDisconnect'):swift.index('private func peerObservationWindow')]
        self.assertIn('node.value as? String',connected)
        self.assertIn('$0 == "已连接"',connected)
        self.assertNotIn('["Esc", "Ctrl-C", "Enter"]',connected)
        self.assertIn('!element(app, addressLabel).exists',connected)
        self.assertIn('Date().addingTimeInterval(30)',connected)
        window=swift[swift.index('private func peerObservationWindow'):swift.index('func testSystemMasking')]
        self.assertLess(window.index('DisconnectTapped'),window.index('usleep(15_000_000)'))
        self.assertLess(window.index('usleep(15_000_000)'),window.index('DisconnectWindowEnded'))
        for name, phase, button in (('testPasswordSSH', 'password', 'disconnect'), ('testEncryptedKeySSH', 'key', 'keyDisconnect')):
            case=swift[swift.index('func '+name):].split('\n    func ',1)[0]
            self.assertLess(case.index('mark("'+phase+'DisconnectAttempt")'),case.index('tap(app, '+button+')'))
            self.assertLess(case.index('tap(app, '+button+')'),case.index('peerObservationWindow("'+phase+'")'))
            self.assertLess(case.index('peerObservationWindow("'+phase+'")'),case.index('verifyLocalDisconnect(app'))
            self.assertLess(case.index('verifyLocalDisconnect(app'),case.index('app.terminate()'))
        key=swift[swift.index('func testEncryptedKeySSH'):swift.index('func testReturnAndReopen')]
        self.assertLess(key.index('clickFormButton(app, label: "粘贴私钥")'),key.index('app.typeText("q")'))
        self.assertLess(key.index('XCTAssertTrue(sentinelConfirmed'),key.index('app.typeText(phrase)'))
        self.assertIn('try inputMatches(app, index: 0)',key)
        self.assertIn('clickNativeKeyPassphrase(app)',key)
        self.assertIn('keyPassphraseNativeClicked',swift)
        return_case=swift[swift.index('func testReturnAndReopen'): ]
        self.assertIn('field.click();app.typeText(password)',return_case)
        self.assertNotIn('tap(app, field, phase: "returnSecure")',return_case)
        self.assertIn('gutter.scroll(byDeltaX: 0, deltaY: amount)',swift)
        self.assertIn('try inputMatches(app, index: 1)',key)
        self.assertNotIn('maskedValue.isEmpty',key)

    def test_staged_auth_waits_for_confirmation_and_checks_clearing(self):
        swift=(Path(__file__).parent/'macos_secure_xcuitest.swift').read_text()
        self.assertIn('frame.width >= 700 && frame == window.frame',swift)
        self.assertIn('private let trustConfirmationLabel = "指纹一致，确认继续"',swift)
        self.assertIn('XCTAssertEqual(app.secureTextFields.count, 0',swift)
        result=swift[swift.index('private func verifyClearedCredentials'):swift.index('private func typeOrdinaryOnce')]
        self.assertIn('HPCLEAR:K1P1',result)
        self.assertIn('app.secureTextFields.count == secureEditors',result)
        self.assertIn('containsCloseTitle(text, title: "本机已断开")',result)
        self.assertIn('[$0.label, $0.value as? String ?? ""]',result)
        self.assertIn('closeConfirmed = text.contains { $0.contains("HPCLOSE:L1F0") }',result)
        self.assertIn('if closeConfirmed && systemTitle && returnAvailable { break }',result)
        for gate in ('closeConfirmed', 'systemTitle', 'returnAvailable'):
            self.assertIn('XCTAssertTrue(' + gate + ',', result)
        self.assertIn('$0.components(separatedBy: separators).contains(title)',result)
        self.assertIn('returnHome.count == 1 && returnHome.firstMatch.isEnabled',result)
        self.assertIn('try assertNoSecrets(app, secrets)',result)
        masking=swift[swift.index('func testSystemMasking'):swift.index('func testPasswordSSH')]
        self.assertLess(masking.index('try probeAndReview(app'),masking.index('secureField(app, "direct-secret")'))
        reopened=swift[swift.index('func testReturnAndReopen'):]
        self.assertLess(reopened.index('phase: "returnReopened")'),reopened.index('let reopened = secureField'))
        self.assertIn('verifyClearedCredentials(app, secureEditors: 1)',reopened)

    def test_reopened_target_requires_actual_input_and_exact_controller_readback(self):
        swift = (Path(__file__).parent / 'macos_secure_xcuitest.swift').read_text()
        target = swift[swift.index('private func enterTarget'):swift.index('private func clickEntryBack')]
        self.assertLess(target.index('requireFreshForm(app'), target.index('typeOrdinaryOnce(app, field: address'))
        self.assertIn('phase: phase + "Address", controllerBit: 0', target)
        self.assertIn('phase: phase + "Port", controllerBit: portBit', target)
        self.assertIn('phase: phase + "User", controllerBit: 3', target)
        helper = swift[swift.index('private func verifyOrdinaryValue'):swift.index('private func targetDiagnostics')]
        self.assertIn('(field.value as? String) == value', helper)
        self.assertIn('matching?[controllerBit] == true', helper)
        self.assertEqual(helper.count('app.typeText(value)'), 1)
        self.assertNotIn('phase: "sentinel"', helper)

    def test_ordinary_sentinel_replaces_the_retained_address_using_the_same_system_text_field(self):
        swift = (Path(__file__).parent / 'macos_secure_xcuitest.swift').read_text()
        helper = swift[swift.index('private func ordinaryValues'):swift.index('private func verifyFingerprint')]
        self.assertIn('let node = try address.snapshot()', helper)
        self.assertIn('node.elementType == .textField', helper)
        self.assertIn('return node.value as? String', helper)
        self.assertIn('window.descendants(matching: .any).matching(identifier: addressLabel)', helper)
        self.assertIn('XCTAssertEqual(addresses.count, 1', helper)
        self.assertIn('retained?[0] == true && retained?[1] == true && retained?[3] == true && retained?[8] == false', helper)
        self.assertIn('XCTAssertFalse(try ordinaryValue(address) == sentinel', helper)
        self.assertLess(helper.index('tap(app, address)'), helper.index('trailing.click(forDuration:'))
        self.assertLess(helper.index('trailing.click(forDuration:'), helper.index('address.typeText(sentinel)'))
        self.assertEqual(helper.count('address.typeText(sentinel)'), 1)
        self.assertNotIn('XCUIKeyboardKey.delete', helper)
        after_type = helper[helper.index('address.typeText(sentinel)'):]
        self.assertNotIn('targetDiagnostics(', after_type)
        self.assertIn('seen = try ordinaryValue(address) == sentinel', after_type)
        self.assertIn('XCTAssertTrue(seen,', after_type)
        masking = swift[swift.index('func testSystemMasking'):swift.index('func testPasswordSSH')]
        returned = masking[masking.index('clickEntryBack(app, phase: "maskingBack")'):]
        self.assertLess(returned.index('try verifyClearedCredentials'), returned.index('try verifyOrdinarySentinel'))
        self.assertLess(returned.index('try verifyOrdinarySentinel'), returned.index('try assertNoSecrets'))
        self.assertLess(returned.index('try assertNoSecrets'), returned.index('mark("ordinarySentinelObserved")'))
        self.assertNotIn('reopenSSH(', returned)

    def test_focus_diagnostic_is_read_only_and_never_replays_sentinel(self):
        swift = (Path(__file__).parent / 'macos_secure_xcuitest.swift').read_text()
        diagnostic = swift[swift.index('private func ordinaryFocusObservation'):swift.index('private func verifyOrdinarySentinel')]
        self.assertIsNone(re.search(r'\bapp\.processID\b', swift))
        self.assertIn('NSRunningApplication.runningApplications(withBundleIdentifier:', diagnostic)
        self.assertIn('app.state == .runningForeground', diagnostic)
        self.assertIn('app.windows.count == 1', diagnostic)
        self.assertIn('candidates.count == 1', diagnostic)
        self.assertIn('frontmost.isEqual(candidate)', diagnostic)
        self.assertIn('candidate.isActive', diagnostic)
        self.assertIn('candidate.processIdentifier > 0', diagnostic)
        self.assertIn('AXUIElementCreateApplication(candidate.processIdentifier)', diagnostic)
        self.assertIn('kAXFocusedUIElementAttribute', diagnostic)
        self.assertIn('kAXPositionAttribute', diagnostic)
        self.assertIn('frame match is only a geometric clue', swift.lower())
        self.assertNotIn('AXUIElementSetAttributeValue', diagnostic)
        self.assertNotIn('typeText(', diagnostic)
        self.assertNotIn('node.label', diagnostic)
        helper = swift[swift.index('private func verifyOrdinarySentinel'):swift.index('private func verifyFingerprint')]
        self.assertLess(helper.index('phase: "tap"'), helper.index('trailing.click(forDuration:'))
        self.assertLess(helper.index('trailing.click(forDuration:'), helper.index('phase: "drag"'))
        self.assertLess(helper.index('phase: "drag"'), helper.index('address.typeText(sentinel)'))
        self.assertEqual(helper.count('address.typeText(sentinel)'), 1)
        self.assertIn('seen = try ordinaryValue(address) == sentinel', helper)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), 'requires macOS Swift and AppKit')
    def test_focus_observation_typechecks_without_any_xcui_process_id(self):
        swift = (Path(__file__).parent / 'macos_secure_xcuitest.swift').read_text()
        helper = swift[swift.index('    private func ordinaryFocusObservation'):swift.index('    private func verifyOrdinarySentinel')]
        # This deliberately models only the public XCUI state/query surface and
        # has no processID. AppKit and ApplicationServices are the real SDK.
        stub = """import Foundation
import AppKit
import ApplicationServices
class XCUIElement { var exists = false; var frame = CGRect.zero; var isEnabled = false; var isHittable = false }
class XCUIElementQuery { var count = 0 }
class XCUIApplication { enum State { case runningForeground, notRunning }; var state: State = .notRunning; var windows = XCUIElementQuery() }
class Probe { func ordinaryValue(_ address: XCUIElement) throws -> String? { nil }
"""
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'Focus.swift'; binary=Path(temp)/'focus'
            source.write_text(stub + helper.replace('    private func ordinaryFocusObservation', '    func ordinaryFocusObservation', 1)
                              + '}\nProbe().ordinaryFocusObservation(XCUIApplication(), address: XCUIElement(), addresses: XCUIElementQuery(), initialFrame: .zero, phase: "tap")\n')
            build=subprocess.run(['swiftc', '-swift-version', '5', str(source), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            observed=subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(observed.returncode, 0, observed.stderr)
            self.assertIn('owner:unknown,ax:unavailable', observed.stdout)
            self.assertIn('role:unknown,match:unknown', observed.stdout)

    def test_fingerprint_mouse_fallback_requires_unique_visible_target_and_actual_confirmation(self):
        swift=(Path(__file__).parent/'macos_secure_xcuitest.swift').read_text()
        helper=swift[swift.index('private func confirmFingerprint'):swift.index('private func typeOrdinaryOnce')]
        self.assertIn('XCTAssertEqual(matches.count, 1',helper)
        self.assertIn('frame.intersection(windowFrame).contains(center)',helper)
        self.assertIn('XCTAssertEqual(overlapping, 0',helper)
        self.assertIn('button.waitForNonExistence',helper)
        self.assertIn('target?[12] == true',helper)
        self.assertIn('clickWindowCenter(app, matches: matches)',helper)
        click=swift[swift.index('private func clickWindowCenter'):swift.index('private func clickFormButton')]
        self.assertIn('XCTAssertEqual(matches.count, 1',click)
        self.assertIn('frame.intersection(windowFrame).contains(center)',click)
        self.assertIn('$0.exists && $0.isHittable && $0.frame.contains(center)',click)
        self.assertIn('XCTAssertEqual(overlapping, 0',click)
        self.assertEqual(click.count('.click()'),1)
        form=swift[swift.index('private func clickFormButton'):swift.index('private func keyInputBits')]
        for condition in ('viewport.contains(center)', 'viewport == currentViewport', 'secure credential overlay', 'stableHit(button)', 'origin.withOffset'):
            self.assertIn(condition,form)
        key=swift[swift.index('func testEncryptedKeySSH'):swift.index('func testReturnAndReopen')]
        self.assertLess(key.index('verifyFingerprint(app, expected: keyFingerprint'),key.index('connectByWindowCenter(app)'))
        self.assertLess(key.index('diagnoseKeyInputs(app)'),key.index('connectByWindowCenter(app)'))
        self.assertIn('XCTAssertTrue(pasted?[0] == true && pasted?[1] == true',key)
        self.assertNotIn('pemKeyboardFallback',key)
        diagnostics=swift[swift.index('private func diagnoseKeyInputs'):swift.index('private func ordinaryMetrics')]
        self.assertIn('HP_XCUI_KEYINPUT=visible:',diagnostics)
        self.assertIn('HPKEY:K([01])P([01])Q([01])',swift)
        self.assertIn('Date().addingTimeInterval(10)',diagnostics)
        self.assertNotIn('XCTFail',diagnostics)

if __name__ == '__main__':
    unittest.main()
