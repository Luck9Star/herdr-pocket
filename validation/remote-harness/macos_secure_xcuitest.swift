import XCTest
import AppKit
import Darwin

@available(macOS 15.0, *)
final class SecureCredentialUITests: XCTestCase {
    override func tearDown() {
        XCUIApplication().terminate()
        super.tearDown()
    }

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

    private func formScroll(_ app: XCUIApplication) -> XCUIElement? {
        let window = app.windows.firstMatch
        guard window.exists else { return nil }
        return app.scrollViews.allElementsBoundByIndex.filter {
            $0.exists && $0.isHittable && !$0.frame.intersection(window.frame).isEmpty
        }.max {
            let a = $0.frame.intersection(window.frame), b = $1.frame.intersection(window.frame)
            return a.width * a.height < b.width * b.height
        }
    }

    private func scrollForm(_ app: XCUIApplication, _ amount: CGFloat) {
        let scroll = formScroll(app)
        let target = scroll ?? app.windows.firstMatch
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

    private func reveal(_ app: XCUIApplication, _ element: XCUIElement, phase: String = "control") {
        for _ in 0..<10 {
            if stableHit(element) { break }
            usleep(100_000)
        }
        if !stableHit(element) {
            for delta in [CGFloat(-240), -240, -240, -240, -240, 240, 240, 240, 240, 240, 240] {
                scrollForm(app, delta)
                if stableHit(element) { break }
            }
        }
        if !stableHit(element) {
            let exists = element.exists
            let window = app.windows.firstMatch
            let inside = exists && window.exists && element.frame.intersects(window.frame)
            print("HP_XCUI_HIT=phase:\(phase),exists:\(exists ? 1 : 0),enabled:\(exists && element.isEnabled ? 1 : 0),hittable:\(exists && element.isHittable ? 1 : 0),inside:\(inside ? 1 : 0)")
            fflush(stdout)
        }
        XCTAssertTrue(stableHit(element), "requested control is not hittable")
    }

    private func tap(_ app: XCUIApplication, _ element: XCUIElement, phase: String = "control") {
        reveal(app, element, phase: phase)
        XCTAssertTrue(element.isEnabled, "requested control is disabled")
        element.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).click()
    }

    // Use the same guarded real window-center click for controls obscured in AX hit testing.
    private func clickWindowCenter(_ app: XCUIApplication, matches: XCUIElementQuery) {
        XCTAssertEqual(matches.count, 1, "requested control is not unique")
        let button = matches.firstMatch
        let window = app.windows.firstMatch
        XCTAssertTrue(button.exists && button.isEnabled && window.exists && app.state == .runningForeground, "requested control unavailable")
        let frame = button.frame
        let windowFrame = window.frame
        let center = CGPoint(x: frame.midX, y: frame.midY)
        usleep(100_000)
        XCTAssertTrue(!frame.isEmpty && frame == button.frame && windowFrame == window.frame && frame.intersection(windowFrame).contains(center), "requested control center not stable and visible")
        let overlapping = app.secureTextFields.allElementsBoundByIndex.filter { $0.exists && $0.frame.contains(center) }.count
        XCTAssertEqual(overlapping, 0, "secure credential overlay obstructs requested control")
        let origin = window.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
        origin.withOffset(CGVector(dx: center.x - windowFrame.minX, dy: center.y - windowFrame.minY)).click()
    }

    private func clickFormButton(_ app: XCUIApplication, label: String) {
        let matches = app.buttons.matching(NSPredicate(format: "label == %@", label))
        XCTAssertEqual(matches.count, 1, "form action is not unique")
        let button = matches.firstMatch
        let window = app.windows.firstMatch
        for delta in [CGFloat(0), -240, -240, -240, -240, -240, 240, 240, 240, 240, 240] {
            if delta != 0 { scrollForm(app, delta) }
            guard button.exists && button.isEnabled && window.exists else { continue }
            let frame = button.frame
            let scroll = formScroll(app)
            let viewport = scroll.map { window.frame.intersection($0.frame) } ?? window.frame
            let center = CGPoint(x: frame.midX, y: frame.midY)
            guard !frame.isEmpty && viewport.contains(center) else { continue }
            usleep(100_000)
            let currentViewport = scroll.map { window.frame.intersection($0.frame) } ?? window.frame
            guard frame == button.frame && viewport == currentViewport && viewport.contains(center) else { continue }
            let blocked = app.secureTextFields.allElementsBoundByIndex.contains {
                $0.exists && !$0.frame.intersection(viewport).isEmpty && $0.frame.contains(center)
            }
            XCTAssertFalse(blocked, "secure credential overlay obstructs form action")
            if stableHit(button) {
                button.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).click()
            } else {
                let origin = window.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
                origin.withOffset(CGVector(dx: center.x - window.frame.minX, dy: center.y - window.frame.minY)).click()
            }
            return
        }
        let scroll = formScroll(app)
        let viewport = scroll.map { window.frame.intersection($0.frame) } ?? window.frame
        let center = CGPoint(x: button.frame.midX, y: button.frame.midY)
        let visible = button.exists && !button.frame.isEmpty && viewport.contains(center)
        print("HP_XCUI_FORM=phase:\(label == "粘贴私钥" ? "paste" : "connect"),count:\(min(matches.count, 9)),enabled:\(button.exists && button.isEnabled ? 1 : 0),hittable:\(button.exists && button.isHittable ? 1 : 0),inside:\(visible ? 1 : 0),scroll:\(scroll == nil ? 0 : 1)")
        fflush(stdout)
        XCTFail("form action center not visible and stable")
    }

    private func connectByWindowCenter(_ app: XCUIApplication) {
        clickFormButton(app, label: "连接 SSH")
    }

    private func keyInputBits(_ app: XCUIApplication) throws -> [Bool]? {
        let expression = try NSRegularExpression(pattern: "HPKEY:K([01])P([01])E([01])L([01])T([01])")
        for field in try snapshotNodes(app).flatMap({ [$0.label, $0.value as? String ?? ""] }) {
            guard let match = expression.firstMatch(in: field, range: NSRange(field.startIndex..., in: field)) else { continue }
            return (1...5).map { index in
                guard let range = Range(match.range(at: index), in: field) else { return false }
                return field[range] == "1"
            }
        }
        return nil
    }

    private func phraseMatches(_ app: XCUIApplication) throws -> Bool {
        let deadline = Date().addingTimeInterval(8)
        repeat {
            for delta in [CGFloat(0), -200, -200, -200, 200, 200, 200] {
                if delta != 0 { scrollForm(app, delta) }
                if try keyInputBits(app)?[1] == true { return true }
            }
        } while Date() < deadline
        return false
    }

    private func diagnoseKeyInputs(_ app: XCUIApplication) throws -> [Bool]? {
        let deadline = Date().addingTimeInterval(10)
        var bits: [Bool]?
        repeat {
            bits = try keyInputBits(app)
            if bits?[0] == true && bits?[1] == true { break }
            usleep(200_000)
        } while Date() < deadline
        let values = bits ?? Array(repeating: false, count: 5)
        print("HP_XCUI_KEYINPUT=visible:\(bits == nil ? 0 : 1),key:\(values[0] ? 1 : 0),passphrase:\(values[1] ? 1 : 0),empty:\(values[2] ? 1 : 0),length:\(values[3] ? 1 : 0),trimmed:\(values[4] ? 1 : 0)")
        fflush(stdout)
        return bits
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

    private func confirmFingerprint(_ app: XCUIApplication, phase: String) throws {
        let matches = app.buttons.matching(NSPredicate(format: "label == %@", "已核对并确认"))
        XCTAssertEqual(matches.count, 1, "fingerprint confirmation is not unique")
        let button = matches.firstMatch
        let window = app.windows.firstMatch
        XCTAssertTrue(button.exists && button.isEnabled && window.exists && app.state == .runningForeground, "fingerprint confirmation unavailable")
        let frame = button.frame
        let windowFrame = window.frame
        let center = CGPoint(x: frame.midX, y: frame.midY)
        XCTAssertTrue(!frame.isEmpty && frame == button.frame && windowFrame == window.frame && frame.intersection(windowFrame).contains(center), "fingerprint confirmation center not visible")
        let overlapping = app.secureTextFields.allElementsBoundByIndex.filter { $0.isHittable && $0.frame.contains(center) }.count
        let windowClick = !button.isHittable
        print("HP_XCUI_CONFIRM=phase:\(phase),windowclick:\(windowClick ? 1 : 0),secureoverlap:\(min(overlapping,10000))")
        fflush(stdout)
        XCTAssertEqual(overlapping, 0, "secure credential overlay obstructs fingerprint confirmation")
        if windowClick {
            clickWindowCenter(app, matches: matches)
        } else {
            tap(app, button, phase: phase + "Confirm")
        }
        XCTAssertTrue(button.waitForNonExistence(timeout: 15), "fingerprint dialog did not close")
        for _ in 0..<20 {
            let target = try targetDiagnostics(app, phase: phase + "Confirmed", emit: false)
            if target?.count == 13 && target?[12] == true { break }
            usleep(100_000)
        }
        let target = try targetDiagnostics(app, phase: phase + "Confirmed")
        XCTAssertTrue(target?.count == 13 && target?[12] == true, "fingerprint confirmation not reflected in form")
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
        let expression = try NSRegularExpression(pattern: "HPAX:H([01])P([01])K([01])U([01])V([01])B([01])F([01])E([01])A([01])N([01])T([01])D([01])C([01])")
        for field in fields {
            let range = NSRange(field.startIndex..., in: field)
            guard let match = expression.firstMatch(in: field, range: range) else { continue }
            let bits = (1...13).map { index -> String in
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
            if bits?.count == 13 && bits?[8] == true && bits?[9] == true && bits?[10] == true { break }
            usleep(100_000)
        }
        let bits = try targetDiagnostics(app, phase: phase)
        XCTAssertTrue(bits?.count == 13 && bits?[8] == true && bits?[9] == true && bits?[10] == true,
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
            if bits?.count == 13 && bits?[11] == true { break }
            usleep(100_000)
        }
        let cleared = try targetDiagnostics(app, phase: phase + "PortCleared")
        XCTAssertTrue(cleared?.count == 13 && cleared?[11] == true, "default port was not cleared")
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
        let preferred = buttons.matching(NSPredicate(format: "label == %@", "返回主机列表"))
        let exact = app.descendants(matching: .any).matching(NSPredicate(format: "label IN %@", ["返回主机列表", "Back", "返回", "后退", "上一页"]))
        let hittable = exact.allElementsBoundByIndex.filter { stableHit($0) }
        print("HP_XCUI_BACK=buttons:\(min(buttons.count,10000)),exact:\(min(exact.count,10000)),hittable:\(min(hittable.count,10000))")
        fflush(stdout)
        if preferred.count == 1 && stableHit(preferred.firstMatch) {
            tap(app, preferred.firstMatch, phase: "returnBack")
            mark("returnBackTapped");mark("returnButtonUsed")
        } else if hittable.count == 1 {
            tap(app, hittable[0], phase: "returnBack")
            mark("returnBackTapped");mark("returnButtonUsed")
        } else {
            app.typeKey(XCUIKeyboardKey.escape, modifierFlags: [])
            mark("returnEscapeUsed")
        }
        XCTAssertTrue(homeVisible(app), "normal homepage did not return")
        let entry = homeEntry(app)
        XCTAssertTrue(entry.exists, "normal homepage did not return")
        try assertNoSecrets(app, secrets)
        let matches = app.buttons.matching(NSPredicate(format: "label == %@", "普通 SSH"))
        if matches.count == 1 { clickWindowCenter(app, matches: matches) }
        else { tap(app, entry, phase: "returnReopenEntry") }
        mark("returnReopenEntryTapped")
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

    private var forcedEmbedder = false

    private func fixture() throws -> [String: Any] {
        guard let data = Data(base64Encoded: "__HP_FIXTURE_BASE64__"),
              let config = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              config["password"] is String, config["username"] is String,
              config["port"] is Int, config["fingerprint"] is String,
              config["keyPort"] is Int, config["keyFingerprint"] is String,
              config["privateKey"] is String, config["passphrase"] is String else {
            XCTFail("owned loopback fixture unavailable")
            throw NSError(domain: "fixture", code: 1)
        }
        mark("fixtureReadable")
        return config
    }

    private func homeVisible(_ app: XCUIApplication) -> Bool {
        let add = element(app, "配对添加")
        return add.waitForExistence(timeout: 15) && !element(app, "地址").exists
    }

    private func launchSSH(_ app: XCUIApplication, stage: String) {
        app.launchArguments = forcedEmbedder ? ["--herdr-xcui-embedder-semantics"] : []
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 20), "candidate app did not launch")
        mark("appLaunched")
        if !homeVisible(app) && !forcedEmbedder {
            app.terminate();forcedEmbedder = true
            app.launchArguments = ["--herdr-xcui-embedder-semantics"]
            mark("embedderFallbackRequested")
            app.launch()
            XCTAssertTrue(app.wait(for: .runningForeground, timeout: 20), "candidate app did not launch")
        }
        XCTAssertTrue(homeVisible(app), "normal homepage not confirmed")
        mark("homepage");mark(stage)
        let entry = homeEntry(app)
        XCTAssertTrue(entry.exists, "normal homepage SSH entry missing")
        if stage == "returnHomepage" {
            let matches = app.buttons.matching(NSPredicate(format: "label == %@", "普通 SSH"))
            if matches.count == 1 { clickWindowCenter(app, matches: matches) }
            else { tap(app, entry, phase: "returnEntry") }
            mark("returnEntryTapped")
        } else {
            tap(app, entry)
        }
    }

    private func connectedDisconnect(_ app: XCUIApplication) throws -> XCUIElement {
        let disconnect = app.buttons.matching(NSPredicate(format: "label == %@", "断开"))
        let deadline = Date().addingTimeInterval(30)
        repeat {
            let nodes = try snapshotNodes(app)
            let statusSeen = nodes.contains { node in
                [node.label, node.value as? String ?? ""].contains {
                    $0.contains("已连接 · 输入直接发送到远端 shell")
                }
            }
            let keysSeen = ["Esc", "Ctrl-C", "Enter"].allSatisfy { name in
                let button = app.buttons.matching(NSPredicate(format: "label == %@", name))
                return button.count == 1 && stableHit(button.firstMatch) && button.firstMatch.isEnabled
            }
            let connectedPage = statusSeen || (keysSeen && !element(app, "地址").exists)
            if connectedPage && disconnect.count == 1 && stableHit(disconnect.firstMatch) && disconnect.firstMatch.isEnabled {
                return disconnect.firstMatch
            }
            usleep(100_000)
        } while Date() < deadline
        XCTFail("connected page and usable disconnect action not confirmed")
        return disconnect.firstMatch
    }

    // The parent observes the independently owned peer while the app and driver remain alive.
    private func peerObservationWindow(_ phase: String) {
        mark(phase + "DisconnectTapped")
        usleep(15_000_000)
        mark(phase + "DisconnectWindowEnded")
    }

    func testSystemMasking() throws {
        continueAfterFailure = false
        let config = try fixture()
        let password = config["password"] as! String
        let phrase = config["passphrase"] as! String
        let app = XCUIApplication()
        launchSSH(app, stage: "maskingHomepage")
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
        app.terminate()
    }

    func testPasswordSSH() throws {
        continueAfterFailure = false
        let config = try fixture()
        let password = config["password"] as! String
        let phrase = config["passphrase"] as! String
        let username = config["username"] as! String
        let port = config["port"] as! Int
        let fingerprint = config["fingerprint"] as! String
        let app = XCUIApplication()
        launchSSH(app, stage: "passwordHomepage")
        try enterTarget(app, host: "127.0.0.1", port: port, username: username, phase: "password")
        mark("ordinaryInputReadable")
        let probe = app.buttons["探测并核对主机密钥"]
        reveal(app, probe)
        let passwordTarget = try targetDiagnostics(app, phase: "passwordBefore")
        XCTAssertTrue(passwordTarget?.count == 13 && passwordTarget?[0] == true && passwordTarget?[1] == true && passwordTarget?[3] == true && passwordTarget?[4] == true && passwordTarget?[5] == false && passwordTarget?[6] == true, "password target not confirmed")
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
        mark("passwordConfirmAttempt")
        try confirmFingerprint(app, phase: "password")
        mark("passwordConfirmed")
        mark("passwordCredentialAttempt")
        let loginPassword = secureField(app, "direct-secret")
        tap(app, loginPassword);app.typeText(password)
        try assertNoSecrets(app, [password, phrase])
        mark("passwordCredentialEntered")
        let connect = app.buttons["连接 SSH"]
        mark("passwordConnectAttempt")
        tap(app, connect, phase: "passwordConnect")
        let disconnect = try connectedDisconnect(app)
        mark("sshConnected")
        try assertNoSecrets(app, [password, phrase])
        mark("passwordDisconnectAttempt")
        usleep(3_000_000)
        tap(app, disconnect)
        peerObservationWindow("password")
        XCTAssertTrue((secureField(app, "direct-secret").value as? String ?? "").isEmpty, "password not cleared after disconnect")
        mark("disconnectedAndCleared")

        app.terminate()
    }

    func testEncryptedKeySSH() throws {
        continueAfterFailure = false
        let config = try fixture()
        let password = config["password"] as! String
        let phrase = config["passphrase"] as! String
        let username = config["username"] as! String
        let keyPort = config["keyPort"] as! Int
        let keyFingerprint = config["keyFingerprint"] as! String
        let privateKey = config["privateKey"] as! String
        let app = XCUIApplication()
        launchSSH(app, stage: "keyHomepage")
        try enterTarget(app, host: "127.0.0.1", port: keyPort, username: username, phase: "key")
        let keyProbe = app.buttons["探测并核对主机密钥"]
        reveal(app, keyProbe)
        let keyTarget = try targetDiagnostics(app, phase: "keyBefore")
        XCTAssertTrue(keyTarget?.count == 13 && keyTarget?[0] == true && keyTarget?[2] == true && keyTarget?[3] == true && keyTarget?[4] == true && keyTarget?[5] == false && keyTarget?[6] == true, "encrypted key target not confirmed")
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
        mark("keyConfirmAttempt")
        try confirmFingerprint(app, phase: "key")
        mark("keyConfirmed")
        mark("keyCredentialAttempt")
        tap(app, element(app, "使用私钥认证"))
        mark("keyMethodSelected")
        let keyPassphrase = secureField(app, "direct-passphrase")
        mark("keyPassphraseFound")
        tap(app, keyPassphrase);app.typeText(phrase)
        mark("keyPassphraseEntered")
        try assertNoSecrets(app, [password, phrase])
        var phraseConfirmed = try phraseMatches(app)
        if !phraseConfirmed {
            mark("keyPassphraseRetry")
            let field = secureField(app, "direct-passphrase")
            tap(app, field)
            XCTAssertTrue(field.hasKeyboardFocus, "passphrase retry focus not confirmed")
            app.typeKey("a", modifierFlags: .command)
            app.typeText(phrase)
            phraseConfirmed = try phraseMatches(app)
        }
        XCTAssertTrue(phraseConfirmed, "passphrase controller mismatch")
        mark("keyPassphraseConfirmed")
        let clipboard = NSPasteboard.general
        clipboard.clearContents()
        defer { clipboard.clearContents() }
        XCTAssertTrue(clipboard.setString(privateKey, forType: .string), "synthetic PEM pasteboard unavailable")
        mark("pemPasteButtonAttempt")
        clickFormButton(app, label: "粘贴私钥")
        mark("pemPasteButtonTapped")
        let pasted = try diagnoseKeyInputs(app)
        XCTAssertTrue(pasted?[0] == true && pasted?[1] == true, "pasted key and passphrase not confirmed")
        try assertNoSecrets(app, [password, phrase])
        mark("keyCredentialEntered")
        mark("keyConnectAttempt")
        connectByWindowCenter(app)
        let keyDisconnect = try connectedDisconnect(app)
        mark("encryptedKeyConnected")
        mark("keyDisconnectAttempt")
        usleep(3_000_000)
        tap(app, keyDisconnect)
        peerObservationWindow("key")
        XCTAssertTrue((secureField(app, "direct-passphrase").value as? String ?? "").isEmpty, "passphrase not cleared after disconnect")
        mark("encryptedKeyDisconnectedAndCleared")

        app.terminate()
    }

    func testReturnAndReopen() throws {
        continueAfterFailure = false
        let config = try fixture()
        let password = config["password"] as! String
        let phrase = config["passphrase"] as! String
        let app = XCUIApplication()
        launchSSH(app, stage: "returnHomepage")
        let field = secureField(app, "direct-secret")
        mark("returnSecureSelected")
        tap(app, field, phase: "returnSecure");app.typeText(password)
        mark("returnCredentialEntered")
        XCTAssertFalse((field.value as? String ?? "").isEmpty, "return input state unavailable")
        try assertNoSecrets(app, [password, phrase])
        try reopenSSH(app, secrets: [password, phrase])
        let reopened = secureField(app, "direct-secret")
        mark("returnReopenedSecureSelected")
        XCTAssertTrue((reopened.value as? String ?? "").isEmpty, "prior credential retained")
        try assertNoSecrets(app, [password, phrase])
        mark("returnAndReopenCleared")
        app.terminate()
    }
}
