import XCTest
import Darwin

@available(macOS 15.0, *)
final class SecureCredentialUITests: XCTestCase {
    private func mark(_ name: String) {
        print("HP_XCUI_STAGE=\(name)")
        fflush(stdout)
    }

    private func element(_ app: XCUIApplication, _ label: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: label).firstMatch
    }

    // One system snapshot per state; never print the tree or its values.
    private func snapshotNodes(_ app: XCUIApplication) throws -> [any XCUIElementSnapshot] {
        let root = try app.snapshot()
        var pending: [any XCUIElementSnapshot] = [root]
        var nodes: [any XCUIElementSnapshot] = []
        while let node = pending.popLast() {
            nodes.append(node)
            pending.append(contentsOf: node.children)
            if nodes.count > 10000 { XCTFail("system accessibility tree exceeds limit"); break }
        }
        XCTAssertGreaterThan(nodes.count, 5, "system accessibility tree is empty")
        return nodes
    }

    private func assertNoSecrets(_ app: XCUIApplication, _ secrets: [String]) throws {
        let nodes = try snapshotNodes(app)
        let exposed = nodes.contains { node in
            [node.label, node.identifier, node.value as? String ?? ""].contains { field in
                secrets.contains { field.contains($0) }
            }
        }
        XCTAssertFalse(exposed, "synthetic credential exposed in system accessibility tree")
    }

    private func stableHit(_ element: XCUIElement) -> Bool {
        guard element.exists && element.isHittable else { return false }
        let first = element.frame
        return !first.isEmpty && first == element.frame && element.isHittable
    }

    private func scrollForm(_ app: XCUIApplication, _ amount: CGFloat) {
        let scroll = app.scrollViews.firstMatch
        let target = scroll.exists && scroll.isHittable ? scroll : app.windows.firstMatch
        XCTAssertTrue(target.exists && target.isHittable, "form scroll target unavailable")
        target.scroll(byDeltaX: 0, deltaY: amount)
    }

    private func secureField(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
        let expected = identifier == "direct-secret" ? "密码（仅本次使用）" : "私钥口令（可选）"
        let phase = identifier == "direct-secret" ? "password" : "passphrase"
        let secure = app.secureTextFields
        let exact = secure.matching(NSPredicate(format: "identifier == %@", identifier))
        let all = app.descendants(matching: .any)
        let ids = all.matching(NSPredicate(format: "identifier == %@", identifier))
        let labels = all.matching(NSPredicate(format: "label == %@", expected))
        let secureLabels = secure.matching(NSPredicate(format: "label == %@", expected))
        for delta in [CGFloat(0), -240, -240, -240, -240, -240, 240, 240, 240, 240, 240, 240] {
            if delta != 0 { scrollForm(app, delta) }
            if exact.count == 1 && stableHit(exact.firstMatch) { return exact.firstMatch }
            if secure.count == 1 && secureLabels.count == 1 && stableHit(secureLabels.firstMatch) {
                return secureLabels.firstMatch
            }
        }
        print("HP_XCUI_SECURE=phase:\(phase),secure:\(min(secure.count,10000)),text:\(min(app.textFields.count,10000)),other:\(min(app.otherElements.count,10000)),id:\(min(ids.count,10000)),label:\(min(labels.count,10000)),securelabel:\(min(secureLabels.count,10000))")
        fflush(stdout)
        XCTFail("native secure field missing from system tree")
        return exact.firstMatch
    }

    private func reveal(_ app: XCUIApplication, _ element: XCUIElement) {
        if !stableHit(element) {
            for delta in [CGFloat(-240), -240, -240, -240, -240, 240, 240, 240, 240, 240, 240] {
                scrollForm(app, delta)
                if stableHit(element) { break }
            }
        }
        XCTAssertTrue(stableHit(element), "requested control is not hittable")
    }

    private func tap(_ app: XCUIApplication, _ element: XCUIElement) {
        reveal(app, element)
        XCTAssertTrue(element.isEnabled, "requested control is disabled")
        element.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).click()
    }

    private func ordinaryMetrics(_ app: XCUIApplication, sentinel: String) throws -> Bool {
        let nodes = try snapshotNodes(app)
        let values = nodes.compactMap { $0.value as? String }.filter { !$0.isEmpty }
        let seen = !sentinel.isEmpty && values.contains { $0.contains(sentinel) }
        print("HP_XCUI_ORDINARY=nodes:\(min(nodes.count,10000)),values:\(min(values.count,10000)),sentinel:\(seen ? 1 : 0)")
        fflush(stdout)
        XCTAssertGreaterThan(nodes.count, 5, "system accessibility tree is empty")
        return seen
    }

    private func verifyFingerprint(_ app: XCUIApplication, expected: String, phase: String) throws -> Bool {
        let nodes = try snapshotNodes(app)
        let fields = nodes.flatMap { [$0.label, $0.value as? String ?? ""] }
        let normalized = fields.map { $0.components(separatedBy: .whitespacesAndNewlines).joined() }
        let prefixes = normalized.filter { $0.contains("SHA256:") }.count
        let exact = normalized.filter { $0.contains(expected) }.count
        print("HP_XCUI_FINGERPRINT=phase:\(phase),nodes:\(min(nodes.count,10000)),prefix:\(min(prefixes,10000)),exact:\(min(exact,10000))")
        fflush(stdout)
        return exact > 0
    }

    private func typeOrdinaryOnce(_ app: XCUIApplication, field: XCUIElement, value: String, phase: String) throws {
        tap(app, field);app.typeText(value)
        var nodes = try snapshotNodes(app)
        for _ in 0..<20 {
            if nodes.contains(where: { ($0.value as? String ?? "") == value }) { break }
            usleep(100_000);nodes = try snapshotNodes(app)
        }
        let count = nodes.filter { ($0.value as? String ?? "") == value }.count
        print("HP_XCUI_INPUT=phase:\(phase),target:\(min(count,10000))")
        fflush(stdout)
        if count == 0 { try? targetDiagnostics(app, phase: "inputFailure") }
        XCTAssertGreaterThan(count, 0, "ordinary field target not read back")
    }

    @discardableResult
    private func targetDiagnostics(_ app: XCUIApplication, phase: String, emit: Bool = true) throws -> [Bool]? {
        let fields = try snapshotNodes(app).flatMap { [$0.label, $0.value as? String ?? ""] }
        let expression = try NSRegularExpression(pattern: "HPAX:H([01])P([01])K([01])U([01])V([01])B([01])F([01])E([01])A([01])N([01])T([01])D([01])")
        for field in fields {
            let range = NSRange(field.startIndex..., in: field)
            guard let match = expression.firstMatch(in: field, range: range) else { continue }
            let bits = (1...12).map { index -> String in
                guard let span = Range(match.range(at: index), in: field) else { return "0" }
                return String(field[span])
            }.joined()
            if emit { print("HP_XCUI_TARGET=phase:\(phase),bits:\(bits)"); fflush(stdout) }
            return bits.map { $0 == "1" }
        }
        if emit { print("HP_XCUI_TARGET=phase:\(phase),bits:missing"); fflush(stdout) }
        return nil
    }

    private func requireFreshForm(_ app: XCUIApplication, phase: String) throws {
        for _ in 0..<20 {
            let bits = try targetDiagnostics(app, phase: phase, emit: false)
            if bits?.count == 12 && bits?[8] == true && bits?[9] == true && bits?[10] == true { break }
            usleep(100_000)
        }
        let bits = try targetDiagnostics(app, phase: phase)
        XCTAssertTrue(bits?.count == 12 && bits?[8] == true && bits?[9] == true && bits?[10] == true,
                      "fresh ordinary form defaults unconfirmed")
    }

    private func enterTarget(_ app: XCUIApplication, host: String, port: Int, username: String, phase: String) throws {
        try requireFreshForm(app, phase: phase + "Fresh")
        mark(phase + "FreshVerified")
        let address = element(app, "地址").descendants(matching: .textField).firstMatch
        let portField = element(app, "端口").descendants(matching: .textField).firstMatch
        let userField = element(app, "用户名").descendants(matching: .textField).firstMatch
        try typeOrdinaryOnce(app, field: address, value: host, phase: phase + "Address")
        mark(phase + "AddressTyped")
        tap(app, portField)
        app.typeKey(XCUIKeyboardKey.end, modifierFlags: [])
        app.typeKey(XCUIKeyboardKey.delete, modifierFlags: [])
        app.typeKey(XCUIKeyboardKey.delete, modifierFlags: [])
        for _ in 0..<20 {
            let bits = try targetDiagnostics(app, phase: phase + "PortCleared", emit: false)
            if bits?.count == 12 && bits?[11] == true { break }
            usleep(100_000)
        }
        let cleared = try targetDiagnostics(app, phase: phase + "PortCleared")
        XCTAssertTrue(cleared?.count == 12 && cleared?[11] == true, "default port was not cleared")
        mark(phase + "PortCleared")
        app.typeText(String(port))
        var nodes = try snapshotNodes(app)
        for _ in 0..<20 {
            if nodes.contains(where: { ($0.value as? String ?? "") == String(port) }) { break }
            usleep(100_000);nodes = try snapshotNodes(app)
        }
        let portCount = nodes.filter { ($0.value as? String ?? "") == String(port) }.count
        print("HP_XCUI_INPUT=phase:\(phase)Port,target:\(min(portCount,10000))");fflush(stdout)
        XCTAssertGreaterThan(portCount, 0, "ordinary field target not read back")
        mark(phase + "PortTyped")
        try typeOrdinaryOnce(app, field: userField, value: username, phase: phase + "User")
        mark(phase + "UsernameTyped")
    }

    private func reopenSSH(_ app: XCUIApplication, secrets: [String]) throws {
        let buttons = app.buttons
        let exact = app.descendants(matching: .any).matching(NSPredicate(format: "label IN %@", ["Back", "返回", "后退", "上一页"]))
        let hittable = exact.allElementsBoundByIndex.filter { stableHit($0) }
        print("HP_XCUI_BACK=buttons:\(min(buttons.count,10000)),exact:\(min(exact.count,10000)),hittable:\(min(hittable.count,10000))")
        fflush(stdout)
        if hittable.count == 1 {
            tap(app, hittable[0])
            mark("returnButtonUsed")
        } else {
            app.typeKey(XCUIKeyboardKey.escape, modifierFlags: [])
            mark("returnEscapeUsed")
        }
        let entry = homeEntry(app)
        XCTAssertTrue(entry.exists && entry.isHittable, "normal homepage did not return")
        try assertNoSecrets(app, secrets)
        tap(app, entry)
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
              let fingerprint = fixture["fingerprint"] as? String,
              let keyPort = fixture["keyPort"] as? Int,
              let keyFingerprint = fixture["keyFingerprint"] as? String,
              let privateKey = fixture["privateKey"] as? String,
              let phrase = fixture["passphrase"] as? String else {
            XCTFail("owned loopback fixture unavailable")
            return
        }
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
        tap(app, entry)
        let address = element(app, "地址").descendants(matching: .textField).firstMatch
        XCTAssertTrue(address.waitForExistence(timeout: 15), "named address group or ordinary input missing")
        _ = try ordinaryMetrics(app, sentinel: "")
        let passwordField = secureField(app, "direct-secret")
        mark("passwordSecureField")
        tap(app, passwordField)
        app.typeText(password)
        mark((passwordField.value as? String ?? "").isEmpty ? "passwordValueUnavailable" : "passwordValuePresent")
        try assertNoSecrets(app, [password, phrase])
        mark("passwordHiddenFocused")
        tap(app, address)
        try assertNoSecrets(app, [password, phrase])
        mark("passwordHiddenBlurred")

        let keyMode = element(app, "使用私钥认证")
        tap(app, keyMode)
        let passphraseField = secureField(app, "direct-passphrase")
        mark("passphraseSecureField")
        tap(app, passphraseField)
        app.typeText(phrase)
        mark((passphraseField.value as? String ?? "").isEmpty ? "passphraseValueUnavailable" : "passphraseValuePresent")
        try assertNoSecrets(app, [password, phrase])
        tap(app, address)
        try assertNoSecrets(app, [password, phrase])
        tap(app, passphraseField)
        try assertNoSecrets(app, [password, phrase])
        mark("passphraseHiddenAfterFocusChanges")
        tap(app, keyMode)
        XCTAssertTrue((secureField(app, "direct-secret").value as? String ?? "").isEmpty, "password retained after mode switch")
        tap(app, keyMode)
        XCTAssertTrue((secureField(app, "direct-passphrase").value as? String ?? "").isEmpty, "passphrase retained after mode switch")
        mark("modeSwitchCleared")
        try assertNoSecrets(app, [password, phrase])

        tap(app, keyMode)
        let passwordAgain = secureField(app, "direct-secret")
        tap(app, passwordAgain);app.typeText(password)
        try assertNoSecrets(app, [password, phrase])
        mark("maskingScanCompleted")

        let sentinel = "hp-address-" + UUID().uuidString
        try typeOrdinaryOnce(app, field: address, value: sentinel, phase: "sentinel")
        mark("ordinarySentinelObserved")
        try reopenSSH(app, secrets: [password, phrase])
        try enterTarget(app, host: host, port: port, username: username, phase: "password")
        mark("ordinaryInputReadable")

        let probe = app.buttons["探测并核对主机密钥"]
        reveal(app, probe)
        let passwordTarget = try targetDiagnostics(app, phase: "passwordBefore")
        XCTAssertTrue(passwordTarget?.count == 12 && passwordTarget?[0] == true && passwordTarget?[1] == true && passwordTarget?[3] == true && passwordTarget?[4] == true && passwordTarget?[5] == false && passwordTarget?[6] == true, "password target not confirmed")
        tap(app, probe)
        mark("passwordProbeTapped")
        let confirm = app.buttons["已核对并确认"]
        let dialogPresent = confirm.waitForExistence(timeout: 20)
        try targetDiagnostics(app, phase: "passwordAfter")
        XCTAssertTrue(dialogPresent, "fingerprint confirmation unavailable")
        mark("passwordFingerprintDialog")
        let fingerprintMatches = try verifyFingerprint(app, expected: fingerprint, phase: "password")
        XCTAssertTrue(fingerprintMatches, "independently expected host fingerprint missing")
        mark("fingerprintVerified")
        tap(app, confirm)
        let loginPassword = secureField(app, "direct-secret")
        tap(app, loginPassword);app.typeText(password)
        try assertNoSecrets(app, [password, phrase])
        let connect = app.buttons["连接 SSH"]
        tap(app, connect)
        let connected = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "已连接 · 输入直接发送到远端 shell")).firstMatch
        XCTAssertTrue(connected.waitForExistence(timeout: 30), "native SSH session did not authenticate")
        mark("sshConnected")
        let disconnect = app.buttons["断开"]
        XCTAssertTrue(disconnect.waitForExistence(timeout: 10), "disconnect action missing")
        try assertNoSecrets(app, [password, phrase])
        tap(app, disconnect)
        XCTAssertTrue((secureField(app, "direct-secret").value as? String ?? "").isEmpty, "password not cleared after disconnect")
        mark("disconnectedAndCleared")

        try reopenSSH(app, secrets: [password, phrase])
        try enterTarget(app, host: host, port: keyPort, username: username, phase: "key")
        let keyProbe = app.buttons["探测并核对主机密钥"]
        reveal(app, keyProbe)
        let keyTarget = try targetDiagnostics(app, phase: "keyBefore")
        XCTAssertTrue(keyTarget?.count == 12 && keyTarget?[0] == true && keyTarget?[2] == true && keyTarget?[3] == true && keyTarget?[4] == true && keyTarget?[5] == false && keyTarget?[6] == true, "encrypted key target not confirmed")
        tap(app, keyProbe)
        mark("encryptedKeyProbeTapped")
        let keyConfirm = app.buttons["已核对并确认"]
        let keyDialogPresent = keyConfirm.waitForExistence(timeout: 20)
        try targetDiagnostics(app, phase: "keyAfter")
        XCTAssertTrue(keyDialogPresent, "fingerprint confirmation unavailable")
        mark("encryptedKeyFingerprintDialog")
        let keyFingerprintMatches = try verifyFingerprint(app, expected: keyFingerprint, phase: "encryptedKey")
        XCTAssertTrue(keyFingerprintMatches, "independently expected host fingerprint missing")
        mark("encryptedKeyFingerprintVerified")
        tap(app, keyConfirm)
        tap(app, element(app, "使用私钥认证"))
        let pemGroup = element(app, "私钥 PEM（仅本次使用）")
        reveal(app, pemGroup)
        let pemView = pemGroup.descendants(matching: .textView).firstMatch
        let pem = pemView.exists ? pemView : pemGroup.descendants(matching: .textField).firstMatch
        tap(app, pem);app.typeText(privateKey)
        let keyPassphrase = secureField(app, "direct-passphrase")
        tap(app, keyPassphrase);app.typeText(phrase)
        try assertNoSecrets(app, [password, phrase])
        let keyConnect = app.buttons["连接 SSH"]
        tap(app, keyConnect)
        let keyConnected = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "已连接 · 输入直接发送到远端 shell")).firstMatch
        XCTAssertTrue(keyConnected.waitForExistence(timeout: 30), "encrypted key session did not authenticate")
        mark("encryptedKeyConnected")
        let keyDisconnect = app.buttons["断开"]
        XCTAssertTrue(keyDisconnect.exists && keyDisconnect.isHittable, "disconnect action missing")
        tap(app, keyDisconnect)
        XCTAssertTrue((secureField(app, "direct-passphrase").value as? String ?? "").isEmpty, "passphrase not cleared after disconnect")
        mark("encryptedKeyDisconnectedAndCleared")

        try reopenSSH(app, secrets: [password, phrase])
        let reopened = secureField(app, "direct-secret")
        XCTAssertTrue((reopened.value as? String ?? "").isEmpty, "prior credential retained")
        try assertNoSecrets(app, [password, phrase])
        mark("returnAndReopenCleared")
        app.terminate()
    }
}
