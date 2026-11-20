import XCTest
import Foundation
import CoreGraphics
import UIKit
import Vision

// BEGIN NATIVE FRAME POLICY -- real Foundation/CoreGraphics, no UI substitutes.
enum NativeFramePolicy {
    enum ScrollDirection: String { case swipeUp = "swipe_up", swipeDown = "swipe_down" }

    enum GeometryFailure: String, Error {
        case windowInvalid = "window_invalid"
        case screenInvalid = "screen_invalid"
        case webAncestorInvalid = "web_ancestor_invalid"
        case viewportEmpty = "viewport_empty"
        case fieldInvalid = "field_invalid"
        case fieldOutside = "field_outside"
        case fieldOccluded = "field_occluded"
        case fieldUnhittable = "field_unhittable"
        case queriedUnhittable = "queried_unhittable"
        case boundUnhittable = "bound_unhittable"
        case scrollDirectionUnproven = "scroll_direction_unproven"
        case scrollSurfaceUnhittable = "scroll_surface_unhittable"
        case scrollNoProgress = "scroll_no_progress"

        var canRetryTap: Bool {
            [.fieldOutside, .fieldOccluded, .fieldUnhittable, .queriedUnhittable, .boundUnhittable].contains(self)
        }
    }

    static func valid(_ value: CGRect) -> Bool {
        [value.minX, value.minY, value.width, value.height].allSatisfy { $0.isFinite } && !value.isEmpty && !value.isNull
    }
    static func diagnosticRect(_ frame: CGRect?) -> Any {
        guard let frame = frame else { return NSNull() }
        let values = [frame.minX, frame.minY, frame.width, frame.height]
        guard values.allSatisfy({ $0.isFinite && abs($0) <= 10000 }), frame.width >= 0, frame.height >= 0 else {
            return NSNull()
        }
        return values.map { Int($0.rounded()) }
    }
    static func unique(_ values: [CGRect]) -> [CGRect] {
        values.reduce(into: []) { if !$0.contains($1) { $0.append($1) } }
    }
    static func sameOwner(windowPaths: [[Int]], webPaths: [[Int]]) -> Bool {
        guard let window = windowPaths.first, let web = webPaths.first,
              windowPaths.count == webPaths.count else { return false }
        return windowPaths.allSatisfy { $0 == window } && webPaths.allSatisfy { $0 == web }
    }
    static func compatibleOwner(windowPaths: [[Int]], webPaths: [[Int]], nodePaths: [[Int]], selected: Int) -> Bool {
        guard windowPaths.count == webPaths.count, webPaths.count == nodePaths.count,
              nodePaths.indices.contains(selected) else { return false }
        return nodePaths.indices.allSatisfy { index in
            windowPaths[index] == windowPaths[selected] && (webPaths[index] == webPaths[selected] ||
                (nodePaths[index].count < nodePaths[selected].count &&
                 Array(nodePaths[selected].prefix(nodePaths[index].count)) == nodePaths[index]))
        }
    }
    static func viewport(window: CGRect?, screen: CGRect, webAncestors: [CGRect]) -> Result<CGRect, GeometryFailure> {
        let ancestors = unique(webAncestors)
        guard let window = window, valid(window) else { return .failure(.windowInvalid) }
        guard valid(screen) else { return .failure(.screenInvalid) }
        guard !ancestors.isEmpty, ancestors.allSatisfy(valid) else { return .failure(.webAncestorInvalid) }
        var frame = window.intersection(screen)
        for ancestor in ancestors { frame = frame.intersection(ancestor) }
        return valid(frame) ? .success(frame) : .failure(.viewportEmpty)
    }
    static func interactionFailure(_ frames: [CGRect], in viewport: CGRect,
                                   occlusions: [CGRect], hittable: Bool) -> GeometryFailure? {
        guard frames.allSatisfy(valid) else { return .fieldInvalid }
        guard frames.allSatisfy(viewport.contains) else { return .fieldOutside }
        for blocker in occlusions where valid(blocker) {
            if frames.contains(where: { valid($0.intersection(blocker)) }) { return .fieldOccluded }
        }
        return hittable ? nil : .fieldUnhittable
    }
    static func scrollBand(in viewport: CGRect, occlusions: [CGRect]) -> CGRect? {
        // A vertical gesture stays in one full-width unobscured band, even
        // when an occlusion lies inside the viewport or covers only part of it.
        let blockers = occlusions.filter(valid).map { viewport.intersection($0) }
            .filter(valid).sorted { $0.minY < $1.minY }
        var top = viewport.minY
        var bands: [CGRect] = []
        for blocker in blockers {
            if blocker.minY > top {
                bands.append(CGRect(x: viewport.minX, y: top, width: viewport.width, height: blocker.minY - top))
            }
            top = max(top, blocker.maxY)
        }
        if top < viewport.maxY {
            bands.append(CGRect(x: viewport.minX, y: top, width: viewport.width, height: viewport.maxY - top))
        }
        return bands.max { $0.height < $1.height }
    }
    static func visible(window: CGRect, screen: CGRect, webAncestors: [CGRect], occlusions: [CGRect]) -> CGRect? {
        guard case .success(var frame) = viewport(window: window, screen: screen, webAncestors: webAncestors) else { return nil }
        for blocker in unique(occlusions) where valid(blocker) && frame.intersects(blocker) {
            if blocker.minY <= frame.minY {
                let top = max(frame.minY, blocker.maxY)
                frame = CGRect(x: frame.minX, y: top, width: frame.width, height: frame.maxY - top)
            } else if blocker.maxY >= frame.maxY {
                frame.size.height = blocker.minY - frame.minY
            } else { return nil }
            guard valid(frame) else { return nil }
        }
        return frame
    }
    struct ActiveViewport {
        let viewport: CGRect?
        let visible: CGRect?
        let reason: String?
    }

    static func activeViewport(window: CGRect?, screen: CGRect, webAncestors: [CGRect], statusBars: [CGRect],
                               keyboardPresent: Bool, keyboardFrames: [CGRect]) -> ActiveViewport {
        let raw: CGRect
        switch viewport(window: window, screen: screen, webAncestors: webAncestors) {
        case .failure(let issue): return ActiveViewport(viewport: nil, visible: nil, reason: issue.rawValue)
        case .success(let frame): raw = frame
        }
        guard let window, var safe = visible(window: window, screen: screen, webAncestors: webAncestors,
                                             occlusions: statusBars) else {
            return ActiveViewport(viewport: raw, visible: nil, reason: "status_bar_viewport_invalid")
        }
        let keyboards = unique(keyboardFrames)
        if keyboardPresent {
            guard keyboards.count == 1, let keyboard = keyboards.first, valid(keyboard), screen.contains(keyboard),
                  keyboard.minX == screen.minX, keyboard.maxX == screen.maxX, keyboard.minY >= screen.midY,
                  screen.maxY - keyboard.maxY < keyboard.height else {
                return ActiveViewport(viewport: raw, visible: nil, reason: "keyboard_frame_unproven")
            }
            // The docked keyboard may stop above the system gesture area.
            // Only the continuous region above it is usable, never the gap below.
            let bottom = min(safe.maxY, keyboard.minY)
            guard bottom > safe.minY else {
                return ActiveViewport(viewport: raw, visible: nil, reason: "keyboard_covers_viewport")
            }
            safe.size.height = bottom - safe.minY
        } else if !keyboards.isEmpty {
            return ActiveViewport(viewport: raw, visible: nil, reason: "keyboard_state_changed")
        }
        return ActiveViewport(viewport: raw, visible: safe, reason: nil)
    }
    static func semanticIndex(frames: [CGRect], preferred: [Int], visible: CGRect, clippedControl: Bool) -> Int? {
        guard !frames.isEmpty, frames.allSatisfy(valid), valid(visible) else { return nil }
        // Normal parent/leaf semantics may have distinct containing bounds.
        // Two independent occurrences, even partly overlapping, remain ambiguous.
        for first in frames { for second in frames {
            guard first.contains(second) || second.contains(first) else { return nil }
        }}
        let order = preferred + frames.indices.filter { !preferred.contains($0) }.sorted {
            frames[$0].width * frames[$0].height < frames[$1].width * frames[$1].height
        }
        return order.first { frames.indices.contains($0) &&
            (clippedControl ? valid(frames[$0].intersection(visible)) : visible.contains(frames[$0])) }
    }
    static func terminalCrop(target: CGRect, output: CGRect, safe: CGRect) -> CGRect? {
        let crop = output.intersection(safe)
        guard valid(target), safe.contains(target), valid(crop), target.maxY <= crop.minY else { return nil }
        return crop
    }
    static func terminalScroll(target: CGRect, output: CGRect, safe: CGRect) -> ScrollDirection? {
        guard valid(target), valid(output), valid(safe), target.minX >= safe.minX, target.maxX <= safe.maxX,
              output.minX < safe.maxX, output.maxX > safe.minX else { return nil }
        let down = target.minY < safe.minY || output.minY < target.maxY
        let up = target.maxY > safe.maxY || output.minY >= safe.maxY
        guard down != up else { return nil }
        return down ? .swipeDown : .swipeUp
    }
    static func terminalPageScrollBand(safe: CGRect, output: CGRect) -> CGRect? {
        let overlap = safe.intersection(output)
        guard valid(overlap) else { return safe }
        // Start in the page gutter, where the WebView can move the page
        // without moving or selecting the xterm scrollback.
        let gutters = [CGRect(x: safe.minX, y: safe.minY, width: overlap.minX - safe.minX, height: safe.height),
                       CGRect(x: overlap.maxX, y: safe.minY, width: safe.maxX - overlap.maxX, height: safe.height)]
        return gutters.filter(valid).max { $0.width < $1.width } ?? scrollBand(in: safe, occlusions: [output])
    }
    static func headerStatusBarsValid(_ bars: [CGRect], screen: CGRect) -> Bool {
        (1...4).contains(bars.count) && bars.allSatisfy { valid($0) && screen.contains($0) }
    }
    static func headerFrameClear(_ frame: CGRect, safe: CGRect, statusBars: [CGRect]) -> Bool {
        valid(frame) && safe.contains(frame) && statusBars.allSatisfy { frame.minY >= $0.maxY }
    }
    static func terminalControlBand(dismiss: CGRect, helpers: [CGRect], safe: CGRect) -> CGRect? {
        guard valid(dismiss), valid(safe), helpers.count == 4, helpers.allSatisfy(valid), let first = helpers.first,
              helpers.allSatisfy({ abs($0.minY - first.minY) <= 1 && abs($0.maxY - first.maxY) <= 1 }),
              zip(helpers, helpers.dropFirst()).allSatisfy({ $0.0.maxX <= $0.1.minX }),
              let top = helpers.map(\.minY).min(), let sharedTop = helpers.map(\.minY).max(),
              let sharedBottom = helpers.map(\.maxY).min(), sharedTop < sharedBottom, dismiss.maxY < top else { return nil }
        return CGRect(x: safe.minX, y: dismiss.maxY, width: safe.width, height: top - dismiss.maxY)
    }

    static func terminalTargetBeforeKeyboard(_ target: CGRect, _ keyboard: CGRect, compact: Bool) -> Bool {
        if !compact { return target.maxY <= keyboard.minY }
        return target.maxX <= keyboard.minX && max(target.minY, keyboard.minY) < min(target.maxY, keyboard.maxY)
            && target.maxY <= keyboard.maxY
    }

    static func terminalControlScroll(target: CGRect, dismiss: CGRect, helpers: [CGRect], safe: CGRect,
                                      compact: Bool = false) -> ScrollDirection? {
        let anchors = [target, dismiss] + helpers
        guard anchors.allSatisfy({ valid($0) && $0.minX >= safe.minX && $0.maxX <= safe.maxX }) else { return nil }
        let frame = anchors.reduce(CGRect.null) { $0.union($1) }
        guard frame.height <= safe.height else { return nil }
        let ordered = terminalTargetBeforeKeyboard(target, dismiss, compact: compact)
        if compact && !ordered { return nil }
        let down = frame.minY < safe.minY || !ordered
        let up = frame.maxY > safe.maxY
        guard down != up else { return nil }
        return down ? .swipeDown : .swipeUp
    }
}
enum NativeConnectPolicy {
    enum Attempt: String { case ordinary, rotationRefused = "rotation_refused", rotationApproved = "rotation_approved" }
    enum Status: String {
        case unknown, ambiguous, idle, disconnected, connecting, connected
        case reviewBlocked = "review_blocked", reviewRequired = "review_required"
        case authenticationFailed = "authentication_failed", startFailed = "start_failed"
        case connectionFailed = "connection_failed", sessionEnded = "session_ended"
    }

    static func status(_ values: [String]) -> Status {
        let messages: [String: Status] = [
            "尚未连接。": .idle, "已断开；重新连接需要再次输入凭据。": .disconnected,
            "正在连接…": .connecting, "已连接，可以输入。": .connected,
            "主机指纹发生变化": .reviewBlocked,
            "主机指纹变化尚未重新核对；请先探测并独立核对本目标的主机指纹。": .reviewBlocked,
            "主机公钥与已核对的指纹不一致，连接已拒绝。请重新探测并核对。": .reviewBlocked,
            "请先核对指纹并选择一种认证方式。": .reviewRequired,
            "认证失败，请检查用户名和认证方式后重试。": .authenticationFailed,
            "连接未能启动，请核查连接资料。": .startFailed,
            "连接失败或已中断，请核查连接资料。": .connectionFailed,
            "远端会话已结束。": .sessionEnded
        ]
        let found = Set(values.compactMap { messages[$0] })
        return found.count > 1 ? .ambiguous : found.first ?? .unknown
    }

    static func sample(_ status: Status, keyboardVisible: Bool, submitFrame: CGRect?,
                       submitEnabled: Bool, submitHittable: Bool) -> [String: Any] {
        ["status": status.rawValue, "keyboardVisible": keyboardVisible,
         "submitFrame": NativeFramePolicy.diagnosticRect(submitFrame),
         "submitEnabled": submitEnabled, "submitHittable": submitHittable]
    }
}

enum NativeActivePage: String {
    case terminal, board, network, settings

    var routeAction: (String, String) {
        switch self {
        case .terminal: return ("nav-terminal", "终端")
        case .board: return ("show-remote", "看板")
        case .network: return ("nav-network", "网络")
        case .settings: return ("nav-settings", "设置")
        }
    }

    func witnesses(endpoint: String) -> [(String?, String, Bool)] {
        switch self {
        case .terminal: return [("ssh-active-title", "普通 SSH", false), ("ssh-live-endpoint", endpoint, false),
                                (nil, "已连接", false), ("ssh-disconnect", "断开连接", true)]
        case .board: return [(nil, "还没有主机", false), ("host-empty-add", "添加主机", true)]
        // The phone tab opens the configuration panel and hides the launcher.
        case .network: return [(nil, "网络配置", false), (nil, "新增网络配置", true)]
        case .settings: return [(nil, "设置", false), ("ssh-settings-active", "普通 SSH 会话保持连接", false),
                                ("ssh-settings-endpoint", endpoint, false)]
        }
    }
}
enum NativeActiveContext: String {
    case connect, disconnect
    case keyboardOpenBefore = "keyboard_open_before", keyboardOpenAfter = "keyboard_open_after"
    case keyboardCloseBefore = "keyboard_close_before", keyboardCloseAfter = "keyboard_close_after"
    case routeBefore = "route_before", routeAfter = "route_after"
}

enum NativeHostObservation {
    enum AX: String {
        case missing = "nil"
        case empty, nonString, match, different
    }

    enum Visual: String {
        case match, unavailable
        case textPresent = "text_present"
        case noTextDetected = "no_text_detected"
    }

    static func ax(_ value: Any?, expected: String) -> AX {
        guard let value else { return .missing }
        guard let text = value as? String else { return .nonString }
        if text == expected { return .match }
        return text.isEmpty ? .empty : .different
    }

    static func region(_ field: CGRect, viewport: CGRect, occlusions: [CGRect], otherWindows: [CGRect]) -> CGRect? {
        guard NativeFramePolicy.valid(field), viewport.contains(field),
              (occlusions + otherWindows).allSatisfy({
                  NativeFramePolicy.valid($0) && !NativeFramePolicy.valid(field.intersection($0))
              }) else { return nil }
        let interior = field.insetBy(dx: 1, dy: 1)
        return NativeFramePolicy.valid(interior) ? interior : nil
    }

    static func pixelCrop(_ region: CGRect, screen: CGRect, pixels: CGSize) -> CGRect? {
        guard screen.origin == .zero, NativeFramePolicy.valid(screen), NativeFramePolicy.valid(region),
              screen.contains(region), pixels.width.isFinite, pixels.height.isFinite else { return nil }
        let scale = (pixels.width / screen.width).rounded()
        guard (1...4).contains(scale), pixels.width == screen.width * scale,
              pixels.height == screen.height * scale else { return nil }
        let left = ceil(region.minX * scale), top = ceil(region.minY * scale)
        let crop = CGRect(x: left, y: top, width: floor(region.maxX * scale) - left,
                          height: floor(region.maxY * scale) - top)
        return NativeFramePolicy.valid(crop) && CGRect(origin: .zero, size: pixels).contains(crop) ? crop : nil
    }

    static func visual(_ lines: [(text: String, confidence: Float)], expected: String) -> Visual {
        if lines.isEmpty { return .noTextDetected }
        let recognized = lines.filter { $0.confidence >= 0.5 && !$0.text.isEmpty }
        guard !recognized.isEmpty else { return .unavailable }
        return lines.count == 1 && recognized[0].text == expected ? .match : .textPresent
    }
}

enum NativeHomeReadiness {
    enum State: String {
        case ready, loading, shell, error, alert, unexpected, notForeground = "not_foreground"
        case unidentifiedStartup = "unidentified_startup"
    }

    static let errors: [(String, [String])] = [
        ("connectionError", ["Could not connect to the server", "Could not connect to server", "无法连接到服务器"]),
        ("dnsError", ["hostname could not be found", "找不到服务器"]),
        ("webProcessError", ["WebKitErrorDomain", "NSURLErrorDomain"]),
        ("devURL", ["http://localhost:1420"]),
        ("browserPreview", ["浏览器预览"]),
        ("hostStorageError", ["本机主机资料不可用", "host_storage_unavailable", "host_path_bridge_unavailable"])
    ]

    static func permitsNavigation(_ state: [String: Any], from page: String) -> Bool {
        state["page"] as? String == page && state["appForeground"] as? Bool == true &&
            state["noAlerts"] as? Bool == true && state["noKnownErrors"] as? Bool == true &&
            state["credentialsEmpty"] as? Bool == true && (state["windowCount"] as? Int ?? 0) > 0 &&
            (state["webViewCount"] as? Int ?? 0) > 0
    }

    static func classify(_ state: [String: Any], home: [String: Any]) -> State {
        if state["appForeground"] as? Bool != true { return .notForeground }
        if state["noAlerts"] as? Bool != true { return .alert }
        let flags = home["knownErrors"] as? [String: Bool] ?? [:]
        if flags.contains(where: { $0.key != "loading" && $0.value }) { return .error }
        if state["page"] as? String == "sshForm" || state["page"] as? String == "addChoice" ||
            (state["inputCount"] as? Int ?? 0) > 0 { return .unexpected }
        if flags["loading"] == true { return .loading }
        if home["knownEmptyHome"] as? Bool == true && permitsNavigation(state, from: "emptyHome") { return .ready }
        return .shell
    }
    static func compactEntryReady(_ geometry: [String: Any], witnessed: CGRect) -> Bool {
        // The design's independent touch minimum is 44pt. The collector
        // checks the painted 48pt button height with the rendering tolerance.
        guard NativeFramePolicy.valid(witnessed), min(witnessed.width, witnessed.height) >= 44,
              let frame = geometry["frame"] as? [Double], frame.count == 4, min(frame[2], frame[3]) >= 44 else { return false }
        return geometry["role"] as? String == "button" &&
            ["enabled", "hittable", "ownerResolved", "fullyVisible"].allSatisfy { geometry[$0] as? Bool == true }
    }

    static func canResampleUnidentifiedStartup(_ state: [String: Any], home: [String: Any]) -> Bool {
        guard state["page"] as? String == "unexpected", state["noKnownErrors"] as? Bool == true,
              state["windowCount"] as? Int == 1, state["webViewCount"] as? Int == 1,
              state["inputCount"] as? Int == 1, state["credentialsEmpty"] as? Bool == true,
              state["sshTitleSeen"] as? Bool == false, state["addTitleSeen"] as? Bool == false,
              let members = home["members"] as? [String: [String: Any]], !members.isEmpty,
              let controls = state["formControls"] as? [String: [String: Any]], controls.count == 4 else { return false }
        return members.values.allSatisfy { $0["count"] as? Int == 0 } &&
            controls.values.allSatisfy { $0["reason"] as? String == "missing" }
    }
}
enum NativeViewPolicy {
    enum Scope: Equatable { case current, otherWindow, nativeSystem, ambiguous }
    struct Action {
        let scope: Scope
        let label: String
        let frame: CGRect
        let enabled: Bool
        let hittable: Bool
    }
    static func scope(window: [Int], web: [Int], currentWindow: [Int], currentWeb: [Int]) -> Scope {
        if window != currentWindow { return .otherWindow }
        if web.isEmpty { return .nativeSystem }
        if Array(web.prefix(currentWeb.count)) == currentWeb || Array(currentWeb.prefix(web.count)) == web { return .current }
        return .ambiguous
    }
    static func reached(member: String, page: String) -> Bool {
        page == "sshForm" || (member != "sshChoice" && page == "addChoice")
    }
    static func unsafeCredential(nonempty: Bool, enabled: Bool, hittable: Bool, visible: Bool) -> Bool {
        nonempty || visible || (enabled && hittable)
    }
    static func reviewValid(_ actions: [Action], expected: Set<String>, visible: CGRect) -> Bool {
        let current = actions.filter { $0.scope == .current && $0.hittable &&
            NativeFramePolicy.valid($0.frame) && $0.frame.intersects(visible) }
        guard Set(current.map { $0.label }) == expected else { return false }
        return expected.allSatisfy { label in
            let matches = current.filter { $0.label == label }
            return !matches.isEmpty && matches.allSatisfy { $0.enabled } && NativeFramePolicy.unique(matches.map { $0.frame }).count == 1
        }
    }
}
enum NativeControlPolicy {
    static let desktopPasswordLabel = "密码"
    static let mobilePasswordLabel = "密码（仅本次使用）"
    // WebKit can insert a single ASCII space at the inline label boundary.
    static let mobilePasswordLabels = [mobilePasswordLabel, "密码 （仅本次使用）"]

    enum AuthMethod: String, CaseIterable {
        case key, password

        var identifier: String { "ssh-auth-" + rawValue }
        var label: String { self == .key ? "已有私钥" : "密码" }

        // WebKit adds the Toggle trait to these aria-pressed buttons on iOS.
        static let roles: Set<String> = ["button", "toggle", "switch"]

        func matches(_ fact: Fact) -> Bool {
            fact.label == label && (fact.identifier == identifier || fact.identifier.isEmpty || fact.identifier == label)
        }

        enum Issue: String, Error {
            case missing = "native_encrypted_auth_method_missing"
            case ambiguous = "native_encrypted_auth_method_ambiguous"
            case wrongRole = "native_encrypted_auth_method_role_invalid"
            case wrongIdentity = "native_encrypted_auth_method_identity_invalid"
        }

        func candidate(_ facts: [Fact]) -> Result<Int, Issue> {
            let matches = facts.indices.filter {
                facts[$0].identifier == identifier || (self.matches(facts[$0]) && facts[$0].role != "staticText")
            }
            guard matches.count <= 1 else { return .failure(.ambiguous) }
            guard let index = matches.first else { return .failure(.missing) }
            guard self.matches(facts[index]) else { return .failure(.wrongIdentity) }
            guard Self.roles.contains(facts[index].role) else { return .failure(.wrongRole) }
            return .success(index)
        }
    }
    enum KeyField: String, CaseIterable {
        case pem = "ssh-key"
        case passphrase = "ssh-passphrase"

        var labels: [String] {
            switch self {
            case .pem: return ["私钥 PEM（仅本次使用）"]
            case .passphrase: return ["私钥口令（加密私钥需要）", "私钥口令 （加密私钥需要）"]
            }
        }

        func matches(identifier: String, label: String) -> Bool {
            identifier == rawValue || ((identifier.isEmpty || identifier == label) && labels.contains(label))
        }

        func accepts(role: String) -> Bool {
            switch self {
            case .pem: return role == "textView" || role == "textField"
            case .passphrase: return role == "secureTextField"
            }
        }
    }
    enum CollapsedPEM {
        static let identifier = "ssh-key-summary"
        static let label = "已填写私钥 · 重新编辑"

        enum Issue: String, Error {
            case missing = "native_encrypted_key_summary_missing"
            case ambiguous = "native_encrypted_key_summary_ambiguous"
            case identifier = "native_encrypted_key_summary_identifier_unproven"
            case label = "native_encrypted_key_summary_label_unproven"
            case role = "native_encrypted_key_summary_role_invalid"
            case disabled = "native_encrypted_key_summary_disabled"
            case editorPresent = "native_encrypted_key_summary_editor_present"
        }

        static func candidate(_ rows: [(identifier: String, label: String, role: String, enabled: Bool, visible: Bool)])
            -> Result<Int, Issue> {
            if rows.contains(where: { row in
                (row.enabled || row.visible) && (row.identifier == KeyField.pem.rawValue ||
                    (KeyField.pem.accepts(role: row.role) && KeyField.pem.matches(identifier: row.identifier, label: row.label)))
            }) { return .failure(.editorPresent) }
            let matches = rows.indices.filter { index in
                let row = rows[index]
                return row.identifier == identifier || (row.label == label && row.role != "staticText")
            }
            guard matches.count <= 1 else { return .failure(.ambiguous) }
            guard let index = matches.first else { return .failure(.missing) }
            let row = rows[index]
            guard row.identifier == identifier else { return .failure(.identifier) }
            guard row.label == label else { return .failure(.label) }
            guard row.role == "button" else { return .failure(.role) }
            guard row.enabled else { return .failure(.disabled) }
            return .success(index)
        }
    }
    enum PEMRepresentation: String {
        case editorValue, editorText
        case editorAfterBlur = "editor_after_blur"
        case editorUnproven = "editor_unproven"
        case outsideEditor = "outside_editor"
        case geometryMismatch = "geometry_mismatch"
        case subtreeUnproven = "subtree_unproven"
        case unsupportedNode = "unsupported_node"

        var rejection: String {
            switch self {
            case .editorValue, .editorText: return "content_not_exact"
            default: return rawValue
            }
        }
    }
    static let openSSHPrivateKeyHeader = "-----BEGIN OPENSSH PRIVATE KEY-----"
    static func encryptedPEMBodyLines(_ pem: String) -> [String] {
        let lines = pem.split(whereSeparator: \.isNewline).map(String.init)
        guard lines.first == openSSHPrivateKeyHeader, lines.last == "-----END OPENSSH PRIVATE KEY-----" else { return [] }
        // A complete long line identifies this fixture without matching common short fragments.
        return lines.dropFirst().dropLast().filter {
            $0.range(of: #"^[A-Za-z0-9+/]{40,}={0,2}$"#, options: .regularExpression) != nil
        }
    }
    static func encryptedSecretHits(identifier: String, label: String, value: String, pem: String,
                                    bodyLines: [String], passwords: [String], representation: PEMRepresentation)
        -> (header: [Bool], body: [Bool], password: [Bool]) {
        let fields = [identifier, label, value]
        let passwordHits = fields.map { field in passwords.contains { field.contains($0) } }
        var headerHits = fields.map { $0.contains(openSSHPrivateKeyHeader) }
        var bodyHits = fields.map { field in bodyLines.contains { field.contains($0) } }
        if representation == .editorValue && value == pem {
            headerHits[2] = false
            bodyHits[2] = false
        } else if representation == .editorText && identifier.isEmpty &&
                    (label == pem || label.isEmpty) && (value == pem || value.isEmpty) {
            headerHits[1] = false
            headerHits[2] = false
            bodyHits[1] = false
            bodyHits[2] = false
        }
        return (headerHits, bodyHits, passwordHits)
    }

    static func isMobilePasswordField(identifier: String, label: String) -> Bool {
        identifier == "ssh-password" ||
            ((identifier.isEmpty || identifier == label) && mobilePasswordLabels.contains(label))
    }

    static func isPasswordField(identifier: String, label: String) -> Bool {
        identifier == "ssh-password" || label == desktopPasswordLabel || mobilePasswordLabels.contains(label)
    }

    static func passwordLabelKind(_ label: String) -> String {
        switch label {
        case mobilePasswordLabels[0]: return "compact"
        case mobilePasswordLabels[1]: return "spaced"
        case desktopPasswordLabel: return "base"
        case "（仅本次使用）", "仅本次使用": return "hint"
        case "": return "empty"
        default: return "other"
        }
    }

    enum MobilePasswordIssue: String, Error {
        case identityMissing = "native_mobile_password_identity_missing"
        case secureRoleMissing = "native_mobile_password_secure_role_missing"
        case wrongRole = "native_mobile_password_wrong_role"
        case rawAmbiguous = "native_mobile_password_raw_ambiguous"
        case rawOwner = "native_mobile_password_raw_owner_unproven"
        case liveOwner = "native_mobile_password_live_owner_unproven"
        case liveMissing = "native_mobile_password_live_missing"
        case liveUnreadable = "native_mobile_password_live_unreadable"
        case liveAmbiguous = "native_mobile_password_live_ambiguous"
        case liveIdentity = "native_mobile_password_live_identity_mismatch"
        case ownerChanged = "native_mobile_password_owner_changed"
        case frameUnsettled = "native_mobile_password_frame_unsettled"
        case unhittable = "native_mobile_password_unhittable"
        case disabled = "native_control_disabled"

        var pending: Bool {
            switch self {
            case .identityMissing, .secureRoleMissing, .liveMissing, .liveUnreadable, .frameUnsettled, .unhittable:
                return true
            default: return false
            }
        }
    }

    struct Fact {
        let identifier: String
        let label: String
        let role: String
        let value: String?
    }
    struct RoleTypes {
        let textField: UInt
        let textView: UInt
        let searchField: UInt
        let button: UInt
        let stepper: UInt
        let staticText: UInt
    }
    static func projectRole(_ raw: UInt, types: RoleTypes) -> String {
        if raw == types.textField || raw == types.searchField { return "textField" }
        if raw == types.textView { return "textView" }
        if raw == types.button { return "button" }
        if raw == types.stepper { return "stepper" }
        if raw == types.staticText { return "staticText" }
        return "other"
    }
    struct Verdict {
        let index: Int?
        let role: String
        let reason: String
        let matches: Int
        let owner: Bool
        let identified: Bool
    }
    struct Selection {
        let controls: [String: Verdict]
        let ownerResolved: Bool
    }
    static func formVerdict(facts: [Fact], paths: [[Int]], identifier: String?, label: String,
                            editableRoles: Set<String>) -> (index: Int?, role: String, reason: String, matches: Int) {
        guard facts.count == paths.count else { return (nil, "none", "missing", 0) }
        let identified = facts.indices.filter { identifier?.isEmpty == false && facts[$0].identifier == identifier! }
        let identity = identified.isEmpty ? facts.indices.filter {
            facts[$0].label == label && (identifier?.isEmpty != false || facts[$0].identifier.isEmpty)
        } : identified
        let matches = min(identity.count, 10000)
        if !identified.isEmpty && identified.count != 1 { return (nil, "none", "ambiguous", matches) }
        var eligible = identity.filter { editableRoles.contains(facts[$0].role) }
        var wrapped: Set<Int> = []
        // Only an explicitly numeric/stepper port wrapper may authorize its
        // editor. Static labels and arbitrary containers never do so.
        if identifier == "ssh-port" || label == "端口" {
            for index in identity where ["stepper", "inputWrapper"].contains(facts[index].role) {
                let prefix = paths[index]
                let descendants = facts.indices.filter { candidate in
                    paths[candidate].count > prefix.count && Array(paths[candidate].prefix(prefix.count)) == prefix &&
                        editableRoles.contains(facts[candidate].role)
                }
                if descendants.count > 1 { return (nil, "none", "ambiguous", matches) }
                eligible.append(contentsOf: descendants)
                wrapped.formUnion(descendants)
            }
        }
        eligible = Array(Set(eligible)).sorted()
        if eligible.count == 1 {
            let index = eligible[0]
            return (index, wrapped.contains(index) ? "inputWrapper" : publicRole(facts[index].role), "matched", matches)
        }
        if eligible.count > 1 { return (nil, "none", "ambiguous", matches) }
        return (nil, identity.count == 1 ? publicRole(facts[identity[0]].role) : "none",
                identity.isEmpty ? "missing" : identity.count == 1 ? "wrongRole" : "ambiguous", matches)
    }
    static func formSelection(facts: [Fact], paths: [[Int]], windowPaths: [[Int]], webPaths: [[Int]],
                              ownerEligible: [Bool]) -> Selection {
        let definitions = [("host", "ssh-host", "主机地址"), ("port", "ssh-port", "端口"),
                           ("user", "ssh-user", "用户名"), ("probe", "ssh-probe", "探测主机指纹")]
        func owned(_ index: Int) -> Bool {
            guard paths.indices.contains(index), windowPaths.indices.contains(index), webPaths.indices.contains(index),
                  ownerEligible.indices.contains(index), ownerEligible[index],
                  !windowPaths[index].isEmpty, !webPaths[index].isEmpty else { return false }
            return webPaths[index].count > windowPaths[index].count &&
                Array(webPaths[index].prefix(windowPaths[index].count)) == windowPaths[index] &&
                paths[index].count > webPaths[index].count && Array(paths[index].prefix(webPaths[index].count)) == webPaths[index]
        }
        var controls: [String: Verdict] = [:]
        let targetFacts = facts.map { fact in
            fact.role == "button" && fact.label == "探测并核对主机密钥"
                ? Fact(identifier: fact.identifier, label: "探测主机指纹", role: fact.role, value: fact.value) : fact
        }
        for (name, identifier, label) in definitions {
            let roles: Set<String> = name == "probe" ? ["button"] : ["textField", "textView", "searchField"]
            let result = formVerdict(facts: targetFacts, paths: paths, identifier: identifier, label: label, editableRoles: roles)
            let owner = result.index.map(owned) ?? false
            controls[name] = Verdict(index: result.index, role: result.role,
                reason: result.reason == "matched" && !owner ? "ownerUnproven" : result.reason,
                matches: result.matches, owner: owner, identified: facts.contains { $0.identifier == identifier })
        }
        let selected = definitions.compactMap { controls[$0.0] }
        let indices = selected.compactMap { $0.index }
        let eligibleWindows = Set(windowPaths.indices.filter { ownerEligible.indices.contains($0) && ownerEligible[$0] &&
            !windowPaths[$0].isEmpty }.map { windowPaths[$0] })
        // A page heading proves the product owner even when another Web
        // window is present. The add-choice button's text is not a heading.
        let interactive: Set<String> = ["button", "textField", "textView", "searchField", "inputWrapper", "stepper"]
        let titles = facts.indices.filter { index in
            guard owned(index), (facts[index].role == "staticText" && ["普通 SSH 终端", "普通 SSH"].contains(facts[index].label)) ||
                (["ssh-page-heading", "ssh-step-title"].contains(facts[index].identifier) && !interactive.contains(facts[index].role)) else { return false }
            return !facts.indices.contains { ancestor in
                paths.indices.contains(ancestor) && interactive.contains(facts[ancestor].role) && paths[ancestor].count < paths[index].count &&
                    Array(paths[index].prefix(paths[ancestor].count)) == paths[ancestor]
            }
        }
        // WebKit may expose both a heading node and its text leaf. They are
        // one ownership witness, rather than two independent product windows.
        let titleOwners = titles.reduce(into: [Int]()) { result, index in
            if !result.contains(where: { windowPaths[$0] == windowPaths[index] && webPaths[$0] == webPaths[index] }) {
                result.append(index)
            }
        }
        let trustedOwner: Bool
        if let title = titleOwners.first, titleOwners.count == 1, let selected = indices.first, owned(selected) {
            trustedOwner = windowPaths[title] == windowPaths[selected] && webPaths[title] == webPaths[selected]
        } else {
            trustedOwner = titleOwners.isEmpty && eligibleWindows.count == 1
        }
        let ownerResolved = trustedOwner && selected.allSatisfy { $0.owner } && indices.count == 4 && Set(indices).count == 4 &&
            NativeFramePolicy.sameOwner(windowPaths: indices.map { windowPaths[$0] }, webPaths: indices.map { webPaths[$0] })
        return Selection(controls: controls, ownerResolved: ownerResolved)
    }
    static func publicRole(_ role: String) -> String {
        switch role {
        case "textField", "textView", "inputWrapper", "button": return role
        case "searchField": return "textField"
        default: return "other"
        }
    }
    static func select(_ facts: [Fact], identifier: String?, label: String, roles: Set<String>, value: String? = nil) -> Int? {
        let allowed = { (index: Int) in roles.contains(facts[index].role) && (value == nil || facts[index].value == value!) }
        if let id = identifier, !id.isEmpty {
            let exact = facts.indices.filter { facts[$0].identifier == id }
            if !exact.isEmpty { return exact.count == 1 && allowed(exact[0]) ? exact[0] : nil }
        }
        let exact = facts.indices.filter { allowed($0) && facts[$0].label == label }
        return exact.count == 1 ? exact[0] : nil
    }
    static func pageWitness(_ facts: [Fact], paths: [[Int]], windows: [[Int]], webs: [[Int]],
                            targets: [(String?, String, Bool)]) -> [Int]? {
        guard facts.count == paths.count, facts.count == windows.count, facts.count == webs.count else { return nil }
        var selected: [Int] = []
        for (identifier, label, button) in targets {
            let ids = facts.indices.filter { identifier != nil && facts[$0].identifier == identifier }
            let candidates = (ids.isEmpty ? Array(facts.indices) : ids).filter { index in
                let fact = facts[index]
                if identifier != nil && ids.isEmpty && !fact.identifier.isEmpty && fact.identifier != fact.label { return false }
                if button { return fact.role == "button" && fact.label == label }
                let heading = fact.role == "staticText" && fact.label == label
                let wrapper = !ids.isEmpty && fact.role == "other" && (fact.label == label ||
                    facts.indices.filter { child in
                        facts[child].role == "staticText" && facts[child].label == label &&
                            windows[child] == windows[index] && webs[child] == webs[index] &&
                            paths[child].count > paths[index].count && paths[child].starts(with: paths[index])
                    }.count == 1)
                guard heading || wrapper else { return false }
                // A choice/shortcut button's text leaf is not a heading.
                return !facts.indices.contains { other in
                    facts[other].role == "button" && paths[other].count < paths[index].count && paths[index].starts(with: paths[other])
                }
            }
            guard ids.count <= 1, candidates.count == 1, let index = candidates.first,
                  !windows[index].isEmpty, webs[index].count > windows[index].count,
                  webs[index].starts(with: windows[index]), paths[index].count > webs[index].count,
                  paths[index].starts(with: webs[index]) else { return nil }
            selected.append(index)
        }
        guard Set(selected).count == selected.count,
              NativeFramePolicy.sameOwner(windowPaths: selected.map { windows[$0] }, webPaths: selected.map { webs[$0] }) else { return nil }
        return selected
    }
    struct ShortcutEvidence {
        enum Issue: String {
            case anchors = "card_anchors_unproven", candidateCount = "candidate_count", addChoice = "add_choice_visible"
            case candidateIdentity = "candidate_identity", cardScope = "card_scope", buttonParent = "card_button_parent"
            case textParent = "card_text_parent", order = "card_tree_order"
            case verticalGeometry = "card_vertical_geometry", horizontalGeometry = "card_horizontal_geometry"
            case wrongPage = "page_not_clear", foreground = "app_not_foreground", alert = "alert_present"
            case path = "live_path_unresolved", snapshot = "live_snapshot_unavailable", owner = "live_owner_unresolved"
            case scope = "live_scope_changed", identity = "live_identity_changed", movement = "live_geometry_changed"
            case small = "button_size_or_role", disabled = "button_disabled", hit = "button_not_hittable"
            case occluded = "button_occluded"
            case capture = "home_capture_unproven"
        }
        var issue: Issue? = .anchors
        var candidates = 0
        var addMarkers = 0
        var candidateSize: [Int]?
        var liveSize: [Int]?
        var buttonGap: Int?

        static func size(_ frame: CGRect) -> [Int]? {
            (NativeFramePolicy.diagnosticRect(frame) as? [Int]).map { Array($0.suffix(2)) }
        }

        static func actionIssue(_ geometry: [String: Any], witnessed: CGRect) -> Issue? {
            if geometry["centerVisible"] as? Bool == true && NativeHomeReadiness.compactEntryReady(geometry, witnessed: witnessed) {
                return nil
            }
            if geometry["ownerResolved"] as? Bool != true { return .owner }
            if geometry["centerVisible"] as? Bool != true || geometry["fullyVisible"] as? Bool != true { return .occluded }
            if geometry["enabled"] as? Bool != true { return .disabled }
            if geometry["hittable"] as? Bool != true { return .hit }
            return .small
        }

        func publicFields(_ reason: Issue) -> [String: Any] {
            ["reason": reason.rawValue, "visibleCandidates": min(candidates, 10000),
             "visibleAddMarkers": min(addMarkers, 10000), "candidateSizePt": candidateSize as Any? ?? NSNull(),
             "liveSizePt": liveSize as Any? ?? NSNull(), "buttonGapPt": buttonGap as Any? ?? NSNull()]
        }
    }

    static func compactHomeShortcut(_ facts: [Fact], paths: [[Int]], windows: [[Int]], webs: [[Int]],
                                    frames: [CGRect], card: [Int]?, evidence: inout ShortcutEvidence) -> Int? {
        evidence = ShortcutEvidence()
        guard facts.count == paths.count, facts.count == windows.count, facts.count == webs.count,
              facts.count == frames.count else { return nil }
        let label = "普通 SSH 终端", identifier = "home-open-ssh"
        let visible = facts.indices.filter { NativeFramePolicy.valid(frames[$0]) }
        let candidates = visible.filter {
            facts[$0].identifier == identifier || (facts[$0].role == "button" && facts[$0].label == label)
        }
        let addIDs: Set<String> = ["add-ssh", "add-ssh-label", "add-ssh-detail", "add-herdr", "add-choice-heading", "add-back"]
        let addLabels: Set<String> = ["添加连接", "选择连接方式", "返回看板", "herdr 配对 / 手动连接",
            "使用服务器密码或已有私钥打开远程 Shell。"]
        let markers = visible.filter {
            addIDs.contains(facts[$0].identifier) || addLabels.contains(facts[$0].label)
        }
        evidence.candidates = candidates.count
        evidence.addMarkers = markers.count
        if candidates.count == 1 { evidence.candidateSize = ShortcutEvidence.size(frames[candidates[0]]) }
        evidence.issue = candidates.count == 1 ? .anchors : .candidateCount
        guard let card, card.count == 5, card.allSatisfy(facts.indices.contains),
              NativeFramePolicy.sameOwner(windowPaths: card.map { windows[$0] }, webPaths: card.map { webs[$0] })
              else { return nil }
        let heading = card[1], description = card[2], shortcut = card[3], add = card[4]
        evidence.issue = .candidateCount
        guard candidates == [shortcut] else { return nil }
        evidence.issue = .addChoice
        guard markers.isEmpty else { return nil }
        evidence.issue = .candidateIdentity
        guard facts[shortcut].role == "button", facts[shortcut].label == label,
              ["", label, identifier].contains(facts[shortcut].identifier) else { return nil }
        let parent = Array(paths[shortcut].dropLast())
        let web = webs[shortcut], window = windows[shortcut]
        evidence.issue = .cardScope
        guard !window.isEmpty, web.count > window.count, web.starts(with: window), parent.starts(with: web) else { return nil }
        evidence.issue = .buttonParent
        guard paths[add].dropLast().elementsEqual(parent) else { return nil }
        evidence.issue = .textParent
        guard paths[heading].starts(with: parent), paths[description].starts(with: parent) else { return nil }
        evidence.issue = .order
        guard paths[heading].lexicographicallyPrecedes(paths[description]),
              paths[description].lexicographicallyPrecedes(paths[add]),
              paths[add].lexicographicallyPrecedes(paths[shortcut]) else { return nil }
        let title = frames[heading], hint = frames[description], first = frames[add], second = frames[shortcut]
        let gap = second.minY - first.maxY
        if gap.isFinite && abs(gap) <= 10000 { evidence.buttonGap = Int(gap.rounded()) }
        evidence.issue = .verticalGeometry
        guard [title, hint, first, second].allSatisfy(NativeFramePolicy.valid),
              title.maxY <= hint.minY, hint.maxY <= first.minY, (0...24).contains(gap) else { return nil }
        evidence.issue = .horizontalGeometry
        guard abs(first.minX - second.minX) <= 1, abs(first.maxX - second.maxX) <= 1,
              hint.minX >= first.minX - 1, hint.maxX <= first.maxX + 1 else { return nil }
        evidence.issue = nil
        return shortcut
    }
    static func valueText(_ value: Any?) -> String? {
        if value == nil { return "" }
        if let text = value as? String { return text }
        if let number = value as? NSNumber { return number.stringValue }
        return nil
    }
    static func credentialEmpty(_ value: Any?, placeholder: String?) -> Bool {
        guard let text = valueText(value) else { return false }
        return text.isEmpty || (placeholder?.isEmpty == false && text == placeholder)
    }
    static func credentialMasked(_ value: Any?) -> Bool {
        guard let text = value as? String, !text.isEmpty else { return false }
        return text.allSatisfy { "•●∙*".contains($0) }
    }
    static func fingerprintText(_ text: String) -> String {
        text.contains("SHA256:") ? text.filter { !$0.isWhitespace } : text
    }
    static func clearCount(_ value: Any?, placeholder: String?, secure: Bool) -> Int? {
        guard let text = valueText(value) else { return nil }
        if credentialEmpty(value, placeholder: placeholder) { return 0 }
        if secure { return nil }
        return text.count <= 5 ? text.count : nil
    }
    static func isPortEditingCandidate(role: UInt, stepper: UInt, button: UInt, value: Any?) -> Bool {
        role != stepper && role != button && valueText(value) == "22"
    }
    enum QueryChoice { case identifier, label, none, ambiguous }
    static func queryChoice(identifierCount: Int, labelCount: Int) -> QueryChoice {
        if identifierCount > 0 { return identifierCount == 1 ? .identifier : .ambiguous }
        if labelCount > 0 { return labelCount == 1 ? .label : .ambiguous }
        return .none
    }
}
// END NATIVE FRAME POLICY

// URLSession completion runs off the main actor. Synchronize its tiny reply
// explicitly; no callback captures a UI object or actor-isolated local state.
private final class CheckpointReply: @unchecked Sendable {
    private let lock = NSLock()
    private var response: (accepted: Bool, visualTargetReady: Bool) = (false, false)
    func set(accepted: Bool, visualTargetReady: Bool) {
        lock.lock(); defer { lock.unlock() }
        response = (accepted, visualTargetReady)
    }
    func get() -> (accepted: Bool, visualTargetReady: Bool) {
        lock.lock(); defer { lock.unlock() }
        return response
    }
}

// The fixture configuration is read from a private test-bundle resource at run time.
// The installed product receives normal taps/keystrokes and real SSH traffic.
final class TauriDirectSSHUITests: XCTestCase {
    private struct Observed {
        let snapshot: any XCUIElementSnapshot
        let path: [Int]
        let window: CGRect?
        let windowPath: [Int]
        let webs: [CGRect]
        let webPath: [Int]
    }
    private var config: [String: Any] = [:]
    private var app: XCUIApplication!
    private var scenario = "ordinary"
    private var mobileFlow = false
    private var nativePhase = "ordinary_launch"
    private var lastHomeSample: [String: Any]?
    private var nativeHomeDeadline: TimeInterval = 0
    private var manualHomeCardSeen = false
    private var shortcutEvidence = NativeControlPolicy.ShortcutEvidence()
    private var pageButtons: [String: Observed] = [:]
    private var navigationFormOwner: Observed?
    private struct LiveControl {
        let element: XCUIElement
        let snapshot: any XCUIElementSnapshot
        let hittable: Bool
    }
    private struct FormControl {
        let live: LiveControl
        let owner: Observed
        let window: Observed
        let web: Observed
        let identified: Bool
        let adjacentFields: [String: any XCUIElementSnapshot]
    }
    private struct RevealedControl {
        let live: LiveControl
        let owner: Observed
        let window: Observed
        let web: Observed
    }
    private enum MobileWitnessObservation<Proof> {
        case ready(Proof)
        case pending(String, (() -> [String: Any])?)
    }
    private struct TerminalHeader {
        let nodes: [Observed]
        let statusBars: [CGRect]
        let bottom: CGFloat
    }
    @MainActor
    private struct CaptureAnchors {
        let nodes: [Observed]
        let usesControls: Bool
        var activeHeader: [Observed]? = nil

        var frames: [CGRect] { nodes.map { $0.snapshot.frame } }

        func output(in safe: CGRect) -> CGRect? {
            usesControls ? NativeFramePolicy.terminalControlBand(dismiss: frames[1], helpers: Array(frames.dropFirst(2)), safe: safe) : frames[1]
        }

        func visibleOutput(in safe: CGRect) -> CGRect? {
            guard let output = output(in: safe) else { return nil }
            if usesControls && (!frames.allSatisfy(safe.contains) ||
                !NativeFramePolicy.terminalTargetBeforeKeyboard(frames[0], frames[1], compact: activeHeader != nil)) { return nil }
            return NativeFramePolicy.terminalCrop(target: frames[0], output: output, safe: safe)
        }

        func direction(in safe: CGRect) -> NativeFramePolicy.ScrollDirection? {
            usesControls ? NativeFramePolicy.terminalControlScroll(target: frames[0], dismiss: frames[1],
                helpers: Array(frames.dropFirst(2)), safe: safe, compact: activeHeader != nil) :
                NativeFramePolicy.terminalScroll(target: frames[0], output: frames[1], safe: safe)
        }
    }

    @MainActor
    private func require(_ condition: Bool, _ code: String, passwordObservation: [String: Any]? = nil,
                         shortcutIssue: NativeControlPolicy.ShortcutEvidence.Issue? = nil) throws {
        if !condition {
            var payload: [String: Any] = ["nativeCheckpoint": nativePhase, "nativeFailureCode": code]
            if let passwordObservation { payload["passwordObservation"] = passwordObservation }
            if let shortcutIssue { payload["shortcutDiagnostic"] = shortcutEvidence.publicFields(shortcutIssue) }
            try? post("native_failure", payload)
            throw NSError(domain: code, code: 1)
        }
    }

    @MainActor
    private func phase(_ name: String) throws {
        nativePhase = scenario + "_" + name
        try post("native_progress", ["nativeCheckpoint": nativePhase])
    }

    @MainActor
    @discardableResult
    private func post(_ stage: String, _ extra: [String: Any] = [:]) throws -> Bool {
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
                reply.set(accepted: value["ok"] as? Bool == true,
                          visualTargetReady: value["visualTargetReady"] as? Bool == true)
            }
            done.signal()
        }
        task.resume()
        let completed = done.wait(timeout: .now() + 105) == .success
        if !completed { task.cancel() }
        // Do not call require here: a network failure must not recurse while
        // reporting a native failure to the same checkpoint server.
        let response = reply.get()
        if !completed || !response.accepted { throw NSError(domain: "checkpoint_rejected", code: 1) }
        return response.visualTargetReady
    }

    @MainActor
    private func nodes() throws -> [any XCUIElementSnapshot] {
        try observedNodes().map { $0.snapshot }
    }

    @MainActor
    private func observedNodes(reportLimit: Bool = true) throws -> [Observed] {
        var pending: [(any XCUIElementSnapshot, [Int], CGRect?, [Int], [CGRect], [Int])] = [(try app.snapshot(), [], nil, [], [], [])]
        var result: [Observed] = []
        while let (node, path, inheritedWindow, inheritedWindowPath, inheritedWebs, inheritedWebPath) = pending.popLast() {
            let isWindow = node.elementType == .window
            let isWeb = node.elementType == .webView
            let window = isWindow ? node.frame : inheritedWindow
            let windowPath = isWindow ? path : inheritedWindowPath
            let webs = isWeb ? inheritedWebs + [node.frame] : inheritedWebs
            let webPath = isWeb ? path : inheritedWebPath
            result.append(Observed(snapshot: node, path: path, window: window, windowPath: windowPath, webs: webs, webPath: webPath))
            if result.count >= 10000 {
                if reportLimit { try require(false, "native_tree_limit") }
                throw NSError(domain: "native_tree_limit", code: 1)
            }
            for (index, child) in node.children.enumerated().reversed() {
                pending.append((child, path + [index], window, windowPath, webs, webPath))
            }
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
    private func uniqueElement(_ query: XCUIElementQuery) -> XCUIElement {
        // An absent/ambiguous query stays nonmatching. Its metadata is never read.
        query.count == 1 ? query.firstMatch : query.matching(NSPredicate(value: false)).firstMatch
    }

    @MainActor
    private func resolveControl(_ typed: XCUIElementQuery, _ fallback: XCUIElementQuery,
                                identifier: String?, label: String, requireTypedID: Bool = false) -> XCUIElement {
        let absent = app.descendants(matching: .any).matching(NSPredicate(value: false)).firstMatch
        if let id = identifier, !id.isEmpty {
            let identified = app.descendants(matching: .any).matching(identifier: id)
            switch NativeControlPolicy.queryChoice(identifierCount: identified.count, labelCount: 0) {
            case .identifier:
                if requireTypedID && typed.matching(identifier: id).count != 1 { return absent }
                return identified.firstMatch
            case .ambiguous: return absent
            case .none, .label: break
            }
        }
        let predicate = NSPredicate(format: "label == %@", label)
        let preferred = typed.matching(predicate)
        switch NativeControlPolicy.queryChoice(identifierCount: 0, labelCount: preferred.count) {
        case .label: return preferred.firstMatch
        case .ambiguous: return absent
        case .none, .identifier: break
        }
        let remaining = fallback.matching(predicate)
        return NativeControlPolicy.queryChoice(identifierCount: 0, labelCount: remaining.count) == .label ? remaining.firstMatch : absent
    }

    @MainActor
    private func liveControl(_ item: XCUIElement) -> LiveControl? {
        guard item.exists, let snapshot = try? item.snapshot() else { return nil }
        return LiveControl(element: item, snapshot: snapshot, hittable: item.isHittable)
    }

    @MainActor
    private func button(_ label: String) -> XCUIElement {
        if label == "探测主机指纹" {
            return (try? formControl("probe"))?.live.element ?? app.descendants(matching: .any).matching(NSPredicate(value: false)).firstMatch
        }
        let ids = ["看板": "show-remote", "普通 SSH 终端": "add-ssh", "herdr 配对 / 手动连接": "add-herdr",
            "打开键盘": "ssh-focus", "收起键盘": "ssh-hide-keyboard", "断开连接": "ssh-disconnect", "重新核对主机指纹": "ssh-key-recheck",
            "取消连接，保留旧信任": "ssh-key-cancel"]
        return resolveControl(app.buttons, app.descendants(matching: .any), identifier: ids[label], label: label)
    }

    @MainActor
    private func formTargets(_ tree: [Observed]) -> [NativeControlPolicy.Fact] {
        let types = NativeControlPolicy.RoleTypes(textField: XCUIElement.ElementType.textField.rawValue,
            textView: XCUIElement.ElementType.textView.rawValue, searchField: XCUIElement.ElementType.searchField.rawValue,
            button: XCUIElement.ElementType.button.rawValue, stepper: XCUIElement.ElementType.stepper.rawValue,
            staticText: XCUIElement.ElementType.staticText.rawValue)
        return tree.map { NativeControlPolicy.Fact(identifier: $0.snapshot.identifier, label: $0.snapshot.label,
            role: NativeControlPolicy.projectRole($0.snapshot.elementType.rawValue, types: types), value: nil) }
    }

    @MainActor
    private func formSelection(_ tree: [Observed]) -> NativeControlPolicy.Selection {
        let excluded = tree.filter { [.keyboard, .alert].contains($0.snapshot.elementType) }.map { $0.path }
        return NativeControlPolicy.formSelection(facts: formTargets(tree), paths: tree.map { $0.path },
            windowPaths: tree.map { $0.windowPath }, webPaths: tree.map { $0.webPath }, ownerEligible: tree.map { row in
                row.window != nil && !row.webs.isEmpty &&
                    !excluded.contains { prefix in Array(row.path.prefix(prefix.count)) == prefix }
            })
    }

    @MainActor
    private func resolveByPath(_ observed: Observed) -> XCUIElement {
        var element: XCUIElement = app
        for step in observed.path { element = element.children(matching: .any).element(boundBy: step) }
        return element
    }

    @MainActor
    private func sameIdentity(_ lhs: any XCUIElementSnapshot, _ rhs: any XCUIElementSnapshot) -> Bool {
        lhs.elementType == rhs.elementType && lhs.identifier == rhs.identifier && lhs.label == rhs.label
    }

    @MainActor
    private func liveOnPath(_ row: Observed) -> LiveControl? {
        guard let live = liveControl(resolveByPath(row)), sameIdentity(row.snapshot, live.snapshot) else { return nil }
        return live
    }

    @MainActor
    private func controlScope(_ row: Observed, _ rows: [Observed]) -> (window: Observed, web: Observed)? {
        guard !row.windowPath.isEmpty, row.webPath.count > row.windowPath.count, row.path.count > row.webPath.count,
              row.webPath.starts(with: row.windowPath), row.path.starts(with: row.webPath),
              let window = rows.first(where: { $0.path == row.windowPath && $0.snapshot.elementType == .window }),
              let web = rows.first(where: { $0.path == row.webPath && $0.snapshot.elementType == .webView }) else { return nil }
        return (window, web)
    }

    @MainActor
    private func formControl(_ name: String, matching expected: FormControl? = nil) throws -> FormControl {
        func select(_ rows: [Observed]) -> (owner: Observed, window: Observed, web: Observed, identified: Bool,
                                          adjacentFields: [String: any XCUIElementSnapshot])? {
            let selection = formSelection(rows)
            guard selection.ownerResolved, let verdict = selection.controls[name], verdict.reason == "matched",
                  let index = verdict.index, let scope = controlScope(rows[index], rows) else { return nil }
            var adjacentFields: [String: any XCUIElementSnapshot] = [:]
            if name == "host" && nativePhase == "encrypted_key_host" {
                for name in ["port", "user"] {
                    if let index = selection.controls[name]?.index { adjacentFields[name] = rows[index].snapshot }
                }
            }
            return (rows[index], scope.window, scope.web, verdict.identified, adjacentFields)
        }
        guard let original = try select(observedNodes()) else {
            try require(false, "native_form_control_unproven")
            throw NSError(domain: "native_form_control_unproven", code: 1)
        }
        if let expected = expected {
            try require(original.window.path == expected.window.path && original.web.path == expected.web.path &&
                sameIdentity(original.window.snapshot, expected.window.snapshot) && sameIdentity(original.web.snapshot, expected.web.snapshot) &&
                sameIdentity(original.owner.snapshot, expected.owner.snapshot) && (!expected.identified || original.identified),
                "native_form_control_changed")
        }
        // The keyboard may move the field or reorder siblings. Re-select
        // within the same form and resolve the current path before acting.
        guard let fresh = try select(observedNodes()), fresh.window.path == original.window.path, fresh.web.path == original.web.path,
              sameIdentity(fresh.window.snapshot, original.window.snapshot), sameIdentity(fresh.web.snapshot, original.web.snapshot),
              sameIdentity(fresh.owner.snapshot, original.owner.snapshot), !original.identified || fresh.identified,
              liveOnPath(fresh.window) != nil, liveOnPath(fresh.web) != nil, let current = liveOnPath(fresh.owner) else {
            try require(false, "native_form_control_changed")
            throw NSError(domain: "native_form_control_changed", code: 1)
        }
        return FormControl(live: current, owner: fresh.owner, window: fresh.window, web: fresh.web,
            identified: fresh.identified, adjacentFields: fresh.adjacentFields)
    }

    @MainActor
    private func field(_ label: String) -> XCUIElement {
        let names = ["主机地址": "host", "端口": "port", "用户名": "user"]
        if let name = names[label], let current = try? formControl(name) { return current.live.element }
        return app.descendants(matching: .any).matching(NSPredicate(value: false)).firstMatch
    }

    @MainActor
    private func controlGeometry(_ owner: Observed, _ controls: [LiveControl], measureScrollBand: Bool = false,
                                 scrollOcclusion: ((CGRect, Bool) -> CGRect?)? = nil)
        -> (failure: NativeFramePolicy.GeometryFailure?, viewport: CGRect?, scrollFrame: CGRect?) {
        let viewport: CGRect
        switch NativeFramePolicy.viewport(window: owner.window, screen: app.frame, webAncestors: owner.webs) {
        case .failure(let failure): return (failure, nil, nil)
        case .success(let frame): viewport = frame
        }
        var occlusions = nativeOcclusions()
        let frames = [owner.snapshot.frame] + controls.map { $0.snapshot.frame }
        let hittable = controls.allSatisfy { $0.hittable }
        var failure = NativeFramePolicy.interactionFailure(frames, in: viewport, occlusions: occlusions, hittable: hittable)
        if failure == nil || failure?.canRetryTap == true,
           let blocker = scrollOcclusion?(viewport, failure != nil) {
            occlusions.append(blocker)
            failure = NativeFramePolicy.interactionFailure(frames, in: viewport, occlusions: occlusions, hittable: hittable)
        }
        let scrollFrame = measureScrollBand && failure?.canRetryTap == true
            ? NativeFramePolicy.scrollBand(in: viewport, occlusions: occlusions) : nil
        return (failure, viewport, scrollFrame)
    }

    @MainActor
    private func routeTabsOcclusion(_ owner: Observed, _ rows: [Observed], _ viewport: CGRect,
                                    _ controls: [CGRect], scrolling: Bool) -> CGRect? {
        // The product's route navigation is a fixed overlay in the narrow layout.
        guard viewport.width <= 599 else { return nil }
        let sameWeb = rows.filter { $0.windowPath == owner.windowPath && $0.webPath == owner.webPath &&
            $0.path.count > owner.webPath.count }
        func relevant(_ frame: CGRect) -> Bool {
            NativeFramePolicy.valid(frame) && (scrolling || controls.contains { NativeFramePolicy.valid($0.intersection(frame)) })
        }
        let landmarks = sameWeb.filter {
            $0.snapshot.label == "主导航" && [.group, .other].contains($0.snapshot.elementType)
        }
        if landmarks.count == 1, let landmark = landmarks.first, relevant(landmark.snapshot.frame),
           let live = liveOnPath(landmark), NativeFramePolicy.valid(live.snapshot.frame),
           live.snapshot.frame.minX <= viewport.minX, live.snapshot.frame.maxX >= viewport.maxX,
           live.snapshot.frame.midY > viewport.midY {
            return live.snapshot.frame
        }
        let definitions = [("show-remote", "看板"), ("nav-terminal", "终端"), ("nav-network", "网络"), ("nav-settings", "设置")]
        let roles: Set<XCUIElement.ElementType> = [.button, .checkBox, .switch, .toggle]
        var tabs: [Observed] = []
        for (id, label) in definitions {
            let identified = sameWeb.filter { $0.snapshot.identifier == id }
            let matches = identified.isEmpty ? sameWeb.filter { $0.snapshot.identifier.isEmpty && $0.snapshot.label == label &&
                roles.contains($0.snapshot.elementType) } : identified
            guard matches.count == 1, let tab = matches.first, roles.contains(tab.snapshot.elementType),
                  NativeFramePolicy.valid(tab.snapshot.frame) else { return nil }
            tabs.append(tab)
        }
        let observedButtons = tabs.reduce(CGRect.null) { $0.union($1.snapshot.frame) }
        guard relevant(observedButtons) else { return nil }
        let live = tabs.compactMap(liveOnPath)
        guard live.count == tabs.count, live.allSatisfy({ $0.hittable && NativeFramePolicy.valid($0.snapshot.frame) }) else { return nil }
        let frames = live.map { $0.snapshot.frame }
        guard zip(frames, frames.dropFirst()).allSatisfy({ $0.0.maxX <= $0.1.minX }),
              let upper = frames.map(\.minY).max(), let lower = frames.map(\.maxY).min(), upper < lower else { return nil }
        return frames.reduce(CGRect.null) { $0.union($1) }
    }

    @MainActor
    private func reportFormGeometry(_ failure: NativeFramePolicy.GeometryFailure, detail: [String: Any]? = nil) throws {
        var payload: [String: Any] = ["nativeCheckpoint": nativePhase, "geometryReason": failure.rawValue]
        if let detail = detail { payload["geometryDetail"] = detail }
        try post("native_progress", payload)
    }

    @MainActor
    private func failControlGeometry(_ failure: NativeFramePolicy.GeometryFailure) throws -> Never {
        let code = failure.canRetryTap ? "native_control_not_visible" : "native_visible_frame_invalid"
        try require(false, code)
        throw NSError(domain: code, code: 1)
    }

    @MainActor
    @discardableResult
    private func tapForm(_ name: String) throws -> FormControl {
        var expected: FormControl?
        var lastFailure: NativeFramePolicy.GeometryFailure = .fieldUnhittable
        for _ in 0..<10 {
            let form = try formControl(name, matching: expected)
            expected = form
            let (current, owner) = (form.live, form.owner)
            try require(current.snapshot.isEnabled && owner.snapshot.isEnabled, "native_control_disabled")
            let geometry = controlGeometry(owner, [current], measureScrollBand: true)
            guard let failure = geometry.failure else {
                current.element.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
                return form
            }
            if let visible = geometry.scrollFrame, let direction = scrollDirection([owner.snapshot.frame, current.snapshot.frame], visible) {
                try scrollToControl(owner, form.window, form.web, visible, direction, formFailure: failure)
            }
            try reportFormGeometry(failure)
            guard failure.canRetryTap else { try failControlGeometry(failure) }
            lastFailure = failure
        }
        try failControlGeometry(lastFailure)
    }

    @MainActor
    private func manualHostKeyboard() -> String {
        let screen = app.frame
        if keyboardFrames().contains(where: { NativeFramePolicy.valid($0.intersection(screen)) }) { return "visible" }
        return app.keyboards.firstMatch.exists ? "unproven" : "hidden"
    }

    private func inputReadback(_ value: Any?, expected: String) -> String {
        guard let text = NativeControlPolicy.valueText(value) else { return "unavailable" }
        if text == expected { return "match" }
        return text.isEmpty ? "empty" : "different"
    }

    @MainActor
    private func manualHostRegion(_ expected: FormControl, screen: CGRect) -> CGRect? {
        let system = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        guard app.state == .runningForeground, app.frame == screen, screen.origin == .zero,
              !app.alerts.firstMatch.exists, !system.alerts.firstMatch.exists,
              let rows = try? observedNodes(reportLimit: false) else { return nil }
        let selection = formSelection(rows)
        guard selection.ownerResolved, let verdict = selection.controls["host"], verdict.reason == "matched",
              let index = verdict.index else { return nil }
        let owner = rows[index]
        guard owner.path == expected.owner.path, sameIdentity(owner.snapshot, expected.owner.snapshot),
              owner.snapshot.elementType == .textField, owner.snapshot.isEnabled,
              owner.snapshot.placeholderValue?.isEmpty != false,
              let scope = controlScope(owner, rows),
              scope.window.path == expected.window.path, scope.web.path == expected.web.path,
              sameIdentity(scope.window.snapshot, expected.window.snapshot),
              sameIdentity(scope.web.snapshot, expected.web.snapshot),
              scope.window.snapshot.frame == expected.window.snapshot.frame,
              scope.web.snapshot.frame == expected.web.snapshot.frame,
              liveOnPath(scope.window) != nil, liveOnPath(scope.web) != nil,
              let live = liveOnPath(owner), live.hittable, live.snapshot.isEnabled else { return nil }
        let field = owner.snapshot.frame
        guard field == live.snapshot.frame, field == expected.live.snapshot.frame,
              case .success(let viewport) = NativeFramePolicy.viewport(
                window: owner.window, screen: screen, webAncestors: owner.webs) else { return nil }
        let keyboards = keyboardFrames().filter { NativeFramePolicy.valid($0.intersection(screen)) }
        if app.keyboards.firstMatch.exists && keyboards.isEmpty { return nil }
        let tabs = routeTabsOcclusion(owner, rows, viewport, [field], scrolling: false)
        let otherWindows = rows.filter { $0.snapshot.elementType == .window && $0.path != scope.window.path }
            .map { $0.snapshot.frame }
        return NativeHostObservation.region(field, viewport: viewport,
            occlusions: statusBarFrames() + keyboards + (tabs.map { [$0] } ?? []), otherWindows: otherWindows)
    }

    @MainActor
    private func manualHostPixels(_ form: FormControl, expected: String) -> NativeHostObservation.Visual {
        // Only the first public loopback host entry has this diagnostic. The
        // driver publishes only the result category, which never gates the probe.
        guard nativePhase == "encrypted_key_host", expected == "127.0.0.1" else { return .unavailable }
        let screen = app.frame
        guard let region = manualHostRegion(form, screen: screen) else { return .unavailable }
        let shot = XCUIScreen.main.screenshot().image
        guard manualHostRegion(form, screen: screen) == region, shot.imageOrientation == .up,
              let original = shot.cgImage,
              let crop = NativeHostObservation.pixelCrop(region, screen: screen,
                pixels: CGSize(width: CGFloat(original.width), height: CGFloat(original.height))),
              let image = original.cropping(to: crop) else { return .unavailable }
        let request = VNRecognizeTextRequest()
        request.usesLanguageCorrection = false
        do {
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
            guard let results = request.results else { return .unavailable }
            let lines = results.compactMap { $0.topCandidates(1).first }.map { ($0.string, $0.confidence) }
            guard lines.count == results.count else { return .unavailable }
            return NativeHostObservation.visual(lines, expected: expected)
        } catch {
            return .unavailable
        }
    }

    @MainActor
    private func reportManualHostEntry(_ form: FormControl, expected: String, initialKeyboard: String,
                                       beforeInput: FormControl? = nil, visual: NativeHostObservation.Visual? = nil) throws {
        let fields: [(String, (any XCUIElementSnapshot)?)] = [
            ("host", form.owner.snapshot), ("port", form.adjacentFields["port"]), ("user", form.adjacentFields["user"]),
        ]
        let focus = fields.filter { $0.1?.hasFocus == true }.map { $0.0 }
        func adjacentReadback(_ name: String) -> String {
            guard let beforeInput else { return "notCompared" }
            guard let before = beforeInput.adjacentFields[name], let after = form.adjacentFields[name],
                  sameIdentity(before, after), let prior = NativeControlPolicy.valueText(before.value),
                  let latest = NativeControlPolicy.valueText(after.value) else { return "unavailable" }
            return prior == latest ? "unchanged" : "changed"
        }
        // hasFocus describes UI focus. XCTest's element-scoped typeText
        // separately requires keyboard focus on that element or a descendant.
        var detail: [String: Any] = [
            "sample": beforeInput == nil ? "afterTap" : "afterInput",
            "initialKeyboard": initialKeyboard, "keyboard": manualHostKeyboard(),
            "formUIFocus": focus.count > 1 ? "multiple" : focus.first ?? "none",
            "liveHostUIFocus": form.live.snapshot.hasFocus,
            "treeHostReadback": NativeHostObservation.ax(form.owner.snapshot.value, expected: expected).rawValue,
            "liveHostReadback": NativeHostObservation.ax(form.live.snapshot.value, expected: expected).rawValue,
            "portReadback": adjacentReadback("port"), "userReadback": adjacentReadback("user"),
        ]
        if let visual { detail["visualReadback"] = visual.rawValue }
        try post("native_progress", ["nativeCheckpoint": nativePhase, "manualHostEntry": detail])
    }

    @MainActor
    private func fillForm(_ name: String, _ text: String) throws {
        let initialKeyboard = name == "host" && nativePhase == "encrypted_key_host" ? manualHostKeyboard() : nil
        let tapped = try tapForm(name)
        let keyboardAppeared = app.keyboards.firstMatch.waitForExistence(timeout: 10)
        if !keyboardAppeared && initialKeyboard == nil { try require(false, "native_input_keyboard_missing") }
        let afterTap = try formControl(name, matching: tapped)
        if let initialKeyboard {
            try reportManualHostEntry(afterTap, expected: text, initialKeyboard: initialKeyboard)
        }
        try require(keyboardAppeared, "native_input_keyboard_missing")
        let current = afterTap.live
        try require(current.snapshot.isEnabled, "native_control_disabled")
        try post("native_progress", ["nativeCheckpoint": nativePhase, "nativeInputRole": role(current.snapshot.elementType)])
        if name == "port" {
            try post("native_progress", ["nativeCheckpoint": nativePhase,
                "nativePortType": current.snapshot.elementType == .textField ? "textField" : "other"])
        }
        var lastFailure: NativeFramePolicy.GeometryFailure = .fieldInvalid
        for _ in 0..<3 {
            let form = try formControl(name, matching: tapped)
            let (ready, selected) = (form.live, form.owner)
            try require(ready.snapshot.isEnabled && selected.snapshot.isEnabled, "native_control_disabled")
            if let failure = controlGeometry(selected, [ready]).failure {
                try reportFormGeometry(failure)
                lastFailure = failure
                continue
            }
            guard let clearCount = NativeControlPolicy.clearCount(ready.snapshot.value, placeholder: ready.snapshot.placeholderValue, secure: false) else {
                try require(false, "native_unexpected_existing_input")
                throw NSError(domain: "native_unexpected_existing_input", code: 1)
            }
            ready.element.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: clearCount) + text)
            // WebKit's accessibility snapshot can lag behind the one input.
            // Re-read only the same proven field; never repeat the input.
            for sample in 0..<6 {
                let after = try formControl(name, matching: tapped)
                let readbackState = inputReadback(after.live.snapshot.value, expected: text)
                if readbackState == "match" || sample == 5 {
                    let publishedState: String
                    if let initialKeyboard {
                        let visual = manualHostPixels(after, expected: text)
                        try reportManualHostEntry(after, expected: text, initialKeyboard: initialKeyboard,
                                                  beforeInput: form, visual: visual)
                        publishedState = NativeHostObservation.ax(after.live.snapshot.value, expected: text).rawValue
                    } else {
                        publishedState = readbackState
                    }
                    try post("native_progress", ["nativeCheckpoint": nativePhase,
                        "inputReadback": ["state": publishedState, "samples": sample + 1]])
                }
                if readbackState == "match" { return }
                if sample < 5 { Thread.sleep(forTimeInterval: 0.2) }
            }
            try require(false, "native_input_value_invalid")
            throw NSError(domain: "native_input_value_invalid", code: 1)
        }
        try failControlGeometry(lastFailure)
    }

    @MainActor
    private func password() -> XCUIElement {
        resolveControl(app.secureTextFields, app.secureTextFields, identifier: "ssh-password",
            label: mobileFlow ? NativeControlPolicy.mobilePasswordLabel : NativeControlPolicy.desktopPasswordLabel, requireTypedID: true)
    }
    @MainActor
    private func review() -> XCUIElement {
        let identified = app.descendants(matching: .any).matching(identifier: "ssh-review")
        if identified.count > 0 { return uniqueElement(identified) }
        return uniqueElement(app.descendants(matching: .any).matching(NSPredicate(format:
            "(elementType == %d OR elementType == %d) AND label == %@",
            XCUIElement.ElementType.checkBox.rawValue, XCUIElement.ElementType.switch.rawValue,
            "我已通过可信渠道独立核对以上指纹。")))
    }

    @MainActor
    private func controlIdentityRows(_ current: any XCUIElementSnapshot, _ rows: [Observed]) -> [Observed] {
        if !current.identifier.isEmpty {
            return rows.filter { $0.snapshot.identifier == current.identifier }
        }
        guard !current.label.isEmpty else { return [] }
        return rows.filter { $0.snapshot.identifier.isEmpty && $0.snapshot.label == current.label }
    }

    @MainActor
    private func controlOwner(_ current: any XCUIElementSnapshot, _ rows: [Observed]) -> Observed? {
        let identity = controlIdentityRows(current, rows)
        if !current.identifier.isEmpty && identity.count != 1 { return nil }
        let typed = identity.filter { sameIdentity($0.snapshot, current) }
        // Permit parent/leaf representations of one control in the same
        // branch when the tree gives them the same frame. Siblings and
        // rows in other windows remain ambiguous even at equal frames.
        guard let match = typed.max(by: { $0.path.count < $1.path.count }),
              typed.allSatisfy({ $0.windowPath == match.windowPath && match.path.starts(with: $0.path) &&
                  $0.snapshot.frame == match.snapshot.frame }),
              controlScope(match, rows) != nil else { return nil }
        return match
    }

    @MainActor
    private func controlVisibleFrame(_ owner: Observed, _ current: LiveControl) -> CGRect? {
        guard let window = owner.window, NativeFramePolicy.valid(owner.snapshot.frame),
              NativeFramePolicy.valid(current.snapshot.frame) else { return nil }
        return NativeFramePolicy.visible(window: window, screen: app.frame, webAncestors: owner.webs, occlusions: nativeOcclusions())
    }

    @MainActor
    private func scrollDirection(_ frames: [CGRect], _ visible: CGRect) -> NativeFramePolicy.ScrollDirection? {
        guard frames.allSatisfy({ $0.minX >= visible.minX && $0.maxX <= visible.maxX }) else { return nil }
        let above = frames.allSatisfy { $0.minY < visible.minY }
        let below = frames.allSatisfy { $0.maxY > visible.maxY }
        guard above != below else { return nil }
        return above ? .swipeDown : .swipeUp
    }

    @MainActor
    private func edgeScrollDirection(_ frames: [CGRect], _ visible: CGRect) -> NativeFramePolicy.ScrollDirection? {
        guard frames.allSatisfy(visible.contains) else { return nil }
        // Use the actual field height to bound how close it must be to an edge.
        let above = frames.allSatisfy { $0.midY < visible.midY && $0.minY - visible.minY <= $0.height }
        let below = frames.allSatisfy { $0.midY > visible.midY && visible.maxY - $0.maxY <= $0.height }
        guard above != below else { return nil }
        return above ? .swipeDown : .swipeUp
    }

    @MainActor
    private func passwordGeometryDetail(_ viewport: CGRect?, _ usable: CGRect?, _ owner: Observed,
                                        _ query: LiveControl, _ bound: LiveControl, scrollAttempted: Bool,
                                        direction: NativeFramePolicy.ScrollDirection?) -> [String: Any] {
        let rounded = NativeFramePolicy.diagnosticRect
        return ["viewport": rounded(viewport), "usable": rounded(usable), "owner": rounded(owner.snapshot.frame),
            "query": rounded(query.snapshot.frame), "bound": rounded(bound.snapshot.frame), "queryEnabled": query.snapshot.isEnabled,
            "boundEnabled": bound.snapshot.isEnabled, "queryHittable": query.hittable, "boundHittable": bound.hittable,
            "scrollAttempted": scrollAttempted, "scrollDirection": direction?.rawValue ?? "none"]
    }

    @MainActor
    private func scrollToControl(_ owner: Observed, _ window: Observed, _ web: Observed, _ visible: CGRect,
                                 _ direction: NativeFramePolicy.ScrollDirection, rows: [Observed] = [],
                                 formFailure: NativeFramePolicy.GeometryFailure? = nil, geometryDetail: [String: Any]? = nil) throws {
        guard liveOnPath(window) != nil, let surface = liveOnPath(web) else {
            if let failure = formFailure { try reportFormGeometry(failure, detail: geometryDetail) }
            try require(false, "native_scroll_owner_unproven")
            throw NSError(domain: "native_scroll_owner_unproven", code: 1)
        }
        let webFrame = surface.snapshot.frame
        let frameValid = NativeFramePolicy.valid(webFrame) && webFrame.contains(visible)
        if !frameValid {
            if let failure = formFailure {
                try reportFormGeometry(failure)
                try reportFormGeometry(.webAncestorInvalid, detail: geometryDetail)
            }
            try failControlGeometry(.webAncestorInvalid)
        }
        var target = surface
        var band = visible
        if !surface.hittable {
            // A visible scroll container on the same bound path can supply
            // the gesture's origin when the WebView itself has no hit point.
            let ancestors = rows.filter { row in
                row.snapshot.elementType == .scrollView && row.windowPath == window.path &&
                    row.path.count > window.path.count && row.path.count < owner.path.count &&
                    owner.path.starts(with: row.path) && (row.webPath == web.path || web.path.starts(with: row.path))
            }.sorted { $0.path.count > $1.path.count }
            for ancestor in ancestors {
                guard let live = liveOnPath(ancestor), live.hittable, NativeFramePolicy.valid(live.snapshot.frame) else { continue }
                let clipped = visible.intersection(live.snapshot.frame)
                guard NativeFramePolicy.valid(clipped),
                      let current = NativeFramePolicy.scrollBand(in: clipped, occlusions: nativeOcclusions()) else { continue }
                target = live
                band = current
                break
            }
        }
        if !target.hittable, let failure = formFailure {
            try reportFormGeometry(failure)
            if let detail = geometryDetail { try reportFormGeometry(.scrollSurfaceUnhittable, detail: detail) }
            try failControlGeometry(failure)
        }
        try require(target.hittable, "native_control_not_visible")
        let frame = target.snapshot.frame
        func point(_ fraction: CGFloat) -> XCUICoordinate {
            target.element.coordinate(withNormalizedOffset: CGVector(
                dx: (band.midX - frame.minX) / frame.width,
                dy: (band.minY + fraction * band.height - frame.minY) / frame.height))
        }
        // Keep the entire gesture in the proven WebView's unobscured area.
        let start: CGFloat = direction == .swipeDown ? 0.25 : 0.75
        point(start).press(forDuration: 0.05, thenDragTo: point(1 - start))
    }

    @MainActor
    private func reveal(_ item: XCUIElement, matching expected: RevealedControl? = nil, scrolling: Bool = true,
                        protectRouteTabs: Bool = false, mobileOwnerFailure: String? = nil,
                        authMethod: NativeControlPolicy.AuthMethod? = nil) throws -> RevealedControl {
        try require(item.waitForExistence(timeout: 20), "native_control_missing")
        let ownerFailure = mobileOwnerFailure ?? "native_control_owner_unproven"
        let queryMayBind = expected != nil && mobileOwnerFailure != nil
        let passwordDiagnostics = nativePhase == "ordinary_password" || nativePhase == "key_change_password"
        let attempts = scrolling ? 10 : 3
        var prior = expected
        var lastScroll: (frames: [CGRect], direction: NativeFramePolicy.ScrollDirection)?
        var retriedMotionSample = false
        var triedEdgeScroll = false
        for attempt in 0..<attempts {
            guard let current = liveControl(item) else {
                try require(false, "native_control_missing")
                throw NSError(domain: "native_control_missing", code: 1)
            }
            let rows = try observedNodes()
            guard let owner = controlOwner(current.snapshot, rows), let scope = controlScope(owner, rows),
                  liveOnPath(scope.window) != nil, let web = liveOnPath(scope.web),
                  let bound = queryMayBind ? (try? mobileLiveControl(owner, in: web).get()) : liveOnPath(owner) else {
                try require(false, ownerFailure)
                throw NSError(domain: ownerFailure, code: 1)
            }
            let resolved = RevealedControl(live: bound, owner: owner, window: scope.window, web: scope.web)
            if let method = authMethod {
                guard case .success(let index) = method.candidate(rows.map({ authMethodFact($0.snapshot) })),
                      rows[index].path == owner.path, owner.snapshot.isEnabled else {
                    try require(false, ownerFailure)
                    throw NSError(domain: ownerFailure, code: 1)
                }
            }
            if let prior = prior {
                try require(sameControlScope(resolved, prior) && sameIdentity(owner.snapshot, prior.owner.snapshot), ownerFailure)
            }
            prior = resolved
            let frames = [owner.snapshot.frame, current.snapshot.frame, bound.snapshot.frame]
            let geometry = controlGeometry(owner, [current, bound], measureScrollBand: scrolling || passwordDiagnostics) { viewport, failed in
                guard failed || passwordDiagnostics || protectRouteTabs else { return nil }
                return self.routeTabsOcclusion(owner, rows, viewport, frames, scrolling: scrolling && failed)
            }
            guard let failure = geometry.failure else { return resolved }
            var reason = failure
            if failure == .fieldUnhittable && current.hittable != bound.hittable {
                reason = current.hittable ? .boundUnhittable : .queriedUnhittable
            }
            func detail(_ direction: NativeFramePolicy.ScrollDirection?) -> [String: Any]? {
                guard passwordDiagnostics else { return nil }
                return passwordGeometryDetail(geometry.viewport, geometry.scrollFrame, owner, current, bound,
                    scrollAttempted: lastScroll != nil, direction: direction ?? lastScroll?.direction)
            }
            guard failure.canRetryTap else {
                if passwordDiagnostics { try reportFormGeometry(reason, detail: detail(nil)) }
                try failControlGeometry(failure)
            }
            let lastAttempt = attempt == attempts - 1
            if let previous = lastScroll, !zip(previous.frames, frames).allSatisfy({ before, after in
                previous.direction == .swipeUp ? after.midY < before.midY : after.midY > before.midY
            }) {
                if retriedMotionSample || lastAttempt {
                    if passwordDiagnostics { try reportFormGeometry(.scrollNoProgress, detail: detail(nil)) }
                    break
                }
                retriedMotionSample = true
                if passwordDiagnostics { try reportFormGeometry(reason) }
                Thread.sleep(forTimeInterval: 0.15)
                continue
            }
            if scrolling, !lastAttempt, let visible = geometry.scrollFrame {
                let regular = scrollDirection(frames, visible)
                let edge = failure == .fieldUnhittable && !triedEdgeScroll ? edgeScrollDirection(frames, visible) : nil
                if let direction = regular ?? edge {
                    let enabled = owner.snapshot.isEnabled && current.snapshot.isEnabled && bound.snapshot.isEnabled
                    if !enabled && passwordDiagnostics { try reportFormGeometry(reason, detail: detail(direction)) }
                    try require(enabled, "native_control_disabled")
                    try scrollToControl(owner, scope.window, scope.web, visible, direction, rows: rows,
                        formFailure: passwordDiagnostics ? reason : nil, geometryDetail: detail(direction))
                    lastScroll = (frames, direction)
                    retriedMotionSample = false
                    if regular == nil { triedEdgeScroll = true }
                    if passwordDiagnostics { try reportFormGeometry(reason) }
                    continue
                }
            }
            if lastAttempt || (scrolling && failure == .fieldUnhittable && attempt >= 2) {
                if passwordDiagnostics {
                    let direction = geometry.scrollFrame.flatMap { scrollDirection(frames, $0) }
                    let unproven = scrolling && direction == nil && failure != .fieldUnhittable
                    try reportFormGeometry(unproven ? .scrollDirectionUnproven : reason, detail: detail(direction))
                }
                break
            }
            if passwordDiagnostics { try reportFormGeometry(reason) }
        }
        try require(false, "native_control_not_visible")
        throw NSError(domain: "native_control_not_visible", code: 1)
    }

    @MainActor
    private func tap(_ item: XCUIElement) throws {
        let current = try reveal(item).live
        try require(current.snapshot.isEnabled, "native_control_disabled")
        current.element.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    }

    @MainActor
    private func fillPassword(_ item: XCUIElement, _ text: String, mobileOwner: RevealedControl? = nil) throws {
        try require(!mobileFlow || mobileOwner != nil, "native_mobile_password_owner_unproven")
        let ownerFailure = mobileOwner == nil ? nil : "native_mobile_password_owner_unproven"
        let initial = try reveal(item, matching: mobileOwner, mobileOwnerFailure: ownerFailure)
        let current = initial.live
        try require(current.snapshot.elementType == .secureTextField, "native_control_owner_unproven")
        try require(current.snapshot.isEnabled, "native_control_disabled")
        current.element.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        try post("native_progress", ["nativeCheckpoint": nativePhase, "nativeInputRole": role(current.snapshot.elementType)])
        try require(app.keyboards.firstMatch.waitForExistence(timeout: 10), "native_input_keyboard_missing")
        let ready = try reveal(item, matching: initial, scrolling: false, mobileOwnerFailure: ownerFailure).live
        try require(ready.snapshot.isEnabled, "native_control_disabled")
        try require(NativeControlPolicy.credentialEmpty(ready.snapshot.value, placeholder: ready.snapshot.placeholderValue),
                    "native_unexpected_existing_input")
        ready.element.typeText(text)
    }

    @MainActor
    private func check(_ expected: Bool, enabled: Bool) throws {
        let item = review()
        try require(item.waitForExistence(timeout: 10), "native_review_lock_invalid")
        guard let current = liveControl(item) else {
            try require(false, "native_review_lock_invalid")
            throw NSError(domain: "native_review_lock_invalid", code: 1)
        }
        try require(current.snapshot.isEnabled == enabled, "native_review_lock_invalid")
        try require(NativeControlPolicy.valueText(current.snapshot.value) == (expected ? "1" : "0"), "native_review_value_invalid")
    }

    @MainActor
    private func approve(_ fingerprint: String, port: Int, excluding: String? = nil) throws -> RevealedControl? {
        if mobileFlow {
            let cancel = excluding == nil ? "取消核对" : "取消核对，保留旧信任"
            let algorithmKey: String
            switch scenario {
            case "ordinary": algorithmKey = "ordinaryAlgorithm"
            case "encrypted_key": algorithmKey = "encryptedAlgorithm"
            default: algorithmKey = excluding == nil ? "rotationAlgorithm" : "rotatedAlgorithm"
            }
            let algorithm = config[algorithmKey] as! String
            let (rows, anchors) = try mobileWitness([
                ("ssh-step-title", "核对主机密钥", false), ("ssh-reviewed-endpoint", target(port), false),
                ("ssh-reviewed-algorithm", algorithm, false), ("ssh-reviewed-fingerprint", fingerprint, false),
                ("ssh-trust-cancel", cancel, true), ("ssh-trust-confirm", "指纹一致，确认继续", true)])
            try assertMobileSecretsLocked(anchors[0], rows)
            try require(anchors[4].snapshot.isEnabled, "native_review_lock_invalid")
            let ownerFailure = "native_mobile_confirmation_owner_unproven"
            let confirmation = try mobileControl(anchors[5], rows, ownerFailure)
            try tapMobileButton(confirmation, ownerFailure)
            return try mobileAuth(port: port, ready: false, previous: confirmation).password
        }
        try waitText(fingerprint)
        if let excluding = excluding { try require(try !contains(excluding), "native_old_fingerprint_stale") }
        try check(false, enabled: true)
        try tap(review())
        try check(true, enabled: true)
        return nil
    }

    @MainActor
    private func mobileWitness(_ targets: [(String?, String, Bool)], includeOffscreenText: Bool = false) throws -> ([Observed], [Observed]) {
        try waitForMobileWitness(targets, includeOffscreenText: includeOffscreenText) { .ready(($0, $1)) }
    }

    @MainActor
    private func visibleWitness(_ rows: [Observed], _ targets: [(String?, String, Bool)], includeOffscreenText: Bool = false) -> [Observed]? {
        let displayed = rows.filter { NativeFramePolicy.valid($0.snapshot.frame) &&
            (includeOffscreenText || $0.snapshot.frame.intersects(app.frame) || $0.snapshot.elementType == .button) }
        let facts = displayed.map { row in
            let snapshot = row.snapshot
            let label = texts(snapshot).first(where: { !$0.isEmpty }) ?? ""
            // The active settings status can wrap its sole static text leaf.
            let statusGroup = snapshot.identifier == "ssh-settings-active" && snapshot.elementType == .group
            return NativeControlPolicy.Fact(identifier: snapshot.identifier,
                label: NativeControlPolicy.fingerprintText(label), role: statusGroup ? "other" : role(snapshot.elementType), value: nil)
        }
        return NativeControlPolicy.pageWitness(facts, paths: displayed.map(\.path), windows: displayed.map(\.windowPath),
            webs: displayed.map(\.webPath), targets: targets)?.map { displayed[$0] }
    }

    @MainActor
    private func waitForMobileWitness<Proof>(_ targets: [(String?, String, Bool)], includeOffscreenText: Bool,
                                    onMissing: (() throws -> Void)? = nil,
                                    prove: ([Observed], [Observed]) throws -> MobileWitnessObservation<Proof>) throws -> Proof {
        let deadline = Date().addingTimeInterval(20)
        var pending = "native_mobile_setup_unproven"
        var pendingObservation: (() -> [String: Any])?
        repeat {
            let rows = try observedNodes()
            if let matches = visibleWitness(rows, targets, includeOffscreenText: includeOffscreenText) {
                switch try prove(rows, matches) {
                case .ready(let proof): return proof
                case .pending(let reason, let observe):
                    pending = reason
                    pendingObservation = observe
                }
            } else {
                pending = "native_mobile_setup_unproven"
                pendingObservation = nil
            }
            Thread.sleep(forTimeInterval: 0.2)
        } while Date() < deadline
        if pending == "native_mobile_setup_unproven" { try onMissing?() }
        try require(false, pending, passwordObservation: pendingObservation?())
        throw NSError(domain: pending, code: 1)
    }

    @MainActor
    private func mobileLiveControl(_ owner: Observed, in web: LiveControl) -> Result<LiveControl, NativeControlPolicy.MobilePasswordIssue> {
        // WebKit can flatten intermediary AX nodes in XCUI's child queries.
        // Re-query the role inside the proven WebView and require a unique
        // live element that agrees with the raw snapshot identity and frame.
        let snapshot = owner.snapshot
        let match: NSPredicate
        let method = authMethodFact(snapshot)
        if let choice = NativeControlPolicy.AuthMethod.allCases.first(where: { $0.matches(method) }),
           NativeControlPolicy.AuthMethod.roles.contains(method.role) {
            match = NSPredicate(format: "identifier == %@ OR label == %@", choice.identifier, choice.label)
        } else if let field = NativeControlPolicy.KeyField.allCases.first(where: {
            $0.matches(identifier: snapshot.identifier, label: snapshot.label)
        }), field.accepts(role: snapshot.elementType == .textView ? "textView" : role(snapshot.elementType)) {
            match = NSPredicate(format: "identifier == %@ OR label IN %@", field.rawValue, field.labels)
        } else if snapshot.elementType == .secureTextField {
            // Include both names in the scoped query so a second live
            // representation cannot be ignored at the actual interaction.
            // The raw witness still has to match the returned node exactly.
            match = NSPredicate(format: "identifier == %@ OR label IN %@", "ssh-password", NativeControlPolicy.mobilePasswordLabels)
        } else if snapshot.elementType == .button {
            match = snapshot.identifier.isEmpty ? NSPredicate(format: "label == %@", snapshot.label) :
                NSPredicate(format: "identifier == %@", snapshot.identifier)
        } else {
            return .failure(.liveIdentity)
        }
        let query = web.element.descendants(matching: snapshot.elementType).matching(match)
        let matches = query.count
        guard matches <= 1 else { return .failure(.liveAmbiguous) }
        guard matches == 1 else { return .failure(.liveMissing) }
        guard let queried = liveControl(query.firstMatch) else { return .failure(.liveUnreadable) }
        guard sameIdentity(snapshot, queried.snapshot) else { return .failure(.liveIdentity) }
        guard NativeFramePolicy.valid(snapshot.frame), snapshot.frame == queried.snapshot.frame else { return .failure(.frameUnsettled) }
        return .success(queried)
    }

    @MainActor
    private func sameControlScope(_ lhs: RevealedControl, _ rhs: RevealedControl) -> Bool {
        sameControlScope((lhs.window, lhs.web), rhs)
    }

    @MainActor
    private func sameControlScope(_ scope: (window: Observed, web: Observed), _ previous: RevealedControl) -> Bool {
        scope.window.path == previous.window.path && scope.web.path == previous.web.path &&
            sameIdentity(scope.window.snapshot, previous.window.snapshot) && sameIdentity(scope.web.snapshot, previous.web.snapshot)
    }

    @MainActor
    private func mobileControl(_ anchor: Observed, _ rows: [Observed], _ ownerFailure: String) throws -> RevealedControl {
        guard case .success(let bound) = mobileBinding(anchor, rows) else {
            try require(false, ownerFailure)
            throw NSError(domain: ownerFailure, code: 1)
        }
        return bound
    }

    @MainActor
    private func mobileBinding(_ anchor: Observed, _ rows: [Observed]) -> Result<RevealedControl, NativeControlPolicy.MobilePasswordIssue> {
        guard let scope = controlScope(anchor, rows) else { return .failure(.rawOwner) }
        guard let owner = controlOwner(anchor.snapshot, rows), owner.path == anchor.path else { return .failure(.rawAmbiguous) }
        guard liveOnPath(scope.window) != nil, let web = liveOnPath(scope.web) else { return .failure(.liveOwner) }
        return mobileLiveControl(owner, in: web).map {
            RevealedControl(live: $0, owner: owner, window: scope.window, web: scope.web)
        }
    }

    @MainActor
    private func tapMobileButton(_ control: RevealedControl, _ ownerFailure: String,
                                 authMethod: NativeControlPolicy.AuthMethod? = nil) throws {
        let current = try reveal(control.live.element, matching: control,
            protectRouteTabs: true, mobileOwnerFailure: ownerFailure, authMethod: authMethod).live
        if let method = authMethod {
            let fact = authMethodFact(current.snapshot)
            try require(method.matches(fact) && NativeControlPolicy.AuthMethod.roles.contains(fact.role), ownerFailure)
        } else {
            try require(current.snapshot.elementType == .button, ownerFailure)
        }
        try require(current.snapshot.isEnabled, "native_control_disabled")
        current.element.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    }

    @MainActor
    private func mobileTarget(prior: String? = nil) throws {
        var targets: [(String?, String, Bool)] = [("ssh-step-title", "普通 SSH", false),
            ("ssh-step-back", "返回", true), ("ssh-probe", "探测并核对主机密钥", true)]
        if let prior = prior { targets.append(("ssh-prior-fingerprint", "保留的旧指纹：" + prior, false)) }
        let (rows, anchors) = try mobileWitness(targets)
        try assertMobileSecretsLocked(anchors[0], rows)
    }

    @MainActor
    @discardableResult
    private func mobileDisconnected() throws -> RevealedControl {
        let (rows, anchors) = try mobileWitness([("ssh-step-title", "普通 SSH", false), ("ssh-closed-title", "本机已断开", false),
            ("ssh-closed-detail", "凭据已清空，重连时请重新填写。", false), ("ssh-return-home", "返回首页", true)])
        try assertMobileSecretsLocked(anchors[0], rows)
        return try mobileControl(anchors[3], rows, "native_mobile_return_owner_unproven")
    }

    @MainActor
    private func assertMobileSecretsLocked(_ anchor: Observed, _ rows: [Observed]) throws {
        try assertCredentialsInactive(anchor, rows)
        let submits = rows.filter { $0.snapshot.elementType == .button &&
            ($0.snapshot.identifier == "ssh-connect" || $0.snapshot.label == "连接 SSH") }
        try require(submits.count <= 1 && submits.allSatisfy {
            !$0.snapshot.isEnabled && !NativeFramePolicy.valid($0.snapshot.frame)
        }, "native_review_lock_invalid")
    }

    @MainActor
    private func mobileAuth(port: Int, ready: Bool, previous: RevealedControl) throws -> (password: RevealedControl, submit: RevealedControl) {
        try waitForMobileWitness([("ssh-step-title", "SSH 账号认证", false),
            ("ssh-reviewed-endpoint", target(port), false), ("ssh-approved-note", "本次主机密钥已确认", false),
            ("ssh-connect", "连接 SSH", true)], includeOffscreenText: ready) { rows, anchors in
            let submit = anchors[3]
            try require(submit.snapshot.isEnabled == ready, "native_review_lock_invalid")
            let password: RevealedControl
            switch mobilePassword(in: rows, submit: submit, previous: previous, requireHittable: !ready) {
            case .success(let control): password = control
            case .failure(let issue):
                let observe = { self.mobilePasswordObservation(in: rows, submit: submit, previous: previous) }
                if issue.pending { return .pending(issue.rawValue, observe) }
                try require(false, issue.rawValue, passwordObservation: issue == .disabled ? nil : observe())
                throw issue
            }
            let current = password.live.snapshot
            if !ready || current.value != nil {
                try require(NativeControlPolicy.credentialEmpty(current.value, placeholder: current.placeholderValue) != ready,
                            "native_review_lock_invalid")
            }
            try assertNoSecret(rows.map { $0.snapshot })
            let submitControl = try mobileControl(submit, rows, "native_mobile_submit_owner_unproven")
            try require(submitControl.live.snapshot.isEnabled == ready, "native_review_lock_invalid")
            return .ready((password, submitControl))
        }
    }

    @MainActor
    private func mobilePassword(in rows: [Observed], submit: Observed, previous: RevealedControl, requireHittable: Bool)
        -> Result<RevealedControl, NativeControlPolicy.MobilePasswordIssue> {
        guard let scope = controlScope(submit, rows) else { return .failure(.rawOwner) }
        guard sameControlScope(scope, previous) else { return .failure(.ownerChanged) }
        let named = rows.filter { row in
            let field = row.snapshot
            return NativeControlPolicy.isMobilePasswordField(identifier: field.identifier, label: field.label)
        }
        let fields = named.filter { $0.snapshot.elementType == .secureTextField }
        guard fields.count <= 1, named.filter({ $0.snapshot.identifier == "ssh-password" }).count <= 1 else {
            return .failure(.rawAmbiguous)
        }
        guard !named.contains(where: { [.textField, .searchField, .textView].contains($0.snapshot.elementType) }) else {
            return .failure(.wrongRole)
        }
        guard let field = fields.first else { return .failure(named.isEmpty ? .identityMissing : .secureRoleMissing) }
        guard field.windowPath == submit.windowPath, field.webPath == submit.webPath else { return .failure(.rawOwner) }
        guard field.snapshot.isEnabled else { return .failure(.disabled) }
        return mobileBinding(field, rows).flatMap { password in
            guard password.live.snapshot.isEnabled else { return .failure(.disabled) }
            // After password entry the keyboard can scroll the field away.
            // The submit action has its own fresh geometry and hit test.
            guard requireHittable else { return .success(password) }
            let frame = password.live.snapshot.frame
            let geometry = controlGeometry(field, [password.live]) { viewport, _ in
                self.routeTabsOcclusion(field, rows, viewport, [frame], scrolling: false)
            }
            switch geometry.failure {
            // A real, stable offscreen frame can be revealed before touching
            // the field, using the existing guarded scrolling path.
            case nil, .fieldOutside, .fieldOccluded: return .success(password)
            case .fieldUnhittable: return .failure(.unhittable)
            default: return .failure(.frameUnsettled)
            }
        }
    }

    @MainActor
    private func mobilePasswordObservation(in rows: [Observed], submit: Observed, previous: RevealedControl) -> [String: Any] {
        let limit = 12
        let visible = submit.window.flatMap {
            NativeFramePolicy.visible(window: $0, screen: app.frame, webAncestors: submit.webs, occlusions: nativeOcclusions())
        }
        func row(_ snapshot: any XCUIElementSnapshot, owner: String, hit: Bool?) -> [String: Any] {
            let label = NativeControlPolicy.passwordLabelKind(snapshot.label)
            let identifier = snapshot.identifier == "ssh-password" ? "expected" : snapshot.identifier.isEmpty ? "empty" :
                snapshot.identifier == snapshot.label ? "labelAlias" : "other"
            let role = snapshot.elementType == .textView ? "textView" : snapshot.elementType == .searchField ? "searchField" :
                self.role(snapshot.elementType)
            let frame: String
            if !NativeFramePolicy.valid(snapshot.frame) { frame = "invalid" }
            else if let visible, owner == "sameWeb" {
                frame = visible.contains(snapshot.frame) ? "inside" : visible.intersects(snapshot.frame) ? "intersects" : "outside"
            } else { frame = "unmeasured" }
            return ["role": role, "owner": owner, "idKind": identifier, "labelKind": label,
                    "frameKind": frame, "enabled": snapshot.isEnabled,
                    "hit": hit.map { $0 ? "yes" : "no" } ?? "unknown"]
        }
        let candidates = rows.filter {
            let snapshot = $0.snapshot
            let label = NativeControlPolicy.passwordLabelKind(snapshot.label)
            return [.secureTextField, .textField, .textView, .searchField].contains(snapshot.elementType) ||
                snapshot.identifier == "ssh-password" || !["empty", "other"].contains(label)
        }
        let raw = candidates.prefix(limit).map { candidate in
            let owner: String
            if candidate.windowPath.isEmpty { owner = "unowned" }
            else if candidate.windowPath != submit.windowPath { owner = "otherWindow" }
            else if candidate.webPath.isEmpty { owner = "unowned" }
            else if candidate.webPath != submit.webPath { owner = "otherWeb" }
            else { owner = "sameWeb" }
            return row(candidate.snapshot, owner: owner, hit: nil)
        }
        var live: [[String: Any]] = []
        var liveCount = -1
        if let scope = controlScope(submit, rows), sameControlScope(scope, previous),
           liveOnPath(scope.window) != nil, let web = liveOnPath(scope.web) {
            let query = web.element.descendants(matching: .secureTextField)
            liveCount = min(10000, query.count)
            live = (0..<min(limit, liveCount)).compactMap { index in
                liveControl(query.element(boundBy: index)).map { row($0.snapshot, owner: "sameWeb", hit: $0.hittable) }
            }
        }
        return ["rawCount": candidates.count, "raw": raw, "scopedSecureCount": liveCount, "scopedSecure": live]
    }

    @MainActor
    private func assertNoSecret(_ rows: [any XCUIElementSnapshot]) throws {
        var secrets = ["ordinaryPassword", "rotationPassword", "encryptedWrongPassphrase", "encryptedPassphrase"]
            .compactMap { config[$0] as? String }
        if scenario == "encrypted_key" {
            secrets.append(NativeControlPolicy.openSSHPrivateKeyHeader)
            secrets += NativeControlPolicy.encryptedPEMBodyLines(config["encryptedPEM"] as? String ?? "")
        }
        try require(!rows.contains { node in
            ([node.identifier] + texts(node)).contains { value in secrets.contains { value.contains($0) } }
        }, "native_secret_exposed")
    }

    @MainActor
    private func pageScope(_ item: any XCUIElementSnapshot, _ rows: [Observed], _ page: Observed) throws -> NativeViewPolicy.Scope {
        func scope(_ row: Observed) -> NativeViewPolicy.Scope {
            NativeViewPolicy.scope(window: row.windowPath, web: row.webPath,
                currentWindow: page.windowPath, currentWeb: page.webPath)
        }
        if let owner = controlOwner(item, rows) { return scope(owner) }
        // A native or auxiliary control needs a positive snapshot match.
        // A missing or changed ID could still be a product control.
        let candidates = controlIdentityRows(item, rows)
        if let match = candidates.first {
            let classification = scope(match)
            if (classification == .nativeSystem || classification == .otherWindow) &&
                candidates.allSatisfy({ sameIdentity($0.snapshot, item) && scope($0) == classification }) {
                return classification
            }
        }
        try require(false, "native_owner_ambiguous")
        throw NSError(domain: "native_owner_ambiguous", code: 1)
    }

    @MainActor
    private func assertCredentialsInactive(_ page: Observed, _ rows: [Observed], visible activeVisible: CGRect? = nil) throws {
        let visible = try activeVisible ?? safeFrame([page])
        for (identifier, labels) in [("ssh-password", mobileFlow ? NativeControlPolicy.mobilePasswordLabels : [NativeControlPolicy.desktopPasswordLabel]),
            ("ssh-key", mobileFlow ? NativeControlPolicy.KeyField.pem.labels : ["私钥"]),
            ("ssh-passphrase", mobileFlow ? NativeControlPolicy.KeyField.passphrase.labels : ["私钥口令（可选）"])] {
            let query = app.descendants(matching: .any).matching(NSPredicate(format:
                "identifier == %@ OR label IN %@", identifier, labels))
            var visibleLabel = false
            for text in app.staticTexts.matching(NSPredicate(format: "label IN %@", labels)).allElementsBoundByIndex
            {
                guard let current = liveControl(text), current.hittable,
                      current.snapshot.frame.intersects(visible) else { continue }
                if try pageScope(current.snapshot, rows, page) == .current { visibleLabel = true }
            }
            for field in query.allElementsBoundByIndex {
                guard let current = liveControl(field),
                      [.textField, .secureTextField, .textView, .other].contains(current.snapshot.elementType) else { continue }
                let snapshot = current.snapshot
                let nonempty = !NativeControlPolicy.credentialEmpty(snapshot.value, placeholder: snapshot.placeholderValue)
                // A retained AX node alone is not visibility or interactivity.
                if !nonempty && !snapshot.isEnabled && !current.hittable && !visibleLabel { continue }
                let scope = try pageScope(snapshot, rows, page)
                try require(scope != .ambiguous, "native_owner_ambiguous")
                if scope != .current { continue }
                let painted = visibleLabel || (current.hittable && NativeFramePolicy.valid(snapshot.frame) && snapshot.frame.intersects(visible))
                try require(!NativeViewPolicy.unsafeCredential(nonempty: nonempty, enabled: snapshot.isEnabled,
                    hittable: current.hittable, visible: painted), "native_credentials_visible_after_connect")
            }
        }
    }

    @MainActor
    private func assertReviewActions(_ page: Observed, _ rows: [Observed], _ labels: Set<String>, reviewSample: String) throws {
        let visible = try safeFrame([page])
        var actions: [NativeViewPolicy.Action] = []
        for item in app.buttons.allElementsBoundByIndex {
            guard let current = liveControl(item), current.hittable,
                  NativeFramePolicy.valid(current.snapshot.frame), current.snapshot.frame.intersects(visible) else { continue }
            let scope = try pageScope(current.snapshot, rows, page)
            try require(scope != .ambiguous, "native_owner_ambiguous")
            actions.append(NativeViewPolicy.Action(scope: scope, label: current.snapshot.label, frame: current.snapshot.frame,
                enabled: current.snapshot.isEnabled, hittable: current.hittable))
        }
        let valid = NativeViewPolicy.reviewValid(actions, expected: labels, visible: visible)
        if !valid {
            let expected = [("重新核对主机指纹", "review_recheck"), ("取消连接，保留旧信任", "review_cancel")]
            let failed = expected.first { label, _ in
                !NativeViewPolicy.reviewValid(actions.filter { $0.label == label }, expected: [label], visible: visible)
            }
            let candidates = rows.filter { row in row.snapshot.elementType == .button &&
                (failed == nil || row.snapshot.label == failed?.0) }
            try captureDiagnostic(failed?.1 ?? "review_title", "geometry_ambiguous", candidates, rows,
                visible: visible, reviewSample: reviewSample)
        }
        try require(valid, "native_review_exits_invalid")
    }

    @MainActor
    private func target(_ port: Int) -> String { "fixture@127.0.0.1:\(port)" }
    @MainActor
    private func rect(_ value: CGRect) -> [Double] {
        [Double(value.minX), Double(value.minY), Double(value.width), Double(value.height)]
    }

    @MainActor
    private func statusBarFrames() -> [CGRect] {
        let system = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        return NativeFramePolicy.unique((app.statusBars.allElementsBoundByIndex + system.statusBars.allElementsBoundByIndex)
            .compactMap { liveControl($0)?.snapshot.frame }.filter(NativeFramePolicy.valid))
    }

    @MainActor
    private func keyboardFrames() -> [CGRect] {
        app.keyboards.allElementsBoundByIndex.compactMap { liveControl($0)?.snapshot.frame }
    }

    @MainActor
    private func nativeOcclusions() -> [CGRect] {
        NativeFramePolicy.unique(statusBarFrames() + keyboardFrames().filter { NativeFramePolicy.valid($0.intersection(app.frame)) })
    }

    @MainActor
    private func safeFrame(_ anchors: [Observed], occlusions: [CGRect]? = nil,
                           onInvalid: ((String) throws -> Void)? = nil) throws -> CGRect {
        guard let first = anchors.first, let window = first.window else {
            try onInvalid?("owner_unproven")
            try require(false, "native_window_missing")
            throw NSError(domain: "native_window_missing", code: 1)
        }
        let validWeb = !first.webs.isEmpty && first.webs.count <= 16
        if !validWeb { try onInvalid?("owner_unproven") }
        try require(validWeb, "native_webview_ambiguous")
        let sameOwner = NativeFramePolicy.sameOwner(windowPaths: anchors.map { $0.windowPath }, webPaths: anchors.map { $0.webPath }) &&
            anchors.allSatisfy { $0.window == window }
        if !sameOwner { try onInvalid?("owner_ambiguous") }
        try require(sameOwner, "native_owner_ambiguous")
        let blockers = occlusions ?? nativeOcclusions()
        var common = window
        for anchor in anchors {
            guard let visible = NativeFramePolicy.visible(window: window, screen: app.frame,
                    webAncestors: anchor.webs, occlusions: blockers) else {
                try onInvalid?("viewport_invalid")
                try require(false, "native_visible_frame_invalid")
                throw NSError(domain: "native_visible_frame_invalid", code: 1)
            }
            common = common.intersection(visible)
        }
        if !NativeFramePolicy.valid(common) { try onInvalid?("viewport_invalid") }
        try require(NativeFramePolicy.valid(common), "native_visible_frame_invalid")
        return common
    }

    @MainActor
    private func captureDiagnostic(_ anchor: String, _ reason: String, _ candidates: [Observed],
                                   _ rows: [Observed], visible: CGRect? = nil, reviewSample: String? = nil) throws {
        let items = candidates.prefix(8).map { item in
            let frame = item.snapshot.frame
            return ["role": role(item.snapshot.elementType), "frame": NativeFramePolicy.diagnosticRect(frame),
                "ownerResolved": controlScope(item, rows) != nil,
                "visible": visible.map { NativeFramePolicy.valid(frame.intersection($0)) } ?? false] as [String: Any]
        }
        var detail: [String: Any] = ["anchor": anchor, "reason": reason, "matchCount": min(candidates.count, 10000),
                                    "candidates": items, "truncated": candidates.count > items.count]
        if let sample = reviewSample { detail["sample"] = sample }
        try post("native_capture_diagnostic", ["nativeCheckpoint": nativePhase, "detail": detail])
    }

    @MainActor
    private func exactObserved(_ rows: [Observed], _ text: String, identifiers: [String] = [], control: Bool = false,
                               captureAnchor: String? = nil, requireVisible: Bool = true, reviewSample: String? = nil,
                               occlusions: [CGRect]? = nil, requireExactText: Bool = false) throws -> Observed {
        let expectedText = NativeControlPolicy.fingerprintText(text)
        let matchesText: (Observed) -> Bool = { row in
            self.texts(row.snapshot).map(NativeControlPolicy.fingerprintText).contains(expectedText)
        }
        let allMatches = rows.filter { identifiers.contains($0.snapshot.identifier) || matchesText($0) }
        // The identifier alone cannot prove displayed text.
        let checkText = reviewSample != nil || requireExactText
        let exact = checkText ? allMatches.filter(matchesText) : allMatches
        let matches = exact.filter { NativeFramePolicy.valid($0.snapshot.frame) }
        let preferIdentifier = control || (checkText && !identifiers.isEmpty)
        let preferred = matches.indices.sorted {
            let left = preferIdentifier ? identifiers.contains(matches[$0].snapshot.identifier) :
                matches[$0].snapshot.elementType == .staticText
            let right = preferIdentifier ? identifiers.contains(matches[$1].snapshot.identifier) :
                matches[$1].snapshot.elementType == .staticText
            return left != right ? left : matches[$0].path.count > matches[$1].path.count
        }
        var reason = exact.isEmpty ? "not_found" : matches.isEmpty ? "frame_invalid" : "owner_unproven"
        var lastVisible: CGRect?
        for candidate in preferred where matches[candidate].window != nil && !matches[candidate].webs.isEmpty {
            let owner = matches[candidate]
            if captureAnchor != nil && controlScope(owner, rows) == nil { continue }
            if (captureAnchor == "review_recheck" || captureAnchor == "review_cancel") && owner.snapshot.elementType != .button {
                reason = "geometry_ambiguous"
                continue
            }
            if captureAnchor == "terminal" && ![.other, .group, .scrollView].contains(owner.snapshot.elementType) {
                reason = "geometry_ambiguous"
                continue
            }
            let compatible = NativeFramePolicy.compatibleOwner(windowPaths: matches.map { $0.windowPath },
                webPaths: matches.map { $0.webPath }, nodePaths: matches.map { $0.path }, selected: candidate)
            let related = captureAnchor == nil || matches.allSatisfy { row in
                row.path.starts(with: owner.path) || owner.path.starts(with: row.path)
            }
            let identifiersAgree = !checkText || allMatches.filter {
                identifiers.contains($0.snapshot.identifier)
            }.allSatisfy { row in
                row.windowPath == owner.windowPath && row.webPath == owner.webPath &&
                    (row.path.starts(with: owner.path) || owner.path.starts(with: row.path))
            }
            if !(compatible && related && identifiersAgree), let anchor = captureAnchor {
                try captureDiagnostic(anchor, "owner_ambiguous", allMatches, rows, reviewSample: reviewSample)
            }
            try require(compatible && related && identifiersAgree, "native_owner_ambiguous")
            let visible: CGRect
            if requireVisible {
                visible = try safeFrame([owner], occlusions: occlusions) { reason in
                    if let anchor = captureAnchor { try self.captureDiagnostic(anchor, reason, allMatches, rows, reviewSample: reviewSample) }
                }
            } else { visible = owner.snapshot.frame }
            lastVisible = requireVisible ? visible : nil
            reason = "geometry_ambiguous"
            if requireVisible && !(control ? NativeFramePolicy.valid(owner.snapshot.frame.intersection(visible)) :
                                     visible.contains(owner.snapshot.frame)) { reason = "outside_safe_frame" }
            if let index = NativeFramePolicy.semanticIndex(frames: matches.map { $0.snapshot.frame }, preferred: [candidate],
                    visible: visible, clippedControl: control), index == candidate { return owner }
        }
        if let anchor = captureAnchor { try captureDiagnostic(anchor, reason, allMatches, rows, visible: lastVisible, reviewSample: reviewSample) }
        try require(false, "native_geometry_ambiguous")
        throw NSError(domain: "native_geometry_ambiguous", code: 1)
    }

    @MainActor
    private func terminalBoundaryControls(_ title: Observed, _ rows: [Observed]) throws -> [Observed] {
        // These controls are adjacent to xterm in the real connected page.
        // They bound a candidate strip and are never tapped to capture it.
        let keyboard = mobileFlow ? ("ssh-focus", "打开键盘") : ("ssh-hide-keyboard", "收起键盘")
        let labels = [[keyboard.1], ["Esc"], ["Tab"], ["上方向键", "↑"], ["下方向键", "↓"]]
        var controls: [Observed] = []
        for (index, aliases) in labels.enumerated() {
            let matches = rows.filter { row in
                (index == 0 && row.snapshot.identifier == keyboard.0) ||
                    (row.snapshot.elementType == .button && aliases.contains(row.snapshot.label))
            }
            if matches.count != 1 {
                try captureDiagnostic("terminal", matches.isEmpty ? "not_found" : "owner_ambiguous", controls + matches, rows)
                try require(false, matches.isEmpty ? "native_geometry_ambiguous" : "native_owner_ambiguous")
            }
            guard let control = matches.first, control.snapshot.elementType == .button,
                  control.windowPath == title.windowPath, control.webPath == title.webPath,
                  controlScope(control, rows) != nil else {
                try captureDiagnostic("terminal", "owner_unproven", controls + matches, rows)
                try require(false, "native_owner_ambiguous")
                throw NSError(domain: "native_owner_ambiguous", code: 1)
            }
            if !NativeFramePolicy.valid(control.snapshot.frame) {
                try captureDiagnostic("terminal", "frame_invalid", controls + [control], rows)
                try require(false, "native_geometry_ambiguous")
            }
            controls.append(control)
        }
        return controls
    }

    @MainActor
    private func verifyCaptureControls(_ selected: CaptureAnchors, _ rows: [Observed], _ safe: CGRect) throws {
        guard selected.usesControls else { return }
        let controls = selected.nodes.dropFirst()
        let proven = controls.allSatisfy { control in
            guard let live = liveOnPath(control) else { return false }
            return live.hittable && live.snapshot.isEnabled && live.snapshot.frame == control.snapshot.frame && safe.contains(live.snapshot.frame)
        }
        if !proven {
            try captureDiagnostic("terminal", "layout_unstable", Array(controls), rows, visible: safe)
            try require(false, "native_capture_geometry_changed")
        }
    }

    @MainActor
    private func waitForCaptureKeyboardToHide(reviewSample: String? = nil, reportDiagnostic: Bool = true) throws {
        let end = Date().addingTimeInterval(8)
        repeat {
            if !app.keyboards.firstMatch.exists {
                Thread.sleep(forTimeInterval: 0.15)
                if !app.keyboards.firstMatch.exists { return }
            }
            Thread.sleep(forTimeInterval: 0.15)
        } while Date() < end
        if reportDiagnostic {
            try captureDiagnostic(reviewSample == nil ? "keyboard" : "review_title", "keyboard_visible", [], [], reviewSample: reviewSample)
        }
        try require(false, "native_terminal_keyboard_visible")
    }

    @MainActor
    private func stableCaptureLayout(_ before: [Observed], _ after: [Observed]) -> Bool {
        before.count == after.count && zip(before, after).allSatisfy { left, right in
            left.windowPath == right.windowPath && left.webPath == right.webPath && left.path == right.path &&
                left.window == right.window && left.webs == right.webs &&
                sameIdentity(left.snapshot, right.snapshot) && left.snapshot.frame == right.snapshot.frame
        }
    }

    @MainActor
    private func terminalCaptureFrame(_ anchors: [Observed], _ rows: [Observed]) throws -> CGRect {
        let safe = try safeFrame(anchors)
        if let bar = routeTabsOcclusion(anchors[0], rows, safe, anchors.map { $0.snapshot.frame }, scrolling: true) {
            if let unobscured = NativeFramePolicy.scrollBand(in: safe, occlusions: [bar]) { return unobscured }
            try captureDiagnostic("terminal", "viewport_invalid", anchors, rows)
            try require(false, "native_visible_frame_invalid")
        }
        return safe
    }

    @MainActor
    private func terminalHeader(_ title: Observed, _ rows: [Observed], safe: CGRect,
                                active: [Observed]? = nil) throws -> TerminalHeader {
        let bars = statusBarFrames()
        if !NativeFramePolicy.headerStatusBarsValid(bars, screen: app.frame) {
            try captureDiagnostic("status_bar", bars.isEmpty ? "not_found" : "frame_invalid", [], rows, visible: safe)
            try require(false, "native_terminal_header_unproven")
        }
        if let active {
            let heading = active[0], disconnect = active[1]
            let h = heading.snapshot.frame, d = disconnect.snapshot.frame
            let ordered = h.maxX <= d.minX && max(h.minY, d.minY) < min(h.maxY, d.maxY) && max(h.maxY, d.maxY) <= title.snapshot.frame.minY
            if !ordered || !active.allSatisfy({ node in
                node.windowPath == title.windowPath && node.webPath == title.webPath &&
                    NativeFramePolicy.headerFrameClear(node.snapshot.frame, safe: safe, statusBars: bars)
            }) {
                try captureDiagnostic("terminal_heading", "outside_safe_frame", active, rows, visible: safe)
                try require(false, "native_terminal_header_unproven")
            }
            let bound = try mobileControl(disconnect, rows, "native_terminal_header_unproven")
            if !bound.live.hittable || !bound.live.snapshot.isEnabled {
                try captureDiagnostic("header_disconnect", "outside_safe_frame", [disconnect], rows, visible: safe)
                try require(false, "native_terminal_header_unproven")
            }
            return TerminalHeader(nodes: active, statusBars: bars, bottom: max(h.maxY, d.maxY))
        }
        let brand = try exactObserved(rows, "Herdr Pocket", captureAnchor: "header_brand", requireVisible: false)
        let add = try exactObserved(rows, "＋ 添加主机", identifiers: ["host-open-remote"], control: true,
            captureAnchor: "header_add", requireVisible: false)
        for (index, node) in [brand, add].enumerated() {
            let anchor = index == 0 ? "header_brand" : "header_add"
            if node.windowPath != title.windowPath || node.webPath != title.webPath ||
                (index == 1 && node.snapshot.elementType != .button) {
                try captureDiagnostic(anchor, "owner_unproven", [node], rows, visible: safe)
                try require(false, "native_terminal_header_unproven")
            }
            if !NativeFramePolicy.headerFrameClear(node.snapshot.frame, safe: safe, statusBars: bars) {
                try captureDiagnostic(anchor, "outside_safe_frame", [node], rows, visible: safe)
                try require(false, "native_terminal_header_unproven")
            }
        }
        let heading = try exactObserved(rows, "普通 SSH 终端", identifiers: ["ssh-page-heading"],
            captureAnchor: "terminal_heading", requireVisible: false, requireExactText: true)
        let actionLabel = rows.contains { row in
            row.snapshot.elementType == .button && heading.path.starts(with: row.path)
        }
        if heading.windowPath != title.windowPath || heading.webPath != title.webPath || actionLabel {
            try captureDiagnostic("terminal_heading", "owner_unproven", [heading], rows, visible: safe)
            try require(false, "native_terminal_header_unproven")
        }
        let brandFrame = brand.snapshot.frame, addFrame = add.snapshot.frame
        // A WebKit snapshot can flatten the banner. Its two controls then
        // still bound the content edge, plus the phone header's 6pt padding.
        let measuredBottom = rows.filter { row in
            row.windowPath == title.windowPath && row.webPath == title.webPath &&
                row.path.count > title.webPath.count && row.path.count < min(brand.path.count, add.path.count) &&
                brand.path.starts(with: row.path) && add.path.starts(with: row.path) &&
                !title.path.starts(with: row.path) && [.group, .other].contains(row.snapshot.elementType) &&
                NativeFramePolicy.valid(row.snapshot.frame) && row.snapshot.frame.contains(brandFrame) &&
                row.snapshot.frame.contains(addFrame)
        }.max { $0.path.count < $1.path.count }?.snapshot.frame.maxY
        let minimumBottom = max(brandFrame.maxY, addFrame.maxY) + 6
        let bottom = max(minimumBottom, measuredBottom ?? minimumBottom)
        let headingFrame = heading.snapshot.frame
        if !NativeFramePolicy.headerFrameClear(headingFrame, safe: safe, statusBars: bars) ||
            headingFrame.minY < bottom || headingFrame.maxY > title.snapshot.frame.minY {
            try captureDiagnostic("terminal_heading", "outside_safe_frame", [heading], rows, visible: safe)
            try require(false, "native_terminal_header_unproven")
        }
        return TerminalHeader(nodes: [brand, add, heading], statusBars: bars, bottom: bottom)
    }

    @MainActor
    private func screenshot(_ stage: String, port: Int, reviewPage: Bool = false, activeOwner: RevealedControl? = nil) throws {
        let reviewMembers = [("review_title", []), ("review_blocked", []),
            ("review_old_fingerprint", ["ssh-key-change-old"]), ("review_new_fingerprint", ["ssh-key-change-new"]),
            ("review_target", [mobileFlow ? "ssh-key-change-endpoint" : "ssh-key-change-target"]),
            ("review_recheck", ["ssh-key-recheck"]),
            ("review_cancel", ["ssh-key-cancel"])]
        let labels = reviewPage ? ["主机指纹发生变化", "已阻止连接与输入",
            "旧：" + (config["fingerprintA"] as! String), "新：" + (config["fingerprintB"] as! String),
            (mobileFlow ? "" : "目标：") + target(port), "重新核对主机指纹", "取消连接，保留旧信任"] :
            [target(port) + " · SSH 已连接", "SSH 终端输出"]
        func anchors(_ source: [Observed], reviewSample: String? = nil, occlusions: [CGRect]? = nil) throws -> CaptureAnchors {
            if let sample = reviewSample {
                let resolved = try zip(reviewMembers, labels).map { member, label in
                    try exactObserved(source, label, identifiers: member.1, captureAnchor: member.0, reviewSample: sample, occlusions: occlusions)
                }
                return CaptureAnchors(nodes: resolved, usesControls: false)
            }
            let title: Observed
            var activeHeader: [Observed]?
            if mobileFlow {
                guard let activeOwner,
                      let page = visibleWitness(source, NativeActivePage.terminal.witnesses(endpoint: target(port))),
                      let scope = controlScope(page[1], source), sameControlScope(scope, activeOwner) else {
                    try captureDiagnostic("target", "owner_unproven", [], source)
                    try require(false, "native_active_page_unproven")
                    throw NSError(domain: "native_active_page_unproven", code: 1)
                }
                title = page[1]
                activeHeader = [page[0], page[3]]
            } else {
                title = try exactObserved(source, labels[0], captureAnchor: "target", requireVisible: false)
            }
            if source.contains(where: { $0.snapshot.identifier == "ssh-terminal-output" || texts($0.snapshot).contains(labels[1]) }) {
                let output = try exactObserved(source, labels[1], identifiers: ["ssh-terminal-output"], control: true,
                    captureAnchor: "terminal", requireVisible: false)
                return CaptureAnchors(nodes: [title, output], usesControls: false, activeHeader: activeHeader)
            }
            return CaptureAnchors(nodes: [title] + (try terminalBoundaryControls(title, source)), usesControls: true, activeHeader: activeHeader)
        }
        if reviewPage { try waitForCaptureKeyboardToHide(reviewSample: "before") }
        var tree = try observedNodes()
        try assertNoSecret(tree.map { $0.snapshot })
        let reviewOcclusions = reviewPage ? nativeOcclusions() : nil
        var selected = try anchors(tree, reviewSample: reviewPage ? "before" : nil, occlusions: reviewOcclusions)
        var safe = reviewPage ? try safeFrame(selected.nodes, occlusions: reviewOcclusions) { reason in
            try self.captureDiagnostic("review_title", reason, selected.nodes, tree, reviewSample: "before")
        } : try terminalCaptureFrame(selected.nodes, tree)
        if !reviewPage {
            var previous: (anchors: CaptureAnchors, safe: CGRect)?
            var lastScroll: (output: CGRect, direction: NativeFramePolicy.ScrollDirection)?
            var scrolls = 0
            var settled = false
            for sample in 0..<5 {
                try waitForCaptureKeyboardToHide()
                if selected.visibleOutput(in: safe) != nil {
                    if let prior = previous, prior.safe == safe, prior.anchors.usesControls == selected.usesControls,
                       stableCaptureLayout(prior.anchors.nodes, selected.nodes) {
                        settled = true
                        break
                    }
                    previous = (selected, safe)
                } else if let output = selected.output(in: safe) {
                    previous = nil
                    let moved = lastScroll.map { prior in
                        prior.direction == .swipeUp ? output.midY < prior.output.midY : output.midY > prior.output.midY
                    } ?? true
                    if sample < 4, scrolls < 2, moved, let direction = selected.direction(in: safe),
                       let band = NativeFramePolicy.terminalPageScrollBand(safe: safe, output: output),
                       let scope = controlScope(selected.nodes[0], tree) {
                        try assertCredentialsInactive(selected.nodes[0], tree)
                        try scrollToControl(selected.nodes[0], scope.window, scope.web, band, direction, rows: tree)
                        lastScroll = (output, direction)
                        scrolls += 1
                    }
                } else { previous = nil }
                if sample < 4 {
                    Thread.sleep(forTimeInterval: 0.2)
                    tree = try observedNodes()
                    try assertNoSecret(tree.map { $0.snapshot })
                    selected = try anchors(tree)
                    safe = try terminalCaptureFrame(selected.nodes, tree)
                }
            }
            if !settled {
                let index = safe.contains(selected.frames[0]) ? 1 : 0
                let reason = selected.output(in: safe) == nil ? "geometry_ambiguous" : previous == nil ? "outside_safe_frame" : "layout_unstable"
                let candidates = index == 0 ? [selected.nodes[0]] : Array(selected.nodes.dropFirst())
                try captureDiagnostic(index == 0 ? "target" : "terminal", reason, candidates, tree, visible: safe)
                try require(false, previous == nil ? (index == 0 ? "native_target_clipped" : "native_terminal_frame_invalid") :
                    "native_capture_geometry_changed")
            }
        }
        let owner = selected.nodes[0]
        try assertCredentialsInactive(owner, tree)
        var extra: [String: Any] = ["safeFrame": rect(safe), "identityVerified": true, "noCredentialsVisible": true,
            "nativeOwner": ["windowFrame": rect(owner.window!), "webFrames": owner.webs.map(rect),
                            "webWrapperCount": owner.webs.count, "uniqueWebBoundsCount": NativeFramePolicy.unique(owner.webs).count]]
        let frames = selected.frames
        var header: TerminalHeader?
        if reviewPage {
            try require(frames.allSatisfy { safe.contains($0) && !$0.isEmpty }, "native_review_clipped")
            try assertReviewActions(owner, tree, Set(labels.suffix(2)), reviewSample: "before")
            extra["reviewFrames"] = frames.map(rect)
        } else {
            let verified = try terminalHeader(owner, tree, safe: safe, active: selected.activeHeader)
            header = verified
            if selected.activeHeader != nil {
                extra["activeHeaderBounds"] = ["titleFrame": rect(verified.nodes[0].snapshot.frame),
                    "disconnectFrame": rect(verified.nodes[1].snapshot.frame), "statusBarFrames": verified.statusBars.map(rect),
                    "sameOwner": true, "disconnectHittable": true]
            } else {
                extra["headerBounds"] = ["brandFrame": rect(verified.nodes[0].snapshot.frame),
                    "addFrame": rect(verified.nodes[1].snapshot.frame), "headingFrame": rect(verified.nodes[2].snapshot.frame),
                    "headerBottom": Double(verified.bottom), "statusBarFrames": verified.statusBars.map(rect), "sameOwner": true]
            }
            try require(safe.contains(frames[0]) && !frames[0].isEmpty, "native_target_clipped")
            guard let crop = selected.visibleOutput(in: safe) else {
                try require(false, "native_terminal_frame_invalid")
                throw NSError(domain: "native_terminal_frame_invalid", code: 1)
            }
            extra["terminalFrame"] = rect(crop); extra["targetFrame"] = rect(frames[0])
            extra["boundSource"] = selected.usesControls ? "terminal_control_bounds" : "native_region"
            if selected.usesControls {
                try verifyCaptureControls(selected, tree, safe)
                let keyboardKey = selected.activeHeader == nil ? "dismissFrame" : "keyboardFrame"
                extra["controlBounds"] = [keyboardKey: rect(frames[1]), "helperFrames": frames.dropFirst(2).map(rect), "sameOwner": true]
            }
        }
        let screenFrame = app.frame
        try require(screenFrame.minX == 0 && screenFrame.minY == 0 && !screenFrame.isEmpty, "native_screen_frame_invalid")
        if reviewPage && app.keyboards.firstMatch.exists {
            try captureDiagnostic("review_title", "keyboard_visible", [], [], reviewSample: "before")
            try require(false, "native_terminal_keyboard_visible")
        }
        let shot = XCUIScreen.main.screenshot()
        let afterTree = try observedNodes()
        try assertNoSecret(afterTree.map { $0.snapshot })
        if reviewPage && app.keyboards.firstMatch.exists {
            try captureDiagnostic("review_title", "keyboard_visible", [], [], reviewSample: "after")
            try require(false, "native_terminal_keyboard_visible")
        }
        let afterOcclusions = reviewPage ? nativeOcclusions() : nil
        let after = try anchors(afterTree, reviewSample: reviewPage ? "after" : nil, occlusions: afterOcclusions)
        let afterSafe = reviewPage ? try safeFrame(after.nodes, occlusions: afterOcclusions) { reason in
            try self.captureDiagnostic("review_title", reason, after.nodes, afterTree, reviewSample: "after")
        } : try terminalCaptureFrame(after.nodes, afterTree)
        let unchanged = afterSafe == safe && app.frame == screenFrame && selected.usesControls == after.usesControls &&
            stableCaptureLayout(selected.nodes, after.nodes) && !app.keyboards.firstMatch.exists
        if !unchanged {
            if reviewPage {
                let index = after.nodes.indices.first {
                    !stableCaptureLayout([selected.nodes[$0]], [after.nodes[$0]])
                } ?? 0
                try captureDiagnostic(reviewMembers[index].0, "layout_unstable", [after.nodes[index]], afterTree,
                    visible: afterSafe, reviewSample: "after")
            } else { try captureDiagnostic("terminal", "layout_unstable", after.nodes, afterTree, visible: afterSafe) }
        }
        try require(unchanged, "native_capture_geometry_changed")
        if let header = header {
            let rechecked = try terminalHeader(after.nodes[0], afterTree, safe: afterSafe, active: after.activeHeader)
            if Set(header.statusBars.map(rect)) != Set(rechecked.statusBars.map(rect)) {
                try captureDiagnostic("status_bar", "layout_unstable", [], afterTree, visible: afterSafe)
                try require(false, "native_capture_geometry_changed")
            }
            if header.bottom != rechecked.bottom || !stableCaptureLayout(header.nodes, rechecked.nodes) {
                let index = rechecked.nodes.indices.first {
                    !stableCaptureLayout([header.nodes[$0]], [rechecked.nodes[$0]])
                } ?? rechecked.nodes.count - 1
                let members = after.activeHeader == nil ? ["header_brand", "header_add", "terminal_heading"] : ["terminal_heading", "header_disconnect"]
                try captureDiagnostic(members[index], "layout_unstable",
                    [rechecked.nodes[index]], afterTree, visible: afterSafe)
                try require(false, "native_capture_geometry_changed")
            }
        }
        try verifyCaptureControls(after, afterTree, afterSafe)
        try assertCredentialsInactive(after.nodes[0], afterTree)
        if reviewPage { try assertReviewActions(after.nodes[0], afterTree, Set(labels.suffix(2)), reviewSample: "after") }
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
    private func homeDiagnostics(_ tree: [Observed], compact: Bool, noOtherPage: Bool) throws -> [String: Any] {
        let rows = tree.map { $0.snapshot }
        let definitions: [(String, [String], [String])] = [
            ("brand", ["Herdr Pocket"], []),
            ("headerAdd", ["＋ 添加主机"], ["host-open-remote"]),
            ("emptyAdd", ["添加主机"], ["host-empty-add"]),
            ("homeHeading", ["主机与会话"], []),
            ("emptyHeading", ["还没有主机"], []),
            ("zeroHosts", ["0 台已存主机"], []),
            ("ordinaryShortcut", ["普通 SSH"], ["home-open-ssh"]),
            ("emptyDescription", ["添加主机后，在这里查看会话和任务状态。"], []),
            ("compactShortcut", ["普通 SSH 终端"], ["home-open-ssh"]),
            ("addHeading", ["添加连接"], []),
            ("sshOption", ["普通 SSH 终端"], ["add-ssh"])
        ]
        var members: [String: Any] = [:]
        for (key, labels, identifiers) in definitions {
            let matching = rows.filter { node in
                if key == "compactShortcut" {
                    return node.elementType == .button && node.identifier != "add-ssh" && texts(node).contains { labels.contains($0) }
                }
                return identifiers.contains(node.identifier) || texts(node).contains { labels.contains($0) }
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
            guard alert.exists, let snapshot = try? alert.snapshot() else { alertSnapshotFailed = true; continue }
            var pending: [any XCUIElementSnapshot] = [snapshot]
            var count = 0
            while let node = pending.popLast(), count < 1000 {
                count += 1; pending.append(contentsOf: node.children)
                for (key, terms) in alertTerms {
                    if texts(node).contains(where: { value in terms.contains { value.contains($0) } }) { alertMembers[key] = true }
                }
            }
        }
        let flags = NativeHomeReadiness.errors + [("loading", ["正在读取主机资料…"])]
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
        let screen = app.frame
        let visible = rows.filter { !$0.frame.isEmpty && $0.frame.intersects(screen) }
        let inputCount = rows.filter { [.textField, .secureTextField, .textView, .searchField].contains($0.elementType) }.count
        let unknownTextCount = visible.filter { node in
            texts(node).contains { !$0.isEmpty && !publicHomeText.contains($0) }
        }.count
        let member = { (key: String) -> Int in (members[key] as? [String: Any])?["count"] as? Int ?? 0 }
        let foreground = app.state == .runningForeground
        let webCount = rows.filter { $0.elementType == .webView }.count
        let legacy = member("brand") > 0 && member("homeHeading") > 0 && member("zeroHosts") > 0 && member("emptyHeading") > 0
        let compactHome = compact && member("homeHeading") == 0 && member("zeroHosts") == 0 && member("headerAdd") == 0
        let safe = foreground && webCount > 0 && (compactHome || legacy) && inputCount == 0 && noOtherPage &&
            appAlerts.isEmpty && systemAlerts.isEmpty && !alertSnapshotFailed && errors.values.allSatisfy { !$0 }
        let result: [String: Any] = ["appForeground": foreground, "webViewCount": min(webCount, 10000),
            "windowCount": min(rows.filter { $0.elementType == .window }.count, 10000), "members": members, "knownErrors": errors,
            "appAlertCount": min(appAlerts.count, 10000), "systemAlertCount": min(systemAlerts.count, 10000),
            "alertMembers": alertMembers, "alertSnapshotFailed": alertSnapshotFailed,
            "inputCount": min(inputCount, 10000), "unknownVisibleTextCount": min(unknownTextCount, 10000),
            "knownEmptyHome": safe, "compactEmptyHome": safe && compactHome]
        return result
    }

    @MainActor
    private func navigationState(publish: Bool = true) throws -> [String: Any] {
        let tree = try observedNodes()
        let screen = app.frame
        let visible = tree.filter { NativeFramePolicy.valid($0.snapshot.frame) && $0.snapshot.frame.intersects(screen) }
        let facts = visible.map { node in
            NativeControlPolicy.Fact(identifier: node.snapshot.identifier,
                label: texts(node.snapshot).first(where: { !$0.isEmpty }) ?? "", role: role(node.snapshot.elementType), value: nil)
        }
        let paths = visible.map(\.path), windows = visible.map(\.windowPath), webs = visible.map(\.webPath)
        func witness(_ targets: [(String?, String, Bool)]) -> [Observed]? {
            NativeControlPolicy.pageWitness(facts, paths: paths, windows: windows, webs: webs, targets: targets)?.map { visible[$0] }
        }
        let emptyCardText: [(String?, String, Bool)] = [(nil, "Herdr Pocket", false), (nil, "还没有主机", false),
            (nil, "添加主机后，在这里查看会话和任务状态。", false)]
        let addTarget = ("host-empty-add" as String?, "添加主机", true)
        let homeTargets = emptyCardText + [("home-open-ssh", "普通 SSH 终端", true), addTarget]
        let homeIndices = NativeControlPolicy.pageWitness(facts, paths: paths, windows: windows, webs: webs, targets: homeTargets)
        let homeCard = homeIndices?.map { visible[$0] }
        let choices = [("add-herdr" as String?, "herdr 配对 / 手动连接", true), ("add-ssh" as String?, "普通 SSH 终端", true)]
        let mobileChoice = witness([(nil, "添加主机", false), ("add-choice-heading", "选择连接方式", false),
            ("add-back", "返回看板", true)] + choices)
        let legacyChoice = witness([(nil, "添加连接", false)] + choices)
        let selection = formSelection(tree)
        let noForm = selection.controls.values.allSatisfy { $0.reason == "missing" }
        navigationFormOwner = selection.ownerResolved ? selection.controls["host"]?.index.map { tree[$0] } : nil
        let home = try homeDiagnostics(tree, compact: homeCard != nil,
            noOtherPage: noForm && mobileChoice == nil && legacyChoice == nil)
        lastHomeSample = home
        if publish { try post("native_home", ["nativeCheckpoint": nativePhase, "home": home]) }
        let members = home["members"] as! [String: [String: Any]]
        let seen = { (key: String) in (members[key]?["count"] as? Int ?? 0) > 0 }
        var formControls: [String: Any] = [:]
        for name in ["host", "port", "user", "probe"] {
            let item = selection.controls[name]!
            formControls[name] = ["role": item.role, "matches": item.matches, "owner": item.owner, "reason": item.reason]
        }
        let noErrors = !(home["knownErrors"] as! [String: Bool]).values.contains(true)
        let noAlerts = (home["appAlertCount"] as! Int) == 0 && (home["systemAlertCount"] as! Int) == 0 && home["alertSnapshotFailed"] as? Bool == false
        let empty = home["knownEmptyHome"] as? Bool == true
        let choice = homeCard == nil && noForm && home["inputCount"] as? Int == 0 && ((mobileChoice != nil) != (legacyChoice != nil))
        let formOwnerResolved = selection.ownerResolved
        let form = formOwnerResolved
        let page = form ? "sshForm" : choice ? "addChoice" : empty ? "emptyHome" : "unexpected"
        let compact = empty && home["compactEmptyHome"] as? Bool == true
        manualHomeCardSeen = nativePhase == "encrypted_key_open_add" && noForm && mobileChoice == nil && legacyChoice == nil &&
            (homeCard != nil || witness(emptyCardText + [addTarget]) != nil)
        pageButtons.removeAll()
        if compact, let entry = homeCard?.last { pageButtons["emptyAdd"] = entry }
        if nativePhase == "encrypted_key_open_add" {
            let index = NativeControlPolicy.compactHomeShortcut(facts, paths: paths, windows: windows, webs: webs,
                frames: visible.map { $0.snapshot.frame }, card: homeIndices, evidence: &shortcutEvidence)
            if compact, let index { pageButtons["ordinaryShortcut"] = visible[index] }
            if !compact && homeIndices != nil { shortcutEvidence.issue = .wrongPage }
        }
        if choice, let ssh = (mobileChoice ?? legacyChoice)?.last { pageButtons["sshChoice"] = ssh }
        let title = witness([("ssh-page-heading", "普通 SSH 终端", false)]) != nil
        let passwords = tree.filter { $0.snapshot.elementType == .secureTextField &&
            NativeControlPolicy.isPasswordField(identifier: $0.snapshot.identifier, label: $0.snapshot.label) }
        let credentialsEmpty = passwords.allSatisfy { NativeControlPolicy.credentialEmpty($0.snapshot.value, placeholder: $0.snapshot.placeholderValue) }
        return ["page": page, "appForeground": home["appForeground"]!, "inputCount": home["inputCount"]!,
            "windowCount": home["windowCount"]!, "webViewCount": home["webViewCount"]!,
            "noAlerts": noAlerts, "noKnownErrors": noErrors,
            "emptyHomeIdentity": empty, "compactEmptyHome": compact, "mobileAddChoice": choice && mobileChoice != nil,
            "formByStructure": form, "formOwnerResolved": formOwnerResolved, "sshTitleSeen": title,
            "addTitleSeen": mobileChoice != nil || seen("addHeading"), "credentialsEmpty": credentialsEmpty, "formControls": formControls]
    }

    @MainActor
    private func navigationGeometry(_ item: XCUIElement) throws -> [String: Any] {
        guard let current = liveControl(item) else {
            try require(false, "native_control_missing")
            throw NSError(domain: "native_control_missing", code: 1)
        }
        return try navigationGeometry(current)
    }
    @MainActor
    private func navigationGeometry(_ current: LiveControl) throws -> [String: Any] {
        navigationGeometry(current, owner: controlOwner(current.snapshot, try observedNodes()))
    }
    @MainActor
    private func navigationGeometry(_ current: LiveControl, owner: Observed?) -> [String: Any] {
        let snapshot = current.snapshot
        let measured = owner.flatMap { controlVisibleFrame($0, current) }
        let visible = measured ?? .zero
        let center = CGPoint(x: snapshot.frame.midX, y: snapshot.frame.midY)
        let selectedFrame = owner?.snapshot.frame ?? .null
        let selectedCenter = CGPoint(x: selectedFrame.midX, y: selectedFrame.midY)
        let system = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let bars = NativeFramePolicy.unique((app.statusBars.allElementsBoundByIndex + system.statusBars.allElementsBoundByIndex)
            .compactMap { liveControl($0)?.snapshot.frame }.filter(NativeFramePolicy.valid))
        return ["frame": rect(snapshot.frame), "visibleFrame": rect(visible), "screenFrame": rect(app.frame),
            "statusBarFrames": bars.map(rect), "role": role(snapshot.elementType), "enabled": snapshot.isEnabled,
            "hittable": current.hittable, "ownerResolved": owner != nil,
            "centerVisible": measured != nil && visible.contains(center) && visible.contains(selectedCenter),
            "fullyVisible": measured != nil && visible.contains(snapshot.frame) && visible.contains(selectedFrame)]
    }
    @MainActor
    private func navigationElement(_ member: String) -> (XCUIElement, String)? {
        if let button = pageButtons[member] {
            guard let live = liveOnPath(button), live.snapshot.elementType == .button else { return nil }
            return (live.element, button.snapshot.identifier.isEmpty ? "buttonRole" : "uniqueIdentifier")
        }
        let targets = ["headerAdd": ("host-open-remote", "＋ 添加主机"), "emptyAdd": ("host-empty-add", "添加主机"),
            "ordinaryShortcut": ("home-open-ssh", "普通 SSH"), "sshChoice": ("add-ssh", "普通 SSH 终端")]
        guard let (identifier, label) = targets[member] else { return nil }
        let byID = app.descendants(matching: .any).matching(identifier: identifier)
        if byID.count > 0 { return byID.count == 1 ? (byID.firstMatch, "uniqueIdentifier") : nil }
        let buttons = app.buttons.matching(NSPredicate(format: "label == %@", label))
        if buttons.count > 0 { return buttons.count == 1 ? (buttons.firstMatch, "buttonRole") : nil }
        let exact = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", label))
        return exact.count == 1 ? (exact.firstMatch, "uniqueLabel") : nil
    }

    @MainActor
    private func captureManualShortcut(_ card: [Observed], _ geometry: [String: Any]) throws -> Bool? {
        let witness = card[1]
        func sample() throws -> [Observed]? {
            let state = try navigationState(publish: false)
            guard NativeHomeReadiness.permitsNavigation(state, from: "emptyHome"),
                  state["compactEmptyHome"] as? Bool == true, state["inputCount"] as? Int == 0,
                  state["windowCount"] as? Int == 1, !app.keyboards.firstMatch.exists,
                  let add = pageButtons["emptyAdd"], let shortcut = pageButtons["ordinaryShortcut"],
                  stableCaptureLayout(card, [add, shortcut]) else { return nil }
            return [add, shortcut]
        }
        let screen = app.frame
        let occlusions = nativeOcclusions()
        guard let first = try sample(), let window = witness.window, screen.origin == .zero, window == screen,
              let visible = NativeFramePolicy.visible(window: window, screen: screen,
                  webAncestors: witness.webs, occlusions: occlusions),
              geometry["visibleFrame"] as? [Double] == rect(visible),
              first.allSatisfy({ visible.contains($0.snapshot.frame) }) else { return nil }
        try assertNoSecret(try nodes())
        let shot = XCUIScreen.main.screenshot()
        guard let second = try sample(), app.frame == screen, stableCaptureLayout(first, second),
              Set(nativeOcclusions()) == Set(occlusions) else { return nil }
        try assertNoSecret(try nodes())
        return try post("native_shortcut_capture", ["nativeCheckpoint": nativePhase,
            "geometry": geometry, "emptyAddFrame": rect(first[0].snapshot.frame), "windowFrame": rect(window),
            "webFrames": witness.webs.map(rect), "pngBase64": shot.pngRepresentation.base64EncodedString()])
    }

    private struct ManualShortcutAction {
        let before: [String: Any]
        let witness: Observed
        let element: XCUIElement
        let selection: String
        let geometry: [String: Any]
        let binding: [String: Any]
    }

    @MainActor
    private func prepareManualShortcut() throws -> ManualShortcutAction {
        let failure = "native_encrypted_key_home_shortcut_unproven"
        var captures = 0
        func waitForLayout() -> Bool {
            let remaining = nativeHomeDeadline - ProcessInfo.processInfo.systemUptime
            guard remaining > 0 else { return false }
            Thread.sleep(forTimeInterval: min(0.4, remaining))
            return true
        }
        func reject(_ issue: NativeControlPolicy.ShortcutEvidence.Issue) throws -> Never {
            if let home = lastHomeSample { try post("native_home", ["nativeCheckpoint": nativePhase, "home": home]) }
            try require(false, failure, shortcutIssue: issue)
            throw NSError(domain: failure, code: 1)
        }
        while true {
            let before = try navigationState(publish: false)
            guard before["appForeground"] as? Bool == true else { try reject(.foreground) }
            guard before["noAlerts"] as? Bool == true else { try reject(.alert) }
            guard NativeHomeReadiness.permitsNavigation(before, from: "emptyHome"),
                  before["compactEmptyHome"] as? Bool == true, before["windowCount"] as? Int == 1,
                  before["addTitleSeen"] as? Bool == false, before["formByStructure"] as? Bool == false,
                  !app.keyboards.firstMatch.exists else { try reject(.wrongPage) }
            guard let add = pageButtons["emptyAdd"], let witness = pageButtons["ordinaryShortcut"] else {
                try reject(shortcutEvidence.issue ?? .path)
            }
            guard let live = liveOnPath(witness) else { try reject(.path) }
            let liveSize = NativeControlPolicy.ShortcutEvidence.size(live.snapshot.frame)
            shortcutEvidence.liveSize = liveSize
            guard let owner = controlOwner(live.snapshot, try observedNodes()) else { try reject(.owner) }
            guard owner.path == witness.path, owner.windowPath == witness.windowPath, owner.webPath == witness.webPath else {
                try reject(.scope)
            }
            guard owner.snapshot.frame == live.snapshot.frame, witness.snapshot.frame == live.snapshot.frame else {
                if waitForLayout() { continue }
                try reject(.movement)
            }
            let geometry = navigationGeometry(live, owner: owner)
            let issue = NativeControlPolicy.ShortcutEvidence.actionIssue(geometry, witnessed: witness.snapshot.frame)
            if let issue {
                guard issue == .small else { try reject(issue) }
                if waitForLayout() { continue }
            }
            let card = [add, witness]
            // Read AX on both sides of the original system capture. An early
            // AX-ready state can still have an unpainted application surface.
            guard let painted = try captureManualShortcut(card, geometry) else {
                if waitForLayout() { continue }
                shortcutEvidence.liveSize = liveSize
                try reject(issue ?? .capture)
            }
            captures += 1
            shortcutEvidence.liveSize = liveSize
            guard issue == nil, painted else {
                if captures < 3 && waitForLayout() { continue }
                try reject(issue ?? .capture)
            }
            // Check current ownership again after authorization of the original
            // pixels. Only the verified live element supplies a hit point.
            let rechecked = try navigationState(publish: false)
            guard NativeHomeReadiness.permitsNavigation(rechecked, from: "emptyHome"),
                  rechecked["windowCount"] as? Int == 1, !app.keyboards.firstMatch.exists,
                  let currentAdd = pageButtons["emptyAdd"], let current = pageButtons["ordinaryShortcut"],
                  stableCaptureLayout(card, [currentAdd, current]),
                  let currentLive = liveOnPath(current), currentLive.snapshot.frame == current.snapshot.frame,
                  let visible = controlVisibleFrame(current, currentLive), rect(visible) == geometry["visibleFrame"] as? [Double],
                  visible.contains(current.snapshot.frame), currentLive.snapshot.isEnabled, currentLive.hittable,
                  ProcessInfo.processInfo.systemUptime < nativeHomeDeadline else {
                shortcutEvidence.liveSize = liveSize
                try reject(.capture)
            }
            let binding: [String: Any] = ["witnessFrame": NativeFramePolicy.diagnosticRect(witness.snapshot.frame),
                "liveFrame": NativeFramePolicy.diagnosticRect(live.snapshot.frame),
                "ownerFrame": NativeFramePolicy.diagnosticRect(owner.snapshot.frame),
                "windowFrame": NativeFramePolicy.diagnosticRect(witness.window),
                "webFrames": witness.webs.map { NativeFramePolicy.diagnosticRect($0) }]
            return ManualShortcutAction(before: before, witness: witness, element: currentLive.element,
                selection: witness.snapshot.identifier == "home-open-ssh" ? "uniqueIdentifier" : "buttonRole",
                geometry: geometry, binding: binding)
        }
    }

    @MainActor
    private func navigate(_ member: String, compactRoute: Bool = false) throws -> (String, String, String) {
        let manualShortcut = nativePhase == "encrypted_key_open_add" && member == "ordinaryShortcut"
        let action = try manualShortcut ? prepareManualShortcut() : nil
        let before = try action?.before ?? navigationState()
        // A delayed view transition may already have produced the real form.
        // Preserve this newly sampled source state; never rewrite it as addChoice
        // or synthesize an unperformed click to make a historical row fit.
        if !compactRoute && member == "sshChoice" && before["page"] as? String == "sshForm" {
            try require(NativeHomeReadiness.permitsNavigation(before, from: "sshForm"), "native_home_retry_unsafe")
            let host = field("主机地址")
            try post("native_navigation_arrival", ["nativeCheckpoint": nativePhase, "state": before,
                "geometry": try navigationGeometry(host), "source": "currentFormObservation", "performed": false])
            guard let current = liveControl(host) else { throw NSError(domain: "native_control_missing", code: 1) }
            return ("sshForm", "uniqueIdentifier", role(current.snapshot.elementType))
        }
        try require(NativeHomeReadiness.permitsNavigation(before, from: member == "sshChoice" ? "addChoice" : "emptyHome"),
                    "native_home_retry_unsafe")
        if compactRoute && !manualShortcut {
            let witness = member == "sshChoice" ? "mobileAddChoice" : "compactEmptyHome"
            try require(pageButtons[member] != nil && before[witness] as? Bool == true, "native_home_retry_unsafe")
        }
        guard let (item, selection) = action.map({ ($0.element, $0.selection) }) ?? navigationElement(member) else {
            return ("missing", "uniqueLabel", "otherNative")
        }
        // Retain the first page witness and its live owner as geometry only.
        // This records the actual native binding, never a guessed hit point.
        var binding = action?.binding
        let witness = action?.witness ?? pageButtons[member]
        if action == nil, let witness, let live = liveControl(item) {
            let owner = controlOwner(live.snapshot, try observedNodes())
            binding = ["witnessFrame": NativeFramePolicy.diagnosticRect(witness.snapshot.frame),
                "liveFrame": NativeFramePolicy.diagnosticRect(live.snapshot.frame),
                "ownerFrame": NativeFramePolicy.diagnosticRect(owner?.snapshot.frame),
                "windowFrame": NativeFramePolicy.diagnosticRect(witness.window),
                "webFrames": witness.webs.map { NativeFramePolicy.diagnosticRect($0) }]
        }
        let geometry = try action?.geometry ?? navigationGeometry(item)
        let allowed = geometry["ownerResolved"] as? Bool == true && geometry["centerVisible"] as? Bool == true &&
            geometry["enabled"] as? Bool == true && geometry["hittable"] as? Bool == true
        func reached(_ state: [String: Any]) -> Bool {
            NativeViewPolicy.reached(member: member, page: state["page"] as! String) ||
                (manualShortcut && state["addTitleSeen"] as? Bool == true)
        }
        let started = ProcessInfo.processInfo.systemUptime
        if action != nil {
            item.tap()
        } else if allowed {
            item.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        }
        var after = try navigationState()
        if allowed && (!manualShortcut || !reached(after)) {
            let deadline = Date().addingTimeInterval(6)
            repeat {
                after = try navigationState()
                if reached(after) { break }
                Thread.sleep(forTimeInterval: 0.2)
            } while Date() < deadline
        }
        let page = after["page"] as! String
        let outcome = !allowed ? "blocked" : page == "sshForm" ? "sshForm" : page == "addChoice" ? "addChoice" :
            page == "emptyHome" ? "noProgress" : "unexpected"
        let afterGeometry: Any
        if manualShortcut {
            if page == "emptyHome", let current = pageButtons[member], let witness, current.path == witness.path,
               current.windowPath == witness.windowPath, current.webPath == witness.webPath,
               sameIdentity(current.snapshot, witness.snapshot), let live = liveOnPath(current) {
                afterGeometry = try navigationGeometry(live)
            } else {
                afterGeometry = NSNull()
            }
        } else {
            afterGeometry = item.exists ? try navigationGeometry(item) : NSNull()
        }
        var navigation: [String: Any] = ["nativeCheckpoint": nativePhase, "member": member, "selection": selection,
            "method": manualShortcut ? "systemHitPoint" : "elementCenter", "performed": allowed, "geometry": geometry,
            "targetPresentAfter": !(afterGeometry is NSNull), "afterGeometry": afterGeometry,
            "elapsedMs": min(60000, max(0, Int((ProcessInfo.processInfo.systemUptime - started) * 1000))),
            "before": before, "after": after, "outcome": outcome]
        if let binding = binding { navigation["binding"] = binding }
        let afterInShortcutScope = navigationFormOwner != nil && navigationFormOwner?.windowPath == witness?.windowPath &&
            navigationFormOwner?.webPath == witness?.webPath && navigationFormOwner?.window == witness?.window &&
            navigationFormOwner?.webs == witness?.webs
        if manualShortcut { navigation["afterInShortcutScope"] = afterInShortcutScope }
        try post("native_navigation", navigation)
        if manualShortcut {
            try require(NativeHomeReadiness.permitsNavigation(after, from: "sshForm") &&
                        after["addTitleSeen"] as? Bool == false && after["emptyHomeIdentity"] as? Bool == false &&
                        afterInShortcutScope,
                        "native_encrypted_key_home_shortcut_no_progress")
        }
        return (page, selection, geometry["role"] as! String)
    }

    @MainActor
    private func awaitEmptyHome() throws {
        let clock = { ProcessInfo.processInfo.systemUptime }
        let start = clock()
        var deadline = start
        var sampleSeconds = 0.0
        var strictSamples = 0
        var waitCalls = 0
        var markerSeen = false
        var transitions: [[String: Any]] = []
        var outcome: NativeHomeReadiness.State
        let markers = [NSPredicate(format: "label == %@", "还没有主机")] +
            NativeHomeReadiness.errors.flatMap { $0.1 }.map { NSPredicate(format: "label CONTAINS %@", $0) }
        let wake = app.staticTexts.matching(NSCompoundPredicate(orPredicateWithSubpredicates: markers)).firstMatch
        let milliseconds = { (seconds: TimeInterval) in min(900_000, max(0, Int(seconds * 1000))) }
        repeat {
            let sampledAt = clock()
            let state = try navigationState(publish: false)
            strictSamples += 1
            // The first snapshot may be slow and represent an earlier layout.
            // Give an unfinished app time to advance and take a fresh sample.
            if strictSamples == 1 {
                deadline = clock() + 35
                nativeHomeDeadline = deadline
            }
            outcome = NativeHomeReadiness.classify(state, home: lastHomeSample!)
            if strictSamples == 1 && outcome == .unexpected &&
                NativeHomeReadiness.canResampleUnidentifiedStartup(state, home: lastHomeSample!) {
                outcome = .unidentifiedStartup
            }
            let checkedAt = clock()
            sampleSeconds += checkedAt - sampledAt
            if transitions.last?["state"] as? String != outcome.rawValue {
                transitions.append(["state": outcome.rawValue, "elapsedMs": milliseconds(checkedAt - start)])
            }
            // The unidentified first observation gets only one passive resample.
            // An already visible manual empty card with an unproven shortcut is final.
            if outcome == .shell && manualHomeCardSeen { break }
            guard outcome == .loading || outcome == .shell || outcome == .unidentifiedStartup else { break }
            let slice = min(4, deadline - clock())
            if slice <= 0 { break }
            if markerSeen { Thread.sleep(forTimeInterval: slice) }
            else {
                waitCalls += 1
                let waitStarted = clock()
                markerSeen = wake.waitForExistence(timeout: slice)
                let unused = slice - (clock() - waitStarted)
                if !markerSeen && unused > 0 { Thread.sleep(forTimeInterval: unused) }
            }
        } while true
        let readiness: [String: Any] = ["outcome": outcome.rawValue, "elapsedMs": milliseconds(clock() - start),
            "strictSampleMs": milliseconds(sampleSeconds), "strictSamples": strictSamples, "waitCalls": waitCalls, "samples": transitions]
        try post("native_home", ["nativeCheckpoint": nativePhase, "home": lastHomeSample!, "readiness": readiness])
        let manual = nativePhase == "encrypted_key_open_add"
        switch outcome {
        case .ready: return
        case .shell where manualHomeCardSeen:
            try require(false, "native_encrypted_key_home_shortcut_unproven", shortcutIssue: shortcutEvidence.issue ?? .anchors)
        case .error: try require(false, "native_home_known_loading_error")
        case .alert: try require(false, "native_home_alert_present", shortcutIssue: manual ? .alert : nil)
        case .notForeground: try require(false, "native_home_not_foreground", shortcutIssue: manual ? .foreground : nil)
        default: try require(false, "native_home_identity_unproven", shortcutIssue: manual ? .wrongPage : nil)
        }
    }

    @MainActor
    private func openHomeSSH() throws {
        try awaitEmptyHome()
        let compact = lastHomeSample?["compactEmptyHome"] as? Bool == true
        if nativePhase == "encrypted_key_open_add" {
            try require(compact, "native_encrypted_key_home_shortcut_unproven", shortcutIssue: shortcutEvidence.issue ?? .wrongPage)
            let (page, selection, originalRole) = try navigate("ordinaryShortcut", compactRoute: true)
            try require(page != "missing", "native_encrypted_key_home_shortcut_unproven", shortcutIssue: .path)
            try require(page == "sshForm", "native_encrypted_key_home_shortcut_no_progress")
            try post("native_home_entry", ["nativeCheckpoint": nativePhase, "member": "ordinaryShortcut", "selection": selection,
                "role": originalRole, "enteredAddPage": false, "enteredSSHForm": true, "route": "directSSH"])
            return
        }
        for member in compact ? ["emptyAdd"] : ["headerAdd", "emptyAdd", "ordinaryShortcut"] {
            let (page, selection, originalRole) = try navigate(member, compactRoute: compact)
            if page == "missing" { continue }
            if page == "sshForm" {
                try require(!compact, "native_home_retry_unsafe")
                try post("native_home_entry", ["nativeCheckpoint": nativePhase, "member": member, "selection": selection,
                    "role": originalRole, "enteredAddPage": false, "enteredSSHForm": true, "route": "directSSH"])
                return
            }
            if page == "addChoice" {
                try phase("open_ssh")
                let (form, _, _) = try navigate("sshChoice", compactRoute: compact)
                try require(form == "sshForm", "native_ssh_form_unproven")
                try post("native_home_entry", ["nativeCheckpoint": nativePhase, "member": member, "selection": selection,
                    "role": originalRole, "enteredAddPage": true, "enteredSSHForm": true, "route": "viaAdd"])
                return
            }
            try require(page == "emptyHome", "native_home_retry_unsafe")
        }
        if let home = lastHomeSample { try post("native_home", ["nativeCheckpoint": nativePhase, "home": home]) }
        try require(false, "native_home_navigation_failed")
    }

    @MainActor
    private func launchForm(port: Int) throws {
        mobileFlow = false
        try phase("launch")
        app.launch()
        try require(app.wait(for: .runningForeground, timeout: 30), "native_app_launch_failed")
        try phase("open_add")
        try openHomeSSH()
        let probeLabel = try formControl("probe").live.snapshot.label
        mobileFlow = app.frame.width <= 599
        try require(probeLabel == (mobileFlow ? "探测并核对主机密钥" : "探测主机指纹"), "native_mobile_setup_unproven")
        if mobileFlow { try mobileTarget() }
        try phase("host")
        try fillForm("host", "127.0.0.1")
        try phase("port")
        try fillForm("port", String(port))
        try phase("username")
        try fillForm("user", "fixture")
        try phase("probe")
        try tapForm("probe")
    }

    @MainActor
    private func connectionRows(_ rows: [Observed], in control: RevealedControl) -> [Observed] {
        guard rows.contains(where: { $0.path == control.window.path && sameIdentity($0.snapshot, control.window.snapshot) }),
              rows.contains(where: { $0.path == control.web.path && sameIdentity($0.snapshot, control.web.snapshot) }) else { return [] }
        return rows.filter { $0.windowPath == control.window.path && $0.webPath == control.web.path }
    }

    @MainActor
    private func connectionStatus(_ rows: [Observed]) -> NativeConnectPolicy.Status {
        let visible = rows.filter { NativeFramePolicy.valid($0.snapshot.frame) }
        let statusPaths = visible.filter { $0.snapshot.identifier == "ssh-status" }.map(\.path)
        let reported = visible.filter { row in statusPaths.contains { row.path.starts(with: $0) } }
        let status = NativeConnectPolicy.status(reported.flatMap { texts($0.snapshot) })
        // A WebKit live region can appear as text without the DOM identifier.
        return status == .unknown ? NativeConnectPolicy.status(visible.flatMap { texts($0.snapshot) }) : status
    }

    @MainActor
    private func submitConnection(_ attempt: NativeConnectPolicy.Attempt, waitingFor expected: String, control: RevealedControl? = nil,
                                  activePort: Int? = nil) throws {
        try require(!mobileFlow || control != nil, "native_mobile_submit_owner_unproven")
        let ownerFailure = control == nil ? nil : "native_mobile_submit_owner_unproven"
        let submit = try reveal(control?.live.element ?? button("连接 / 重新连接"), matching: control,
            protectRouteTabs: true, mobileOwnerFailure: ownerFailure)
        try require(submit.live.snapshot.elementType == .button, "native_control_owner_unproven")
        try require(submit.live.snapshot.isEnabled, "native_control_disabled")
        let beforeRows = connectionRows(try observedNodes(), in: submit)
        let beforeSubmit = beforeRows.filter { sameIdentity($0.snapshot, submit.owner.snapshot) }
        try require(beforeSubmit.count == 1 && beforeSubmit.first?.path == submit.owner.path,
                    ownerFailure ?? "native_control_owner_unproven")
        try require(beforeSubmit.first?.snapshot.isEnabled == true, "native_control_disabled")
        var status = connectionStatus(beforeRows)
        let before = NativeConnectPolicy.sample(status, keyboardVisible: app.keyboards.firstMatch.exists,
            submitFrame: beforeSubmit.first?.snapshot.frame, submitEnabled: submit.live.snapshot.isEnabled, submitHittable: submit.live.hittable)
        var statuses = [status.rawValue]
        // Ask XCTest for the actual hit point of the uniquely bound button.
        // A geometric center can fall outside the hittable portion as the
        // software keyboard moves. No retry may submit credentials again.
        submit.live.element.tap()
        let deadline = Date().addingTimeInterval(40)
        var rows: [Observed]
        repeat {
            rows = connectionRows(try observedNodes(), in: submit)
            if let activePort {
                if visibleWitness(rows, NativeActivePage.terminal.witnesses(endpoint: target(activePort))) != nil { return }
            } else if rows.contains(where: { texts($0.snapshot).contains { $0.contains(expected) } }) { return }
            status = connectionStatus(rows)
            if !statuses.contains(status.rawValue) { statuses.append(status.rawValue) }
            Thread.sleep(forTimeInterval: 0.25)
        } while Date() < deadline
        let matches = rows.filter { sameIdentity($0.snapshot, submit.owner.snapshot) }
        let afterSubmit = matches.count == 1 ? matches.first.flatMap(liveOnPath) : nil
        let after = NativeConnectPolicy.sample(status, keyboardVisible: app.keyboards.firstMatch.exists,
            submitFrame: afterSubmit?.snapshot.frame, submitEnabled: afterSubmit?.snapshot.isEnabled ?? false,
            submitHittable: afterSubmit?.hittable ?? false)
        try post("native_connect_diagnostic", ["nativeCheckpoint": nativePhase,
            "detail": ["attempt": attempt.rawValue, "before": before, "after": after, "statuses": statuses]])
        try require(false, "native_expected_text_missing")
    }

    @MainActor
    private func connect(password secret: String, mobileOwner: RevealedControl?) throws -> RevealedControl? {
        try phase("password")
        let port = config[scenario == "ordinary" ? "ordinaryPort" : "rotationPort"] as! Int
        try fillPassword(mobileOwner?.live.element ?? password(), secret, mobileOwner: mobileOwner)
        if !mobileFlow { try check(true, enabled: true) }
        let control = try mobileOwner.map { try mobileAuth(port: port, ready: true, previous: $0).submit }
        try phase("connect")
        try submitConnection(scenario == "ordinary" ? .ordinary : .rotationApproved,
            waitingFor: target(port) + " · SSH 已连接", control: control, activePort: mobileFlow ? port : nil)
        if let control, mobileFlow {
            let (rows, anchors) = try activePage(.terminal, port: port, owner: control)
            return try mobileControl(anchors[3], rows, "native_active_owner_unproven")
        }
        let rows = try observedNodes()
        let page = try exactObserved(rows, target(port) + " · SSH 已连接")
        try assertCredentialsInactive(page, rows)
        return nil
    }

    @MainActor
    private func encryptedFieldAnchor(_ field: NativeControlPolicy.KeyField, _ rows: [Observed]) -> Observed? {
        let fields = rows.filter { row in
            let snapshot = row.snapshot
            return [.textField, .secureTextField, .textView, .searchField].contains(snapshot.elementType) &&
                field.matches(identifier: snapshot.identifier, label: snapshot.label)
        }
        guard fields.count == 1, let row = fields.first,
              field.accepts(role: row.snapshot.elementType == .textView ? "textView" : role(row.snapshot.elementType)),
              row.snapshot.isEnabled else { return nil }
        return row
    }

    @MainActor
    private func encryptedField(_ field: NativeControlPolicy.KeyField, rows: [Observed], owner: RevealedControl) throws -> RevealedControl {
        let failure = "native_encrypted_key_passphrase_owner_unproven"
        guard let row = encryptedFieldAnchor(field, rows) else {
            try require(false, failure)
            throw NSError(domain: failure, code: 1)
        }
        let control = try mobileControl(row, rows, failure)
        try require(sameControlScope(control, owner) && control.live.snapshot.isEnabled, failure)
        return control
    }

    @MainActor
    private func confirmedPEMEditor(_ rows: [Observed], previous: RevealedControl, pem: String) -> RevealedControl? {
        guard let anchor = encryptedFieldAnchor(.pem, rows),
              case .success(let editor) = mobileBinding(anchor, rows),
              sameControlScope(editor, previous), sameIdentity(editor.owner.snapshot, previous.owner.snapshot),
              editor.live.snapshot.isEnabled, editor.owner.snapshot.value as? String == pem,
              editor.live.snapshot.value as? String == pem else { return nil }
        return editor
    }

    @MainActor
    private func pemRepresentation(_ row: Observed, editor: RevealedControl?) -> NativeControlPolicy.PEMRepresentation {
        guard let editor else { return .editorUnproven }
        guard row.windowPath == editor.owner.windowPath, row.webPath == editor.owner.webPath,
              row.path.starts(with: editor.owner.path) else { return .outsideEditor }
        let snapshot = row.snapshot
        if row.path == editor.owner.path {
            guard sameIdentity(snapshot, editor.owner.snapshot) else { return .subtreeUnproven }
            return snapshot.frame == editor.owner.snapshot.frame ? .editorValue : .geometryMismatch
        }
        guard snapshot.elementType == .staticText, snapshot.children.isEmpty,
              snapshot.value == nil || snapshot.value is String else { return .unsupportedNode }
        guard NativeFramePolicy.valid(snapshot.frame),
              editor.owner.snapshot.frame.contains(snapshot.frame) else { return .geometryMismatch }
        // Resolve the same relative path in the editor's independently scoped live
        // snapshot. A matching path in the application tree alone is insufficient.
        let relative = row.path.dropFirst(editor.owner.path.count)
        var raw: any XCUIElementSnapshot = editor.owner.snapshot
        var live: any XCUIElementSnapshot = editor.live.snapshot
        for (offset, index) in relative.enumerated() {
            guard raw.children.indices.contains(index), live.children.indices.contains(index) else { return .subtreeUnproven }
            raw = raw.children[index]
            live = live.children[index]
            guard sameIdentity(raw, live),
                  NativeControlPolicy.valueText(raw.value) == NativeControlPolicy.valueText(live.value) else { return .subtreeUnproven }
            guard raw.frame == live.frame else { return .geometryMismatch }
            if offset < relative.count - 1 {
                guard [.other, .group].contains(live.elementType), live.identifier.isEmpty, live.label.isEmpty,
                      NativeControlPolicy.valueText(live.value) == "" else { return .unsupportedNode }
            }
        }
        guard raw.children.isEmpty, live.children.isEmpty, sameIdentity(snapshot, raw),
              NativeControlPolicy.valueText(raw.value) == NativeControlPolicy.valueText(snapshot.value) else {
            return .subtreeUnproven
        }
        return raw.frame == snapshot.frame ? .editorText : .geometryMismatch
    }

    @MainActor
    private func collapsedPEMControl(_ rows: [Observed], owner: RevealedControl) throws -> RevealedControl {
        let failure = "native_encrypted_key_summary_owner_unproven"
        let facts = rows.map { row in
            let snapshot = row.snapshot
            return (identifier: snapshot.identifier, label: snapshot.label,
                role: snapshot.elementType == .textView ? "textView" : role(snapshot.elementType),
                enabled: snapshot.isEnabled, visible: NativeFramePolicy.valid(snapshot.frame))
        }
        switch NativeControlPolicy.CollapsedPEM.candidate(facts) {
        case .success(let index):
            let control = try mobileControl(rows[index], rows, failure)
            try require(sameControlScope(control, owner), failure)
            try require(control.live.snapshot.isEnabled, "native_encrypted_key_summary_disabled")
            return control
        case .failure(let issue):
            try require(false, issue.rawValue)
            throw issue
        }
    }

    @MainActor
    private func encryptedForm(port: Int, owner: RevealedControl, notice: String? = nil,
                               collapsedPEM: (draft: String, editor: RevealedControl)? = nil) throws ->
        (pem: RevealedControl, passphrase: RevealedControl, submit: RevealedControl) {
        var targets: [(String?, String, Bool)] = [("ssh-step-title", "SSH 账号认证", false),
            ("ssh-reviewed-endpoint", target(port), false), ("ssh-approved-note", "本次主机密钥已确认", false),
            ("ssh-connect", "连接 SSH", true)]
        if let notice { targets.append(("ssh-status", notice, false)) }
        let (rows, anchors) = try mobileWitness(targets, includeOffscreenText: true)
        if let collapsedPEM {
            try assertEncryptedCredentialsHidden(rows, pem: collapsedPEM.draft, previousEditor: collapsedPEM.editor)
        }
        let failure = "native_encrypted_key_submit_owner_unproven"
        let submit = try mobileControl(anchors[3], rows, failure)
        try require(sameControlScope(submit, owner), failure)
        let passwords = rows.filter { NativeControlPolicy.isMobilePasswordField(identifier: $0.snapshot.identifier,
                                                                               label: $0.snapshot.label) &&
            [.textField, .secureTextField, .textView].contains($0.snapshot.elementType) }
        try require(passwords.allSatisfy { !NativeFramePolicy.valid($0.snapshot.frame) && credentialEmpty($0.snapshot) },
                    "native_encrypted_key_method_unproven")
        let pem: RevealedControl
        if collapsedPEM != nil {
            pem = try collapsedPEMControl(rows, owner: owner)
        } else if let anchor = encryptedFieldAnchor(.pem, rows) {
            let editorFailure = "native_encrypted_key_editor_owner_unproven"
            let control = try mobileControl(anchor, rows, editorFailure)
            try require(sameControlScope(control, owner) && control.live.snapshot.isEnabled, editorFailure)
            pem = control
        } else {
            pem = try collapsedPEMControl(rows, owner: owner)
        }
        return (pem, try encryptedField(.passphrase, rows: rows, owner: submit), submit)
    }

    private func credentialEmpty(_ field: any XCUIElementSnapshot) -> Bool {
        NativeControlPolicy.credentialEmpty(field.value, placeholder: field.placeholderValue)
    }

    @MainActor
    private func typeEncryptedCredential(_ control: RevealedControl, text: String, keyboardWasHidden: Bool) throws {
        let failure = "native_encrypted_key_entry_unproven"
        let field = try reveal(control.live.element, matching: control, protectRouteTabs: true, mobileOwnerFailure: failure)
        try require(app.state == .runningForeground && !app.alerts.firstMatch.exists &&
                    (!keyboardWasHidden || !app.keyboards.firstMatch.exists) &&
                    field.live.snapshot.isEnabled && credentialEmpty(field.live.snapshot), failure)
        field.live.element.tap()
        try require(app.keyboards.firstMatch.waitForExistence(timeout: 10), "native_input_keyboard_missing")
        let focused = try reveal(field.live.element, matching: field, scrolling: false,
                                 protectRouteTabs: true, mobileOwnerFailure: failure)
        try require(app.state == .runningForeground && !app.alerts.firstMatch.exists &&
                    focused.live.snapshot.isEnabled && credentialEmpty(focused.live.snapshot), failure)
        // XCTest itself requires this exact native element to hold keyboard focus.
        // Any failed or ambiguous action ends the test without typing again.
        focused.live.element.typeText(text)
    }

    @MainActor
    private func encryptedDraft(port: Int, owner: RevealedControl, passphrase: String, valid: Bool) throws -> RevealedControl {
        let prefix = valid ? "encrypted_key_correct" : "encrypted_key_wrong"
        let failure = "native_encrypted_key_entry_unproven"
        let pem = (config["encryptedPEM"] as! String).trimmingCharacters(in: .newlines)
        let before = try encryptedForm(port: port, owner: owner)
        try require(credentialEmpty(before.pem.live.snapshot) && credentialEmpty(before.passphrase.live.snapshot) &&
                    !before.submit.live.snapshot.isEnabled, "native_encrypted_key_credentials_retained")
        try phase("pem")
        try post(prefix + "_pem_entry")
        try typeEncryptedCredential(before.pem, text: pem, keyboardWasHidden: true)
        let entered = try encryptedForm(port: port, owner: before.pem)
        try require(entered.pem.live.snapshot.value as? String == pem && credentialEmpty(entered.passphrase.live.snapshot) &&
                    !entered.submit.live.snapshot.isEnabled, failure)
        try post(prefix + "_pem_verified")

        try phase("passphrase")
        try typeEncryptedCredential(entered.passphrase, text: passphrase, keyboardWasHidden: false)
        try phase("pem_collapse")
        var filled = try encryptedForm(port: port, owner: entered.passphrase, collapsedPEM: (pem, entered.pem))
        // UIKit may briefly show the last typed character. Observe only and
        // stop without submitting if the secure field never shows a mask.
        let deadline = Date().addingTimeInterval(2)
        while !NativeControlPolicy.credentialMasked(filled.passphrase.live.snapshot.value) && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.2)
            filled = try encryptedForm(port: port, owner: entered.passphrase, collapsedPEM: (pem, entered.pem))
        }
        let maskFailure = "native_encrypted_key_passphrase_mask_unproven"
        try require(NativeControlPolicy.credentialMasked(filled.passphrase.live.snapshot.value), maskFailure)
        try require(filled.submit.owner.snapshot.isEnabled && filled.submit.live.snapshot.isEnabled, "native_control_disabled")

        try phase("pem_reopen")
        let summaryFailure = "native_encrypted_key_summary_owner_unproven"
        let summary = try reveal(filled.pem.live.element, matching: filled.pem,
            protectRouteTabs: true, mobileOwnerFailure: summaryFailure)
        try require(app.state == .runningForeground && !app.alerts.firstMatch.exists &&
                    summary.owner.snapshot.isEnabled && summary.live.snapshot.isEnabled, summaryFailure)
        summary.live.element.tap()
        try require(app.keyboards.firstMatch.waitForExistence(timeout: 2), "native_encrypted_key_reopen_keyboard_missing")
        let reopenedRows = try observedNodes()
        let editorFailure = "native_encrypted_key_editor_owner_unproven"
        guard let reopenedAnchor = encryptedFieldAnchor(.pem, reopenedRows) else {
            try require(false, editorFailure)
            throw NSError(domain: editorFailure, code: 1)
        }
        let reopenedEditor = try mobileControl(reopenedAnchor, reopenedRows, editorFailure)
        try require(sameControlScope(reopenedEditor, summary) &&
                    sameIdentity(reopenedEditor.owner.snapshot, entered.pem.owner.snapshot) &&
                    reopenedEditor.live.snapshot.isEnabled, editorFailure)
        try require(reopenedEditor.owner.snapshot.value as? String == pem &&
                    reopenedEditor.live.snapshot.value as? String == pem, "native_encrypted_key_reopen_readback_unproven")
        try post(prefix + "_pem_reopened")

        try phase("pem_recollapse")
        let passphraseOwner = try encryptedField(.passphrase, rows: reopenedRows, owner: reopenedEditor)
        let passphraseFailure = "native_encrypted_key_passphrase_owner_unproven"
        let current = try reveal(passphraseOwner.live.element, matching: passphraseOwner,
            protectRouteTabs: true, mobileOwnerFailure: passphraseFailure)
        try require(app.state == .runningForeground && !app.alerts.firstMatch.exists &&
                    current.owner.snapshot.isEnabled && current.live.snapshot.isEnabled, passphraseFailure)
        try require(NativeControlPolicy.credentialMasked(current.live.snapshot.value), maskFailure)
        current.live.element.tap()
        let secured = try encryptedForm(port: port, owner: current, collapsedPEM: (pem, reopenedEditor))
        try require(NativeControlPolicy.credentialMasked(secured.passphrase.live.snapshot.value), maskFailure)
        try require(secured.submit.owner.snapshot.isEnabled && secured.submit.live.snapshot.isEnabled, "native_control_disabled")
        try post(prefix + "_ready")
        return secured.submit
    }

    @MainActor
    private func assertEncryptedCredentialsHidden(_ observed: [Observed], pem: String, previousEditor: RevealedControl) throws {
        let editor = confirmedPEMEditor(observed, previous: previousEditor, pem: pem)
        let passphrases = ["ordinaryPassword", "rotationPassword", "encryptedWrongPassphrase", "encryptedPassphrase"]
            .compactMap { config[$0] as? String }
        let bodyLines = NativeControlPolicy.encryptedPEMBodyLines(pem)
        let suspicious = observed.compactMap { node -> [String: Any]? in
            let snapshot = node.snapshot
            // Once focus leaves the editor, even its exact value or a proven
            // text descendant is a disclosure. Scan the whole application tree.
            let editingRepresentation = pemRepresentation(node, editor: editor)
            let representation: NativeControlPolicy.PEMRepresentation =
                editingRepresentation == .editorValue || editingRepresentation == .editorText ? .editorAfterBlur : editingRepresentation
            let (headerHits, bodyHits, passwordHits) = NativeControlPolicy.encryptedSecretHits(
                identifier: snapshot.identifier, label: snapshot.label, value: snapshot.value as? String ?? "",
                pem: pem, bodyLines: bodyLines, passwords: passphrases, representation: representation)
            let headerHit = headerHits.contains(true), bodyHit = bodyHits.contains(true), passwordHit = passwordHits.contains(true)
            guard headerHit || bodyHit || passwordHit else { return nil }
            let pemOwner = editor?.owner ?? previousEditor.owner
            let path = node.path, pemPath = pemOwner.path
            let relation = path == pemPath ? "same" : pemPath.starts(with: path) ? "ancestor" :
                path.starts(with: pemPath) ? "descendant" : "other"
            let scope = node.windowPath == pemOwner.windowPath && node.webPath == pemOwner.webPath ?
                "sameWeb" : "other"
            return ["role": node.snapshot.elementType == .textView ? "textView" : role(node.snapshot.elementType),
                "scope": scope, "relation": relation, "identifier": headerHits[0] || bodyHits[0] || passwordHits[0],
                "label": headerHits[1] || bodyHits[1] || passwordHits[1], "value": headerHits[2] || bodyHits[2] || passwordHits[2],
                "privateKeyHeader": headerHit, "privateKeyBody": bodyHit, "passphrase": passwordHit,
                "pemReason": headerHit || bodyHit ? representation.rejection : "none"]
        }
        if !suspicious.isEmpty {
            try post("native_progress", ["nativeCheckpoint": nativePhase,
                "secretDiagnostic": ["count": min(suspicious.count, 10000), "candidates": Array(suspicious.prefix(12))]])
        }
        try require(suspicious.isEmpty, "native_secret_exposed")
    }

    @MainActor
    private func authMethodFact(_ node: any XCUIElementSnapshot) -> NativeControlPolicy.Fact {
        let category: String
        switch node.elementType {
        case .toggle: category = "toggle"
        case .switch: category = "switch"
        default: category = role(node.elementType)
        }
        return .init(identifier: node.identifier, label: node.label, role: category, value: nil)
    }

    @MainActor
    private func selectAuthMethod(_ method: NativeControlPolicy.AuthMethod, port: Int, owner: RevealedControl) throws -> RevealedControl {
        try phase("select_" + method.rawValue)
        let pageFailure = "native_encrypted_auth_page_unproven"
        let ownerFailure = "native_encrypted_auth_method_owner_unproven"
        let choice: RevealedControl = try waitForMobileWitness([("ssh-step-title", "SSH 账号认证", false),
            ("ssh-reviewed-endpoint", target(port), false), ("ssh-approved-note", "本次主机密钥已确认", false),
            ("ssh-connect", "连接 SSH", true)], includeOffscreenText: true,
            onMissing: { try self.require(false, pageFailure) }) { rows, anchors in
            let submit = anchors[3]
            guard let scope = controlScope(submit, rows), sameControlScope(scope, owner) else {
                try require(false, ownerFailure)
                throw NSError(domain: ownerFailure, code: 1)
            }
            try require(!submit.snapshot.isEnabled, "native_review_lock_invalid")
            switch method.candidate(rows.map { authMethodFact($0.snapshot) }) {
            case .success(let index):
                let candidate = rows[index]
                guard let candidateScope = controlScope(candidate, rows), sameControlScope(candidateScope, owner) else {
                    try require(false, ownerFailure)
                    throw NSError(domain: ownerFailure, code: 1)
                }
                try require(candidate.snapshot.isEnabled, "native_control_disabled")
                guard case .success(let control) = mobileBinding(candidate, rows) else {
                    return .pending("native_encrypted_auth_method_live_unproven", nil)
                }
                try require(control.live.snapshot.isEnabled, "native_control_disabled")
                return .ready(control)
            case .failure(let issue):
                if issue == .missing { return .pending(issue.rawValue, nil) }
                try require(false, issue.rawValue)
                throw issue
            }
        }
        try tapMobileButton(choice, "native_encrypted_auth_method_live_unproven", authMethod: method)
        try phase(method.rawValue + "_form")
        return choice
    }

    @MainActor
    private func exerciseEncryptedKey(port: Int) throws {
        scenario = "encrypted_key"
        try post("encrypted_key_form")
        try launchForm(port: port)
        try require(mobileFlow, "native_encrypted_key_method_unproven")
        try post("encrypted_key_probe")
        try phase("fingerprint")
        guard let approval = try approve(config["encryptedFingerprint"] as! String, port: port) else {
            throw NSError(domain: "native_encrypted_key_owner_unproven", code: 1)
        }
        try post("encrypted_key_reviewed")
        let key = try selectAuthMethod(.key, port: port, owner: approval)

        let wrong = try encryptedDraft(port: port, owner: key, passphrase: config["encryptedWrongPassphrase"] as! String, valid: false)
        try phase("wrong_submit")
        try post("encrypted_key_wrong_submit")
        try tapMobileButton(wrong, "native_encrypted_key_owner_unproven")
        try waitForCaptureKeyboardToHide(reportDiagnostic: false)
        let rejected = try encryptedForm(port: port, owner: key, notice: "连接失败或已中断，请核查连接资料。")
        try require(credentialEmpty(rejected.pem.live.snapshot) && credentialEmpty(rejected.passphrase.live.snapshot) &&
                    !rejected.submit.live.snapshot.isEnabled, "native_encrypted_key_rejection_unproven")
        try post("encrypted_key_wrong_rejected")

        let correct = try encryptedDraft(port: port, owner: rejected.pem, passphrase: config["encryptedPassphrase"] as! String, valid: true)
        try phase("connect")
        try post("encrypted_key_correct_submit")
        try tapMobileButton(correct, "native_encrypted_key_owner_unproven")
        try waitForCaptureKeyboardToHide(reportDiagnostic: false)
        let (activeRows, activeAnchors) = try activePage(.terminal, port: port, owner: correct)
        let active = try mobileControl(activeAnchors[3], activeRows, "native_active_owner_unproven")
        try post("encrypted_key_connected")
        try terminal("encrypted_key", port: port, owner: active)
        try returnOrdinaryHome("encrypted_key")
    }

    private struct ActiveLayout {
        let screen: CGRect
        let statusBars: [CGRect]
        let keyboards: [CGRect]
        let keyboardPresent: Bool

        func viewport(for anchor: Observed) -> NativeFramePolicy.ActiveViewport {
            NativeFramePolicy.activeViewport(window: anchor.window, screen: screen, webAncestors: anchor.webs,
                statusBars: statusBars, keyboardPresent: keyboardPresent, keyboardFrames: keyboards)
        }
    }

    @MainActor
    private func activeLayout() -> ActiveLayout {
        ActiveLayout(screen: app.frame, statusBars: statusBarFrames(), keyboards: keyboardFrames(),
                     keyboardPresent: app.keyboards.firstMatch.exists)
    }

    @MainActor
    private func activeDiagnostic(_ context: NativeActiveContext, _ page: NativeActivePage, _ reason: String,
                                  layout measured: ActiveLayout? = nil, viewport: NativeFramePolicy.ActiveViewport? = nil,
                                  frames: [CGRect] = []) throws {
        let layout = measured ?? activeLayout()
        let rect = NativeFramePolicy.diagnosticRect
        try post("native_active_diagnostic", ["nativeCheckpoint": nativePhase, "detail": [
            "context": context.rawValue, "page": page.rawValue, "reason": reason, "keyboardVisible": layout.keyboardPresent,
            "screen": rect(layout.screen), "viewport": rect(viewport?.viewport), "visible": rect(viewport?.visible),
            "statusBars": layout.statusBars.prefix(4).map { rect($0) },
            "keyboards": layout.keyboards.prefix(4).map { rect($0) },
            "frames": frames.prefix(5).map { rect($0) },
        ]])
    }

    @MainActor
    private func activePage(_ page: NativeActivePage, port: Int, owner: RevealedControl,
                            context: NativeActiveContext = .connect,
                            keyboardAction: (String, String)? = nil) throws -> ([Observed], [Observed]) {
        var expected = page.witnesses(endpoint: target(port))
        if let keyboardAction { expected.append((keyboardAction.0, keyboardAction.1, true)) }
        let (rows, anchors) = try waitForMobileWitness(expected, includeOffscreenText: false,
            onMissing: { try self.activeDiagnostic(context, page, "page_witness_unproven") }) { .ready(($0, $1)) }
        let first = anchors[0]
        guard let scope = controlScope(first, rows), sameControlScope(scope, owner),
              first.webs.count <= 16, anchors.allSatisfy({
                  $0.windowPath == first.windowPath && $0.webPath == first.webPath &&
                  $0.window == first.window && $0.webs == first.webs
              }) else {
            try activeDiagnostic(context, page, "owner_unproven", frames: anchors.map { $0.snapshot.frame })
            try require(false, "native_active_owner_unproven")
            throw NSError(domain: "native_active_owner_unproven", code: 1)
        }
        let layout = activeLayout(), geometry = layout.viewport(for: first)
        let frames = anchors.map { $0.snapshot.frame }
        guard let visible = geometry.visible else {
            try activeDiagnostic(context, page, geometry.reason ?? "viewport_empty", layout: layout, viewport: geometry, frames: frames)
            try require(false, "native_visible_frame_invalid")
            throw NSError(domain: "native_visible_frame_invalid", code: 1)
        }
        if !frames.allSatisfy(visible.contains) {
            try activeDiagnostic(context, page, "page_clipped", layout: layout, viewport: geometry, frames: frames)
            try require(false, "native_active_page_unproven")
        }
        if page != .terminal {
            let activeButtons = Set(["ssh-focus", "ssh-hide-keyboard", "ssh-disconnect"])
            let activeLabels = Set(["打开键盘", "收起键盘", "断开连接"])
            let controls = rows.filter { item in
                item.webPath == scope.web.path && item.snapshot.elementType == .button &&
                    (activeButtons.contains(item.snapshot.identifier) || activeLabels.contains(item.snapshot.label)) &&
                    NativeFramePolicy.valid(item.snapshot.frame.intersection(visible))
            }
            if !controls.isEmpty {
                try activeDiagnostic(context, page, "page_conflict", layout: layout, viewport: geometry,
                                     frames: controls.map { $0.snapshot.frame })
                try require(false, "native_active_page_unproven")
            }
        }
        try assertNoSecret(rows.map { $0.snapshot })
        try assertCredentialsInactive(first, rows, visible: visible)
        return (rows, anchors)
    }

    @MainActor
    private func activeAction(_ action: (String, String), rows: [Observed], owner: RevealedControl,
                              context: NativeActiveContext, page: NativeActivePage = .terminal,
                              route: Bool = false) throws -> (element: XCUIElement, geometry: [String: Any]) {
        let (identifier, label) = action
        let roles: Set<XCUIElement.ElementType> = route ? [.button, .checkBox, .switch, .toggle] : [.button]
        let identified = rows.filter { $0.snapshot.identifier == identifier }
        let candidates = identified.isEmpty ? rows.filter {
            let snapshot = $0.snapshot
            return roles.contains(snapshot.elementType) && snapshot.label == label &&
                (snapshot.identifier.isEmpty || snapshot.identifier == label)
        } : identified
        guard candidates.count == 1, let candidate = candidates.first,
              roles.contains(candidate.snapshot.elementType), candidate.snapshot.label == label,
              candidate.snapshot.isEnabled, let scope = controlScope(candidate, rows), sameControlScope(scope, owner),
              liveOnPath(scope.window) != nil, let web = liveOnPath(scope.web) else {
            try activeDiagnostic(context, page, "action_unbound", frames: candidates.map { $0.snapshot.frame })
            try require(false, "native_active_action_unproven")
            throw NSError(domain: "native_active_action_unproven", code: 1)
        }
        let predicate = NSPredicate(format: "identifier == %@ OR label == %@", identifier, label)
        let query = web.element.descendants(matching: candidate.snapshot.elementType).matching(predicate)
        guard query.count == 1, let live = liveControl(query.firstMatch), live.snapshot.isEnabled,
              sameIdentity(candidate.snapshot, live.snapshot), candidate.snapshot.frame == live.snapshot.frame else {
            try activeDiagnostic(context, page, "action_live_unproven", frames: [candidate.snapshot.frame])
            try require(false, "native_active_action_unproven")
            throw NSError(domain: "native_active_action_unproven", code: 1)
        }
        let frame = live.snapshot.frame
        let layout = activeLayout(), geometry = layout.viewport(for: candidate)
        guard let visible = geometry.visible, let viewport = geometry.viewport else {
            try activeDiagnostic(context, page, geometry.reason ?? "viewport_empty",
                                 layout: layout, viewport: geometry, frames: [frame])
            try require(false, "native_active_action_unproven")
            throw NSError(domain: "native_active_action_unproven", code: 1)
        }
        let tabs = route ? nil : routeTabsOcclusion(candidate, rows, viewport, [frame], scrolling: false)
        let invalid = NativeFramePolicy.interactionFailure([frame], in: visible, occlusions: [], hittable: live.hittable)
        let bars = layout.statusBars
        let tabsBlock = tabs.map { NativeFramePolicy.valid($0.intersection(frame)) } ?? false
        let reason = invalid?.rawValue ?? (tabsBlock ? "route_tabs_occluded" : nil)
        let clearHeader = NativeFramePolicy.headerStatusBarsValid(bars, screen: layout.screen) &&
            NativeFramePolicy.headerFrameClear(frame, safe: visible, statusBars: bars)
        if reason != nil || !clearHeader {
            try activeDiagnostic(context, page, reason ?? "status_bar_action_invalid", layout: layout,
                                 viewport: geometry, frames: [frame] + (tabs.map { [$0] } ?? []))
            try require(false, "native_active_action_unproven")
        }
        return (live.element, ["frame": rect(frame), "visibleFrame": rect(visible), "screenFrame": rect(layout.screen),
            "statusBarFrames": bars.map(rect), "role": role(live.snapshot.elementType), "enabled": live.snapshot.isEnabled,
            "hittable": live.hittable, "ownerResolved": true, "centerVisible": visible.contains(CGPoint(x: frame.midX, y: frame.midY)),
            "fullyVisible": visible.contains(frame)])
    }

    @MainActor
    private func activeKeyboard(open: Bool, port: Int, owner: RevealedControl) throws -> [String: Any] {
        let beforeContext: NativeActiveContext = open ? .keyboardOpenBefore : .keyboardCloseBefore
        let afterContext: NativeActiveContext = open ? .keyboardOpenAfter : .keyboardCloseAfter
        if app.keyboards.firstMatch.exists == open || (!keyboardFrames().isEmpty) == open {
            try activeDiagnostic(beforeContext, .terminal, "keyboard_state_changed")
            try require(false, "native_active_action_unproven")
        }
        let show = ("ssh-focus", "打开键盘"), hide = ("ssh-hide-keyboard", "收起键盘")
        let (before, _) = try activePage(.terminal, port: port, owner: owner, context: beforeContext, keyboardAction: open ? show : hide)
        let action = try activeAction(open ? show : hide, rows: before, owner: owner, context: beforeContext)
        action.element.tap()
        if open {
            if !app.keyboards.firstMatch.waitForExistence(timeout: 10) {
                try activeDiagnostic(afterContext, .terminal, "keyboard_missing")
                try require(false, "native_terminal_keyboard_missing")
            }
        } else { try waitForCaptureKeyboardToHide(reportDiagnostic: false) }
        let (after, _) = try activePage(.terminal, port: port, owner: owner, context: afterContext, keyboardAction: open ? hide : show)
        _ = try activeAction(open ? hide : show, rows: after, owner: owner, context: afterContext)
        if app.keyboards.firstMatch.exists != open || (!keyboardFrames().isEmpty) != open {
            try activeDiagnostic(afterContext, .terminal, "keyboard_state_changed")
            try require(false, "native_active_action_unproven")
        }
        return action.geometry
    }

    @MainActor
    private func activeRoute(from source: NativeActivePage, to destination: NativeActivePage,
                             port: Int, owner: RevealedControl) throws -> [String: Any] {
        let (before, _) = try activePage(source, port: port, owner: owner, context: .routeBefore)
        try require(!app.keyboards.firstMatch.exists, "native_terminal_keyboard_visible")
        let action = try activeAction(destination.routeAction, rows: before, owner: owner, context: .routeBefore, page: source, route: true)
        action.element.tap()
        let (after, _) = try activePage(destination, port: port, owner: owner, context: .routeAfter,
            keyboardAction: destination == .terminal ? ("ssh-focus", "打开键盘") : nil)
        try require(!app.keyboards.firstMatch.exists, "native_terminal_keyboard_visible")
        if destination == .terminal { _ = try activeAction(("ssh-focus", "打开键盘"), rows: after, owner: owner, context: .routeAfter) }
        return action.geometry
    }

    @MainActor
    private func activeFlow(port: Int, owner: RevealedControl) throws {
        try phase("active_flow")
        try waitForCaptureKeyboardToHide(reportDiagnostic: false)
        func record(_ step: String, _ action: [String: Any]) throws {
            try post("ordinary_active", ["step": step, "keyboardVisible": app.keyboards.firstMatch.exists, "action": action])
        }
        try record("keyboard_opened", activeKeyboard(open: true, port: port, owner: owner))
        try record("keyboard_closed", activeKeyboard(open: false, port: port, owner: owner))
        let routes: [(NativeActivePage, String, String)] = [(.board, "board", "terminal_from_board"),
            (.network, "network", "terminal_from_network"), (.settings, "settings", "terminal_from_settings")]
        for (destination, away, returned) in routes {
            try record(away, activeRoute(from: .terminal, to: destination, port: port, owner: owner))
            try record(returned, activeRoute(from: destination, to: .terminal, port: port, owner: owner))
        }
    }

    @MainActor
    private func terminal(_ stage: String, port: Int, owner: RevealedControl?) throws {
        if stage == "ordinary" {
            guard let owner, mobileFlow else {
                try require(false, "native_active_owner_unproven")
                throw NSError(domain: "native_active_owner_unproven", code: 1)
            }
            try activeFlow(port: port, owner: owner)
        }
        try phase("terminal_focus")
        if stage == "key_change" { try waitForCaptureKeyboardToHide(reportDiagnostic: false) }
        if let owner { _ = try activeKeyboard(open: true, port: port, owner: owner) }
        else { try tap(button("打开键盘")) }
        try require(app.keyboards.firstMatch.waitForExistence(timeout: 10), "native_terminal_keyboard_missing")
        // Exactly one UI typing operation. Checkpoints/OCR never replay it.
        try phase("terminal_input")
        app.typeText("hp-check\n")
        try post(stage + "_input")
        // Only wait for server output to render; no client buffers are used as proof.
        Thread.sleep(forTimeInterval: 2)
        try phase("terminal_capture")
        if app.keyboards.firstMatch.exists {
            if let owner { _ = try activeKeyboard(open: false, port: port, owner: owner) }
            else { try tap(button("收起键盘")) }
        }
        try waitForCaptureKeyboardToHide()
        try screenshot(stage + "_terminal", port: port, activeOwner: owner)
        try phase("disconnect")
        try post(stage + "_disconnect_attempt")
        if let owner {
            let (rows, _) = try activePage(.terminal, port: port, owner: owner, context: .disconnect)
            try activeAction(("ssh-disconnect", "断开连接"), rows: rows, owner: owner, context: .disconnect).element.tap()
        } else { try tap(button("断开连接")) }
        if mobileFlow { try mobileDisconnected() } else { try waitText("已断开") }
        try post(stage + "_disconnected")
    }

    @MainActor
    private func returnOrdinaryHome(_ stage: String) throws {
        try phase("return_home")
        if mobileFlow {
            try tapMobileButton(try mobileDisconnected(), "native_mobile_return_owner_unproven")
            _ = try mobileWitness([(nil, "还没有主机", false), ("host-ssh-disconnected", "本机已断开", false)])
        } else {
            try tap(button("看板"))
        }
        try waitText("还没有主机")
        let returnedHome = try navigationState(publish: false)
        try require(NativeHomeReadiness.classify(returnedHome, home: lastHomeSample!) == .ready,
                    "native_home_identity_unproven")
        try post(stage + "_returned_home")
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
        if let encryptedPort = config["encryptedPort"] as? Int {
            try exerciseEncryptedKey(port: encryptedPort)
            return
        }
        let ordinaryPort = config["ordinaryPort"] as! Int
        try post("ordinary_form")
        try launchForm(port: ordinaryPort)
        try post("ordinary_probe")
        try phase("fingerprint")
        let ordinaryOwner = try approve(config["ordinaryFingerprint"] as! String, port: ordinaryPort)
        try post("ordinary_password")
        let activeOrdinary = try connect(password: config["ordinaryPassword"] as! String, mobileOwner: ordinaryOwner)
        try terminal("ordinary", port: ordinaryPort, owner: activeOrdinary)
        try returnOrdinaryHome("ordinary")
        app.terminate()

        let port = config["rotationPort"] as! Int
        scenario = "key_change"
        try post("key_change_form")
        try launchForm(port: port)
        try post("key_change_probe_a")
        try phase("fingerprint")
        let rotationOwner = try approve(config["fingerprintA"] as! String, port: port)
        try post("key_change_password_a")
        try phase("password")
        try fillPassword(rotationOwner?.live.element ?? password(), config["rotationPassword"] as! String, mobileOwner: rotationOwner)
        if !mobileFlow { try check(true, enabled: true) }
        let refusedControl = try rotationOwner.map { try mobileAuth(port: port, ready: true, previous: $0).submit }
        try phase("connect")
        try submitConnection(.rotationRefused, waitingFor: "主机指纹发生变化", control: refusedControl)
        try phase("review_capture")
        if mobileFlow {
            _ = try mobileWitness([(nil, "主机指纹发生变化", false), ("ssh-key-change-endpoint", target(port), false),
                ("ssh-key-change-algorithms", "旧密钥算法 · " + (config["rotationAlgorithm"] as! String), false)])
        }
        try screenshot("key_change_review", port: port, reviewPage: true)
        try phase("cancel")
        try tap(button("取消连接，保留旧信任"))
        try phase("cancel_check")
        if mobileFlow {
            try mobileTarget(prior: config["fingerprintA"] as! String)
        } else {
            try waitText("已保留的旧信任")
            try require(try contains(config["fingerprintA"] as! String), "native_cancel_lost_old_trust")
            try require(try !contains(config["fingerprintB"] as! String), "native_cancel_accepted_new_trust")
            try check(false, enabled: false)
            let cancelledPassword = liveControl(password())
            try require(cancelledPassword != nil && cancelledPassword?.snapshot.isEnabled == false &&
                        NativeControlPolicy.credentialEmpty(cancelledPassword?.snapshot.value, placeholder: cancelledPassword?.snapshot.placeholderValue),
                        "native_cancel_credentials_live")
            let cancelledSubmit = liveControl(button("连接 / 重新连接"))
            try require(cancelledSubmit != nil && cancelledSubmit?.snapshot.isEnabled == false, "native_cancel_submit_live")
        }
        try post("key_change_cancelled")
        try phase("reprobe")
        try tapForm("probe")
        if !mobileFlow {
            try waitText(config["fingerprintB"] as! String)
            try require(try !contains(config["fingerprintA"] as! String), "native_reprobe_old_key_stale")
            try check(false, enabled: true)
            guard let reprobedPassword = liveControl(password()) else {
                try require(false, "native_reprobe_secret_stale")
                throw NSError(domain: "native_reprobe_secret_stale", code: 1)
            }
            try require(NativeControlPolicy.credentialEmpty(reprobedPassword.snapshot.value, placeholder: reprobedPassword.snapshot.placeholderValue), "native_reprobe_secret_stale")
        }
        try post("key_change_probe_b")
        try phase("new_fingerprint")
        let rotatedOwner = try approve(config["fingerprintB"] as! String, port: port, excluding: config["fingerprintA"] as? String)
        try post("key_change_password_b")
        let activeRotation = try connect(password: config["rotationPassword"] as! String, mobileOwner: rotatedOwner)
        try terminal("key_change", port: port, owner: activeRotation)
        if mobileFlow {
            try tapMobileButton(try mobileDisconnected(), "native_mobile_return_owner_unproven")
            _ = try mobileWitness([(nil, "还没有主机", false), ("host-ssh-disconnected", "本机已断开", false)])
        }
        try post("complete")
    }
}
