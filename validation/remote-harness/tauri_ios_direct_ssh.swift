import XCTest
import Foundation
import CoreGraphics
import UIKit

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

    static func terminalControlScroll(target: CGRect, dismiss: CGRect, helpers: [CGRect], safe: CGRect) -> ScrollDirection? {
        let anchors = [target, dismiss] + helpers
        guard anchors.allSatisfy({ valid($0) && $0.minX >= safe.minX && $0.maxX <= safe.maxX }) else { return nil }
        let frame = anchors.reduce(CGRect.null) { $0.union($1) }
        guard frame.height <= safe.height else { return nil }
        let down = frame.minY < safe.minY || target.maxY > dismiss.minY
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
enum NativeHomeReadiness {
    enum State: String {
        case ready, loading, shell, error, alert, unexpected, notForeground = "not_foreground"
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
        for (name, identifier, label) in definitions {
            let roles: Set<String> = name == "probe" ? ["button"] : ["textField", "textView", "searchField"]
            let result = formVerdict(facts: facts, paths: paths, identifier: identifier, label: label, editableRoles: roles)
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
            guard owned(index), (facts[index].role == "staticText" && facts[index].label == "普通 SSH 终端") ||
                (facts[index].identifier == "ssh-page-heading" && !interactive.contains(facts[index].role)) else { return false }
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
    private var accepted = false
    func set(_ value: Bool) { lock.lock(); accepted = value; lock.unlock() }
    func get() -> Bool { lock.lock(); defer { lock.unlock() }; return accepted }
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
    private var nativePhase = "ordinary_launch"
    private var lastHomeSample: [String: Any]?
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
    }
    private struct RevealedControl {
        let live: LiveControl
        let owner: Observed
        let window: Observed
        let web: Observed
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

        var frames: [CGRect] { nodes.map { $0.snapshot.frame } }

        func output(in safe: CGRect) -> CGRect? {
            usesControls ? NativeFramePolicy.terminalControlBand(dismiss: frames[1], helpers: Array(frames.dropFirst(2)), safe: safe) : frames[1]
        }

        func visibleOutput(in safe: CGRect) -> CGRect? {
            guard let output = output(in: safe) else { return nil }
            if usesControls && (!frames.allSatisfy(safe.contains) || frames[0].maxY > frames[1].minY) { return nil }
            return NativeFramePolicy.terminalCrop(target: frames[0], output: output, safe: safe)
        }

        func direction(in safe: CGRect) -> NativeFramePolicy.ScrollDirection? {
            usesControls ? NativeFramePolicy.terminalControlScroll(target: frames[0], dismiss: frames[1],
                helpers: Array(frames.dropFirst(2)), safe: safe) : NativeFramePolicy.terminalScroll(target: frames[0], output: frames[1], safe: safe)
        }
    }

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
        try observedNodes().map { $0.snapshot }
    }

    @MainActor
    private func observedNodes() throws -> [Observed] {
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
            try require(result.count < 10000, "native_tree_limit")
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
        let ids = ["普通 SSH 终端": "add-ssh", "herdr 配对 / 手动连接": "add-herdr",
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
        func select(_ rows: [Observed]) -> (owner: Observed, window: Observed, web: Observed, identified: Bool)? {
            let selection = formSelection(rows)
            guard selection.ownerResolved, let verdict = selection.controls[name], verdict.reason == "matched",
                  let index = verdict.index, let scope = controlScope(rows[index], rows) else { return nil }
            return (rows[index], scope.window, scope.web, verdict.identified)
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
        return FormControl(live: current, owner: fresh.owner, window: fresh.window, web: fresh.web, identified: fresh.identified)
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
    private func fillForm(_ name: String, _ text: String) throws {
        let tapped = try tapForm(name)
        try require(app.keyboards.firstMatch.waitForExistence(timeout: 10), "native_input_keyboard_missing")
        let current = try formControl(name, matching: tapped).live
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
            let after = try formControl(name, matching: tapped).live
            try require(NativeControlPolicy.valueText(after.snapshot.value) == text, "native_input_value_invalid")
            return
        }
        try failControlGeometry(lastFailure)
    }

    @MainActor
    private func password() -> XCUIElement {
        resolveControl(app.secureTextFields, app.secureTextFields, identifier: "ssh-password", label: "密码", requireTypedID: true)
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
                        protectRouteTabs: Bool = false) throws -> RevealedControl {
        try require(item.waitForExistence(timeout: 20), "native_control_missing")
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
                  liveOnPath(scope.window) != nil, liveOnPath(scope.web) != nil, let bound = liveOnPath(owner) else {
                try require(false, "native_control_owner_unproven")
                throw NSError(domain: "native_control_owner_unproven", code: 1)
            }
            if let prior = prior {
                try require(scope.window.path == prior.window.path && scope.web.path == prior.web.path &&
                    sameIdentity(scope.window.snapshot, prior.window.snapshot) && sameIdentity(scope.web.snapshot, prior.web.snapshot) &&
                    sameIdentity(owner.snapshot, prior.owner.snapshot), "native_control_owner_unproven")
            }
            let resolved = RevealedControl(live: bound, owner: owner, window: scope.window, web: scope.web)
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
    private func fillPassword(_ item: XCUIElement, _ text: String) throws {
        let initial = try reveal(item)
        let current = initial.live
        try require(current.snapshot.elementType == .secureTextField, "native_control_owner_unproven")
        try require(current.snapshot.isEnabled, "native_control_disabled")
        current.element.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        try post("native_progress", ["nativeCheckpoint": nativePhase, "nativeInputRole": role(current.snapshot.elementType)])
        try require(app.keyboards.firstMatch.waitForExistence(timeout: 10), "native_input_keyboard_missing")
        let ready = try reveal(item, matching: initial, scrolling: false).live
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
    private func assertCredentialsInactive(_ page: Observed, _ rows: [Observed]) throws {
        let visible = try safeFrame([page])
        for (identifier, label) in [("ssh-password", "密码"), ("ssh-key", "私钥"), ("ssh-passphrase", "私钥口令（可选）")] {
            let query = app.descendants(matching: .any).matching(NSPredicate(format:
                "identifier == %@ OR label == %@", identifier, label))
            var visibleLabel = false
            for text in app.staticTexts.matching(NSPredicate(format: "label == %@", label)).allElementsBoundByIndex
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
    private func nativeOcclusions() -> [CGRect] {
        NativeFramePolicy.unique(statusBarFrames() + app.keyboards.allElementsBoundByIndex
            .compactMap { liveControl($0)?.snapshot.frame }.filter(NativeFramePolicy.valid))
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
        let allMatches = rows.filter { identifiers.contains($0.snapshot.identifier) || texts($0.snapshot).contains(text) }
        // The identifier alone cannot prove displayed text.
        let checkText = reviewSample != nil || requireExactText
        let exact = checkText ? allMatches.filter { texts($0.snapshot).contains(text) } : allMatches
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
        let labels = [["收起键盘"], ["Esc"], ["Tab"], ["上方向键", "↑"], ["下方向键", "↓"]]
        var controls: [Observed] = []
        for (index, aliases) in labels.enumerated() {
            let matches = rows.filter { row in
                (index == 0 && row.snapshot.identifier == "ssh-hide-keyboard") ||
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
    private func waitForCaptureKeyboardToHide(reviewSample: String? = nil) throws {
        let end = Date().addingTimeInterval(8)
        repeat {
            if !app.keyboards.firstMatch.exists {
                Thread.sleep(forTimeInterval: 0.15)
                if !app.keyboards.firstMatch.exists { return }
            }
            Thread.sleep(forTimeInterval: 0.15)
        } while Date() < end
        try captureDiagnostic(reviewSample == nil ? "keyboard" : "review_title", "keyboard_visible", [], [], reviewSample: reviewSample)
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
    private func terminalHeader(_ title: Observed, _ rows: [Observed], safe: CGRect) throws -> TerminalHeader {
        let bars = statusBarFrames()
        if !NativeFramePolicy.headerStatusBarsValid(bars, screen: app.frame) {
            try captureDiagnostic("status_bar", bars.isEmpty ? "not_found" : "frame_invalid", [], rows, visible: safe)
            try require(false, "native_terminal_header_unproven")
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
    private func screenshot(_ stage: String, port: Int, reviewPage: Bool = false) throws {
        let reviewMembers = [("review_title", []), ("review_blocked", []),
            ("review_old_fingerprint", ["ssh-key-change-old"]), ("review_new_fingerprint", ["ssh-key-change-new"]),
            ("review_target", ["ssh-key-change-target"]), ("review_recheck", ["ssh-key-recheck"]),
            ("review_cancel", ["ssh-key-cancel"])]
        let labels = reviewPage ? ["主机指纹发生变化", "已阻止连接与输入",
            "旧：" + (config["fingerprintA"] as! String), "新：" + (config["fingerprintB"] as! String),
            "目标：" + target(port), "重新核对主机指纹", "取消连接，保留旧信任"] :
            [target(port) + " · SSH 已连接", "SSH 终端输出"]
        func anchors(_ source: [Observed], reviewSample: String? = nil, occlusions: [CGRect]? = nil) throws -> CaptureAnchors {
            if let sample = reviewSample {
                let resolved = try zip(reviewMembers, labels).map { member, label in
                    try exactObserved(source, label, identifiers: member.1, captureAnchor: member.0, reviewSample: sample, occlusions: occlusions)
                }
                return CaptureAnchors(nodes: resolved, usesControls: false)
            }
            let title = try exactObserved(source, labels[0], captureAnchor: "target", requireVisible: false)
            if source.contains(where: { $0.snapshot.identifier == "ssh-terminal-output" || texts($0.snapshot).contains(labels[1]) }) {
                let output = try exactObserved(source, labels[1], identifiers: ["ssh-terminal-output"], control: true,
                    captureAnchor: "terminal", requireVisible: false)
                return CaptureAnchors(nodes: [title, output], usesControls: false)
            }
            return CaptureAnchors(nodes: [title] + (try terminalBoundaryControls(title, source)), usesControls: true)
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
            let verified = try terminalHeader(owner, tree, safe: safe)
            header = verified
            extra["headerBounds"] = ["brandFrame": rect(verified.nodes[0].snapshot.frame),
                "addFrame": rect(verified.nodes[1].snapshot.frame), "headingFrame": rect(verified.nodes[2].snapshot.frame),
                "headerBottom": Double(verified.bottom), "statusBarFrames": verified.statusBars.map(rect), "sameOwner": true]
            try require(safe.contains(frames[0]) && !frames[0].isEmpty, "native_target_clipped")
            guard let crop = selected.visibleOutput(in: safe) else {
                try require(false, "native_terminal_frame_invalid")
                throw NSError(domain: "native_terminal_frame_invalid", code: 1)
            }
            extra["terminalFrame"] = rect(crop); extra["targetFrame"] = rect(frames[0])
            extra["boundSource"] = selected.usesControls ? "terminal_control_bounds" : "native_region"
            if selected.usesControls {
                try verifyCaptureControls(selected, tree, safe)
                extra["controlBounds"] = ["dismissFrame": rect(frames[1]), "helperFrames": frames.dropFirst(2).map(rect), "sameOwner": true]
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
            let rechecked = try terminalHeader(after.nodes[0], afterTree, safe: afterSafe)
            if Set(header.statusBars.map(rect)) != Set(rechecked.statusBars.map(rect)) {
                try captureDiagnostic("status_bar", "layout_unstable", [], afterTree, visible: afterSafe)
                try require(false, "native_capture_geometry_changed")
            }
            if header.bottom != rechecked.bottom || !stableCaptureLayout(header.nodes, rechecked.nodes) {
                let index = rechecked.nodes.indices.first {
                    !stableCaptureLayout([header.nodes[$0]], [rechecked.nodes[$0]])
                } ?? 2
                try captureDiagnostic(["header_brand", "header_add", "terminal_heading"][index], "layout_unstable",
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
    private func homeDiagnostics(_ tree: [Observed]) throws -> [String: Any] {
        let rows = tree.map { $0.snapshot }
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
        let safe = foreground && webCount > 0 && member("brand") > 0 && member("homeHeading") > 0 &&
            member("zeroHosts") > 0 && member("emptyHeading") > 0 && inputCount == 0 &&
            appAlerts.isEmpty && systemAlerts.isEmpty && !alertSnapshotFailed && errors.values.allSatisfy { !$0 }
        let result: [String: Any] = ["appForeground": foreground, "webViewCount": min(webCount, 10000),
            "windowCount": min(rows.filter { $0.elementType == .window }.count, 10000), "members": members, "knownErrors": errors,
            "appAlertCount": min(appAlerts.count, 10000), "systemAlertCount": min(systemAlerts.count, 10000),
            "alertMembers": alertMembers, "alertSnapshotFailed": alertSnapshotFailed,
            "inputCount": min(inputCount, 10000), "unknownVisibleTextCount": min(unknownTextCount, 10000),
            "knownEmptyHome": safe]
        return result
    }

    @MainActor
    private func navigationState(publish: Bool = true) throws -> [String: Any] {
        let tree = try observedNodes()
        let home = try homeDiagnostics(tree)
        lastHomeSample = home
        if publish { try post("native_home", ["nativeCheckpoint": nativePhase, "home": home]) }
        let members = home["members"] as! [String: [String: Any]]
        let seen = { (key: String) in (members[key]?["count"] as? Int ?? 0) > 0 }
        let selection = formSelection(tree)
        let facts = formTargets(tree)
        let paths = tree.map { $0.path }
        let choice = NativeControlPolicy.formVerdict(facts: facts, paths: paths, identifier: "add-ssh",
            label: "普通 SSH 终端", editableRoles: ["button"]).index != nil &&
            NativeControlPolicy.formVerdict(facts: facts, paths: paths, identifier: "add-herdr",
                label: "herdr 配对 / 手动连接", editableRoles: ["button"]).index != nil
        var formControls: [String: Any] = [:]
        for name in ["host", "port", "user", "probe"] {
            let item = selection.controls[name]!
            formControls[name] = ["role": item.role, "matches": item.matches, "owner": item.owner, "reason": item.reason]
        }
        let noErrors = !(home["knownErrors"] as! [String: Bool]).values.contains(true)
        let noAlerts = (home["appAlertCount"] as! Int) == 0 && (home["systemAlertCount"] as! Int) == 0 && home["alertSnapshotFailed"] as? Bool == false
        let empty = seen("brand") && seen("homeHeading") && seen("emptyHeading") && seen("zeroHosts") &&
            home["inputCount"] as? Int == 0 && noErrors && noAlerts && ["host", "port", "user"].allSatisfy { selection.controls[$0]?.index == nil }
        let formOwnerResolved = selection.ownerResolved
        let form = formOwnerResolved
        let page = form ? "sshForm" : choice ? "addChoice" : empty ? "emptyHome" : "unexpected"
        let title = tree.contains { texts($0.snapshot).contains { $0.contains("普通 SSH 终端") } }
        let passwords = tree.filter { $0.snapshot.elementType == .secureTextField &&
            ($0.snapshot.identifier == "ssh-password" || $0.snapshot.label == "密码") }
        let credentialsEmpty = passwords.allSatisfy { NativeControlPolicy.credentialEmpty($0.snapshot.value, placeholder: $0.snapshot.placeholderValue) }
        return ["page": page, "appForeground": home["appForeground"]!, "inputCount": home["inputCount"]!,
            "windowCount": home["windowCount"]!, "webViewCount": home["webViewCount"]!,
            "noAlerts": noAlerts, "noKnownErrors": noErrors,
            "emptyHomeIdentity": empty, "formByStructure": form, "formOwnerResolved": formOwnerResolved, "sshTitleSeen": title,
            "addTitleSeen": seen("addHeading"), "credentialsEmpty": credentialsEmpty, "formControls": formControls]
    }

    @MainActor
    private func navigationGeometry(_ item: XCUIElement) throws -> [String: Any] {
        guard let current = liveControl(item) else {
            try require(false, "native_control_missing")
            throw NSError(domain: "native_control_missing", code: 1)
        }
        let snapshot = current.snapshot
        let owner = controlOwner(snapshot, try observedNodes())
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
    private func navigate(_ member: String) throws -> (String, String, String) {
        let before = try navigationState()
        // A delayed view transition may already have produced the real form.
        // Preserve this newly sampled source state; never rewrite it as addChoice
        // or synthesize an unperformed click to make a historical row fit.
        if member == "sshChoice" && before["page"] as? String == "sshForm" {
            try require(NativeHomeReadiness.permitsNavigation(before, from: "sshForm"), "native_home_retry_unsafe")
            let host = field("主机地址")
            try post("native_navigation_arrival", ["nativeCheckpoint": nativePhase, "state": before,
                "geometry": try navigationGeometry(host), "source": "currentFormObservation", "performed": false])
            guard let current = liveControl(host) else { throw NSError(domain: "native_control_missing", code: 1) }
            return ("sshForm", "uniqueIdentifier", role(current.snapshot.elementType))
        }
        try require(NativeHomeReadiness.permitsNavigation(before, from: member == "sshChoice" ? "addChoice" : "emptyHome"),
                    "native_home_retry_unsafe")
        guard let (item, selection) = navigationElement(member) else { return ("missing", "uniqueLabel", "otherNative") }
        let geometry = try navigationGeometry(item)
        let allowed = geometry["ownerResolved"] as? Bool == true && geometry["centerVisible"] as? Bool == true &&
            geometry["enabled"] as? Bool == true && geometry["hittable"] as? Bool == true
        let started = ProcessInfo.processInfo.systemUptime
        if allowed { item.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap() }
        var after = try navigationState()
        if allowed {
            let deadline = Date().addingTimeInterval(6)
            repeat {
                after = try navigationState()
                if NativeViewPolicy.reached(member: member, page: after["page"] as! String) { break }
                Thread.sleep(forTimeInterval: 0.2)
            } while Date() < deadline
        }
        let page = after["page"] as! String
        let outcome = !allowed ? "blocked" : page == "sshForm" ? "sshForm" : page == "addChoice" ? "addChoice" :
            page == "emptyHome" ? "noProgress" : "unexpected"
        let presentAfter = item.exists
        let afterGeometry: Any = presentAfter ? try navigationGeometry(item) : NSNull()
        try post("native_navigation", ["nativeCheckpoint": nativePhase, "member": member, "selection": selection,
            "method": "elementCenter", "performed": allowed, "geometry": geometry,
            "targetPresentAfter": presentAfter, "afterGeometry": afterGeometry,
            "elapsedMs": min(60000, max(0, Int((ProcessInfo.processInfo.systemUptime - started) * 1000))),
            "before": before, "after": after, "outcome": outcome])
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
            let checkedAt = clock()
            sampleSeconds += checkedAt - sampledAt
            strictSamples += 1
            // The first snapshot may be slow and represent an earlier layout.
            // Give an unfinished app time to advance and take a fresh sample.
            if strictSamples == 1 { deadline = checkedAt + 35 }
            outcome = NativeHomeReadiness.classify(state, home: lastHomeSample!)
            if transitions.last?["state"] as? String != outcome.rawValue {
                transitions.append(["state": outcome.rawValue, "elapsedMs": milliseconds(checkedAt - start)])
            }
            guard outcome == .loading || outcome == .shell else { break }
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
        switch outcome {
        case .ready: return
        case .error: try require(false, "native_home_known_loading_error")
        case .alert: try require(false, "native_home_alert_present")
        case .notForeground: try require(false, "native_home_not_foreground")
        default: try require(false, "native_home_identity_unproven")
        }
    }

    @MainActor
    private func openHomeSSH() throws {
        try awaitEmptyHome()
        for member in ["headerAdd", "emptyAdd", "ordinaryShortcut"] {
            let (page, selection, originalRole) = try navigate(member)
            if page == "missing" { continue }
            if page == "sshForm" {
                try post("native_home_entry", ["nativeCheckpoint": nativePhase, "member": member, "selection": selection,
                    "role": originalRole, "enteredAddPage": false, "enteredSSHForm": true, "route": "directSSH"])
                return
            }
            if page == "addChoice" {
                try phase("open_ssh")
                let (form, _, _) = try navigate("sshChoice")
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
        try phase("launch")
        app.launch()
        try require(app.wait(for: .runningForeground, timeout: 30), "native_app_launch_failed")
        try phase("open_add")
        try openHomeSSH()
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
    private func submitConnection(_ attempt: NativeConnectPolicy.Attempt, waitingFor expected: String) throws {
        let submit = try reveal(button("连接 / 重新连接"), protectRouteTabs: true)
        try require(submit.live.snapshot.elementType == .button, "native_control_owner_unproven")
        try require(submit.live.snapshot.isEnabled, "native_control_disabled")
        let beforeRows = connectionRows(try observedNodes(), in: submit)
        let beforeSubmit = beforeRows.filter { sameIdentity($0.snapshot, submit.owner.snapshot) }
        try require(beforeSubmit.count == 1 && beforeSubmit.first?.path == submit.owner.path,
                    "native_control_owner_unproven")
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
            if rows.contains(where: { texts($0.snapshot).contains { $0.contains(expected) } }) { return }
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
    private func connect(password secret: String) throws {
        try phase("password")
        try fillPassword(password(), secret)
        try check(true, enabled: true)
        try phase("connect")
        let port = config[scenario == "ordinary" ? "ordinaryPort" : "rotationPort"] as! Int
        try submitConnection(scenario == "ordinary" ? .ordinary : .rotationApproved, waitingFor: target(port) + " · SSH 已连接")
        let rows = try observedNodes()
        let page = try exactObserved(rows, target(port) + " · SSH 已连接")
        try assertCredentialsInactive(page, rows)
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
        try phase("terminal_capture")
        if app.keyboards.firstMatch.exists { try tap(button("收起键盘")) }
        try waitForCaptureKeyboardToHide()
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
        try fillPassword(password(), config["rotationPassword"] as! String)
        try check(true, enabled: true)
        try phase("connect")
        try submitConnection(.rotationRefused, waitingFor: "主机指纹发生变化")
        try phase("review_capture")
        try screenshot("key_change_review", port: port, reviewPage: true)
        try phase("cancel")
        try tap(button("取消连接，保留旧信任"))
        try phase("cancel_check")
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
        try post("key_change_cancelled")
        try phase("reprobe")
        try tapForm("probe")
        try waitText(config["fingerprintB"] as! String)
        try require(try !contains(config["fingerprintA"] as! String), "native_reprobe_old_key_stale")
        try check(false, enabled: true)
        guard let reprobedPassword = liveControl(password()) else {
            try require(false, "native_reprobe_secret_stale")
            throw NSError(domain: "native_reprobe_secret_stale", code: 1)
        }
        try require(NativeControlPolicy.credentialEmpty(reprobedPassword.snapshot.value, placeholder: reprobedPassword.snapshot.placeholderValue), "native_reprobe_secret_stale")
        try post("key_change_probe_b")
        try phase("new_fingerprint")
        try approve(config["fingerprintB"] as! String, excluding: config["fingerprintA"] as? String)
        try post("key_change_password_b")
        try connect(password: config["rotationPassword"] as! String)
        try terminal("key_change", port: port)
        try post("complete")
    }
}
