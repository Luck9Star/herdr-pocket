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
            "打开键盘": "ssh-focus", "断开连接": "ssh-disconnect", "重新核对主机指纹": "ssh-key-recheck",
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
        func rounded(_ frame: CGRect?) -> Any {
            guard let frame = frame else { return NSNull() }
            let values = [frame.minX, frame.minY, frame.width, frame.height]
            guard values.allSatisfy({ $0.isFinite && abs($0) <= 10000 }), frame.width >= 0, frame.height >= 0 else {
                return NSNull()
            }
            return values.map { Int($0.rounded()) }
        }
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
    private func reveal(_ item: XCUIElement, matching expected: RevealedControl? = nil, scrolling: Bool = true) throws -> RevealedControl {
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
                guard failed || passwordDiagnostics else { return nil }
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
    private func assertReviewActions(_ page: Observed, _ rows: [Observed], _ labels: Set<String>) throws {
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
        try require(NativeViewPolicy.reviewValid(actions, expected: labels, visible: visible), "native_review_exits_invalid")
    }

    @MainActor
    private func target(_ port: Int) -> String { "fixture@127.0.0.1:\(port)" }
    @MainActor
    private func rect(_ value: CGRect) -> [Double] {
        [Double(value.minX), Double(value.minY), Double(value.width), Double(value.height)]
    }

    @MainActor
    private func nativeOcclusions() -> [CGRect] {
        let system = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        return NativeFramePolicy.unique((app.statusBars.allElementsBoundByIndex + system.statusBars.allElementsBoundByIndex +
            app.keyboards.allElementsBoundByIndex).compactMap { liveControl($0)?.snapshot.frame }.filter(NativeFramePolicy.valid))
    }

    @MainActor
    private func safeFrame(_ anchors: [Observed]) throws -> CGRect {
        guard let first = anchors.first, let window = first.window else {
            try require(false, "native_window_missing")
            throw NSError(domain: "native_window_missing", code: 1)
        }
        try require(!first.webs.isEmpty && first.webs.count <= 16, "native_webview_ambiguous")
        try require(NativeFramePolicy.sameOwner(windowPaths: anchors.map { $0.windowPath }, webPaths: anchors.map { $0.webPath }) &&
                    anchors.allSatisfy { $0.window == window },
                    "native_owner_ambiguous")
        var common = window
        for anchor in anchors {
            guard let visible = NativeFramePolicy.visible(window: window, screen: app.frame,
                    webAncestors: anchor.webs, occlusions: nativeOcclusions()) else {
                try require(false, "native_visible_frame_invalid")
                throw NSError(domain: "native_visible_frame_invalid", code: 1)
            }
            common = common.intersection(visible)
        }
        try require(NativeFramePolicy.valid(common), "native_visible_frame_invalid")
        return common
    }

    @MainActor
    private func exactObserved(_ rows: [Observed], _ text: String, identifiers: [String] = [], control: Bool = false) throws -> Observed {
        let matches = rows.filter { NativeFramePolicy.valid($0.snapshot.frame) &&
            (identifiers.contains($0.snapshot.identifier) || texts($0.snapshot).contains(text)) }
        let preferred = matches.indices.sorted {
            let left = control ? identifiers.contains(matches[$0].snapshot.identifier) : matches[$0].snapshot.elementType == .staticText
            let right = control ? identifiers.contains(matches[$1].snapshot.identifier) : matches[$1].snapshot.elementType == .staticText
            return left != right ? left : matches[$0].path.count > matches[$1].path.count
        }
        for candidate in preferred where matches[candidate].window != nil && !matches[candidate].webs.isEmpty {
            let owner = matches[candidate]
            let compatible = NativeFramePolicy.compatibleOwner(windowPaths: matches.map { $0.windowPath },
                webPaths: matches.map { $0.webPath }, nodePaths: matches.map { $0.path }, selected: candidate)
            try require(compatible, "native_owner_ambiguous")
            let visible = try safeFrame([owner])
            if let index = NativeFramePolicy.semanticIndex(frames: matches.map { $0.snapshot.frame }, preferred: [candidate],
                    visible: visible, clippedControl: control), index == candidate { return owner }
        }
        try require(false, "native_geometry_ambiguous")
        throw NSError(domain: "native_geometry_ambiguous", code: 1)
    }

    @MainActor
    private func screenshot(_ stage: String, port: Int, reviewPage: Bool = false) throws {
        let tree = try observedNodes()
        let rows = tree.map { $0.snapshot }
        try assertNoSecret(rows)
        let labels = reviewPage ? ["主机指纹发生变化", "已阻止连接与输入",
            "旧：" + (config["fingerprintA"] as! String), "新：" + (config["fingerprintB"] as! String),
            "目标：" + target(port), "重新核对主机指纹", "取消连接，保留旧信任"] :
            [target(port) + " · SSH 已连接", "SSH 终端输出"]
        func anchors(_ source: [Observed]) throws -> [Observed] {
            try labels.enumerated().map { index, label in
                try exactObserved(source, label, identifiers: !reviewPage && index == 1 ? ["ssh-terminal-output"] : [],
                                  control: !reviewPage && index == 1)
            }
        }
        let selected = try anchors(tree)
        let safe = try safeFrame(selected)
        let owner = selected[0]
        try assertCredentialsInactive(owner, tree)
        var extra: [String: Any] = ["safeFrame": rect(safe), "identityVerified": true, "noCredentialsVisible": true,
            "nativeOwner": ["windowFrame": rect(owner.window!), "webFrames": owner.webs.map(rect),
                            "webWrapperCount": owner.webs.count, "uniqueWebBoundsCount": NativeFramePolicy.unique(owner.webs).count]]
        let frames = selected.map { $0.snapshot.frame }
        if reviewPage {
            try require(frames.allSatisfy { safe.contains($0) && !$0.isEmpty }, "native_review_clipped")
            try assertReviewActions(owner, tree, Set(labels.suffix(2)))
            extra["reviewFrames"] = frames.map(rect)
        } else {
            try require(safe.contains(frames[0]) && !frames[0].isEmpty, "native_target_clipped")
            let crop = frames[1].intersection(safe)
            try require(NativeFramePolicy.valid(crop) && !crop.intersects(frames[0]), "native_terminal_frame_invalid")
            extra["terminalFrame"] = rect(crop); extra["targetFrame"] = rect(frames[0])
        }
        let screenFrame = app.frame
        try require(screenFrame.minX == 0 && screenFrame.minY == 0 && !screenFrame.isEmpty, "native_screen_frame_invalid")
        let shot = XCUIScreen.main.screenshot()
        let after = try anchors(observedNodes())
        try require(try safeFrame(after) == safe && app.frame == screenFrame && after.map { $0.snapshot.frame } == frames,
                    "native_capture_geometry_changed")
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
        let visible = rows.filter { !$0.frame.isEmpty && $0.frame.intersects(app.frame) }
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
    private func navigationState() throws -> [String: Any] {
        let tree = try observedNodes()
        let home = try homeDiagnostics(tree)
        lastHomeSample = home
        try post("native_home", ["nativeCheckpoint": nativePhase, "home": home])
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
            let host = field("主机地址")
            try post("native_navigation_arrival", ["nativeCheckpoint": nativePhase, "state": before,
                "geometry": try navigationGeometry(host), "source": "currentFormObservation", "performed": false])
            guard let current = liveControl(host) else { throw NSError(domain: "native_control_missing", code: 1) }
            return ("sshForm", "uniqueIdentifier", role(current.snapshot.elementType))
        }
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
    private func openHomeSSH() throws {
        let deadline = Date().addingTimeInterval(20)
        var initial = try navigationState()
        while initial["page"] as? String != "emptyHome" && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.2); initial = try navigationState()
        }
        try require(initial["page"] as? String == "emptyHome", "native_home_identity_unproven")
        for member in ["headerAdd", "emptyAdd", "ordinaryShortcut"] {
            let before = try navigationState()
            try require(before["page"] as? String == "emptyHome" && before["credentialsEmpty"] as? Bool == true,
                        "native_home_retry_unsafe")
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
    private func connect(password secret: String) throws {
        try phase("password")
        try fillPassword(password(), secret)
        try check(true, enabled: true)
        try phase("connect")
        try tap(button("连接 / 重新连接"))
        let port = config[scenario == "ordinary" ? "ordinaryPort" : "rotationPort"] as! Int
        try waitText(target(port) + " · SSH 已连接")
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
        let heading = app.descendants(matching: .any).matching(identifier: "ssh-target")
        let text = app.staticTexts[target(port) + " · SSH 已连接"]
        try require(heading.count == 1 || text.exists, "native_target_control_missing")
        try tap(heading.count == 1 ? heading.firstMatch : text)
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
        try fillPassword(password(), config["rotationPassword"] as! String)
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
