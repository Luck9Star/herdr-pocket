"""Safety and scaffold contract; actual XCUITest requires macOS and Xcode."""
import json
import base64
import ast
import os
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
        (root / 'lib/direct_ssh_page.dart').write_text("  Future<void> connect() async {\n      final localSocket = await SSHSocket.connect(\n          Semantics(container: true, explicitChildNodes: true, label: '地址'\n          Semantics(container: true, explicitChildNodes: true, label: keyAuth ? '私钥 PEM（仅本次使用）'\nTextField(key: const ValueKey('direct-secret'), controller: secret, enabled: !busy, obscureText: !keyAuth,\n          OutlinedButton(key: const ValueKey('direct-probe')\n")
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
        self.assertEqual(swift.count('app.typeKey(XCUIKeyboardKey.delete, modifierFlags: [])'),2)
        self.assertIn('cleared?[11] == true',swift)
        scanner=swift[swift.index('private func snapshotNodes'):swift.index('private func stableHit')]
        self.assertIn('try app.snapshot()',scanner)
        self.assertIn('pending.append(contentsOf: node.children)',scanner)
        self.assertNotIn('allElementsBoundByIndex',scanner)

    def test_disconnect_observation_window_and_key_order(self):
        swift=(Path(__file__).parent/'macos_secure_xcuitest.swift').read_text()
        connected=swift[swift.index('private func connectedDisconnect'):swift.index('private func peerObservationWindow')]
        self.assertIn('node.value as? String',connected)
        self.assertIn('["Esc", "Ctrl-C", "Enter"]',connected)
        self.assertIn('!element(app, "地址").exists',connected)
        self.assertIn('Date().addingTimeInterval(30)',connected)
        window=swift[swift.index('private func peerObservationWindow'):swift.index('func testSystemMasking')]
        self.assertLess(window.index('DisconnectTapped'),window.index('usleep(15_000_000)'))
        self.assertLess(window.index('usleep(15_000_000)'),window.index('DisconnectWindowEnded'))
        for name, phase, button in (('testPasswordSSH', 'password', 'disconnect'), ('testEncryptedKeySSH', 'key', 'keyDisconnect')):
            case=swift[swift.index('func '+name):].split('\n    func ',1)[0]
            self.assertLess(case.index('mark("'+phase+'DisconnectAttempt")'),case.index('tap(app, '+button+')'))
            self.assertLess(case.index('tap(app, '+button+')'),case.index('peerObservationWindow("'+phase+'")'))
            self.assertLess(case.index('peerObservationWindow("'+phase+'")'),case.index('app.terminate()'))
        key=swift[swift.index('func testEncryptedKeySSH'):swift.index('func testReturnAndReopen')]
        self.assertLess(key.index('clickFormButton(app, label: "粘贴私钥")'),key.index('app.typeText("q")'))
        self.assertLess(key.index('XCTAssertTrue(sentinelConfirmed'),key.index('app.typeText(phrase)'))
        self.assertIn('try inputMatches(app, index: 0)',key)
        self.assertIn('keyPassphraseTabAttempt',key)
        self.assertIn('gutter.scroll(byDeltaX: 0, deltaY: amount)',swift)
        self.assertIn('try inputMatches(app, index: 1)',key)
        self.assertNotIn('maskedValue.isEmpty',key)

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
