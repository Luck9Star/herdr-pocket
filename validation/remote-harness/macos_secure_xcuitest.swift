import XCTest

final class SecureCredentialUITests: XCTestCase {
    private var progressURL: URL?
    private var progress: [String: Bool] = [:]

    private func mark(_ name: String) throws {
        progress[name] = true
        guard let url = progressURL else { throw CocoaError(.fileNoSuchFile) }
        try JSONSerialization.data(withJSONObject: progress, options: [.sortedKeys]).write(to: url, options: .atomic)
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
        let field = app.secureTextFields[identifier]
        XCTAssertTrue(field.waitForExistence(timeout: 10), "native secure field missing from system tree")
        return field
    }

    func testPasswordAndPrivateKeyPassphraseAreSecure() throws {
        continueAfterFailure = false
        guard let path = ProcessInfo.processInfo.environment["HP_MAC_AX_FIXTURE"],
              let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
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
        progressURL = URL(fileURLWithPath: path).deletingLastPathComponent().appendingPathComponent("progress.json")
        try mark("fixtureReadable")
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 20), "candidate app did not launch")
        try mark("appLaunched")
        let entry = app.buttons["普通 SSH"]
        XCTAssertTrue(entry.waitForExistence(timeout: 30), "normal homepage SSH entry missing")
        try mark("homepage")
        entry.click()
        let address = element(app, "地址").descendants(matching: .textField).firstMatch
        XCTAssertTrue(address.waitForExistence(timeout: 15), "named address group or ordinary input missing")
        address.click()
        address.typeText(host)
        XCTAssertTrue((address.value as? String ?? "").contains(host), "ordinary input is not readable")
        try mark("ordinaryInputReadable")
        let portField = element(app, "端口").descendants(matching: .textField).firstMatch
        let userField = element(app, "用户名").descendants(matching: .textField).firstMatch
        XCTAssertTrue(portField.exists && userField.exists, "ordinary target fields missing")
        portField.click();portField.typeKey("a", modifierFlags: .command);portField.typeText(String(port))
        userField.click();userField.typeText(username)

        let passwordField = secureField(app, "direct-secret")
        try mark("passwordSecureField")
        passwordField.click()
        passwordField.typeText(password)
        assertNoSecrets(app, [password, phrase])
        try mark("passwordHiddenFocused")
        address.click()
        assertNoSecrets(app, [password, phrase])
        try mark("passwordHiddenBlurred")
        XCTAssertTrue((address.value as? String ?? "").contains(host), "ordinary input changed on focus switch")

        let probe = app.buttons["探测并核对主机密钥"]
        XCTAssertTrue(probe.exists && probe.isEnabled, "host key probe unavailable")
        probe.click()
        let keyText = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", fingerprint)).firstMatch
        XCTAssertTrue(keyText.waitForExistence(timeout: 20), "independently expected host fingerprint missing")
        try mark("fingerprintVerified")
        let confirm = app.buttons["已核对并确认"]
        XCTAssertTrue(confirm.exists && confirm.isHittable, "fingerprint confirmation unavailable")
        confirm.click()
        let connect = app.buttons["连接 SSH"]
        XCTAssertTrue(connect.exists && connect.isEnabled, "connection action unavailable")
        connect.click()
        let connected = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "已连接 · 输入直接发送到远端 shell")).firstMatch
        XCTAssertTrue(connected.waitForExistence(timeout: 30), "native SSH session did not authenticate")
        try mark("sshConnected")
        let disconnect = app.buttons["断开"]
        XCTAssertTrue(disconnect.waitForExistence(timeout: 10), "disconnect action missing")
        assertNoSecrets(app, [password, phrase])
        disconnect.click()
        XCTAssertTrue(app.buttons["连接 SSH"].waitForExistence(timeout: 15), "disconnect did not return to form")
        XCTAssertTrue((secureField(app, "direct-secret").value as? String ?? "").isEmpty, "password not cleared after disconnect")
        try mark("disconnectedAndCleared")

        let keyMode = element(app, "使用私钥认证")
        XCTAssertTrue(keyMode.waitForExistence(timeout: 10), "private key mode missing")
        keyMode.click()
        let passphraseField = secureField(app, "direct-passphrase")
        try mark("passphraseSecureField")
        passphraseField.click()
        passphraseField.typeText(phrase)
        assertNoSecrets(app, [password, phrase])
        address.click()
        assertNoSecrets(app, [password, phrase])
        passphraseField.click()
        assertNoSecrets(app, [password, phrase])
        try mark("passphraseHiddenAfterFocusChanges")
        keyMode.click()
        XCTAssertTrue((secureField(app, "direct-secret").value as? String ?? "").isEmpty, "password retained after mode switch")
        keyMode.click()
        XCTAssertTrue((secureField(app, "direct-passphrase").value as? String ?? "").isEmpty, "passphrase retained after mode switch")
        try mark("modeSwitchCleared")
        assertNoSecrets(app, [password, phrase])

        let back = app.buttons["Back"].exists ? app.buttons["Back"] : app.buttons["返回"]
        XCTAssertTrue(back.exists && back.isHittable, "back action missing")
        back.click()
        XCTAssertTrue(entry.waitForExistence(timeout: 10), "normal homepage did not return")
        assertNoSecrets(app, [password, phrase])
        entry.click()
        let reopened = secureField(app, "direct-secret")
        XCTAssertTrue((reopened.value as? String ?? "").isEmpty, "prior credential retained")
        assertNoSecrets(app, [password, phrase])
        try mark("returnAndReopenCleared")
        app.terminate()
    }
}
