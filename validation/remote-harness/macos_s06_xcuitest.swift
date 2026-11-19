import AppKit
import CoreGraphics
import Darwin
import XCTest

@available(macOS 15.0, *)
final class MacosS06UITests: XCTestCase {
    private typealias Peer = MacosS06Fixture.Peer
    private enum Failure: Error { case check(String) }
    private enum Scope: Equatable { case whole, sidebar, main, left, right }
    private enum PairControl: String {
        case entry, host, port, user, session, socket, herdr, hostKey, device, fingerprint
        case targetReview, create, copy, response, preview, sourceReview, accept, connect, back
    }
    private lazy var app = XCUIApplication()
    private lazy var clipboard = NSPasteboard.general
    private var window: XCUIElement { app.windows.firstMatch }
    private var channel: MacosS06Channel!

    private func require(_ condition: @autoclosure () -> Bool, _ code: String) throws {
        guard condition() else { throw Failure.check(code) }
    }

    private func until<T>(_ code: String, seconds: TimeInterval = 15, _ probe: () throws -> T?) throws -> T {
        let deadline = Date().addingTimeInterval(seconds)
        repeat {
            if let value = try probe() { return value }
            Thread.sleep(forTimeInterval: 0.15)
        } while Date() < deadline
        throw Failure.check(code)
    }

    private func mark(_ stage: String) {
        trace("STAGE", stage)
    }

    private func send(_ topic: MacosS06Channel.Topic, _ data: Data) throws {
        do { try channel.send(topic, data) }
        catch let failure as MacosS06Channel.Failure { throw Failure.check("private_channel_" + failure.rawValue) }
        catch { throw Failure.check("private_channel_send_failed") }
    }

    private func receive(_ topic: MacosS06Channel.Topic, or code: String) throws -> Data {
        try until(code) {
            do { return try self.channel.receive(topic) }
            catch let failure as MacosS06Channel.Failure { throw Failure.check("private_channel_" + failure.rawValue) }
            catch { throw Failure.check("private_channel_receive_failed") }
        }
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

    private func query(_ name: String, kind: XCUIElement.ElementType = .any, prefix: Bool = false,
                       root: XCUIElement? = nil, publicValue: Bool = false) -> XCUIElementQuery {
        let condition = prefix ? "label BEGINSWITH %@ OR identifier BEGINSWITH %@" : "label == %@ OR identifier == %@"
        let predicate = publicValue ? NSPredicate(format: "value == %@ OR label == %@", name, name)
                                    : NSPredicate(format: condition, name, name)
        return (root ?? app).descendants(matching: kind).matching(predicate)
    }

    private func within(_ region: CGRect, _ element: XCUIElement) -> Bool {
        let frame = element.frame
        return element.exists && !frame.isEmpty && region.contains(CGPoint(x: frame.midX, y: frame.midY))
    }

    private func matches(_ name: String, scope: Scope, kind: XCUIElement.ElementType = .any,
                         prefix: Bool = false, publicValue: Bool = false) -> [XCUIElement] {
        let region = bounds(scope)
        return query(name, kind: kind, prefix: prefix, root: publicValue ? window : nil, publicValue: publicValue)
            .allElementsBoundByIndex.filter { within(region, $0) }
    }

    private func scroll(_ scope: Scope, _ amount: CGFloat, pairing: Bool = false) {
        let region = bounds(scope), frame = window.frame
        // Pairing has nested, scrollable text editors. Wheel the outer form from its padding.
        let useCenter = scope == .sidebar || (scope == .whole && !pairing)
        let x = useCenter ? region.midX : region.minX + 11
        coordinate(x - frame.minX, region.midY - frame.minY).scroll(byDeltaX: 0, deltaY: amount)
    }

    private func pairMatches(_ name: String, kind: XCUIElement.ElementType, prefix: Bool, control: PairControl)
        -> (named: [XCUIElement], role: [XCUIElement]) {
        let named = query(name, prefix: prefix, root: window, publicValue: control == .fingerprint)
            .allElementsBoundByIndex
        if kind == .textField {
            // The macOS editable proxy does not expose the Flutter field label.
            guard named.count == 1, named[0].elementType != .textField else { return (named, []) }
            return (named, named[0].descendants(matching: .textField).allElementsBoundByIndex)
        }
        return (named, named.filter { kind == .any || $0.elementType == kind })
    }

    private func tracePairAX(_ name: String, kind: XCUIElement.ElementType, scope: Scope,
                             prefix: Bool, control: PairControl) {
        let (named, role) = pairMatches(name, kind: kind, prefix: prefix, control: control)
        let region = bounds(scope)
        let inRegion = role.filter { within(region, $0) }
        let hits = inRegion.filter(\.isHittable)
        let groups = named.filter { $0.elementType != .textField && $0.elementType != .textView }
        let editableChildren = groups.prefix(9).reduce(0) {
            $0 + $1.descendants(matching: .textField).count + $1.descendants(matching: .textView).count
        }
        func formHits(_ title: String, prefix: Bool = false) -> Int {
            query(title, prefix: prefix, root: window).allElementsBoundByIndex
                .filter { within(window.frame, $0) && $0.isHittable }.count
        }
        let counts = [named.count, role.count, inRegion.count, hits.count, hits.filter(\.isEnabled).count,
                      named.filter { $0.elementType == .textView }.count, editableChildren,
                      formHits("设备配对"), formHits("此平台的设备安全存储桥不可用", prefix: true)]
        trace("PAIR_AX", ([control.rawValue] + counts.map { String(min($0, 99)) }).joined(separator: ","))
    }

    private func reveal(_ name: String, in scope: Scope = .whole, kind: XCUIElement.ElementType = .any,
                        prefix: Bool = false, enabled: Bool = false, pair control: PairControl? = nil,
                        publicValue: Bool = false, missing: String = "unique_visible_control_missing") throws -> XCUIElement {
        if let control { trace("PAIR_CONTROL", control.rawValue) }
        func hit() -> XCUIElement? {
            let candidates: [XCUIElement]
            if let control {
                let region = bounds(scope)
                let role = pairMatches(name, kind: kind, prefix: prefix, control: control).role
                if kind == .textField && role.count != 1 { return nil }
                candidates = role.filter { within(region, $0) }
            } else {
                candidates = matches(name, scope: scope, kind: kind, prefix: prefix, publicValue: publicValue)
            }
            let found = candidates.filter { $0.isHittable && (!enabled || $0.isEnabled) }
            return found.count == 1 ? found[0] : nil
        }
        if let element = try? until("initial_control_unavailable", seconds: 4, hit) { return element }
        for direction in [CGFloat(-390), 390] {
            for _ in 0..<14 {
                scroll(scope, direction, pairing: control != nil)
                Thread.sleep(forTimeInterval: 0.15)
                if let element = hit() { return element }
            }
        }
        if let control { tracePairAX(name, kind: kind, scope: scope, prefix: prefix, control: control) }
        throw Failure.check(missing)
    }

    private func click(_ name: String, in scope: Scope = .whole, kind: XCUIElement.ElementType = .button,
                       pair control: PairControl? = nil) throws {
        try reveal(name, in: scope, kind: kind, enabled: true, pair: control).click()
    }

    private func currentPairField(_ label: String, control: PairControl)
        -> (owner: XCUIElement, field: XCUIElement)? {
        guard app.state == .runningForeground, app.windows.count == 1, window.exists else { return nil }
        let (named, fields) = pairMatches(label, kind: .textField, prefix: false, control: control)
        guard named.count == 1, fields.count == 1 else { return nil }
        let field = fields[0]
        guard within(window.frame, field), within(named[0].frame, field),
              field.isHittable, field.isEnabled else { return nil }
        return (named[0], field)
    }

    private func enterPublicValue(_ text: String, into label: String, pair control: PairControl) throws {
        let target = try reveal(label, kind: .textField, enabled: true, pair: control)
        let code = control.rawValue
        trace("PAIR_INPUT", "\(code),click")
        target.click()
        let before = try until("public_pair_field_owner_lost", seconds: 4) {
            self.currentPairField(label, control: control)
        }
        func exact(_ value: String?) -> Bool { value?.utf8.elementsEqual(text.utf8) == true }
        let ownerBeforeExact = exact(before.field.value as? String)
        before.field.typeKey("a", modifierFlags: .command)
        trace("PAIR_INPUT", "\(code),typing")
        // XCTest requires keyboard focus on the element or its descendant.
        // Send the fixture value once, to the named field's own native control.
        before.field.typeText(text)
        trace("PAIR_INPUT", "\(code),typed")
        let after = try until("public_pair_field_owner_lost", seconds: 4) {
            self.currentPairField(label, control: control)
        }
        let ownerAfterExact = exact(after.field.value as? String)
        let editors = after.owner.descendants(matching: .textView).allElementsBoundByIndex
            .filter { within(after.owner.frame, $0) }
        let editorExact = editors.count == 1 && exact(editors[0].value as? String)
        // Only the isolated runner reaches this code. Discard any earlier
        // pasteboard content and compare only an actual copy from the live editor.
        clipboard.clearContents()
        let cleared = clipboard.changeCount
        var changed = false
        var copyExact = false
        defer {
            clipboard.clearContents()
            let bits = [ownerBeforeExact, ownerAfterExact, editors.count == 1, editorExact, changed, copyExact]
                .map { $0 ? "1" : "0" }.joined()
            trace("PAIR_READ", "\(code),\(bits)")
        }
        trace("PAIR_INPUT", "\(code),copy")
        after.field.typeKey("a", modifierFlags: .command)
        after.field.typeKey("c", modifierFlags: .command)
        _ = try until("public_value_not_read_back") {
            changed = self.clipboard.changeCount != cleared
            if changed { copyExact = exact(self.clipboard.string(forType: .string)) }
            return copyExact ? true : nil
        }
        try require(currentPairField(label, control: control) != nil, "public_pair_field_owner_lost")
        trace("PAIR_INPUT", "\(code),verified")
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
        try click("配对添加", in: .main, pair: .entry)
        let fields: [(PairControl, String, String)] = [
            (.host, "SSH 主机 / IP", peer.host),
            (.port, "SSH 端口", String(peer.port)),
            (.user, "主机账号", peer.username),
            (.session, "命名会话（非 default）", peer.session),
            (.socket, "命名会话 socket 绝对路径", peer.socketPath),
            (.herdr, "herdr 可执行文件绝对路径", peer.herdrPath),
            (.hostKey, "可信渠道核验的 Ed25519 主机公钥", peer.expectedHostKey),
            (.device, "设备名称（英文、数字、空格）", peer.session),
        ]
        for (control, label, value) in fields { try enterPublicValue(value, into: label, pair: control) }
        _ = try reveal(peer.fingerprint, kind: .staticText, pair: .fingerprint)
        try click("我已通过可信渠道核验账号、主机公钥与命名会话资料", kind: .checkBox, pair: .targetReview)
        mark(index == 0 ? "keyA" : "keyB")
        try click("在此设备创建独立身份并生成公开请求", pair: .create)
        clipboard.clearContents()
        try click("复制当前公开请求", pair: .copy)
        let request = try until("public_request_unavailable") {
            guard let text = self.clipboard.string(forType: .string),
                  text.utf8.count <= 2048, text.starts(with: "{") else { return nil as String? }
            return text
        }
        try send(index == 0 ? .request0 : .request1, Data(request.utf8))
        mark(index == 0 ? "pairA" : "pairB")
        let payload = try receive(index == 0 ? .response0 : .response1, or: "reviewed_host_response_unavailable")
        guard let response = String(data: payload, encoding: .utf8) else {
            throw Failure.check("reviewed_host_response_invalid")
        }
        try enterPublicValue(response, into: "公开授权／撤销响应 JSON", pair: .response)
        _ = try reveal("待审查响应", prefix: true, pair: .preview)
        try click("我已独立核验响应来源、账号与两端指纹", kind: .checkBox, pair: .sourceReview)
        try click("审查并接受绑定响应", pair: .accept)
        _ = try reveal("主动审查连接并读取看板", kind: .button, enabled: true, pair: .connect)
        try click("Back", pair: .back)
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
        // The macOS embedder publishes the read-only field as static text and
        // its AXValue holds the label. Read the frozen screen via its normal Copy action.
        let field = try reveal("终端可见区域文本 · 只读", in: scope, kind: .staticText, publicValue: true,
                               missing: "native_visible_snapshot_field_unavailable")
        field.click()
        app.typeKey("a", modifierFlags: .command)
        clipboard.clearContents()
        let empty = clipboard.changeCount
        defer { clipboard.clearContents() }
        try reveal("复制选区", in: scope, kind: .button, enabled: true,
                   missing: "native_visible_snapshot_copy_control_unavailable").click()
        let text = try until("native_visible_snapshot_copy_unavailable") {
            guard self.clipboard.changeCount != empty,
                  let value = self.clipboard.string(forType: .string),
                  0 < value.utf8.count, value.utf8.count <= 65536 else { return nil as String? }
            return value
        }
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

    private func advancingResumedTick(_ peer: Peer, in scope: Scope, after previous: Int) throws -> Int {
        try until("native_resumed_peer_tick_not_fresh") {
            let next = try self.tick(peer, in: scope)
            return next > previous ? next : nil
        }
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
        do { channel = try MacosS06Channel(nonce: "__HP_S06_CHANNEL_NONCE__", party: .test) }
        catch { throw Failure.check("private_channel_scope_invalid") }
        mark("channelConfigured")
        let release = try receive(.release, or: "private_release_unavailable")
        mark("releaseRead")
        let fixture: MacosS06Fixture
        do {
            fixture = try JSONDecoder().decode(MacosS06Fixture.self, from: release)
        } catch {
            throw Failure.check("private_release_decode_failed")
        }
        mark("releaseDecoded")
        try require(fixture.hasIndependentTargets, "private_fixture_binding_invalid")
        let a = fixture.peers[0], b = fixture.peers[1]
        mark("targetsValidated")
        let challenge = Data(UUID().uuidString.lowercased().utf8)
        try send(.testReady, challenge)
        let receipt = try receive(.hostReady, or: "private_channel_receipt_missing")
        try require(receipt == challenge, "private_channel_receipt_mismatch")
        mark("channelRoundTrip")
        mark("display")
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
        mark("homepage")
        app.launchArguments = ["--herdr-xcui-embedder-semantics"]
        app.launch()
        try require(window.waitForExistence(timeout: 15), "native_window_missing")
        try moveOwnedWindow()
        let start = try resize(1440, height: 900)
        _ = try reveal("配对添加", in: .main, kind: .button, enabled: true)
        mark("pairA"); try request(a, index: 0)
        mark("pairB"); try request(b, index: 1)
        mark("connectA"); try connect(a, other: b)
        try click("主机看板", in: .sidebar)
        mark("connectB"); try connect(b, other: a)
        mark("split")
        try click("并排观察此标签", in: .sidebar)
        try checkLayout(left: b, right: a)
        try click("恢复原目标观察", in: .right)

        mark("frames")
        let firstA = try tick(a, in: .right)
        let firstB = try tick(b, in: .left)
        let secondA = try tick(a, in: .right)
        let secondB = try tick(b, in: .left)
        try require(secondA > firstA && secondB > firstB, "native_visible_ticks_not_advancing")
        try checkStock(in: .left); try checkStock(in: .right)

        mark("keyboard")
        try click("\(b.title) · 输入焦点", in: .left)
        try selectWithKeys(a, in: .right)
        _ = try reveal("\(b.title) · 观察中", in: .left, kind: .button)
        app.typeKey("x", modifierFlags: [])
        let beforeNarrow = try tick(b, in: .left)
        mark("resize")
        let narrow = try resize(700)
        _ = try reveal("分屏空间不足", prefix: true)
        _ = try reveal(a.remoteTitle)
        try require(matches(b.remoteTitle, scope: .whole).isEmpty, "native_stowed_peer_still_visible")
        let returned = try resize(1440)
        try checkLayout(left: b, right: a)
        _ = try reveal("\(a.title) · 输入焦点", in: .right, kind: .button)
        mark("autoResume")
        _ = try reveal("\(b.title) · 观察中", in: .left, kind: .button)
        // Selection is only enabled on a live frame. Each copy opens a new
        // bound snapshot; a retained old screen cannot advance both samples.
        let firstRestored = try advancingResumedTick(b, in: .left, after: beforeNarrow)
        let secondRestored = try advancingResumedTick(b, in: .left, after: firstRestored)
        _ = try reveal("\(a.title) · 输入焦点", in: .right, kind: .button)
        _ = try reveal("\(b.title) · 观察中", in: .left, kind: .button)
        try checkStock(in: .left); try checkStock(in: .right)
        mark("stop")
        try send(.stopRequested, Data([1]))
        try click("停止并断开", in: .left)
        try click("停止并断开", in: .right)
        let closed = try receive(.peersClosed, or: "peer_close_unconfirmed_while_window_running")
        try require(closed == Data([1]), "peer_close_receipt_invalid")
        mark("remove")
        try click("主机看板", in: .sidebar)
        try remove(a, other: b)
        try remove(b, other: a)
        let checks = ["homepage", "reviewedPairings", "twoVisibleTargets", "bothTicksAdvanced",
                      "stockControlsDisabled", "keyboardFocus", "narrowStowed", "originalSidesRestored",
                      "autoResumedOriginalObservation", "stoppedBoth", "localProfilesAbsentFromBoard", "channelRoundTrip"]
        let evidence: [String: Any] = ["widths": [start, narrow, returned],
                                       "autoResumeTicks": [beforeNarrow, firstRestored, secondRestored],
                                       "checks": Dictionary(uniqueKeysWithValues: checks.map { ($0, true) })]
        try send(.result, JSONSerialization.data(withJSONObject: evidence))
    }
}
