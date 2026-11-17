import XCTest
import Foundation
import CoreGraphics
import UIKit

// URLSession completion runs off the main actor. Synchronize its tiny reply
// explicitly; no callback captures a UI object or actor-isolated local state.
private final class CheckpointReply: @unchecked Sendable {
    private let lock = NSLock()
    private var accepted = false
    func set(_ value: Bool) { lock.lock(); accepted = value; lock.unlock() }
    func get() -> Bool { lock.lock(); defer { lock.unlock() }; return accepted }
}

// The fixture configuration is read from a private test-bundle resource at run time.
// The installed product receives normal taps/keystrokes and real SSH traffic.
final class TauriDirectSSHUITests: XCTestCase {
    private var config: [String: Any] = [:]
    private var app: XCUIApplication!
    private var scenario = "ordinary"
    private var nativePhase = "ordinary_launch"

    @MainActor
    private func require(_ condition: Bool, _ code: String) throws {
        if !condition {
            try? post("native_failure", ["nativeCheckpoint": nativePhase, "nativeFailureCode": code])
            throw NSError(domain: code, code: 1)
        }
    }

    @MainActor
    private func phase(_ name: String) throws {
        nativePhase = scenario + "_" + name
        try post("native_progress", ["nativeCheckpoint": nativePhase])
    }

    @MainActor
    private func post(_ stage: String, _ extra: [String: Any] = [:]) throws {
        var request = URLRequest(url: URL(string: config["checkpointURL"] as! String)!)
        request.httpMethod = "POST"
        request.timeoutInterval = 100
        request.setValue(config["checkpointSecret"] as? String, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: extra.merging(["stage": stage]) { _, new in new })
        let done = DispatchSemaphore(value: 0)
        // The callback never accesses XCTest or the product application.
        let reply = CheckpointReply()
        let queue = OperationQueue()
        let callbackQueue = DispatchQueue(label: "dev.herdrpocket.ui-checkpoint")
        queue.underlyingQueue = callbackQueue
        let session = URLSession(configuration: .ephemeral, delegate: nil, delegateQueue: queue)
        defer {
            session.invalidateAndCancel()
            withExtendedLifetime(callbackQueue) {}
        }
        let task = session.dataTask(with: request) { data, response, _ in
            if let http = response as? HTTPURLResponse, http.statusCode == 200,
               let data = data, let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                reply.set(value["ok"] as? Bool == true)
            }
            done.signal()
        }
        task.resume()
        let completed = done.wait(timeout: .now() + 105) == .success
        if !completed { task.cancel() }
        // Do not call require here: a network failure must not recurse while
        // reporting a native failure to the same checkpoint server.
        if !completed || !reply.get() { throw NSError(domain: "checkpoint_rejected", code: 1) }
    }

    @MainActor
    private func nodes() throws -> [any XCUIElementSnapshot] {
        var pending: [any XCUIElementSnapshot] = [try app.snapshot()]
        var result: [any XCUIElementSnapshot] = []
        while let node = pending.popLast() {
            result.append(node)
            try require(result.count < 10000, "native_tree_limit")
            pending.append(contentsOf: node.children)
        }
        return result
    }

    @MainActor
    private func texts(_ node: any XCUIElementSnapshot) -> [String] {
        [node.label, node.value as? String ?? ""]
    }

    @MainActor
    private func contains(_ text: String) throws -> Bool {
        try nodes().contains { texts($0).contains { $0.contains(text) } }
    }

    @MainActor
    private func waitText(_ text: String) throws {
        let deadline = Date().addingTimeInterval(40)
        repeat {
            if try contains(text) { return }
            Thread.sleep(forTimeInterval: 0.25)
        } while Date() < deadline
        try require(false, "native_expected_text_missing")
    }

    @MainActor
    private func button(_ label: String) -> XCUIElement {
        let identifiers = ["普通 SSH 终端": "add-ssh", "探测主机指纹": "ssh-probe",
            "打开键盘": "ssh-focus", "断开连接": "ssh-disconnect",
            "重新核对主机指纹": "ssh-key-recheck", "取消连接，保留旧信任": "ssh-key-cancel"]
        let query = app.buttons.matching(NSPredicate(format: "identifier == %@ OR label == %@", identifiers[label] ?? "", label))
        if query.count > 0 { return query.firstMatch }
        if let identifier = identifiers[label] {
            let byID = app.descendants(matching: .any).matching(identifier: identifier)
            if byID.count == 1 { return byID.firstMatch }
        }
        let byLabel = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", label))
        return byLabel.count == 1 ? byLabel.firstMatch : query.firstMatch
    }
    @MainActor
    private func field(_ label: String) -> XCUIElement {
        let identifier = ["主机地址": "ssh-host", "端口": "ssh-port", "用户名": "ssh-user"][label] ?? ""
        let typed = app.textFields.matching(NSPredicate(format: "identifier == %@ OR label == %@", identifier, label))
        if typed.count > 0 { return typed.firstMatch }
        let byID = app.descendants(matching: .any).matching(identifier: identifier)
        if byID.count == 1 && [.textField, .textView, .other].contains(byID.firstMatch.elementType) { return byID.firstMatch }
        let editable = app.descendants(matching: .any).matching(NSPredicate(format:
            "label == %@ AND (elementType == %d OR elementType == %d)", label,
            XCUIElement.ElementType.textView.rawValue, XCUIElement.ElementType.other.rawValue))
        return editable.count == 1 ? editable.firstMatch : typed.firstMatch
    }
    @MainActor
    private func portField() throws -> XCUIElement {
        // WKWebView can expose input[type=number] as a text field, a spin
        // control containing one, or an editable Other. Never select its label.
        let text = field("端口")
        if text.exists && text.elementType == .textField {
            try post("native_progress", ["nativeCheckpoint": nativePhase, "nativePortType": "textField"])
            return text
        }
        let stepper = app.steppers["端口"].firstMatch
        if stepper.exists && stepper.textFields.count == 1 {
            try post("native_progress", ["nativeCheckpoint": nativePhase, "nativePortType": "stepperTextField"])
            return stepper.textFields.firstMatch
        }
        let candidates = app.descendants(matching: .other).matching(NSPredicate(format:
            "(identifier == %@ OR label == %@) AND value == %@", "ssh-port", "端口", "22"))
        try require(candidates.count == 1, "native_port_control_ambiguous")
        try post("native_progress", ["nativeCheckpoint": nativePhase, "nativePortType": "other"])
        return candidates.firstMatch
    }
    @MainActor
    private func password() -> XCUIElement {
        app.secureTextFields.matching(NSPredicate(format: "identifier == %@ OR label == %@", "ssh-password", "密码")).firstMatch
    }
    @MainActor
    private func review() -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format:
            "(elementType == %d OR elementType == %d) AND (label CONTAINS %@)",
            XCUIElement.ElementType.checkBox.rawValue, XCUIElement.ElementType.switch.rawValue,
            "我已通过可信渠道独立核对以上指纹")).firstMatch
    }

    @MainActor
    private func visibleFrame() -> CGRect {
        var visible = app.windows.firstMatch.frame.insetBy(dx: 8, dy: 8)
        for bar in app.statusBars.allElementsBoundByIndex where bar.exists && bar.frame.intersects(visible) {
            let top = max(visible.minY, bar.frame.maxY)
            visible = CGRect(x: visible.minX, y: top, width: visible.width, height: visible.maxY - top)
        }
        if app.keyboards.firstMatch.exists {
            visible.size.height = min(visible.maxY, app.keyboards.firstMatch.frame.minY) - visible.minY
        }
        return visible
    }

    @MainActor
    private func reveal(_ item: XCUIElement) throws {
        try require(item.waitForExistence(timeout: 20), "native_control_missing")
        for _ in 0..<10 {
            let visible = visibleFrame()
            if item.isHittable && visible.contains(item.frame) { return }
            let web = app.webViews.firstMatch
            let surface = web.exists ? web : app.windows.firstMatch
            if item.frame.minY < visible.minY { surface.swipeDown() }
            else { surface.swipeUp() }
        }
        try require(false, "native_control_not_visible")
    }

    @MainActor
    private func tap(_ item: XCUIElement) throws {
        try reveal(item)
        try require(item.isEnabled, "native_control_disabled")
        item.tap()
    }

    @MainActor
    private func fill(_ item: XCUIElement, _ text: String) throws {
        try post("native_progress", ["nativeCheckpoint": nativePhase, "nativeInputRole": role(item.elementType)])
        try tap(item)
        let old = item.value as? String ?? ""
        // The only populated field is the initial two-character port. Native
        // delete keys replace it; no web script or clipboard is involved.
        try require(old.count <= 5, "native_unexpected_existing_input")
        try require(app.keyboards.firstMatch.waitForExistence(timeout: 10), "native_input_keyboard_missing")
        app.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: old.count) + text)
        if item.elementType != .secureTextField {
            try require(item.value as? String == text, "native_input_value_invalid")
        }
    }

    @MainActor
    private func check(_ expected: Bool, enabled: Bool) throws {
        let item = review()
        try require(item.waitForExistence(timeout: 10) && item.isEnabled == enabled,
                    "native_review_lock_invalid")
        let value = item.value as? String ?? ""
        try require(value == (expected ? "1" : "0"), "native_review_value_invalid")
    }

    @MainActor
    private func approve(_ fingerprint: String, excluding: String? = nil) throws {
        try waitText(fingerprint)
        if let excluding = excluding { try require(try !contains(excluding), "native_old_fingerprint_stale") }
        try check(false, enabled: true)
        try tap(review())
        try check(true, enabled: true)
    }

    @MainActor
    private func assertNoSecret(_ rows: [any XCUIElementSnapshot]) throws {
        let secrets = [config["ordinaryPassword"] as! String, config["rotationPassword"] as! String]
        try require(!rows.contains { node in
            ([node.identifier] + texts(node)).contains { value in secrets.contains { value.contains($0) } }
        }, "native_secret_exposed")
    }

    @MainActor
    private func target(_ port: Int) -> String { "fixture@127.0.0.1:\(port)" }
    @MainActor
    private func rect(_ value: CGRect) -> [Double] {
        [Double(value.minX), Double(value.minY), Double(value.width), Double(value.height)]
    }

    @MainActor
    private func exactNode(_ rows: [any XCUIElementSnapshot], _ text: String,
                           contains: Bool = false) throws -> any XCUIElementSnapshot {
        let matches = rows.filter { node in
            texts(node).contains { contains ? $0.contains(text) : $0 == text }
        }
        // Parent containers can repeat child labels: require one distinct frame.
        guard let first = matches.first else {
            try require(false, "native_geometry_ambiguous")
            throw NSError(domain: "native_geometry_ambiguous", code: 1)
        }
        try require(matches.allSatisfy { $0.frame == first.frame }, "native_geometry_ambiguous")
        return first
    }

    @MainActor
    private func safeFrame(_ rows: [any XCUIElementSnapshot]) throws -> CGRect {
        let windows = app.windows.allElementsBoundByIndex.filter { $0.exists && !$0.frame.isEmpty }
        try require(!windows.isEmpty, "native_window_missing")
        var frame = windows[0].frame
        let webs = rows.filter { $0.elementType == .webView && !$0.frame.isEmpty }
        try require(webs.count == 1, "native_webview_ambiguous")
        frame = frame.intersection(webs[0].frame)
        for bar in app.statusBars.allElementsBoundByIndex where bar.exists && bar.frame.intersects(frame) {
            let bottom = max(frame.minY, bar.frame.maxY)
            frame = CGRect(x: frame.minX, y: bottom, width: frame.width, height: frame.maxY - bottom)
        }
        for keyboard in app.keyboards.allElementsBoundByIndex where keyboard.exists && keyboard.frame.intersects(frame) {
            frame.size.height = keyboard.frame.minY - frame.minY
        }
        try require(!frame.isEmpty && !frame.isNull, "native_visible_frame_invalid")
        return frame
    }

    @MainActor
    private func screenshot(_ stage: String, port: Int, reviewPage: Bool = false) throws {
        let rows = try nodes()
        try assertNoSecret(rows)
        try require(!rows.contains { [.textField, .secureTextField].contains($0.elementType) },
                    "native_form_visible_in_capture")
        let safe = try safeFrame(rows)
        var extra: [String: Any] = ["safeFrame": rect(safe),
                                    "identityVerified": true, "noCredentialsVisible": true]
        if reviewPage {
            let labels = ["主机指纹发生变化", "已阻止连接与输入",
                          "旧：" + (config["fingerprintA"] as! String),
                          "新：" + (config["fingerprintB"] as! String), "目标：" + target(port),
                          "重新核对主机指纹", "取消连接，保留旧信任"]
            let frames = try labels.map { try exactNode(rows, $0).frame }
            try require(frames.allSatisfy { safe.contains($0) && !$0.isEmpty }, "native_review_clipped")
            let actions = rows.filter { $0.elementType == .button }
            try require(actions.count == 2 && Set(actions.map { $0.label }) == Set(labels.suffix(2)),
                        "native_review_exits_invalid")
            extra["reviewFrames"] = frames.map(rect)
        } else {
            let heading = try exactNode(rows, target(port) + " · SSH 已连接")
            let terminal = try exactNode(rows, "SSH 终端输出")
            try require(safe.contains(heading.frame) && !heading.frame.isEmpty,
                        "native_target_clipped")
            let crop = terminal.frame.intersection(safe)
            try require(!crop.isEmpty && !crop.intersects(heading.frame), "native_terminal_frame_invalid")
            extra["terminalFrame"] = rect(crop)
            extra["targetFrame"] = rect(heading.frame)
        }
        let screenFrame = app.frame
        try require(screenFrame.minX == 0 && screenFrame.minY == 0 && !screenFrame.isEmpty,
                    "native_screen_frame_invalid")
        let shot = XCUIScreen.main.screenshot()
        // Re-read the system tree to refuse layout movement across the capture.
        let after = try nodes()
        try require(try safeFrame(after) == safe && app.frame == screenFrame, "native_capture_geometry_changed")
        if !reviewPage {
            let before = try exactNode(rows, "SSH 终端输出").frame
            try require(try exactNode(after, "SSH 终端输出").frame == before,
                        "native_capture_geometry_changed")
        }
        extra["screenSize"] = [Double(screenFrame.width), Double(screenFrame.height)]
        extra["pngBase64"] = shot.pngRepresentation.base64EncodedString()
        try post(stage, extra)
    }

    @MainActor
    private func role(_ type: XCUIElement.ElementType) -> String {
        switch type {
        case .button: return "button"
        case .staticText: return "staticText"
        case .webView: return "webView"
        case .textField: return "textField"
        case .secureTextField: return "secureTextField"
        case .other: return "other"
        default: return "otherNative"
        }
    }

    @MainActor
    private func homeDiagnostics() throws -> [String: Any] {
        let rows = try nodes()
        let definitions: [(String, [String], [String])] = [
            ("brand", ["Herdr Pocket"], []),
            ("headerAdd", ["＋ 添加主机"], ["host-open-remote"]),
            ("emptyAdd", ["添加主机"], ["host-empty-add"]),
            ("homeHeading", ["主机与会话"], []),
            ("emptyHeading", ["还没有主机"], []),
            ("zeroHosts", ["0 台已存主机"], []),
            ("ordinaryShortcut", ["普通 SSH"], ["home-open-ssh"]),
            ("addHeading", ["添加连接"], []),
            ("sshOption", ["普通 SSH 终端"], ["add-ssh"])
        ]
        var members: [String: Any] = [:]
        for (key, labels, identifiers) in definitions {
            let matching = rows.filter { node in
                identifiers.contains(node.identifier) || texts(node).contains { labels.contains($0) }
            }
            members[key] = ["count": min(matching.count, 10000),
                            "roles": Array(Set(matching.map { role($0.elementType) })).sorted()]
        }
        let appAlerts = app.alerts.allElementsBoundByIndex
        let systemAlerts = XCUIApplication(bundleIdentifier: "com.apple.springboard").alerts.allElementsBoundByIndex
        let alertTerms: [(String, [String])] = [
            ("localNetwork", ["本地网络", "Local Network"]),
            ("allow", ["允许", "Allow"]), ("deny", ["不允许", "Don’t Allow", "Don't Allow"]),
            ("ok", ["好", "OK"]), ("automation", ["自动化", "Automation"])
        ]
        var alertMembers = Dictionary(uniqueKeysWithValues: alertTerms.map { ($0.0, false) })
        var alertSnapshotFailed = false
        for alert in appAlerts + systemAlerts {
            guard let snapshot = try? alert.snapshot() else { alertSnapshotFailed = true; continue }
            var pending: [any XCUIElementSnapshot] = [snapshot]
            var count = 0
            while let node = pending.popLast(), count < 1000 {
                count += 1; pending.append(contentsOf: node.children)
                for (key, terms) in alertTerms {
                    if texts(node).contains(where: { value in terms.contains { value.contains($0) } }) { alertMembers[key] = true }
                }
            }
        }
        let flags: [(String, [String])] = [
            ("connectionError", ["Could not connect to the server", "Could not connect to server", "无法连接到服务器"]),
            ("dnsError", ["hostname could not be found", "找不到服务器"]),
            ("webProcessError", ["WebKitErrorDomain", "NSURLErrorDomain"]),
            ("devURL", ["http://localhost:1420"]),
            ("browserPreview", ["浏览器预览"]),
            ("hostStorageError", ["本机主机资料不可用", "host_storage_unavailable", "host_path_bridge_unavailable"]),
            ("loading", ["正在读取主机资料…"])
        ]
        var errors: [String: Bool] = [:]
        for (key, terms) in flags {
            errors[key] = rows.contains { node in texts(node).contains { value in terms.contains { value.contains($0) } } }
        }
        let publicHomeText: Set<String> = [
            "Herdr Pocket", "HP", "herdr-pocket-tauri-probe", "herdr-pocket · 远端终端原型",
            "主导航", "看板", "终端", "网络", "设置", "主机与会话", "普通 SSH",
            "＋ 添加主机", "添加主机", "还没有主机", "添加主机后，在这里查看会话和任务状态。",
            "0 台已存主机", "正在读取主机资料…", "已存主机", "tauri://localhost", "tauri://localhost/",
            "0", "1", "2"
        ]
        let window = app.windows.firstMatch.frame
        let visible = rows.filter { !$0.frame.isEmpty && $0.frame.intersects(window) }
        let inputCount = rows.filter { [.textField, .secureTextField, .textView, .searchField].contains($0.elementType) }.count
        let unknownTextCount = visible.filter { node in
            texts(node).contains { !$0.isEmpty && !publicHomeText.contains($0) }
        }.count
        let member = { (key: String) -> Int in (members[key] as? [String: Any])?["count"] as? Int ?? 0 }
        let foreground = app.state == .runningForeground
        let webCount = app.webViews.count
        let safe = foreground && webCount == 1 && member("brand") > 0 && member("homeHeading") > 0 &&
            member("zeroHosts") > 0 && member("emptyHeading") > 0 && inputCount == 0 && unknownTextCount == 0 &&
            appAlerts.isEmpty && systemAlerts.isEmpty && !alertSnapshotFailed && errors.values.allSatisfy { !$0 }
        let result: [String: Any] = ["appForeground": foreground, "webViewCount": min(webCount, 10000),
            "windowCount": min(app.windows.count, 10000), "members": members, "knownErrors": errors,
            "appAlertCount": min(appAlerts.count, 10000), "systemAlertCount": min(systemAlerts.count, 10000),
            "alertMembers": alertMembers, "alertSnapshotFailed": alertSnapshotFailed,
            "inputCount": min(inputCount, 10000), "unknownVisibleTextCount": min(unknownTextCount, 10000),
            "knownEmptyHome": safe]
        return result
    }

    @MainActor
    private func openHomeAdd() throws {
        let candidates = app.buttons.matching(NSPredicate(format:
            "identifier IN %@ OR label IN %@", ["host-open-remote", "host-empty-add"], ["＋ 添加主机", "添加主机"]))
        try post("native_home", ["nativeCheckpoint": nativePhase, "home": try homeDiagnostics()])
        let deadline = Date().addingTimeInterval(40)
        repeat {
            let visible = visibleFrame()
            var selected = candidates.allElementsBoundByIndex.first(where: {
                $0.exists && $0.isEnabled && $0.isHittable && !$0.frame.isEmpty && visible.contains($0.frame)
            })
            var selection = "buttonRole"
            var kind = selected?.identifier == "host-empty-add" || selected?.label == "添加主机" ? "emptyAdd" : "headerAdd"
            if selected == nil {
                // Some WKWebView versions expose HTML buttons as Other/StaticText.
                // A unique exact product id or label plus a real hittable frame
                // permits a native element tap; coordinates are never invented.
                for (identifier, label, member) in [("host-open-remote", "＋ 添加主机", "headerAdd"),
                                                      ("host-empty-add", "添加主机", "emptyAdd")] {
                    let byID = app.descendants(matching: .any).matching(identifier: identifier)
                    let byLabel = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", label))
                    for (query, method) in [(byID, "uniqueIdentifier"), (byLabel, "uniqueLabel")] {
                        if query.count == 1 {
                            let item = query.firstMatch
                            if item.exists && item.isEnabled && item.isHittable && !item.frame.isEmpty && visible.contains(item.frame) {
                                selected = item; selection = method; kind = member; break
                            }
                        }
                    }
                    if selected != nil { break }
                }
            }
            if let item = selected {
                let originalRole = role(item.elementType)
                try tap(item)
                let pageDeadline = Date().addingTimeInterval(10)
                repeat {
                    let heading = try contains("添加连接")
                    let instruction = try contains("选择连接方式。")
                    let option = try contains("普通 SSH 终端")
                    if heading && instruction && option {
                        try post("native_home_entry", ["nativeCheckpoint": nativePhase, "member": kind,
                            "selection": selection, "role": originalRole, "enteredAddPage": true])
                        return
                    }
                    Thread.sleep(forTimeInterval: 0.25)
                } while Date() < pageDeadline
                try post("native_home", ["nativeCheckpoint": nativePhase, "home": try homeDiagnostics()])
                try require(false, "native_home_add_did_not_open_page")
            }
            Thread.sleep(forTimeInterval: 0.25)
        } while Date() < deadline
        let diagnostic = try homeDiagnostics()
        try post("native_home", ["nativeCheckpoint": nativePhase, "home": diagnostic])
        let members = diagnostic["members"] as! [String: [String: Any]]
        let errors = diagnostic["knownErrors"] as! [String: Bool]
        let anyAdd = (members["headerAdd"]?["count"] as? Int ?? 0) + (members["emptyAdd"]?["count"] as? Int ?? 0)
        var code = "native_home_add_missing"
        if diagnostic["appForeground"] as? Bool != true { code = "native_home_not_foreground" }
        else if (diagnostic["appAlertCount"] as? Int ?? 0) + (diagnostic["systemAlertCount"] as? Int ?? 0) > 0 { code = "native_home_alert_present" }
        else if diagnostic["webViewCount"] as? Int == 0 { code = "native_home_webview_missing" }
        else if errors.values.contains(true) { code = "native_home_known_loading_error" }
        else if members["brand"]?["count"] as? Int == 0 { code = "native_home_brand_missing" }
        else if candidates.count == 0 && anyAdd > 0 { code = "native_home_add_role_mismatch" }
        else if candidates.count > 0 && !candidates.allElementsBoundByIndex.contains(where: { $0.isEnabled }) { code = "native_home_add_disabled" }
        else if candidates.count > 0 { code = "native_home_add_not_hittable_or_wrong_page" }
        try require(false, code)
    }

    @MainActor
    private func launchForm(port: Int) throws {
        try phase("launch")
        app.launch()
        try require(app.wait(for: .runningForeground, timeout: 30), "native_app_launch_failed")
        try phase("open_add")
        try openHomeAdd()
        try phase("open_ssh")
        try tap(button("普通 SSH 终端"))
        try phase("host")
        try fill(field("主机地址"), "127.0.0.1")
        try phase("port")
        try fill(try portField(), String(port))
        try phase("username")
        try fill(field("用户名"), "fixture")
        try phase("probe")
        try tap(button("探测主机指纹"))
    }

    @MainActor
    private func connect(password secret: String) throws {
        try phase("password")
        try fill(password(), secret)
        try check(true, enabled: true)
        try phase("connect")
        try tap(button("连接 / 重新连接"))
        try waitText("已连接")
        try require(!password().exists, "native_credentials_visible_after_connect")
    }

    @MainActor
    private func terminal(_ stage: String, port: Int) throws {
        try phase("terminal_focus")
        try tap(button("打开键盘"))
        try require(app.keyboards.firstMatch.waitForExistence(timeout: 10), "native_terminal_keyboard_missing")
        // Exactly one UI typing operation. Checkpoints/OCR never replay it.
        try phase("terminal_input")
        app.typeText("hp-check\n")
        try post(stage + "_input")
        // Only wait for server output to render; no client buffers are used as proof.
        Thread.sleep(forTimeInterval: 2)
        let heading = app.staticTexts[target(port) + " · SSH 已连接"].firstMatch
        try tap(heading)
        try phase("terminal_capture")
        try screenshot(stage + "_terminal", port: port)
        try phase("disconnect")
        try post(stage + "_disconnect_attempt")
        try tap(button("断开连接"))
        try waitText("已断开")
        try post(stage + "_disconnected")
    }

    @MainActor
    func testOrdinaryAndKeyChange() throws {
        continueAfterFailure = false
        guard let url = Bundle(for: TauriDirectSSHUITests.self).url(forResource: "Fixture", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NSError(domain: "driver_config_invalid", code: 1)
        }
        config = parsed
        app = XCUIApplication(bundleIdentifier: config["bundleIdentifier"] as! String)
        XCUIDevice.shared.orientation = .portrait
        defer { app.terminate() }
        let ordinaryPort = config["ordinaryPort"] as! Int
        try post("ordinary_form")
        try launchForm(port: ordinaryPort)
        try post("ordinary_probe")
        try phase("fingerprint")
        try approve(config["ordinaryFingerprint"] as! String)
        try post("ordinary_password")
        try connect(password: config["ordinaryPassword"] as! String)
        try terminal("ordinary", port: ordinaryPort)
        app.terminate()

        let port = config["rotationPort"] as! Int
        scenario = "key_change"
        try post("key_change_form")
        try launchForm(port: port)
        try post("key_change_probe_a")
        try phase("fingerprint")
        try approve(config["fingerprintA"] as! String)
        try post("key_change_password_a")
        try phase("password")
        try fill(password(), config["rotationPassword"] as! String)
        try check(true, enabled: true)
        try phase("connect")
        try tap(button("连接 / 重新连接"))
        try waitText("主机指纹发生变化")
        try phase("review_capture")
        try screenshot("key_change_review", port: port, reviewPage: true)
        try phase("cancel")
        try tap(button("取消连接，保留旧信任"))
        try phase("cancel_check")
        try waitText("已保留的旧信任")
        try require(try contains(config["fingerprintA"] as! String), "native_cancel_lost_old_trust")
        try require(try !contains(config["fingerprintB"] as! String), "native_cancel_accepted_new_trust")
        try check(false, enabled: false)
        try require(password().exists && !password().isEnabled && (password().value as? String ?? "").isEmpty,
                    "native_cancel_credentials_live")
        try require(!button("连接 / 重新连接").isEnabled, "native_cancel_submit_live")
        try post("key_change_cancelled")
        try phase("reprobe")
        try tap(button("探测主机指纹"))
        try waitText(config["fingerprintB"] as! String)
        try require(try !contains(config["fingerprintA"] as! String), "native_reprobe_old_key_stale")
        try check(false, enabled: true)
        try require((password().value as? String ?? "").isEmpty, "native_reprobe_secret_stale")
        try post("key_change_probe_b")
        try phase("new_fingerprint")
        try approve(config["fingerprintB"] as! String, excluding: config["fingerprintA"] as? String)
        try post("key_change_password_b")
        try connect(password: config["rotationPassword"] as! String)
        try terminal("key_change", port: port)
        try post("complete")
    }
}
