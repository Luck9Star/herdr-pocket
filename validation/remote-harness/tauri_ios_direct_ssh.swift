import XCTest
import Foundation
import UIKit

// URLSession completion runs off the main actor. Synchronize its tiny reply
// explicitly; no callback captures a UI object or actor-isolated local state.
private final class CheckpointReply: @unchecked Sendable {
    private let lock = NSLock()
    private var accepted = false
    func set(_ value: Bool) { lock.lock(); accepted = value; lock.unlock() }
    func get() -> Bool { lock.lock(); defer { lock.unlock() }; return accepted }
}

// The fixture configuration is compiled only into the disposable UI-test driver.
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
        queue.underlyingQueue = DispatchQueue(label: "dev.herdrpocket.ui-checkpoint")
        let session = URLSession(configuration: .ephemeral, delegate: nil, delegateQueue: queue)
        defer { session.invalidateAndCancel() }
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
    private func button(_ label: String) -> XCUIElement { app.buttons[label].firstMatch }
    @MainActor
    private func field(_ label: String) -> XCUIElement { app.textFields[label].firstMatch }
    @MainActor
    private func portField() throws -> XCUIElement {
        // WKWebView can expose input[type=number] as a text field, a spin
        // control containing one, or an editable Other. Never select its label.
        let text = field("端口")
        if text.exists {
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
    private func password() -> XCUIElement { app.secureTextFields["密码"].firstMatch }
    @MainActor
    private func review() -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format:
            "(elementType == %d OR elementType == %d) AND (label CONTAINS %@)",
            XCUIElement.ElementType.checkBox.rawValue, XCUIElement.ElementType.switch.rawValue,
            "我已通过可信渠道独立核对以上指纹")).firstMatch
    }

    @MainActor
    private func reveal(_ item: XCUIElement) throws {
        try require(item.waitForExistence(timeout: 20), "native_control_missing")
        for _ in 0..<10 {
            let window = app.windows.firstMatch.frame
            var visible = window.insetBy(dx: 8, dy: 60)
            if app.keyboards.firstMatch.exists {
                visible.size.height = min(visible.maxY, app.keyboards.firstMatch.frame.minY) - visible.minY
            }
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
        let frames = Set(matches.map { NSStringFromCGRect($0.frame) })
        try require(!matches.isEmpty && frames.count == 1, "native_geometry_ambiguous")
        return matches[0]
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
            let actions = rows.filter { $0.elementType == .button && !$0.frame.intersection(safe).isEmpty }
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
    private func launchForm(port: Int) throws {
        try phase("launch")
        app.launch()
        try require(app.wait(for: .runningForeground, timeout: 30), "native_app_launch_failed")
        try phase("open_add")
        try tap(button("＋ 添加主机"))
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
        guard let data = Data(base64Encoded: "__HP_CONFIG_BASE64__"),
              let parsed = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
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
