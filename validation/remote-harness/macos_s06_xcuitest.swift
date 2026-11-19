import AppKit
import CoreGraphics
import Darwin
import XCTest

@available(macOS 15.0, *)
final class MacosS06UITests: XCTestCase {
    private typealias Peer = MacosS06Fixture.Peer
    private enum Failure: Error { case check(String) }
    private enum Scope: Equatable { case whole, sidebar, main, left, right }
    private lazy var app = XCUIApplication()
    private lazy var clipboard = NSPasteboard.general
    private var window: XCUIElement { app.windows.firstMatch }
    private var exchange: URL!

    private func require(_ condition: @autoclosure () -> Bool, _ code: String) throws {
        guard condition() else { throw Failure.check(code) }
    }

    private func until<T>(_ code: String, seconds: TimeInterval = 15, _ probe: () -> T?) throws -> T {
        let deadline = Date().addingTimeInterval(seconds)
        repeat {
            if let value = probe() { return value }
            Thread.sleep(forTimeInterval: 0.15)
        } while Date() < deadline
        throw Failure.check(code)
    }

    private func mark(_ stage: String) throws {
        do {
            try Data(stage.utf8).write(to: exchange.appendingPathComponent("stage"), options: .atomic)
        } catch {
            throw Failure.check("exchange_stage_write_failed")
        }
        trace("STAGE", stage)
    }

    private func trace(_ kind: String, _ token: String) {
        print("HP_S06_NATIVE_\(kind)=\(token)")
        fflush(stdout)
    }

    private func bounds(_ scope: Scope) -> CGRect {
        let frame = window.frame
        let start = frame.minX + 224
        let middle = (start + frame.maxX) / 2
        switch scope {
        case .whole: return frame
        case .sidebar: return CGRect(x: frame.minX, y: frame.minY, width: 224, height: frame.height)
        case .main: return CGRect(x: start, y: frame.minY, width: frame.maxX - start, height: frame.height)
        case .left: return CGRect(x: start, y: frame.minY, width: middle - start, height: frame.height)
        case .right: return CGRect(x: middle, y: frame.minY, width: frame.maxX - middle, height: frame.height)
        }
    }

    private func coordinate(_ x: CGFloat, _ y: CGFloat) -> XCUICoordinate {
        window.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
            .withOffset(CGVector(dx: x, dy: y))
    }

    private func query(_ name: String, kind: XCUIElement.ElementType = .any,
                       prefix: Bool = false) -> XCUIElementQuery {
        let condition = prefix ? "label BEGINSWITH %@ OR identifier BEGINSWITH %@" : "label == %@ OR identifier == %@"
        return app.descendants(matching: kind).matching(NSPredicate(format: condition, name, name))
    }

    private func matches(_ name: String, scope: Scope, kind: XCUIElement.ElementType = .any,
                         prefix: Bool = false) -> [XCUIElement] {
        let region = bounds(scope)
        return query(name, kind: kind, prefix: prefix).allElementsBoundByIndex.filter {
            let frame = $0.frame
            return $0.exists && !frame.isEmpty && region.contains(CGPoint(x: frame.midX, y: frame.midY))
        }
    }

    private func scroll(_ scope: Scope, _ amount: CGFloat) {
        let region = bounds(scope), frame = window.frame
        let x = scope == .whole || scope == .sidebar ? region.midX : region.minX + 11
        coordinate(x - frame.minX, region.midY - frame.minY).scroll(byDeltaX: 0, deltaY: amount)
    }

    private func reveal(_ name: String, in scope: Scope = .whole, kind: XCUIElement.ElementType = .any,
                        prefix: Bool = false, enabled: Bool = false) throws -> XCUIElement {
        func hit() -> XCUIElement? {
            let found = matches(name, scope: scope, kind: kind, prefix: prefix).filter {
                $0.isHittable && (!enabled || $0.isEnabled)
            }
            return found.count == 1 ? found[0] : nil
        }
        if let element = try? until("initial_control_unavailable", seconds: 4, hit) { return element }
        for direction in [CGFloat(-390), 390] {
            for _ in 0..<14 {
                scroll(scope, direction)
                Thread.sleep(forTimeInterval: 0.15)
                if let element = hit() { return element }
            }
        }
        throw Failure.check("unique_visible_control_missing")
    }

    private func click(_ name: String, in scope: Scope = .whole, kind: XCUIElement.ElementType = .button) throws {
        try reveal(name, in: scope, kind: kind, enabled: true).click()
    }

    private func paste(_ text: String, into label: String) throws {
        let field = try reveal(label, kind: .textField, enabled: true)
        field.click()
        clipboard.clearContents()
        try require(clipboard.setString(text, forType: .string), "public_clipboard_write_failed")
        app.typeKey("a", modifierFlags: .command)
        app.typeKey("v", modifierFlags: .command)
        _ = try until("public_value_not_read_back") { (field.value as? String) == text ? true : nil }
    }

    private func resize(_ width: CGFloat, height: CGFloat? = nil) throws -> Int {
        let before = window.frame
        if abs(before.width - width) > 2 {
            coordinate(before.width - 1, before.height / 2)
                .click(forDuration: 0.12, thenDragTo: coordinate(width - 1, before.height / 2))
        }
        _ = try until("native_window_width_not_reached") {
            abs(self.window.frame.width - width) <= 2 ? true : nil
        }
        if let height, abs(window.frame.height - height) > 2 {
            let frame = window.frame
            coordinate(frame.width / 2, frame.height - 1)
                .click(forDuration: 0.12, thenDragTo: coordinate(frame.width / 2, height - 1))
            _ = try until("native_window_height_not_reached") {
                abs(self.window.frame.height - height) <= 2 ? true : nil
            }
        }
        return Int(window.frame.width.rounded())
    }

    private func moveOwnedWindow() throws {
        let frame = window.frame
        let x = frame.width / 2
        coordinate(x, 13).click(forDuration: 0.12, thenDragTo:
            coordinate(x + 42 - frame.minX, 13 + 48 - frame.minY))
        _ = try until("native_window_origin_not_reached") {
            self.window.frame.minX < 65 && self.window.frame.minY < 95 ? true : nil
        }
    }

    private func request(_ peer: Peer, index: Int) throws {
        try click("配对添加", in: .main)
        let fields = [("SSH 主机 / IP", peer.host), ("SSH 端口", String(peer.port)),
                      ("主机账号", peer.username), ("命名会话（非 default）", peer.session),
                      ("命名会话 socket 绝对路径", peer.socketPath),
                      ("herdr 可执行文件绝对路径", peer.herdrPath),
                      ("可信渠道核验的 Ed25519 主机公钥", peer.expectedHostKey),
                      ("设备名称（英文、数字、空格）", peer.session)]
        for (label, value) in fields { try paste(value, into: label) }
        _ = try reveal(peer.fingerprint)
        try click("我已通过可信渠道核验账号、主机公钥与命名会话资料", kind: .checkBox)
        try mark(index == 0 ? "keyA" : "keyB")
        try click("在此设备创建独立身份并生成公开请求")
        clipboard.clearContents()
        try click("复制当前公开请求")
        let request = try until("public_request_unavailable") {
            guard let text = self.clipboard.string(forType: .string),
                  text.utf8.count <= 2048, text.starts(with: "{") else { return nil as String? }
            return text
        }
        try Data(request.utf8).write(to: exchange.appendingPathComponent("request-\(index).json"), options: .atomic)
        try mark(index == 0 ? "pairA" : "pairB")
        let responseURL = exchange.appendingPathComponent("response-\(index).json")
        let response = try until("reviewed_host_response_unavailable") {
            try? String(contentsOf: responseURL, encoding: .utf8)
        }
        try paste(response, into: "公开授权／撤销响应 JSON")
        _ = try reveal("待审查响应", prefix: true)
        try click("我已独立核验响应来源、账号与两端指纹", kind: .checkBox)
        try click("审查并接受绑定响应")
        _ = try reveal("主动审查连接并读取看板", kind: .button, enabled: true)
        try click("Back")
    }

    private func rowControl(_ control: String, after title: String, before other: String?,
                            in scope: Scope) throws -> XCUIElement {
        func hit() -> XCUIElement? {
            guard let anchor = matches(title, scope: scope).first else { return nil }
            let boundary = other.flatMap { self.matches($0, scope: scope).first?.frame.minY }
            let candidates = matches(control, scope: scope).filter {
                $0.isHittable && $0.isEnabled && $0.frame.midY > anchor.frame.midY &&
                    (boundary == nil || boundary! < anchor.frame.midY || $0.frame.midY < boundary!)
            }.sorted { $0.frame.minY < $1.frame.minY }
            return candidates.first
        }
        return try until("profile_row_control_missing", hit)
    }

    private func connect(_ peer: Peer, other: Peer) throws {
        try rowControl("新建观察视图", after: peer.title, before: other.title, in: .sidebar).click()
        try click("主动审查连接并读取看板", in: .main)
        try reveal("我已通过可信渠道核验主机公钥、账号与目标资料", in: .main,
                   kind: .checkBox, prefix: true, enabled: true).click()
        try click("核验并读取会话看板", in: .main)
        _ = try reveal(peer.binding, in: .main)
        try click("选择此 pane 观察", in: .main)
        _ = try reveal(peer.remoteTitle, in: .main)
    }

    private func checkLayout(left: Peer, right: Peer) throws {
        let l = try reveal(left.remoteTitle, in: .left), r = try reveal(right.remoteTitle, in: .right)
        try require(abs(l.frame.midY - r.frame.midY) <= 2 && l.frame.maxX < r.frame.minX,
                    "native_panels_not_side_by_side")
    }

    private func tick(_ peer: Peer, in scope: Scope) throws -> Int {
        let toggle = query("选择终端文本", kind: .button).allElementsBoundByIndex.contains {
            bounds(scope).contains(CGPoint(x: $0.frame.midX, y: $0.frame.midY))
        }
        if !toggle { try click("显示与选择工具", in: scope, kind: .any) }
        try click("选择终端文本", in: scope)
        _ = try reveal("\(peer.session) / \(peer.paneId) / \(peer.terminalId) · 打开时 seq", in: scope, prefix: true)
        let field = try reveal("终端可见区域文本 · 只读", in: scope, kind: .textField)
        let text = (field.value as? String) ?? ""
        let tokens = text.split(whereSeparator: { $0.isWhitespace })
        let matches = tokens.indices.dropLast().filter { tokens[$0] == peer.marker }
        try require(matches.count == 1, "native_visible_peer_marker_missing")
        let value = tokens[matches[0] + 1]
        try require(value.count == 6 && !text.contains(peer.marker == "HPS06A" ? "HPS06B" : "HPS06A"),
                    "native_visible_peer_marker_mismatch")
        guard let tick = Int(value), tick > 0 else { throw Failure.check("native_visible_tick_invalid") }
        try click("取消并清除文本", in: scope)
        return tick
    }

    private func checkStock(in scope: Scope) throws {
        for name in ["逐键输入", "草稿编辑"] {
            let mode = try reveal(name, in: scope)
            try require(!mode.isEnabled, "stock_input_mode_unexpectedly_enabled")
        }
    }

    private func pixels(_ element: XCUIElement) throws -> Data {
        // Read the real button highlight. XCUI's hasFocus attribute is tvOS-only.
        guard let image = NSBitmapImageRep(data: element.screenshot().pngRepresentation),
              let bytes = image.bitmapData, image.bytesPerPlane > 0 else {
            throw Failure.check("native_focus_pixels_unavailable")
        }
        return Data(bytes: bytes, count: image.bytesPerPlane)
    }

    private func selectWithKeys(_ peer: Peer, in scope: Scope) throws {
        let heading = try reveal("\(peer.title) · 观察中", in: scope, kind: .button)
        let unfocused = try pixels(heading)
        for _ in 0..<45 {
            app.typeKey(.tab, modifierFlags: [])
            Thread.sleep(forTimeInterval: 0.20)
            let focused = try pixels(heading)
            if focused == unfocused { continue }
            app.typeKey(.tab, modifierFlags: .shift)
            Thread.sleep(forTimeInterval: 0.20)
            let previous = try pixels(heading)
            try require(previous == unfocused, "native_reverse_tab_focus_not_observed")
            app.typeKey(.tab, modifierFlags: [])
            Thread.sleep(forTimeInterval: 0.20)
            let restored = try pixels(heading)
            try require(restored == focused, "native_forward_tab_focus_not_observed")
            app.typeKey(.return, modifierFlags: [])
            _ = try reveal("\(peer.title) · 输入焦点", in: scope, kind: .button)
            return
        }
        throw Failure.check("native_tab_focus_unreachable")
    }

    private func remove(_ peer: Peer, other: Peer) throws {
        try rowControl("管理", after: peer.title, before: other.title, in: .main).click()
        try click("删除本机资料与身份", in: .main)
        _ = try reveal("将删除“\(peer.title)”", prefix: true)
        try click("仅删除本机")
        _ = try until("deleted_temporary_profile_still_listed") {
            self.query(peer.title).count == 0 ? true : nil
        }
    }

    func testTwoPairedPeersInNativeWindow() throws {
        trace("STAGE", "entered")
        continueAfterFailure = false
        do {
            try exerciseTwoPairedPeers()
        } catch let Failure.check(code) {
            trace("FAILURE", code)
            throw Failure.check(code)
        } catch {
            trace("FAILURE", "unexpected_native_error")
            throw Failure.check("unexpected_native_error")
        }
    }

    private func exerciseTwoPairedPeers() throws {
        guard let pathData = Data(base64Encoded: "__HP_S06_EXCHANGE_BASE64__"),
              let path = String(data: pathData, encoding: .utf8) else {
            throw Failure.check("private_exchange_path_invalid")
        }
        exchange = URL(fileURLWithPath: path, isDirectory: true)
        trace("STAGE", "exchangeResolved")
        try mark("exchangeWritable")
        let release: Data
        do {
            release = try Data(contentsOf: exchange.appendingPathComponent("release.json"))
        } catch {
            throw Failure.check("private_release_read_failed")
        }
        try mark("releaseRead")
        let fixture: MacosS06Fixture
        do {
            fixture = try JSONDecoder().decode(MacosS06Fixture.self, from: release)
        } catch {
            throw Failure.check("private_release_decode_failed")
        }
        try mark("releaseDecoded")
        try require(fixture.hasIndependentTargets, "private_fixture_binding_invalid")
        let a = fixture.peers[0], b = fixture.peers[1]
        try mark("targetsValidated")
        try mark("display")
        let display = CGMainDisplayID()
        guard let original = CGDisplayCopyDisplayMode(display) else { throw Failure.check("display_unavailable") }
        if original.width < 1550 || original.height < 1000 {
            let modes = (CGDisplayCopyAllDisplayModes(display, nil) as? [CGDisplayMode]) ?? []
            guard let mode = modes.filter({ $0.width >= 1550 && $0.height >= 1000 })
                .min(by: { $0.width * $0.height < $1.width * $1.height }),
                  CGDisplaySetDisplayMode(display, mode, nil) == .success else {
                throw Failure.check("isolated_display_too_small")
            }
        }
        defer {
            app.terminate()
            clipboard.clearContents()
            _ = CGDisplaySetDisplayMode(display, original, nil)
        }
        try mark("homepage")
        app.launchArguments = ["--herdr-xcui-embedder-semantics"]
        app.launch()
        try require(window.waitForExistence(timeout: 15), "native_window_missing")
        try moveOwnedWindow()
        let start = try resize(1440, height: 900)
        _ = try reveal("配对添加", in: .main, kind: .button, enabled: true)
        try mark("pairA"); try request(a, index: 0)
        try mark("pairB"); try request(b, index: 1)
        try mark("connectA"); try connect(a, other: b)
        try click("主机看板", in: .sidebar)
        try mark("connectB"); try connect(b, other: a)
        try mark("split")
        try click("并排观察此标签", in: .sidebar)
        try checkLayout(left: b, right: a)
        try click("恢复原目标观察", in: .right)

        try mark("frames")
        let firstA = try tick(a, in: .right)
        let firstB = try tick(b, in: .left)
        let secondA = try tick(a, in: .right)
        let secondB = try tick(b, in: .left)
        try require(secondA > firstA && secondB > firstB, "native_visible_ticks_not_advancing")
        try checkStock(in: .left); try checkStock(in: .right)

        try mark("keyboard")
        try click("\(b.title) · 输入焦点", in: .left)
        try selectWithKeys(a, in: .right)
        _ = try reveal("\(b.title) · 观察中", in: .left, kind: .button)
        app.typeKey("x", modifierFlags: [])
        try mark("resize")
        let narrow = try resize(700)
        _ = try reveal("分屏空间不足", prefix: true)
        _ = try reveal(a.remoteTitle)
        try require(matches(b.remoteTitle, scope: .whole).isEmpty, "native_stowed_peer_still_visible")
        let returned = try resize(1440)
        try checkLayout(left: b, right: a)
        _ = try reveal("\(a.title) · 输入焦点", in: .right, kind: .button)
        _ = try reveal("\(b.title) · 已暂停", in: .left, kind: .button)
        try mark("resume")
        try click("恢复原目标观察", in: .left)
        let resumed = try tick(b, in: .left)
        try require(resumed > secondB, "native_resumed_peer_tick_not_fresh")
        try checkStock(in: .left); try checkStock(in: .right)
        try mark("stop")
        try Data([1]).write(to: exchange.appendingPathComponent("stop-requested"), options: .atomic)
        try click("停止并断开", in: .left)
        try click("停止并断开", in: .right)
        _ = try until("peer_close_unconfirmed_while_window_running") {
            FileManager.default.fileExists(atPath: self.exchange.appendingPathComponent("peers-closed").path)
                ? true : nil
        }
        try mark("remove")
        try click("主机看板", in: .sidebar)
        try remove(a, other: b)
        try remove(b, other: a)
        let checks = ["homepage", "reviewedPairings", "twoVisibleTargets", "bothTicksAdvanced",
                      "stockControlsDisabled", "keyboardFocus", "narrowStowed", "originalSidesRestored",
                      "explicitResume", "stoppedBoth", "localProfilesAbsentFromBoard"]
        let evidence: [String: Any] = ["widths": [start, narrow, returned],
                                       "checks": Dictionary(uniqueKeysWithValues: checks.map { ($0, true) })]
        try JSONSerialization.data(withJSONObject: evidence).write(to: exchange.appendingPathComponent("ui.json"),
                                                                    options: .atomic)
    }
}
