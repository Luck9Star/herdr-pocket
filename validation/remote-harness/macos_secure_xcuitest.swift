import XCTest
import Darwin

final class SecureCredentialUITests: XCTestCase {
    private func mark(_ name: String) {
        print("HP_XCUI_STAGE=\(name)")
        fflush(stdout)
    }

    private func element(_ app: XCUIApplication, _ label: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: label).firstMatch
    }

    // Never print snapshots or values: only assertions on synthetic values escape.
    private func assertNoSecrets(_ app: XCUIApplication, _ secrets: [String]) {
        let nodes = app.descendants(matching: .any).allElementsBoundByIndex
        XCTAssertGreaterThan(nodes.count, 5, "system accessibility tree is empty")
        for node in nodes {
            let fields = [node.label, node.identifier, node.value as? String ?? ""]
            for field in fields {
                for secret in secrets {
                    XCTAssertFalse(field.contains(secret), "synthetic credential exposed in system accessibility tree")
                }
            }
        }
    }

    private func secureField(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
        let expected = identifier == "direct-secret" ? "密码（仅本次使用）" : "私钥口令（可选）"
        let phase = identifier == "direct-secret" ? "password" : "passphrase"
        let secure = app.secureTextFields
        let exact = secure.matching(NSPredicate(format: "identifier == %@", identifier))
        if exact.firstMatch.waitForExistence(timeout: 10) && exact.count == 1 && exact.firstMatch.isHittable { return exact.firstMatch }
        let all = app.descendants(matching: .any)
        let ids = all.matching(NSPredicate(format: "identifier == %@", identifier))
        let labels = all.matching(NSPredicate(format: "label == %@", expected))
        let secureLabels = secure.matching(NSPredicate(format: "label == %@", expected))
        print("HP_XCUI_SECURE=phase:\(phase),secure:\(min(secure.count,10000)),text:\(min(app.textFields.count,10000)),other:\(min(app.otherElements.count,10000)),id:\(min(ids.count,10000)),label:\(min(labels.count,10000)),securelabel:\(min(secureLabels.count,10000))")
        fflush(stdout)
        if secure.count == 1 && secureLabels.count == 1 && secureLabels.firstMatch.isHittable {
            return secureLabels.firstMatch
        }
        XCTFail("native secure field missing from system tree")
        return exact.firstMatch
    }

    private func tap(_ element: XCUIElement) {
        element.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).click()
    }

    private func ordinaryMetrics(_ app: XCUIApplication, sentinel: String) -> Bool {
        let nodes = app.descendants(matching: .any).allElementsBoundByIndex
        let values = nodes.compactMap { $0.value as? String }.filter { !$0.isEmpty }
        let seen = !sentinel.isEmpty && values.contains { $0.contains(sentinel) }
        print("HP_XCUI_ORDINARY=nodes:\(min(nodes.count,10000)),values:\(min(values.count,10000)),sentinel:\(seen ? 1 : 0)")
        fflush(stdout)
        XCTAssertGreaterThan(nodes.count, 5, "system accessibility tree is empty")
        return seen
    }

    private func homeEntry(_ app: XCUIApplication) -> XCUIElement {
        let button = app.buttons["普通 SSH"]
        if button.waitForExistence(timeout: 15) && button.isHittable { return button }
        let matches = app.descendants(matching: .any).matching(identifier: "普通 SSH")
        let labels = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "普通 SSH"))
        print("HP_XCUI_METRIC=windows:\(min(app.windows.count,10000)),nodes:\(min(app.descendants(matching: .any).count,10000)),buttons:\(min(app.buttons.count,10000)),exact:\(min(matches.count,10000)),label:\(min(labels.count,10000))")
        fflush(stdout)
        return matches.allElementsBoundByIndex.first(where: { $0.isHittable }) ?? button
    }

    func testPasswordAndPrivateKeyPassphraseAreSecure() throws {
        continueAfterFailure = false
        guard let data = Data(base64Encoded: "__HP_FIXTURE_BASE64__"),
              let fixture = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let password = fixture["password"] as? String,
              let username = fixture["username"] as? String,
              let port = fixture["port"] as? Int,
              let fingerprint = fixture["fingerprint"] as? String else {
            XCTFail("owned loopback fixture unavailable")
            return
        }
        let phrase = "fixture-passphrase-" + UUID().uuidString
        let host = "127.0.0.1"
        mark("fixtureReadable")
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 20), "candidate app did not launch")
        mark("appLaunched")
        var entry = homeEntry(app)
        if !entry.exists || !entry.isHittable {
            app.terminate()
            app.launchArguments = ["--herdr-xcui-embedder-semantics"]
            mark("embedderFallbackRequested")
            app.launch()
            XCTAssertTrue(app.wait(for: .runningForeground, timeout: 20), "candidate app did not launch")
            entry = homeEntry(app)
        }
        XCTAssertTrue(entry.exists && entry.isHittable, "normal homepage SSH entry missing")
        mark("homepage")
        entry.click()
        let address = element(app, "地址").descendants(matching: .textField).firstMatch
        XCTAssertTrue(address.waitForExistence(timeout: 15), "named address group or ordinary input missing")
        _ = ordinaryMetrics(app, sentinel: "")
        let passwordField = secureField(app, "direct-secret")
        mark("passwordSecureField")
        tap(passwordField)
        app.typeText(password)
        mark((passwordField.value as? String ?? "").isEmpty ? "passwordValueUnavailable" : "passwordValuePresent")
        assertNoSecrets(app, [password, phrase])
        mark("passwordHiddenFocused")
        tap(address)
        assertNoSecrets(app, [password, phrase])
        mark("passwordHiddenBlurred")

        let keyMode = element(app, "使用私钥认证")
        XCTAssertTrue(keyMode.waitForExistence(timeout: 10), "private key mode missing")
        keyMode.click()
        let passphraseField = secureField(app, "direct-passphrase")
        mark("passphraseSecureField")
        tap(passphraseField)
        app.typeText(phrase)
        mark((passphraseField.value as? String ?? "").isEmpty ? "passphraseValueUnavailable" : "passphraseValuePresent")
        assertNoSecrets(app, [password, phrase])
        tap(address)
        assertNoSecrets(app, [password, phrase])
        tap(passphraseField)
        assertNoSecrets(app, [password, phrase])
        mark("passphraseHiddenAfterFocusChanges")
        keyMode.click()
        XCTAssertTrue((secureField(app, "direct-secret").value as? String ?? "").isEmpty, "password retained after mode switch")
        keyMode.click()
        XCTAssertTrue((secureField(app, "direct-passphrase").value as? String ?? "").isEmpty, "passphrase retained after mode switch")
        mark("modeSwitchCleared")
        assertNoSecrets(app, [password, phrase])

        keyMode.click()
        let passwordAgain = secureField(app, "direct-secret")
        tap(passwordAgain);app.typeText(password)
        assertNoSecrets(app, [password, phrase])
        mark("maskingScanCompleted")

        let sentinel = "xcui-sentinel-" + UUID().uuidString
        tap(address);app.typeText(sentinel)
        let seen = ordinaryMetrics(app, sentinel: sentinel)
        XCTAssertTrue(seen, "ordinary sentinel not found in system accessibility values")
        mark("ordinarySentinelObserved")
        app.typeKey("a", modifierFlags: .command);app.typeText(host)
        mark("addressTyped")
        let portField = element(app, "端口").descendants(matching: .textField).firstMatch
        let userField = element(app, "用户名").descendants(matching: .textField).firstMatch
        XCTAssertTrue(portField.exists && userField.exists, "ordinary target fields missing")
        tap(portField);app.typeKey("a", modifierFlags: .command);app.typeText(String(port))
        mark("portTyped")
        tap(userField);app.typeText(username)
        mark("usernameTyped")
        mark("ordinaryInputReadable")

        let probe = app.buttons["探测并核对主机密钥"]
        XCTAssertTrue(probe.exists && probe.isEnabled, "host key probe unavailable")
        probe.click()
        let keyText = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", fingerprint)).firstMatch
        XCTAssertTrue(keyText.waitForExistence(timeout: 20), "independently expected host fingerprint missing")
        mark("fingerprintVerified")
        let confirm = app.buttons["已核对并确认"]
        XCTAssertTrue(confirm.exists && confirm.isHittable, "fingerprint confirmation unavailable")
        confirm.click()
        let loginPassword = secureField(app, "direct-secret")
        tap(loginPassword);app.typeText(password)
        assertNoSecrets(app, [password, phrase])
        let connect = app.buttons["连接 SSH"]
        XCTAssertTrue(connect.exists && connect.isEnabled, "connection action unavailable")
        connect.click()
        let connected = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "已连接 · 输入直接发送到远端 shell")).firstMatch
        XCTAssertTrue(connected.waitForExistence(timeout: 30), "native SSH session did not authenticate")
        mark("sshConnected")
        let disconnect = app.buttons["断开"]
        XCTAssertTrue(disconnect.waitForExistence(timeout: 10), "disconnect action missing")
        assertNoSecrets(app, [password, phrase])
        disconnect.click()
        XCTAssertTrue(app.buttons["连接 SSH"].waitForExistence(timeout: 15), "disconnect did not return to form")
        XCTAssertTrue((secureField(app, "direct-secret").value as? String ?? "").isEmpty, "password not cleared after disconnect")
        mark("disconnectedAndCleared")

        let back = app.buttons["Back"].exists ? app.buttons["Back"] : app.buttons["返回"]
        XCTAssertTrue(back.exists && back.isHittable, "back action missing")
        back.click()
        let returnedEntry = homeEntry(app)
        XCTAssertTrue(returnedEntry.exists && returnedEntry.isHittable, "normal homepage did not return")
        assertNoSecrets(app, [password, phrase])
        returnedEntry.click()
        let reopened = secureField(app, "direct-secret")
        XCTAssertTrue((reopened.value as? String ?? "").isEmpty, "prior credential retained")
        assertNoSecrets(app, [password, phrase])
        mark("returnAndReopenCleared")
        app.terminate()
    }
}
