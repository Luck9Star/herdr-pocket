"""Pure Swift policy tests using macOS AX labels, not iOS device evidence."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "requires macOS Swift and Foundation")
class NativeControlPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = pathlib.Path(__file__).with_name("tauri_ios_direct_ssh.swift").read_text()
        cls.cache = tempfile.TemporaryDirectory(prefix="native-controls-modules-")

    @classmethod
    def tearDownClass(cls):
        cls.cache.cleanup()

    def compile_and_run(self, program):
        start = "enum NativeFramePolicy {"
        policy = self.source[self.source.index(start):self.source.index("// END NATIVE FRAME POLICY")]
        with tempfile.TemporaryDirectory(prefix="native-controls-") as temp:
            root = pathlib.Path(temp)
            (root / "Policy.swift").write_text("import Foundation\nimport CoreGraphics\n" + policy)
            (root / "main.swift").write_text(program)
            build = subprocess.run(["swiftc", "-swift-version", "5", "-module-cache-path", self.cache.name,
                                    str(root / "Policy.swift"), str(root / "main.swift"), "-o", str(root / "test")],
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(root / "test")], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def production_method(self, signature):
        start = self.source.index(signature)
        depth = 0
        for index in range(self.source.index("{", start), len(self.source)):
            depth += (self.source[index] == "{") - (self.source[index] == "}")
            if depth == 0:
                return self.source[start:index + 1]
        self.fail("unterminated production method: " + signature)

    def test_production_home_wait_separates_slow_initialization_from_unsafe_navigation(self):
        # Exercise the production launch methods with deterministic XCTest
        # observations and an injectable clock for the cold-start deadline.
        program = r'''
import Foundation
enum Clock { static var time: TimeInterval = 0 }
struct ProcessInfo {
    static let processInfo = Self()
    var systemUptime: TimeInterval { Clock.time }
}
enum Thread {
    static func sleep(forTimeInterval duration: TimeInterval) { Clock.time += duration }
}
struct Rejected: Error { let code: String }
final class Launch {
    var snapshots: [(NativeHomeReadiness.State, TimeInterval)]
    var wakes: [(Bool, TimeInterval)]
    var waits: [TimeInterval] = []
    var clicks: [String] = []
    var posts: [(String, [String: Any])] = []
    var sampled = 0
    init(_ snapshots: [(NativeHomeReadiness.State, TimeInterval)], wakes: [(Bool, TimeInterval)] = []) {
        self.snapshots = snapshots; self.wakes = wakes
    }
}
struct Query {
    let launch: Launch
    func matching(_ predicate: NSPredicate) -> Self {
        precondition(predicate.evaluate(with: ["label": "还没有主机"]))
        precondition(predicate.evaluate(with: ["label": "本机主机资料不可用，请检查设置"]))
        precondition(!predicate.evaluate(with: ["label": "正在读取主机资料…"]))
        return self
    }
    var firstMatch: Self { self }
    func waitForExistence(timeout: TimeInterval) -> Bool {
        precondition(timeout > 0 && timeout <= 4)
        launch.waits.append(timeout)
        let event = launch.wakes.isEmpty ? (false, timeout) : launch.wakes.removeFirst()
        Clock.time += event.1
        return event.0
    }
}
struct App { let staticTexts: Query }
final class Adapter {
    let launch: Launch
    var app: App { App(staticTexts: Query(launch: launch)) }
    var lastHomeSample: [String: Any]?
    var nativePhase = "ordinary_open_add"
    init(_ launch: Launch) { self.launch = launch }
    func navigationState(publish: Bool = true) throws -> [String: Any] {
        precondition(!publish, "cold-start polling must not make a network request per sample")
        launch.sampled += 1
        let (state, delay) = launch.snapshots.count == 1 ? launch.snapshots[0] : launch.snapshots.removeFirst()
        Clock.time += delay
        lastHomeSample = ["knownErrors": ["loading": state == .loading, "hostStorageError": state == .error],
                          "knownEmptyHome": state == .ready]
        return ["page": state == .ready ? "emptyHome" : state == .unexpected ? "addChoice" : "unexpected",
                "appForeground": state != .notForeground, "noAlerts": state != .alert,
                "noKnownErrors": state != .loading && state != .error, "credentialsEmpty": true,
                "windowCount": 1, "webViewCount": 3, "inputCount": 0]
    }
    func require(_ condition: Bool, _ code: String) throws {
        if !condition { throw Rejected(code: code) }
    }
    func post(_ name: String, _ value: [String: Any]) throws { launch.posts.append((name, value)) }
    func navigate(_ member: String) throws -> (String, String, String) {
        launch.clicks.append(member)
        return ("sshForm", "buttonRole", "button")
    }
    func phase(_ name: String) throws { nativePhase = "ordinary_" + name }
    func run() throws { try openHomeSSH() }
''' + "\n".join(self.production_method(signature) for signature in (
            "func awaitEmptyHome()", "func openHomeSSH()")) + r'''
}
func verify(_ launch: Launch, _ outcome: String, _ failure: String? = nil, states: [String]) -> [String: Any] {
    Clock.time = 0
    var caught: String?
    do { try Adapter(launch).run() } catch let rejection as Rejected { caught = rejection.code } catch { fatalError() }
    precondition(caught == failure)
    precondition(launch.clicks == (failure == nil ? ["headerAdd"] : []))
    precondition(launch.posts.map { $0.0 } == (failure == nil ? ["native_home", "native_home_entry"] : ["native_home"]))
    let trace = launch.posts[0].1["readiness"] as! [String: Any]
    precondition(trace["outcome"] as? String == outcome && trace["strictSamples"] as? Int == launch.sampled)
    precondition(trace["waitCalls"] as? Int == launch.waits.count)
    precondition((trace["samples"] as! [[String: Any]]).map { $0["state"] as! String } == states)
    return trace
}
let slow = Launch([(.loading, 42), (.ready, 0.25)], wakes: [(true, 2)])
let trace = verify(slow, "ready", states: ["loading", "ready"])
precondition(slow.sampled == 2 && trace["elapsedMs"] as? Int == 44250 && trace["strictSampleMs"] as? Int == 42250)
let neverReady = Launch([(.loading, 0)])
let timeout = verify(neverReady, "loading", "native_home_identity_unproven", states: ["loading"])
precondition(timeout["elapsedMs"] as? Int == 35000 && neverReady.sampled == 10 && neverReady.waits.count == 9)
let emptyShell = Launch([(.shell, 0)], wakes: [(true, 0)])
_ = verify(emptyShell, "shell", "native_home_identity_unproven", states: ["shell"])
precondition(emptyShell.waits.count == 1 && emptyShell.sampled == 11)
let lateError = Launch([(.loading, 0), (.error, 0)], wakes: [(true, 1)])
_ = verify(lateError, "error", "native_home_known_loading_error", states: ["loading", "error"])
precondition(lateError.waits.count == 1 && lateError.sampled == 2)
let alert = Launch([(.alert, 0)])
_ = verify(alert, "alert", "native_home_alert_present", states: ["alert"])
precondition(alert.waits.isEmpty && alert.sampled == 1)
let wrongPage = Launch([(.unexpected, 0)])
_ = verify(wrongPage, "unexpected", "native_home_identity_unproven", states: ["unexpected"])
precondition(wrongPage.waits.isEmpty)
let ready = try Adapter(Launch([(.ready, 0)])).navigationState(publish: false)
precondition(NativeHomeReadiness.permitsNavigation(ready, from: "emptyHome"))
for change: [String: Any] in [["appForeground": false], ["noAlerts": false], ["noKnownErrors": false],
                             ["credentialsEmpty": false], ["windowCount": 0], ["webViewCount": 0], ["page": "addChoice"]] {
    precondition(!NativeHomeReadiness.permitsNavigation(ready.merging(change) { _, current in current }, from: "emptyHome"))
}
'''
        self.compile_and_run(program)

    def test_production_adapter_roles_and_owner_boundaries(self):
        # Compile the real adapter bodies, using only snapshot/XCTest boundary
        # fixtures. The numeric roles deliberately differ from their names/order.
        program = r'''
import Foundation
import CoreGraphics
struct XCUIElement {
    enum ElementType: UInt {
        case textField = 91, textView = 17, searchField = 42, button = 6
        case stepper = 73, staticText = 12, other = 99, keyboard = 24, alert = 33
    }
}
struct Snapshot {
    let identifier: String
    let label: String
    let elementType: XCUIElement.ElementType
    let frame: CGRect
}
struct Observed {
    let snapshot: Snapshot
    let path: [Int]
    let windowPath: [Int]
    let webPath: [Int]
    let window: Int?
    let webs: [Int]
}
struct Adapter {
''' + self.production_method("func formTargets(_ tree:") + "\n" + self.production_method("func formSelection(_ tree:") + r'''
}
let adapter = Adapter()
func row(_ label: String, _ role: XCUIElement.ElementType, _ path: [Int],
         window: [Int] = [0], web: [Int] = [0, 0], eligible: Bool = true,
         frame: CGRect = CGRect(x: 10, y: 20, width: 100, height: 30)) -> Observed {
    Observed(snapshot: Snapshot(identifier: "", label: label, elementType: role, frame: frame),
             path: path, windowPath: window, webPath: web,
             window: eligible ? 1 : nil, webs: eligible ? [1] : [])
}
let labels = ["主机地址", "端口", "用户名", "探测主机指纹"]
let roles: [XCUIElement.ElementType] = [.textField, .textField, .textField, .button]
let fields = labels.indices.map { row(labels[$0], roles[$0], [0, 0, $0]) }
let projections: [XCUIElement.ElementType] = [.textField, .textView, .searchField, .button, .stepper, .staticText, .other]
precondition(adapter.formTargets(projections.map { row("", $0, [0, 0, 0]) }).map { $0.role } ==
             ["textField", "textView", "textField", "button", "stepper", "staticText", "other"],
             "the actual adapter must project roles, never numeric rawValue strings")
func accepted(_ tree: [Observed]) -> NativeControlPolicy.Selection { adapter.formSelection(tree) }
let normal = accepted(fields)
precondition(normal.ownerResolved)
for (index, name) in ["host", "port", "user", "probe"].enumerated() {
    precondition(normal.controls[name]?.index == index && normal.controls[name]?.reason == "matched" &&
                 normal.controls[name]?.owner == true)
}
let decorations = labels.indices.map { row(labels[$0], .staticText, [0, 0, $0 + 4]) }
precondition(accepted(decorations + fields).ownerResolved,
             "same-label static siblings must not obscure four real controls")
var numeric = fields
numeric[1] = row("端口", .stepper, [0, 0, 1])
numeric.append(row("", .textField, [0, 0, 1, 0]))
let wrapped = accepted(numeric)
precondition(wrapped.ownerResolved && wrapped.controls["port"]?.index == 4 && wrapped.controls["port"]?.role == "inputWrapper",
             "the actual stepper projection must select its single editable child")
precondition(!accepted(Array(numeric.prefix(4))).ownerResolved, "a stepper alone cannot replace the port input")
numeric.append(row("", .textField, [0, 0, 1, 1]))
precondition(!accepted(numeric).ownerResolved, "two editable children cannot authorize a numeric wrapper")
precondition(!accepted(Array(fields.prefix(3)) + [decorations[3]]).ownerResolved,
             "probe decoration alone must not authorize an action")
precondition(!accepted(fields + [fields[0]]).ownerResolved, "duplicate editable remains ambiguous")
precondition(!accepted(fields + [row("主机地址", .textField, [1, 0, 0], window: [1], web: [1, 0])]).ownerResolved,
             "the same editable identity in another window must remain ambiguous")
var changed = fields
changed[3] = row(labels[3], .button, [1, 0, 3], window: [1], web: [1, 0])
precondition(!accepted(changed).ownerResolved, "four controls cannot span windows")
let sideWindow = labels.indices.map { row(labels[$0], roles[$0], [1, 0, $0], window: [1], web: [1, 0]) }
let sideSelection = accepted(sideWindow + [row("主窗口内容", .staticText, [0, 0, 0])])
precondition(!sideSelection.ownerResolved && sideSelection.controls.values.allSatisfy { $0.owner },
             "four internally owned controls in another content window do not prove the foreground form")
let heading = row("普通 SSH 终端", .staticText, [1, 0, 4], window: [1], web: [1, 0])
let provenSideWindow = sideWindow + [row("主窗口内容", .staticText, [0, 0, 0]), heading]
precondition(accepted(provenSideWindow).ownerResolved,
             "a real SSH heading in the selected form owner permits an unrelated Web window")
let headingLeaf = row("普通 SSH 终端", .staticText, [1, 0, 4, 0], window: [1], web: [1, 0])
precondition(accepted(provenSideWindow + [headingLeaf]).ownerResolved,
             "a heading and its static leaf prove one owner rather than two ambiguous titles")
let choiceButton = row("普通 SSH 终端", .button, [1, 0, 4], window: [1], web: [1, 0])
precondition(!accepted(sideWindow + [row("主窗口内容", .staticText, [0, 0, 0]), choiceButton, headingLeaf]).ownerResolved,
             "an add-choice button's static label must not masquerade as the SSH page heading")
let misplacedHeading = row("普通 SSH 终端", .staticText, [0, 0, 4])
precondition(!accepted(sideWindow + [misplacedHeading]).ownerResolved,
             "an SSH heading in a different window cannot prove these four controls")
let siblingHeading = row("普通 SSH 终端", .staticText, [1, 1, 4], window: [1], web: [1, 1])
precondition(!accepted(sideWindow + [row("主窗口内容", .staticText, [0, 0, 0]), siblingHeading]).ownerResolved,
             "an SSH heading in a sibling WebView cannot prove the selected form owner")
precondition(!accepted(provenSideWindow + fields).ownerResolved,
             "a heading must never disambiguate duplicate editable identities across windows")
changed[3] = row(labels[3], .button, [0, 1, 3], web: [0, 1])
precondition(!accepted(changed).ownerResolved, "four controls cannot span sibling WebViews")
changed[3] = row(labels[3], .button, [1, 0, 3])
precondition(!accepted(changed).ownerResolved, "claimed ownership must contain the actual node path")
changed[3] = row(labels[3], .button, [0, 0, 3], eligible: false)
precondition(!accepted(changed).ownerResolved)
changed[3] = row(labels[3], .button, [0, 0, 3], frame: .zero)
precondition(accepted(changed).ownerResolved, "structural identity is independent of the later geometry guard")
for excluded in [XCUIElement.ElementType.keyboard, .alert] {
    let overlay = row("", excluded, [0, 0])
    precondition(!accepted(fields + [overlay]).ownerResolved,
                 "controls inside keyboard or alert trees cannot certify the SSH form")
    precondition(accepted(fields + [row("", excluded, [1])]).ownerResolved,
                 "an unrelated keyboard window does not change ownership of real form controls")
}
let reordered = accepted(Array(fields.reversed()))
precondition(reordered.ownerResolved && reordered.controls["host"]?.index == 3 && reordered.controls["probe"]?.index == 0,
             "diagnosis and a fresh action selection must use the same production adapter")
'''
        self.compile_and_run(program)

    def test_production_control_owner_ignores_layout_but_rejects_identity_ambiguity(self):
        # The real owner and tap adapters run against synthetic snapshots. This
        # models a keyboard-induced layout change, never a device observation.
        program = r'''
import Foundation
import CoreGraphics
final class XCUIElement {
    enum ElementType: UInt {
        case textField = 91, textView = 17, searchField = 42, button = 6
        case stepper = 73, staticText = 12, other = 99, keyboard = 24, alert = 33
        case window = 3, webView = 4, scrollView = 5, group = 13, checkBox = 14, `switch` = 15, toggle = 16, secureTextField = 87
    }
    var taps = 0
    var directTaps = 0
    var drags: [(CGVector, CGVector)] = []
    var inputs: [String] = []
    var inputValue: String?
    var forcedReadback: String?
    var exists = false
    func coordinate(withNormalizedOffset: CGVector) -> XCUICoordinate {
        XCUICoordinate(element: self, offset: withNormalizedOffset)
    }
    func tap() { taps += 1; directTaps += 1 }
    func waitForExistence(timeout: Double) -> Bool { true }
    func swipeDown() { }
    func swipeUp() { }
    func typeText(_ text: String) {
        inputs.append(text)
        inputValue = forcedReadback ?? text.replacingOccurrences(of: "\u{8}", with: "")
    }
}
enum XCUIKeyboardKey: String { case delete = "\u{8}" }
struct XCUICoordinate {
    let element: XCUIElement
    let offset: CGVector
    func tap() { element.taps += 1 }
    func press(forDuration: Double, thenDragTo: XCUICoordinate) { element.drags.append((offset, thenDragTo.offset)) }
}
protocol XCUIElementSnapshot {
    var identifier: String { get }
    var label: String { get }
    var elementType: XCUIElement.ElementType { get }
    var frame: CGRect { get }
    var isEnabled: Bool { get }
}
struct Snapshot: XCUIElementSnapshot {
    let identifier: String
    let label: String
    let elementType: XCUIElement.ElementType
    let frame: CGRect
    var isEnabled: Bool = true
    var value: String? = nil
    var placeholderValue: String? = nil
}
struct Observed {
    let snapshot: Snapshot
    let path: [Int]
    let windowPath: [Int]
    let webPath: [Int]
    let window: CGRect?
    let webs: [CGRect]
}
typealias Element = XCUIElement
struct LiveControl {
    let snapshot: Snapshot
    let hittable: Bool
    let element: Element
}
struct FormControl {
    let live: LiveControl
    let owner: Observed
    let window: Observed
    let web: Observed
    let identified: Bool
}
struct RevealedControl {
    let live: LiveControl
    let owner: Observed
    let window: Observed
    let web: Observed
}
struct Query {
    let allElementsBoundByIndex: [XCUIElement] = []
    var firstMatch: XCUIElement { XCUIElement() }
}
struct App {
    let frame: CGRect
    let input = Element()
    var webViews: Query { Query() }
    var keyboards: Query { Query() }
    func typeText(_ text: String) { input.typeText(text) }
}
struct ScreenShot { let pngRepresentation = Data([1]) }
final class XCUIScreen {
    static let main = XCUIScreen()
    var shots = 0
    func screenshot() -> ScreenShot {
        shots += 1
        return ScreenShot()
    }
}
struct Rejected: Error { let reason: String }
struct Date: Comparable {
    private static var clock: Double = 0
    private let instant: Double
    init() { Self.clock += 25; instant = Self.clock }
    private init(_ instant: Double) { self.instant = instant }
    func addingTimeInterval(_ seconds: Double) -> Self { Self(instant + seconds) }
    static func < (lhs: Self, rhs: Self) -> Bool { lhs.instant < rhs.instant }
}
final class Observations {
    var trees: [[Observed]]
    var liveSnapshots: [Snapshot]
    var occlusionSamples: [[CGRect]]
    var hittableSamples: [Bool]
    var liveReads = 0
    var resolved: [Observed] = []
    var checkpoints: [(String, [String: Any])] = []
    var reviewActionChecks = 0
    let webSurface = Element()
    init(_ trees: [[Observed]], liveSnapshots: [Snapshot] = [], occlusionSamples: [[CGRect]] = [],
         hittableSamples: [Bool] = []) {
        self.trees = trees
        self.liveSnapshots = liveSnapshots
        self.occlusionSamples = occlusionSamples
        self.hittableSamples = hittableSamples
    }
    func next(_ fallback: [Observed]) -> [Observed] {
        trees.isEmpty ? fallback : trees.removeFirst()
    }
    func live(_ fallback: LiveControl) -> LiveControl {
        liveReads += 1
        return LiveControl(snapshot: liveSnapshots.isEmpty ? fallback.snapshot : liveSnapshots.removeFirst(),
                           hittable: hittableSamples.isEmpty ? fallback.hittable : hittableSamples.removeFirst(),
                           element: fallback.element)
    }
}
struct Adapter {
    let app: App
    let current: LiveControl
    let rows: [Observed]
    let blockers: [CGRect]
    var observations: Observations? = nil
    var formControls: [String: LiveControl] = [:]
    var nativePhase = "ordinary_port"
    var pathControls: [[Int]: LiveControl] = [:]
    let config: [String: Any] = ["fingerprintA": "SHA256:fixture-complete-old", "fingerprintB": "SHA256:fixture-complete-new"]
    func require(_ condition: Bool, _ reason: String) throws {
        if !condition { throw Rejected(reason: reason) }
    }
    func nativeOcclusions() -> [CGRect] {
        guard let observations = observations, !observations.occlusionSamples.isEmpty else { return blockers }
        return observations.occlusionSamples.removeFirst()
    }
    func statusBarFrames() -> [CGRect] { blockers.filter { $0.minY == app.frame.minY } }
    func post(_ topic: String, _ payload: [String: Any]) throws { observations?.checkpoints.append((topic, payload)) }
    func role(_ type: XCUIElement.ElementType) -> String {
        if type == .secureTextField { return "secureTextField" }
        if type == .staticText { return "staticText" }
        return type == .textField ? "textField" : "other"
    }
    func texts(_ node: Snapshot) -> [String] { [node.label, node.value ?? ""] }
    func target(_ port: Int) -> String { "fixture-target" }
    func rect(_ value: CGRect) -> [Double] {
        [Double(value.minX), Double(value.minY), Double(value.width), Double(value.height)]
    }
    func assertNoSecret(_ rows: [Snapshot]) throws { }
    func assertCredentialsInactive(_ owner: Observed, _ rows: [Observed]) throws {
        try require(!rows.contains { $0.snapshot.elementType == .secureTextField && $0.snapshot.isEnabled },
                    "native_credentials_visible_after_connect")
    }
    func assertReviewActions(_ owner: Observed, _ rows: [Observed], _ labels: Set<String>, reviewSample: String) throws {
        observations?.reviewActionChecks += 1
        let actions = rows.filter { $0.snapshot.elementType == .button && $0.snapshot.isEnabled &&
            $0.windowPath == owner.windowPath && $0.webPath == owner.webPath }
        try require(actions.count == 2 && Set(actions.map { $0.snapshot.label }) == labels, "native_review_exits_invalid")
    }
    func observedNodes() throws -> [Observed] { observations?.next(rows) ?? rows }
    func resolveByPath(_ row: Observed) -> Observed {
        observations?.resolved.append(row)
        return row
    }
    func liveControl(_ row: Observed) -> LiveControl? {
        if let control = pathControls[row.path] { return control }
        if [.window, .webView].contains(row.snapshot.elementType) {
            let element = row.snapshot.elementType == .webView ? observations?.webSurface ?? Element() : Element()
            return LiveControl(snapshot: row.snapshot, hittable: true, element: element)
        }
        let fallback = formControls[row.snapshot.label] ?? current
        let live = observations?.live(fallback) ?? fallback
        guard let value = live.element.inputValue else { return live }
        let snapshot = Snapshot(identifier: live.snapshot.identifier, label: live.snapshot.label,
                                elementType: live.snapshot.elementType, frame: live.snapshot.frame,
                                isEnabled: live.snapshot.isEnabled, value: value)
        return LiveControl(snapshot: snapshot, hittable: live.hittable, element: live.element)
    }
    func liveControl(_ element: XCUIElement) -> LiveControl? { observations?.live(current) ?? current }
    func owner(_ snapshot: Snapshot, _ rows: [Observed]) -> Observed? {
        let scopes = rows.filter { $0.window != nil && !$0.webs.isEmpty }.flatMap { row in
            [Observed(snapshot: Snapshot(identifier: "", label: "", elementType: .window, frame: row.window!),
                      path: row.windowPath, windowPath: row.windowPath, webPath: [], window: row.window, webs: []),
             Observed(snapshot: Snapshot(identifier: "", label: "", elementType: .webView, frame: row.webs.last!),
                      path: row.webPath, windowPath: row.windowPath, webPath: row.webPath, window: row.window, webs: row.webs)]
        }
        return controlOwner(snapshot, rows + scopes)
    }
    func tapPort() throws { _ = try tapForm("port") }
    func port() throws -> LiveControl { try formControl("port").live }
    func revealCurrent() throws -> LiveControl { try reveal(current.element).live }
    func button(_ label: String) -> XCUIElement { current.element }
    func submit(_ attempt: NativeConnectPolicy.Attempt, expected: String) throws { try submitConnection(attempt, waitingFor: expected) }
    func fillCurrent(_ text: String) throws { try fillPassword(current.element, text) }
    func fillPort(_ text: String) throws { try fillForm("port", text) }
    func fillField(_ name: String, _ text: String) throws { try fillForm(name, text) }
    func tapProbe() throws { _ = try tapForm("probe") }
    func terminalScreenshot() throws { try screenshot("ordinary_terminal", port: 2222) }
    func reviewScreenshot() throws { try screenshot("key_change_review", port: 2222, reviewPage: true) }
    func scope(_ item: Snapshot, _ rows: [Observed], _ page: Observed) throws -> NativeViewPolicy.Scope {
        try pageScope(item, rows, page)
    }
''' + "\n".join(self.production_method(signature) for signature in (
            "func formTargets(_ tree:", "func formSelection(_ tree:", "func formControl(_ name:",
            "func sameIdentity(_ lhs:", "func liveOnPath(_ row:", "func controlScope(_ row:",
            "func scrollDirection(_ frames:", "func edgeScrollDirection(_ frames:",
            "func passwordGeometryDetail(_ viewport:", "func scrollToControl(_ owner:",
            "func controlIdentityRows(_ current:", "func controlOwner(_ current:",
            "func reveal(_ item:", "func tapForm(_ name:",
            "func controlGeometry(_ owner:", "func routeTabsOcclusion(_ owner:",
            "func reportFormGeometry(_ failure:", "func failControlGeometry(_ failure:",
            "func tap(_ item:", "func fillPassword(_ item:",
            "func safeFrame(_ anchors:", "func captureDiagnostic(_ anchor:", "func exactObserved(_ rows:",
            "struct CaptureAnchors {", "func terminalBoundaryControls(_ title:", "func verifyCaptureControls(_ selected:",
            "func waitForCaptureKeyboardToHide(reviewSample:", "func stableCaptureLayout(_ before:",
            "func terminalCaptureFrame(_ anchors:", "struct TerminalHeader {", "func terminalHeader(_ title:", "func screenshot(_ stage:",
            "func connectionRows(_ rows:", "func connectionStatus(_ rows:", "func submitConnection(_ attempt:",
            "func fillForm(_ name:", "func pageScope(_ item:")) + r'''
}
let screen = CGRect(x: 0, y: 0, width: 390, height: 844)
let oldFrame = CGRect(x: 24, y: 430, width: 342, height: 42)
let movedFrame = CGRect(x: 24, y: 260, width: 342, height: 42)
func snapshot(_ role: XCUIElement.ElementType = .textField, frame: CGRect = oldFrame,
              identifier: String = "", label: String = "端口") -> Snapshot {
    Snapshot(identifier: identifier, label: label, elementType: role, frame: frame)
}
func row(_ snapshot: Snapshot, path: [Int] = [0, 0, 1], window: [Int] = [0],
         web: [Int] = [0, 0], eligible: Bool = true) -> Observed {
    Observed(snapshot: snapshot, path: path, windowPath: window, webPath: web,
             window: eligible ? screen : nil, webs: eligible ? [screen] : [])
}
func formRows(_ port: Snapshot, portPath: [Int] = [0, 0, 1], host: Snapshot = snapshot(label: "主机地址"),
              user: Snapshot = snapshot(label: "用户名"), probe: Snapshot = snapshot(.button, label: "探测主机指纹")) -> [Observed] {
    [row(host, path: [0, 0, 0]), row(port, path: portPath), row(user, path: [0, 0, 2]), row(probe, path: [0, 0, 3]),
     row(snapshot(.window, frame: screen, label: ""), path: [0]),
     row(snapshot(.webView, frame: screen, label: ""), path: [0, 0])]
}
let element = Element()
let adapter = Adapter(app: App(frame: screen), current: LiveControl(snapshot: snapshot(), hittable: true, element: element),
                      rows: [row(snapshot())], blockers: [])
var failures: [String] = []
func check(_ condition: Bool, _ message: String) { if !condition { failures.append(message) } }
let moved = snapshot(frame: movedFrame)
check(adapter.owner(moved, [row(snapshot())])?.path == [0, 0, 1],
      "frame-only keyboard movement must preserve a unique typed owner")
let decoration = row(snapshot(.staticText), path: [1, 0, 1], window: [1], web: [1, 0])
check(adapter.owner(snapshot(), [row(snapshot()), decoration])?.path == [0, 0, 1],
      "same-label decoration in another window must not obscure the editable owner")
let button = row(snapshot(.button), path: [0, 0, 2])
check(adapter.owner(snapshot(), [row(snapshot()), button])?.path == [0, 0, 1],
      "same-label different-role sibling must not replace the editable owner")
let otherWindow = row(snapshot(frame: movedFrame), path: [1, 0, 1], window: [1], web: [1, 0])
check(adapter.owner(snapshot(), [row(snapshot()), otherWindow]) == nil,
      "same typed identity across windows stays ambiguous despite different frames")
let sibling = row(snapshot(frame: movedFrame), path: [0, 0, 2])
check(adapter.owner(snapshot(), [row(snapshot()), sibling]) == nil,
      "parallel same-window controls stay ambiguous despite different frames")
check(adapter.owner(snapshot(), [row(snapshot()), row(snapshot(), path: [0, 0, 2])]) == nil,
      "parallel same-window controls stay ambiguous even with equal frames")
let nested = row(snapshot(frame: movedFrame), path: [0, 0, 1, 0])
check(adapter.owner(snapshot(), [row(snapshot()), nested]) == nil,
      "different-frame typed identities stay ambiguous even along one branch")
check(adapter.owner(snapshot(), [row(snapshot()), row(snapshot(), path: [0, 0, 1, 0])])?.path == [0, 0, 1, 0],
      "equal-frame parent/leaf representations preserve their deepest owned node")
let identified = snapshot(identifier: "ssh-port")
let conflictingID = row(snapshot(.button, frame: movedFrame, identifier: "ssh-port"), path: [1, 0, 1], window: [1], web: [1, 0])
check(adapter.owner(identified, [row(identified), conflictingID]) == nil,
      "a duplicate identifier cannot be rescued by role or geometry filtering")
check(adapter.owner(identified, [row(snapshot(.button, identifier: "ssh-port"))]) == nil,
      "a unique identifier on the wrong role cannot authorize an editable control")
check(adapter.owner(snapshot(label: ""), [row(snapshot(label: ""))]) == nil,
      "an empty identity cannot authorize a control")
check(adapter.owner(snapshot(), [row(snapshot(), eligible: false)]) == nil,
      "a typed identity without WebView ownership cannot authorize a control")
func expectTap(_ frame: CGRect, treeFrame: CGRect? = nil, blockers: [CGRect],
               appFrame: CGRect = screen, windowFrame: CGRect = screen, webAncestors: [CGRect] = [screen],
               hittable: Bool = true, diagnostic: String? = nil, samples: Int = 1, reason: String) {
    let current = snapshot(frame: frame)
    let element = Element()
    let observations = Observations([])
    let rows = formRows(snapshot(frame: treeFrame ?? frame)).map {
        Observed(snapshot: $0.snapshot, path: $0.path, windowPath: $0.windowPath, webPath: $0.webPath,
                 window: windowFrame, webs: webAncestors)
    }
    let candidate = Adapter(app: App(frame: appFrame), current: LiveControl(snapshot: current, hittable: hittable, element: element),
                            rows: rows, blockers: blockers, observations: observations)
    var rejected = false
    do { try candidate.tapPort() } catch { rejected = true }
    let published = observations.checkpoints.filter { $0.0 == "native_progress" && $0.1["geometryReason"] != nil }
    check(element.taps == (diagnostic == nil ? 1 : 0) && rejected == (diagnostic != nil), reason)
    if let diagnostic = diagnostic {
        check(published.count == samples && published.allSatisfy {
            $0.1["geometryReason"] as? String == diagnostic &&
                $0.1["nativeCheckpoint"] as? String == "ordinary_port" &&
                Set($0.1.keys) == ["geometryReason", "nativeCheckpoint"]
        }, "expected bounded diagnostic \(diagnostic) for each of \(samples) failed attempts")
    } else {
        check(published.isEmpty, "successful interaction must not publish a geometry failure")
    }
}
expectTap(movedFrame, treeFrame: oldFrame, blockers: [],
          reason: "fresh unique geometry after keyboard movement permits the actual tap adapter")
let keyboard = CGRect(x: 0, y: 400, width: 390, height: 444)
let statusBar = CGRect(x: 0, y: 0, width: 390, height: 47)
let insetKeyboards: [CGRect] = [CGFloat(1), 34].map { gap in
    CGRect(x: keyboard.minX, y: keyboard.minY, width: keyboard.width, height: keyboard.height - gap)
}
expectTap(movedFrame, treeFrame: oldFrame, blockers: [keyboard], diagnostic: "field_occluded", samples: 10,
          reason: "a later tree moving the control behind the keyboard must invalidate an older visible live frame")
expectTap(oldFrame, treeFrame: movedFrame, blockers: [keyboard], diagnostic: "field_occluded", samples: 10,
          reason: "a later visible tree cannot authorize a tap until live geometry is refreshed")
expectTap(oldFrame, blockers: [keyboard], diagnostic: "field_occluded", samples: 10,
          reason: "a keyboard-covered control must never be tapped")
expectTap(CGRect(x: 24, y: 370, width: 342, height: 42), blockers: [keyboard], diagnostic: "field_occluded", samples: 10,
          reason: "a partly keyboard-covered control must never be tapped")
expectTap(CGRect(x: 24, y: -5, width: 342, height: 42), blockers: [], diagnostic: "field_outside", samples: 10,
          reason: "a partly offscreen control must never be tapped")
expectTap(movedFrame, blockers: [], hittable: false, diagnostic: "field_unhittable", samples: 10,
          reason: "a non-hittable control must never be tapped")
expectTap(.zero, blockers: [], diagnostic: "field_invalid",
          reason: "a structurally owned control with invalid geometry must never be tapped")
expectTap(movedFrame, blockers: [], appFrame: .zero, diagnostic: "screen_invalid",
          reason: "the form must reject an invalid screen")
expectTap(movedFrame, blockers: [], windowFrame: .zero, diagnostic: "window_invalid",
          reason: "the form must reject an invalid window")
expectTap(movedFrame, blockers: [statusBar] + insetKeyboards, webAncestors: [screen, .zero, screen],
          diagnostic: "web_ancestor_invalid", reason: "an invalid nested WebView frame must fail closed")
expectTap(movedFrame, blockers: [], webAncestors: [screen.offsetBy(dx: screen.width, dy: 0)],
          diagnostic: "viewport_empty", reason: "nonoverlapping ancestors do not produce a usable viewport")
expectTap(CGRect(x: 24, y: 40, width: 342, height: 42), blockers: [statusBar, insetKeyboards[0]],
          diagnostic: "field_occluded", samples: 10, reason: "even partial status bar occlusion makes the field unsafe")
let sideKeyboard = CGRect(x: 260, y: 250, width: 125, height: 420)
expectTap(CGRect(x: 24, y: 300, width: 220, height: 42), blockers: [statusBar, sideKeyboard],
          reason: "a keyboard alongside a field does not occlude it")
for insetKeyboard in insetKeyboards {
    expectTap(movedFrame, blockers: [statusBar, insetKeyboard],
              reason: "an interior keyboard must not block a wholly visible field above it")
    expectTap(CGRect(x: 24, y: 370, width: 342, height: 42), blockers: [statusBar, insetKeyboard],
              diagnostic: "field_occluded", samples: 10,
              reason: "actual partial overlap with an interior keyboard remains unsafe even with an uncovered center")
    expectTap(CGRect(x: 24, y: 358, width: 342, height: 42), blockers: [statusBar, insetKeyboard],
              reason: "touching a keyboard boundary without an overlap does not occlude the field")

    let host = snapshot(frame: movedFrame.offsetBy(dx: 0, dy: -100), label: "主机地址")
    let user = snapshot(frame: movedFrame.offsetBy(dx: 0, dy: 48), label: "用户名")
    let probe = snapshot(.button, frame: movedFrame.offsetBy(dx: 0, dy: 96), label: "探测主机指纹")
    let controls = Dictionary(uniqueKeysWithValues: [host, moved, user, probe].map { field in
        (field.label, LiveControl(snapshot: field, hittable: true, element: Element()))
    })
    let samples = Observations([], occlusionSamples: [[statusBar]])
    var candidate = Adapter(app: App(frame: screen), current: controls[host.label]!,
                            rows: formRows(moved, host: host, user: user, probe: probe),
                            blockers: [statusBar, insetKeyboard], observations: samples, formControls: controls)
    var succeeded = true
    do {
        candidate.nativePhase = "ordinary_host"
        try candidate.fillField("host", "127.0.0.1")
        candidate.nativePhase = "ordinary_port"
        try candidate.fillPort("2222")
        candidate.nativePhase = "ordinary_username"
        try candidate.fillField("user", "fixture")
        candidate.nativePhase = "ordinary_probe"
        try candidate.tapProbe()
    } catch { succeeded = false }
    check(succeeded && controls[host.label]?.element.inputs == ["127.0.0.1"] &&
          controls[moved.label]?.element.inputs == ["2222"] && controls[user.label]?.element.inputs == ["fixture"] &&
          controls[probe.label]?.element.taps == 1 && samples.checkpoints.allSatisfy { $0.1["geometryReason"] == nil },
          "host input and subsequent port, username and probe must proceed with an inset keyboard")

    let hiddenHost = snapshot(frame: oldFrame, label: host.label)
    let hiddenElement = Element()
    let blockedSamples = Observations([], occlusionSamples: [[statusBar]])
    let blocked = Adapter(app: App(frame: screen), current: LiveControl(snapshot: hiddenHost, hittable: true, element: hiddenElement),
                          rows: formRows(moved, host: hiddenHost), blockers: [statusBar, insetKeyboard],
                          observations: blockedSamples, nativePhase: "key_change_host")
    var rejected = false
    do { try blocked.fillField("host", "127.0.0.1") } catch { rejected = true }
    let diagnostics = blockedSamples.checkpoints.filter { $0.1["geometryReason"] != nil }
    check(rejected && hiddenElement.taps == 1 && hiddenElement.inputs.isEmpty && diagnostics.count == 3 &&
          diagnostics.allSatisfy { $0.1["nativeCheckpoint"] as? String == "key_change_host" &&
              $0.1["geometryReason"] as? String == "field_occluded" },
          "a keyboard covering the focused field must prevent typeText and publish each failed sample")

    let scrollElement = Element()
    let scroll = Observations([formRows(snapshot()), formRows(snapshot())], liveSnapshots: [snapshot(), moved])
    let scrolling = Adapter(app: App(frame: screen),
                            current: LiveControl(snapshot: moved, hittable: true, element: scrollElement),
                            rows: formRows(moved), blockers: [statusBar, insetKeyboard], observations: scroll)
    var scrolled = true
    do { try scrolling.tapPort() } catch { scrolled = false }
    let drag = scroll.webSurface.drags.first
    check(scrolled && scrollElement.taps == 1 && scroll.webSurface.drags.count == 1 &&
          drag.map { from, to in
            from.dx == 0.5 && to.dx == 0.5 && statusBar.maxY < to.dy * screen.height &&
                to.dy < from.dy && from.dy * screen.height < insetKeyboard.minY
          } == true, "the actual scroll path must keep the entire drag between the status bar and keyboard")
}
func expectReselection(_ live: Snapshot, allowed: Bool, reason: String) {
    let observed = Observations([formRows(snapshot()), formRows(moved, portPath: [0, 0, 4])])
    let candidate = Adapter(app: App(frame: screen), current: LiveControl(snapshot: live, hittable: true, element: Element()),
                            rows: formRows(moved, portPath: [0, 0, 4]), blockers: [], observations: observed)
    var accepted = false
    do { _ = try candidate.port(); accepted = true } catch { }
    check(accepted == allowed, reason)
    if allowed {
        check(observed.resolved.last?.path == [0, 0, 4],
              "the actual form adapter must resolve the newly selected path after layout changes")
    }
}
expectReselection(moved, allowed: true,
                  reason: "fresh structural selection accepts a uniquely reselected port after frame and path changes")
expectReselection(snapshot(.button, frame: movedFrame), allowed: false,
                  reason: "a final live role change after path resolution must not return a form control")
expectReselection(snapshot(frame: movedFrame, identifier: "changed"), allowed: false,
                  reason: "a final live identifier change after path resolution must not return a form control")
expectReselection(snapshot(frame: movedFrame, label: "用户名"), allowed: false,
                  reason: "a final live label change after path resolution must not return a form control")
let raceElement = Element()
let raceTrees = [formRows(moved)] + Array(repeating: formRows(snapshot()), count: 19)
let race = Adapter(app: App(frame: screen), current: LiveControl(snapshot: moved, hittable: true, element: raceElement),
                   rows: formRows(snapshot()), blockers: [keyboard], observations: Observations(raceTrees))
do { try race.tapPort() } catch { }
check(raceElement.taps == 0,
      "the actual tap entry must reject a final tree moving the previously visible port behind the keyboard")
let refreshedElement = Element()
let refreshed = Observations([], liveSnapshots: [snapshot(), moved, moved, moved])
let refreshing = Adapter(app: App(frame: screen),
                         current: LiveControl(snapshot: moved, hittable: true, element: refreshedElement),
                         rows: formRows(moved), blockers: [keyboard], observations: refreshed)
var refreshedSucceeded = true
do { try refreshing.tapPort() } catch { refreshedSucceeded = false }
check(refreshedSucceeded && refreshedElement.taps == 1 && refreshed.liveReads >= 2,
      "the actual tap path must reacquire the unique port's latest visible live geometry before clicking")
check(refreshed.checkpoints.compactMap { $0.1["geometryReason"] as? String } == ["field_occluded"],
      "one rejected tap sample must be published even when a later sample allows tapping")
let revealSnapshots = Observations([], liveSnapshots: [snapshot(), moved, moved, moved])
let revealing = Adapter(app: App(frame: screen),
                        current: LiveControl(snapshot: moved, hittable: true, element: Element()),
                        rows: formRows(moved), blockers: [keyboard], observations: revealSnapshots)
var revealed: LiveControl?
do { revealed = try revealing.revealCurrent() } catch { }
check(revealed?.snapshot.frame == movedFrame && revealSnapshots.liveReads >= 4,
      "the actual generic reveal path must refresh both its queried and path-bound live geometry")
func expectReveal(tree: CGRect = movedFrame, queried: CGRect = movedFrame, bound: CGRect = movedFrame,
                  queriedHittable: Bool = true, boundHittable: Bool = true, blockers: [CGRect],
                  error: String? = nil, reason: String) {
    func connect(_ frame: CGRect) -> Snapshot { snapshot(.button, frame: frame, label: "连接") }
    let samples = Observations([], liveSnapshots: Array(repeating: [connect(queried), connect(bound)], count: 10).flatMap { $0 },
                               hittableSamples: Array(repeating: [queriedHittable, boundHittable], count: 10).flatMap { $0 })
    let control = LiveControl(snapshot: connect(queried), hittable: queriedHittable, element: Element())
    let candidate = Adapter(app: App(frame: screen), current: control, rows: formRows(connect(tree)),
                            blockers: blockers, observations: samples, nativePhase: "ordinary_connect")
    do {
        let revealed = try candidate.revealCurrent()
        check(error == nil && revealed.snapshot.frame == bound, reason)
    } catch let failure as Rejected {
        check(failure.reason == error, reason)
    } catch { check(false, reason) }
    check(samples.checkpoints.isEmpty, "the generic reveal path must not publish form geometry samples")
}
for insetKeyboard in insetKeyboards {
    let blockers = [statusBar, insetKeyboard]
    expectReveal(blockers: blockers, reason: "an uncovered generic control must resolve while an interior keyboard is visible")
    check(NativeFramePolicy.visible(window: screen, screen: screen, webAncestors: [screen], occlusions: blockers) == nil,
          "the frame used to bound captures must still reject an interior occlusion")
    let partial = CGRect(x: 24, y: 370, width: 342, height: 42)
    expectReveal(tree: partial, blockers: blockers, error: "native_control_not_visible",
                 reason: "the tree frame must not be partly occluded")
    expectReveal(queried: partial, blockers: blockers, error: "native_control_not_visible",
                 reason: "the queried live frame must not be partly occluded")
    expectReveal(bound: partial, blockers: blockers, error: "native_control_not_visible",
                 reason: "the path-bound live frame must not be partly occluded")
    expectReveal(bound: .zero, blockers: blockers, error: "native_visible_frame_invalid",
                 reason: "invalid live geometry keeps the generic frame error")
    expectReveal(queriedHittable: false, blockers: blockers, error: "native_control_not_visible",
                 reason: "a hittable bound control does not authorize an unhittable queried match")
    expectReveal(boundHittable: false, blockers: blockers, error: "native_control_not_visible",
                 reason: "a hittable queried match does not authorize an unhittable bound control")
}

let passwordScreen = CGRect(x: 0, y: 0, width: 440, height: 956)
let routeFrame = CGRect(x: 0, y: 891, width: 440, height: 65)
let passwordBehindTabs = snapshot(.secureTextField, frame: CGRect(x: 16, y: 890, width: 408, height: 46),
                                 identifier: "ssh-password", label: "密码")
let revealedPassword = snapshot(.secureTextField, frame: passwordBehindTabs.frame.offsetBy(dx: 0, dy: -188),
                                identifier: "ssh-password", label: "密码")
let passwordStatusBar = CGRect(x: 0, y: 0, width: 440, height: 62)
func passwordRow(_ item: Snapshot, _ path: [Int], web: [Int] = [0, 0]) -> Observed {
    Observed(snapshot: item, path: path, windowPath: [0], webPath: web,
             window: passwordScreen, webs: [passwordScreen])
}
let passwordWindow = passwordRow(snapshot(.window, frame: passwordScreen, label: ""), [0])
let passwordWeb = passwordRow(snapshot(.webView, frame: passwordScreen, label: ""), [0, 0])
let formScroller = passwordRow(snapshot(.scrollView, frame: CGRect(x: 12, y: 100, width: 416, height: 748), label: ""), [0, 0, 2])
let otherScroller = passwordRow(snapshot(.scrollView, frame: passwordScreen, label: ""), [0, 0, 3])
let tabDefinitions = [("show-remote", "看板"), ("nav-terminal", "终端"), ("nav-network", "网络"), ("nav-settings", "设置")]
let routeButtons = tabDefinitions.enumerated().map { index, definition in
    let frame = CGRect(x: CGFloat(8 + index * 108), y: 896, width: 100, height: 60)
    let role: XCUIElement.ElementType = [.checkBox, .switch, .toggle, .button][index]
    return passwordRow(snapshot(role, frame: frame, label: definition.1), [0, 0, 8, index])
}
let routeLandmark = passwordRow(snapshot(.group, frame: routeFrame, label: "主导航"), [0, 0, 8])
let connectedText = "fixture-target · SSH 已连接"
let submitBehindTabs = snapshot(.button, frame: CGRect(x: 16, y: 878, width: 132, height: 46), label: "连接 / 重新连接")
let visibleSubmit = snapshot(.button, frame: submitBehindTabs.frame.offsetBy(dx: 0, dy: -184), label: "连接 / 重新连接")
func submitRows(_ submit: Snapshot, status: String, includeUnownedTarget: Bool = false) -> [Observed] {
    var rows = [passwordWindow, passwordWeb, routeLandmark, passwordRow(submit, [0, 0, 1]),
        passwordRow(snapshot(.other, frame: movedFrame, identifier: "ssh-status", label: ""), [0, 0, 12]),
        passwordRow(snapshot(.staticText, frame: movedFrame, label: status), [0, 0, 12, 0])]
    if includeUnownedTarget {
        rows.append(passwordRow(snapshot(.staticText, frame: movedFrame, label: connectedText), [0, 1, 4], web: [0, 1]))
    }
    return rows
}
let coveredSubmit = submitRows(submitBehindTabs, status: "尚未连接。")
let readySubmit = submitRows(visibleSubmit, status: "尚未连接。")
let connectedSubmit = readySubmit + [passwordRow(snapshot(.staticText, frame: movedFrame, label: connectedText), [0, 0, 13])]
let submitElement = Element()
let submitMotion = Observations([coveredSubmit, readySubmit, readySubmit, connectedSubmit],
                                liveSnapshots: [submitBehindTabs, submitBehindTabs, visibleSubmit, visibleSubmit])
let submitAdapter = Adapter(app: App(frame: passwordScreen),
    current: LiveControl(snapshot: visibleSubmit, hittable: true, element: submitElement), rows: connectedSubmit,
    blockers: [passwordStatusBar], observations: submitMotion, nativePhase: "key_change_connect",
    pathControls: [routeLandmark.path: LiveControl(snapshot: routeLandmark.snapshot, hittable: true, element: Element())])
var submitError: String?
do { try submitAdapter.submit(.rotationApproved, expected: connectedText) }
catch let rejected as Rejected { submitError = rejected.reason }
catch { submitError = "unexpected" }
check(submitError == nil && submitMotion.webSurface.drags.count == 1 && submitElement.taps == 1 &&
      submitElement.directTaps == 1 && submitMotion.checkpoints.isEmpty,
      "a hittable submit whose center is under the route tabs must scroll clear before one native hit-point tap")

let triggeredStatus = submitRows(visibleSubmit, status: "请先核对指纹并选择一种认证方式。", includeUnownedTarget: true)
let rejectedSubmit = Observations([readySubmit, readySubmit], liveSnapshots: [visibleSubmit, visibleSubmit])
let singleTap = Element()
let rejectedAdapter = Adapter(app: App(frame: passwordScreen),
    current: LiveControl(snapshot: visibleSubmit, hittable: true, element: singleTap), rows: triggeredStatus,
    blockers: [passwordStatusBar], observations: rejectedSubmit, nativePhase: "key_change_connect",
    pathControls: [routeLandmark.path: LiveControl(snapshot: routeLandmark.snapshot, hittable: true, element: Element())])
var terminalAbsent: String?
do { try rejectedAdapter.submit(.rotationApproved, expected: connectedText) }
catch let rejected as Rejected { terminalAbsent = rejected.reason }
catch { terminalAbsent = "unexpected" }
let diagnostic = rejectedSubmit.checkpoints.first?.1["detail"] as? [String: Any]
let beforeSubmit = diagnostic?["before"] as? [String: Any]
let afterSubmit = diagnostic?["after"] as? [String: Any]
check(terminalAbsent == "native_expected_text_missing" && singleTap.taps == 1 && singleTap.directTaps == 1 &&
      rejectedSubmit.checkpoints.count == 1 && rejectedSubmit.checkpoints.first?.0 == "native_connect_diagnostic" &&
      diagnostic?["attempt"] as? String == "rotation_approved" && diagnostic?["statuses"] as? [String] == ["idle", "review_required"] &&
      beforeSubmit?["status"] as? String == "idle" && afterSubmit?["status"] as? String == "review_required" &&
      afterSubmit?["submitFrame"] as? [Int] == [16, 694, 132, 46] && singleTap.inputs.isEmpty,
      "failed connection reports sanitized read-only state from its own web owner without replaying the submit")
let reboundRows = readySubmit.filter { $0.path != [0, 0, 1] } + [passwordRow(visibleSubmit, [0, 0, 4])]
let reboundSubmit = Observations([readySubmit, reboundRows], liveSnapshots: [visibleSubmit, visibleSubmit])
let reboundElement = Element()
let reboundAdapter = Adapter(app: App(frame: passwordScreen),
    current: LiveControl(snapshot: visibleSubmit, hittable: true, element: reboundElement), rows: reboundRows,
    blockers: [passwordStatusBar], observations: reboundSubmit, nativePhase: "key_change_connect")
var movedSubmitError: String?
do { try reboundAdapter.submit(.rotationApproved, expected: connectedText) }
catch let rejected as Rejected { movedSubmitError = rejected.reason }
catch { movedSubmitError = "unexpected" }
check(movedSubmitError == "native_control_owner_unproven" && reboundElement.taps == 0,
      "a different submit path before the tap must fail closed")

func exercisePassword(webHittable: Bool, provenScroller: Bool, showLandmark: Bool = true, showTabs: Bool = true,
                      initialHits: (Bool, Bool) = (false, false), initialFrame: CGRect = passwordBehindTabs.frame,
                      initialEnabled: Bool = true, phase: String, expected: [String], succeeds: Bool,
                      dragged: Bool = false, direction: String = "none", failureCode: String = "native_control_not_visible") {
    let typed = "fixture-input"
    let element = Element()
    let webElement = Element()
    let scrollElement = Element()
    let unrelatedElement = Element()
    var scopes = [passwordWindow, passwordWeb, otherScroller]
    if showLandmark { scopes.append(routeLandmark) }
    if showTabs { scopes += routeButtons }
    if provenScroller { scopes.append(formScroller) }
    let controls = Dictionary(uniqueKeysWithValues: (routeButtons + [routeLandmark]).map {
        ($0.path, LiveControl(snapshot: $0.snapshot, hittable: true, element: Element()))
    }).merging([
        passwordWeb.path: LiveControl(snapshot: passwordWeb.snapshot, hittable: webHittable, element: webElement),
        formScroller.path: LiveControl(snapshot: formScroller.snapshot, hittable: true, element: scrollElement),
        otherScroller.path: LiveControl(snapshot: otherScroller.snapshot, hittable: true, element: unrelatedElement),
    ]) { _, new in new }
    var initial = snapshot(.secureTextField, frame: initialFrame, identifier: "ssh-password", label: "密码")
    initial.isEnabled = initialEnabled
    let hidden = scopes + [passwordRow(initial, [0, 0, 2, 1])]
    let visible = scopes + [passwordRow(revealedPassword, [0, 0, 2, 1])]
    let samples = succeeds ? Observations([hidden], liveSnapshots: [initial, initial, revealedPassword, revealedPassword],
                                          hittableSamples: [initialHits.0, initialHits.1, true, true]) :
        Observations([], hittableSamples: Array(repeating: [initialHits.0, initialHits.1], count: 10).flatMap { $0 })
    let fallback = LiveControl(snapshot: succeeds ? revealedPassword : initial,
                               hittable: succeeds, element: element)
    let app = App(frame: passwordScreen)
    let candidate = Adapter(app: app, current: fallback, rows: succeeds ? visible : hidden,
                            blockers: [passwordStatusBar], observations: samples, nativePhase: phase, pathControls: controls)
    var error: String?
    do { try candidate.fillCurrent(typed) } catch let rejected as Rejected { error = rejected.reason } catch { }
    let diagnostics = samples.checkpoints.compactMap { $0.1["geometryReason"] as? String }
    let roles = samples.checkpoints.compactMap { $0.1["nativeInputRole"] as? String }
    let details = samples.checkpoints.compactMap { $0.1["geometryDetail"] as? [String: Any] }
    check(diagnostics == expected && samples.checkpoints.allSatisfy { topic, payload in
        topic == "native_progress" && payload["nativeCheckpoint"] as? String == phase &&
            (Set(payload.keys) == ["nativeCheckpoint", "geometryReason"] || Set(payload.keys) == ["nativeCheckpoint", "nativeInputRole"] ||
             Set(payload.keys) == ["nativeCheckpoint", "geometryReason", "geometryDetail"])
    }, "password progress must include only phase and bounded geometry or role data")
    let target = webHittable ? webElement : scrollElement
    let targetFrame = webHittable ? passwordScreen : formScroller.snapshot.frame
    let didDrag = succeeds || dragged
    check(target.drags.count == (didDrag ? 1 : 0), "a password focus operation must never repeat the same drag without progress")
    if didDrag {
        check(target.drags.first.map { from, to in
            let start = targetFrame.minY + from.dy * targetFrame.height
            let end = targetFrame.minY + to.dy * targetFrame.height
            let down = direction == "swipe_down"
            return passwordStatusBar.maxY < min(start, end) && max(start, end) < routeFrame.minY && (down ? end > start : end < start)
        } == true, "the drag must move the field toward the center and keep both endpoints in the safe band")
    }
    if succeeds {
        check(error == nil && element.inputs == [typed] && app.input.inputs.isEmpty && samples.liveReads == 6 &&
              element.taps == 1 && roles == ["secureTextField"] && details.isEmpty,
              "after scrolling, the bound password field receives one input with no app-wide typing or secret readback")
    } else {
        check(error == failureCode && roles.isEmpty && app.input.inputs.isEmpty && element.inputs.isEmpty && element.taps == 0,
              "unproven password geometry or a missing scroll target must never tap or type")
        let expectedRect = [initialFrame.minX, initialFrame.minY, initialFrame.width, initialFrame.height].map { Int($0.rounded()) }
        check(details.count == 1 && details.first.map { detail in
            Set(detail.keys) == ["viewport", "usable", "owner", "query", "bound", "queryEnabled", "boundEnabled",
                                 "queryHittable", "boundHittable", "scrollAttempted", "scrollDirection"] &&
                detail["viewport"] as? [Int] == [0, 0, 440, 956] &&
                detail["usable"] as? [Int] == [0, 62, 440, (showLandmark ? 891 : showTabs ? 896 : 956) - 62] &&
                detail["owner"] as? [Int] == expectedRect && detail["query"] as? [Int] == expectedRect &&
                detail["bound"] as? [Int] == expectedRect && detail["queryEnabled"] as? Bool == initialEnabled &&
                detail["boundEnabled"] as? Bool == initialEnabled && detail["queryHittable"] as? Bool == initialHits.0 &&
                detail["boundHittable"] as? Bool == initialHits.1 && detail["scrollAttempted"] as? Bool == dragged &&
                detail["scrollDirection"] as? String == direction
        } == true, "only the final failure shows bounded layout, both hit states and the attempted scroll direction")
    }
    check(unrelatedElement.drags.isEmpty, "a visible sibling ScrollView must never authorize the password drag")
}
exercisePassword(webHittable: true, provenScroller: false, phase: "ordinary_password", expected: ["field_occluded"], succeeds: true)
exercisePassword(webHittable: true, provenScroller: false, showTabs: false, initialHits: (true, true),
                 phase: "ordinary_password", expected: ["field_occluded"], succeeds: true)
exercisePassword(webHittable: true, provenScroller: false, showLandmark: false,
                 phase: "ordinary_password", expected: ["field_occluded"], succeeds: true)
exercisePassword(webHittable: false, provenScroller: true, phase: "ordinary_password", expected: ["field_occluded"], succeeds: true)
exercisePassword(webHittable: false, provenScroller: false, phase: "key_change_password",
                 expected: ["field_occluded", "scroll_surface_unhittable"], succeeds: false, direction: "swipe_up")
exercisePassword(webHittable: true, provenScroller: false, showLandmark: false, showTabs: false, phase: "ordinary_password",
                 expected: ["field_unhittable"], succeeds: true)
exercisePassword(webHittable: true, provenScroller: false, showLandmark: false, showTabs: false, initialHits: (false, true),
                 phase: "key_change_password", expected: ["queried_unhittable", "queried_unhittable", "scroll_no_progress"],
                 succeeds: false, dragged: true, direction: "swipe_up")
exercisePassword(webHittable: true, provenScroller: false, showLandmark: false, showTabs: false, initialHits: (true, false),
                 initialFrame: revealedPassword.frame, phase: "ordinary_password", expected: Array(repeating: "bound_unhittable", count: 3),
                 succeeds: false)
exercisePassword(webHittable: true, provenScroller: false, showLandmark: false, showTabs: false, initialEnabled: false,
                 phase: "ordinary_password", expected: ["field_unhittable"], succeeds: false, direction: "swipe_up",
                 failureCode: "native_control_disabled")
exercisePassword(webHittable: true, provenScroller: false, showLandmark: false, showTabs: false,
                 initialFrame: CGRect(x: 16, y: 65, width: 408, height: 46), phase: "ordinary_password",
                 expected: ["field_unhittable"], succeeds: true, direction: "swipe_down")
let changedPassword = snapshot(.secureTextField, frame: revealedPassword.frame, identifier: "ssh-replacement", label: "密码")
let focused = Observations([[passwordWindow, passwordWeb, passwordRow(revealedPassword, [0, 0, 1])]],
                           liveSnapshots: [revealedPassword, revealedPassword, changedPassword, changedPassword])
let changedElement = Element()
let changedApp = App(frame: passwordScreen)
let replaced = Adapter(app: changedApp,
                       current: LiveControl(snapshot: changedPassword, hittable: true, element: changedElement),
                       rows: [passwordWindow, passwordWeb, passwordRow(changedPassword, [0, 0, 1])],
                       blockers: [passwordStatusBar], observations: focused, nativePhase: "key_change_password")
var replacementError: String?
do { try replaced.fillCurrent("fixture-input") } catch let rejected as Rejected { replacementError = rejected.reason } catch { }
check(replacementError == "native_control_owner_unproven" && changedElement.taps == 1 && changedElement.inputs.isEmpty &&
      changedApp.input.inputs.isEmpty, "a secure field replaced after focus must never receive the password")

let terminalTitle = "fixture-target · SSH 已连接"
let terminalLabel = "SSH 终端输出"
let titleFrame = CGRect(x: 20, y: 220, width: 250, height: 30)
let outputFrame = CGRect(x: 20, y: 280, width: 350, height: 400)
func terminalRows(_ title: CGRect = titleFrame, _ output: CGRect = outputFrame, outputRole: XCUIElement.ElementType = .group) -> [Observed] {
    [row(snapshot(.window, frame: screen, label: ""), path: [0]),
     row(snapshot(.webView, frame: screen, label: ""), path: [0, 0]),
     row(snapshot(.staticText, frame: title, label: terminalTitle), path: [0, 0, 1]),
     row(snapshot(outputRole, frame: output, identifier: "ssh-terminal-output", label: terminalLabel), path: [0, 0, 2])]
}
func terminalControlRows(offset: CGFloat = 0, helperOffset: CGFloat = 0) -> [Observed] {
    let title = titleFrame.offsetBy(dx: 0, dy: offset)
    let dismiss = snapshot(.button, frame: CGRect(x: 20, y: 260 + offset, width: 82, height: 44),
                           identifier: "ssh-hide-keyboard", label: "收起键盘")
    let helpers = ["Esc", "Tab", "上方向键", "↓"].enumerated().map { index, label in
        let frame = CGRect(x: 20 + CGFloat(index) * 48, y: 710 + offset + (index == 3 ? helperOffset : 0), width: 44, height: 44)
        return row(snapshot(.button, frame: frame, label: label), path: [0, 0, 4, index])
    }
    return Array(terminalRows(title).dropLast()) + [row(dismiss, path: [0, 0, 3])] + helpers
}
func terminalHeaderRows(_ brandY: CGFloat, headingY: CGFloat, addWeb: [Int] = [0, 0],
                        bannerBottom: CGFloat?, headingLabel: String) -> [Observed] {
    let brandFrame = CGRect(x: 20, y: brandY, width: 130, height: 24)
    let brand = snapshot(.staticText, frame: brandFrame, label: "Herdr Pocket")
    let brandWrapper = snapshot(.other, frame: brandFrame, label: "Herdr Pocket")
    let add = snapshot(.button, frame: CGRect(x: 282, y: 72, width: 88, height: 44),
                       identifier: "host-open-remote", label: "＋ 添加主机")
    let heading = snapshot(.staticText, frame: CGRect(x: 20, y: headingY, width: 190, height: 27),
                           identifier: "ssh-page-heading", label: headingLabel)
    let otherWeb = addWeb == [0, 0] ? [] : [row(snapshot(.webView, frame: screen, label: ""), path: addWeb, web: addWeb)]
    if let bottom = bannerBottom, addWeb == [0, 0] {
        let banner = snapshot(.group, frame: CGRect(x: 0, y: 0, width: screen.width, height: bottom), label: "")
        return [row(banner, path: [0, 0, 9]), row(brandWrapper, path: [0, 0, 9, 0]), row(brand, path: [0, 0, 9, 0, 0]),
                row(add, path: [0, 0, 9, 1]), row(heading, path: [0, 0, 11])]
    }
    return [row(brandWrapper, path: [0, 0, 9]), row(brand, path: [0, 0, 9, 0]),
            row(add, path: addWeb + [10], web: addWeb), row(heading, path: [0, 0, 11])] + otherWeb
}
func exerciseCapture(_ distinctSamples: [[Observed]], _ rows: [Observed] = terminalRows(),
                     error: String? = nil, hittable: Bool = true, headerY: CGFloat = 80,
                     afterHeaderY: CGFloat? = nil, addWeb: [Int] = [0, 0], headingY: CGFloat = 150,
                     afterHeadingY: CGFloat? = nil, bannerBottom: CGFloat? = nil, headingLabel: String = "普通 SSH 终端",
                     message: String, validate: (Observations) -> Void) {
    let tree = rows + terminalHeaderRows(headerY, headingY: headingY, addWeb: addWeb, bannerBottom: bannerBottom, headingLabel: headingLabel)
    let samples = distinctSamples.enumerated().map { index, sample in
        let final = index == distinctSamples.count - 1
        return sample + terminalHeaderRows(final ? afterHeaderY ?? headerY : headerY,
            headingY: final ? afterHeadingY ?? headingY : headingY, addWeb: addWeb, bannerBottom: bannerBottom, headingLabel: headingLabel)
    }
    let timeline = Observations(samples)
    let element = Element()
    let app = App(frame: screen)
    let controls = Dictionary(uniqueKeysWithValues: tree.filter { $0.snapshot.elementType == .button }.map {
        ($0.path, LiveControl(snapshot: $0.snapshot, hittable: hittable, element: Element()))
    })
    let candidate = Adapter(app: app, current: LiveControl(snapshot: snapshot(), hittable: true, element: element),
                            rows: tree, blockers: [statusBar], observations: timeline, nativePhase: "ordinary_terminal_capture",
                            pathControls: controls)
    var failure: String?
    do { try candidate.terminalScreenshot() } catch let rejected as Rejected { failure = rejected.reason } catch { failure = "unexpected" }
    check(failure == error && app.input.inputs.isEmpty && element.inputs.isEmpty, message)
    validate(timeline)
}
let exposedTerminal = terminalRows()
let scrolledTerminal = terminalRows(titleFrame.offsetBy(dx: 0, dy: 650), outputFrame.offsetBy(dx: 0, dy: 650))
exerciseCapture([scrolledTerminal, exposedTerminal, exposedTerminal],
                message: "capture must settle after the safely scrolled terminal returns to the viewport") { timeline in
    let capture = timeline.checkpoints.first { $0.0 == "ordinary_terminal" }?.1
    let header = capture?["headerBounds"] as? [String: Any]
    check(timeline.webSurface.drags.count == 1 && capture?["terminalFrame"] as? [Double] == [20, 280, 350, 400] &&
          capture?["targetFrame"] as? [Double] == [20, 220, 250, 30] && capture?["noCredentialsVisible"] as? Bool == true &&
          header?["brandFrame"] as? [Double] == [20, 80, 130, 24] && header?["addFrame"] as? [Double] == [282, 72, 88, 44] &&
          header?["headingFrame"] as? [Double] == [20, 150, 190, 27] && header?["headerBottom"] as? Double == 122 &&
          header?["statusBarFrames"] as? [[Double]] == [[Double(statusBar.minX), Double(statusBar.minY), Double(statusBar.width), Double(statusBar.height)]] &&
          header?["sameOwner"] as? Bool == true &&
          capture?["boundSource"] as? String == "native_region" && capture?["controlBounds"] == nil,
          "capture must reveal both anchors with a bounded scroll and post only the real output container's measured bounds")
}
let stickyTitleLayout = terminalRows(titleFrame, outputFrame.offsetBy(dx: 0, dy: -50))
exerciseCapture([stickyTitleLayout, exposedTerminal, exposedTerminal],
                message: "a sticky title must not overlap the captured terminal region") { timeline in
    let drag = timeline.webSurface.drags.first
    check(timeline.webSurface.drags.count == 1 && drag.map { from, to in
        let x = from.dx * screen.width
        return from.dx == to.dx && from.dy < to.dy && (x < outputFrame.minX || x > outputFrame.maxX)
    } == true, "revealing the page under a sticky title must drag outside xterm and leave scrollback alone")
}
exerciseCapture([], error: "native_terminal_header_unproven", headerY: statusBar.maxY - 1,
                message: "even a one-point brand collision with the native status bar blocks publication") { timeline in
    let detail = timeline.checkpoints.first?.1["detail"] as? [String: Any]
    check(timeline.checkpoints.count == 1 && detail?["anchor"] as? String == "header_brand" &&
          detail?["reason"] as? String == "outside_safe_frame", "the clipped brand gets a bounded diagnosis")
}
exerciseCapture([exposedTerminal, exposedTerminal, exposedTerminal], error: "native_capture_geometry_changed", afterHeaderY: 82,
                message: "a header that moves after the original PNG was taken blocks publication") { timeline in
    let detail = timeline.checkpoints.first?.1["detail"] as? [String: Any]
    check(timeline.checkpoints.count == 1 && detail?["anchor"] as? String == "header_brand" &&
          detail?["reason"] as? String == "layout_unstable", "the moved brand cannot publish an image")
}
exerciseCapture([], error: "native_terminal_header_unproven", addWeb: [0, 1],
                message: "an add button in a different WebView cannot prove this terminal's header") { timeline in
    let detail = timeline.checkpoints.first?.1["detail"] as? [String: Any]
    check(timeline.checkpoints.count == 1 && detail?["anchor"] as? String == "header_add" &&
          detail?["reason"] as? String == "owner_unproven", "foreign header geometry must not publish a screenshot")
}
exerciseCapture([], error: "native_terminal_header_unproven", headingY: 121,
                message: "the flattened banner's trailing padding can cover a heading that clears its controls") { timeline in
    let detail = timeline.checkpoints.first?.1["detail"] as? [String: Any]
    check(timeline.checkpoints.count == 1 && detail?["anchor"] as? String == "terminal_heading" &&
          detail?["reason"] as? String == "outside_safe_frame", "the clipped terminal H2 must not publish an image")
}
exerciseCapture([], error: "native_terminal_header_unproven", headingY: 129, bannerBottom: 130,
                message: "a measured banner overrides the control and padding estimate") { timeline in
    let detail = timeline.checkpoints.first?.1["detail"] as? [String: Any]
    check(timeline.checkpoints.count == 1 && detail?["anchor"] as? String == "terminal_heading",
          "the measured container may cover content below the fallback edge")
}
exerciseCapture([], bannerBottom: 130, message: "an unobscured heading and measured banner can publish") { timeline in
    let header = timeline.checkpoints.first?.1["headerBounds"] as? [String: Any]
    check(header?["headerBottom"] as? Double == 130, "actual banner geometry is sent with the original image")
}
exerciseCapture([exposedTerminal, exposedTerminal, exposedTerminal], error: "native_capture_geometry_changed", afterHeadingY: 152,
                message: "an unobscured H2 that moves while taking the screenshot must still block publication") { timeline in
    let detail = timeline.checkpoints.first?.1["detail"] as? [String: Any]
    check(timeline.checkpoints.count == 1 && detail?["anchor"] as? String == "terminal_heading" &&
          detail?["reason"] as? String == "layout_unstable", "the actual heading must stay still across the screenshot")
}
exerciseCapture([], error: "native_geometry_ambiguous", headingLabel: "普通 SSH",
                message: "the H2 ID alone must not stand in for the whole label") { timeline in
    let detail = timeline.checkpoints.first?.1["detail"] as? [String: Any]
    check(timeline.checkpoints.count == 1 && detail?["anchor"] as? String == "terminal_heading" &&
          detail?["reason"] as? String == "not_found", "a partial label is not a displayed heading witness")
}
exerciseCapture([], terminalRows(outputRole: .staticText), error: "native_geometry_ambiguous",
                message: "a text leaf must never be used as terminal pixel bounds") { timeline in
    let diagnostic = timeline.checkpoints.first?.1["detail"] as? [String: Any]
    check(timeline.checkpoints.count == 1 && timeline.checkpoints.first?.0 == "native_capture_diagnostic" &&
          diagnostic?["anchor"] as? String == "terminal" && diagnostic?["matchCount"] as? Int == 1 &&
          diagnostic?["reason"] as? String == "geometry_ambiguous", "unusable anchors get a bounded terminal diagnostic")
}
let unrelatedOutput = row(snapshot(.group, frame: outputFrame, identifier: "ssh-terminal-output", label: terminalLabel),
                          path: [0, 0, 3])
exerciseCapture([], exposedTerminal + [unrelatedOutput], error: "native_owner_ambiguous",
                message: "an independent same-name region is insufficient evidence for the terminal") { timeline in
    check(timeline.checkpoints.allSatisfy { $0.0 == "native_capture_diagnostic" }, "ambiguous regions must not export an image")
}
let shiftedOutput = terminalRows(titleFrame, outputFrame.offsetBy(dx: 0, dy: 12))
exerciseCapture([exposedTerminal, exposedTerminal, shiftedOutput], error: "native_capture_geometry_changed",
                message: "layout changes between stable observation and post-shot observation block publication") { timeline in
    check(timeline.checkpoints.allSatisfy { $0.0 == "native_capture_diagnostic" }, "changed geometry must not publish an image")
}
let controlRows = terminalControlRows()
exerciseCapture([terminalControlRows(offset: 180), controlRows, controlRows], controlRows,
                message: "the real helper row can bound a capture after one evidenced page scroll") { timeline in
    let capture = timeline.checkpoints.first { $0.0 == "ordinary_terminal" }?.1
    let bounds = capture?["controlBounds"] as? [String: Any]
    let helpers = [[20.0, 710, 44, 44], [68, 710, 44, 44], [116, 710, 44, 44], [164, 710, 44, 44]]
    check(timeline.webSurface.drags.count == 1 && capture?["boundSource"] as? String == "terminal_control_bounds" &&
          capture?["terminalFrame"] as? [Double] == [0, 304, 390, 406] && capture?["targetFrame"] as? [Double] == [20, 220, 250, 30] &&
          bounds?["dismissFrame"] as? [Double] == [20, 260, 82, 44] && bounds?["helperFrames"] as? [[Double]] == helpers &&
          bounds?["sameOwner"] as? Bool == true, "the candidate band must carry the real upper and lower control measurements")
}
exerciseCapture([], controlRows, error: "native_capture_geometry_changed", hittable: false,
                message: "non-hittable boundary controls must not validate a fallback capture") { timeline in
    check(timeline.checkpoints.allSatisfy { $0.0 == "native_capture_diagnostic" }, "unchecked controls must not publish an image")
}
exerciseCapture([], terminalControlRows(helperOffset: 4), error: "native_terminal_frame_invalid",
                message: "a split or misaligned set of helper keys is not a single bound row") { timeline in
    check(timeline.webSurface.drags.isEmpty && timeline.checkpoints.allSatisfy { $0.0 == "native_capture_diagnostic" },
          "misaligned helpers authorize neither a page scroll nor a screenshot")
}
exerciseCapture([], controlRows + [row(snapshot(.button, frame: CGRect(x: 20, y: 770, width: 44, height: 44), label: "Esc"),
                                       path: [0, 0, 7])], error: "native_owner_ambiguous",
                message: "a second Esc cannot be ignored to make a unique lower boundary") { timeline in
    check(timeline.checkpoints.allSatisfy { $0.0 == "native_capture_diagnostic" }, "ambiguous helpers must not export a screenshot")
}
exerciseCapture([controlRows, controlRows, terminalControlRows(helperOffset: 1)], controlRows,
                error: "native_capture_geometry_changed", message: "changed helper bounds after a captured image must block publication") { timeline in
    check(timeline.checkpoints.allSatisfy { $0.0 == "native_capture_diagnostic" }, "a moved boundary cannot publish an image")
}
exerciseCapture([], controlRows + [terminalRows(outputRole: .staticText)[3]], error: "native_geometry_ambiguous",
                message: "an invalid named region must not be bypassed by the boundary fallback") { timeline in
    check(timeline.checkpoints.allSatisfy { $0.0 == "native_capture_diagnostic" }, "invalid named geometry still rejects capture")
}
let reviewStatus = CGRect(x: 0, y: 0, width: 440, height: 54)
let reviewLabels = ["主机指纹发生变化", "已阻止连接与输入", "旧：SHA256:fixture-complete-old",
                    "新：SHA256:fixture-complete-new", "目标：fixture-target", "重新核对主机指纹", "取消连接，保留旧信任"]
func reviewRows(titleY: CGFloat = 66, newFingerprint: String = reviewLabels[3], cancelRole: XCUIElement.ElementType = .button) -> [Observed] {
    func descendant(_ item: Snapshot, _ path: [Int]) -> Observed {
        Observed(snapshot: item, path: path, windowPath: [0], webPath: [0, 0], window: passwordScreen, webs: [passwordScreen])
    }
    var rows = [descendant(snapshot(.window, frame: passwordScreen, label: ""), [0]),
                descendant(snapshot(.webView, frame: passwordScreen, label: ""), [0, 0])]
    let identifiers = ["", "", "ssh-key-change-old", "ssh-key-change-new", "ssh-key-change-target", "ssh-key-recheck", "ssh-key-cancel"]
    for (index, label) in reviewLabels.enumerated() {
        let role: XCUIElement.ElementType = index == 6 ? cancelRole : index == 5 ? .button : .staticText
        let y: CGFloat = index == 0 ? titleY : 110 + CGFloat(index) * 48
        let frame = CGRect(x: 16, y: y, width: 400, height: index < 5 ? 23 : 44)
        let item = snapshot(role, frame: frame, identifier: identifiers[index], label: index == 3 ? newFingerprint : label)
        rows.append(descendant(item, [0, 0, index]))
    }
    return rows
}
func exerciseReview(_ before: [Observed], _ after: [Observed], anchor: String? = nil, sample: String? = nil,
                    reason: String? = nil, expectedError: String? = nil) {
    let timeline = Observations([before, after])
    let app = App(frame: passwordScreen)
    let candidate = Adapter(app: app, current: LiveControl(snapshot: snapshot(), hittable: true, element: Element()),
                            rows: after, blockers: [reviewStatus], observations: timeline, nativePhase: "key_change_review_capture")
    var observedError: String?
    do { try candidate.reviewScreenshot() }
    catch let rejected as Rejected { observedError = rejected.reason }
    catch { observedError = "unexpected" }
    check(observedError == expectedError && app.input.inputs.isEmpty && timeline.webSurface.drags.isEmpty,
          "the review path must validate the actual screen without gestures or terminal input")
    if let anchor = anchor {
        let detail = timeline.checkpoints.first?.1["detail"] as? [String: Any]
        let values = detail?["candidates"] as? [[String: Any]]
        let encoded = (try? JSONSerialization.data(withJSONObject: detail ?? [:])).map { String(decoding: $0, as: UTF8.self) } ?? ""
        check(timeline.checkpoints.count == 1 && timeline.checkpoints.first?.0 == "native_capture_diagnostic" &&
              detail?["anchor"] as? String == anchor && detail?["sample"] as? String == sample &&
              detail?["reason"] as? String == reason && detail?["matchCount"] as? Int == 1 &&
              values?.count == 1 && Set(values?.first?.keys.map { $0 } ?? []) == ["role", "frame", "ownerResolved", "visible"] &&
              !encoded.contains("SHA256") && !encoded.contains("fixture-target"),
              "failed review anchors must identify the sample with only fixed roles and geometry")
    } else {
        let result = timeline.checkpoints.first?.1
        let frames = result?["reviewFrames"] as? [[Double]]
        check(timeline.reviewActionChecks == 2 && timeline.checkpoints.count == 1 && timeline.checkpoints.first?.0 == "key_change_review" &&
              result?["safeFrame"] as? [Double] == [0, 54, 440, 902] && frames?.count == 7 &&
              frames?.first == [16, 66, 400, 23] && result?["pngBase64"] != nil,
              "both samples must preserve all seven visible review anchors and the original PNG")
    }
}
let unobscuredReview = reviewRows()
let statusClippedReview = reviewRows(titleY: 12)
exerciseReview(statusClippedReview, unobscuredReview, anchor: "review_title", sample: "before", reason: "outside_safe_frame",
               expectedError: "native_geometry_ambiguous")
exerciseReview(unobscuredReview, statusClippedReview, anchor: "review_title", sample: "after", reason: "outside_safe_frame",
               expectedError: "native_geometry_ambiguous")
exerciseReview(unobscuredReview, reviewRows(newFingerprint: "新：SHA256:fixture-incomplete"), anchor: "review_new_fingerprint",
               sample: "after", reason: "not_found", expectedError: "native_geometry_ambiguous")
exerciseReview(reviewRows(cancelRole: .staticText), unobscuredReview, anchor: "review_cancel", sample: "before",
               reason: "geometry_ambiguous", expectedError: "native_geometry_ambiguous")
exerciseReview(unobscuredReview, unobscuredReview)
let writeElement = Element()
let offscreen = snapshot(frame: movedFrame.offsetBy(dx: 0, dy: -300))
let writeSnapshots = Observations([], liveSnapshots: [moved, moved, snapshot(), offscreen, moved, moved])
let writing = Adapter(app: App(frame: screen),
                      current: LiveControl(snapshot: moved, hittable: true, element: writeElement),
                      rows: formRows(moved), blockers: [keyboard], observations: writeSnapshots)
var writeSucceeded = true
do { try writing.fillPort("2222") } catch { writeSucceeded = false }
check(writeSucceeded && writeElement.inputs == ["2222"] && writeSnapshots.liveReads >= 6,
      "the actual fill entry must wait for keyboard geometry to stabilize and type exactly once")
check(writeSnapshots.checkpoints.compactMap { $0.1["geometryReason"] as? String } == ["field_occluded", "field_outside"],
      "the fill adapter must preserve distinct rejection reasons in sample order before recovering")
let failedReadback = Element()
failedReadback.forcedReadback = "wrong"
let unread = Adapter(app: App(frame: screen),
                    current: LiveControl(snapshot: moved, hittable: true, element: failedReadback),
                    rows: formRows(moved), blockers: [keyboard])
var readbackRejected = false
do { try unread.fillPort("2222") } catch { readbackRejected = true }
check(readbackRejected && failedReadback.inputs == ["2222"],
      "the actual fill entry must fail a wrong readback without replaying typeText")
let page = formRows(moved)[1]
for (live, stored) in [(snapshot(identifier: "ssh-password", label: "密码"), snapshot(label: "密码")),
                       (snapshot(identifier: "ssh-password", label: "密码"), snapshot(identifier: "changed", label: "密码")),
                       (snapshot(label: "密码"), snapshot(identifier: "ssh-password", label: "密码"))] {
    var rejected = false
    do { _ = try adapter.scope(live, formRows(stored), page) } catch { rejected = true }
    check(rejected, "page scope must reject lost or changed product identifiers rather than infer nativeSystem")
}
let systemSnapshot = snapshot(.button, identifier: "native-keyboard-action", label: "系统按键")
let system = Observed(snapshot: systemSnapshot, path: [0, 1, 0], windowPath: [0], webPath: [],
                      window: screen, webs: [])
let keyboardAncestor = Observed(snapshot: snapshot(.keyboard, frame: keyboard, label: ""),
                                path: [0, 1], windowPath: [0], webPath: [], window: screen, webs: [])
var nativeScope: NativeViewPolicy.Scope?
do { nativeScope = try adapter.scope(systemSnapshot, formRows(moved) + [keyboardAncestor, system], page) } catch { }
check(nativeScope == .nativeSystem,
      "a same-identity observed control with proven native keyboard ancestry keeps its nativeSystem scope")
if !failures.isEmpty {
    FileHandle.standardError.write(Data((failures.joined(separator: "\n") + "\n").utf8))
    exit(1)
}
'''
        self.compile_and_run(program)

    def test_source_bound_form_roles_and_reselection(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        evidence = json.loads((repo / "docs/evidence/ios-ssh-20261117/local-macos-form-identity.json").read_text())
        revision = evidence["build"]["source_binding"]["git_head"]
        self.assertRegex(revision, r"\A[0-9a-f]{40}\Z")
        # The observation belongs to the recorded source tree. Source archives
        # and shallow checkouts can still run the current HTML contract below.
        history_available = shutil.which("git") and (repo / ".git").exists() and subprocess.run(
            ["git", "cat-file", "-e", f"{revision}^{{commit}}"], cwd=repo, capture_output=True, timeout=10,
        ).returncode == 0
        for name, digest in evidence["build"]["source_sha256"].items():
            self.assertRegex(digest, r"\A[0-9a-f]{64}\Z")
            if history_available:
                source = subprocess.run(["git", "show", f"{revision}:{name}"], cwd=repo, capture_output=True,
                                        check=True, timeout=10).stdout
                self.assertEqual(hashlib.sha256(source).hexdigest(), digest, name)
        controls = evidence["controls"]
        self.assert_current_form_markup(repo, controls)
        self.assertEqual([row["ax_role"] for row in controls], ["AXTextField"] * 3 + ["AXButton"])
        self.assertTrue(all(not row["ax_identifier_present"] and row["same_window"] for row in controls))
        self.assertTrue(all(row.get("editable") for row in controls[:3]))
        self.assertTrue(all(row["label"]["ax_role"] == "AXStaticText" for row in controls[:3]))
        samples = []
        for row in controls:
            label = json.dumps(row["visible_name"], ensure_ascii=False)
            role = "textField" if row["ax_role"] == "AXTextField" else "button"
            # The editable labels are observed AX siblings. For the probe,
            # static text is an explicit decoration counterexample.
            samples.extend([f'F(identifier: "", label: {label}, role: "staticText", value: nil)',
                            f'F(identifier: "", label: {label}, role: "{role}", value: nil)'])
        program = "import Foundation\nimport CoreGraphics\ntypealias F = NativeControlPolicy.Fact\nlet observed = [\n" + ",\n".join(samples) + "]\n"
        program += r'''
let edit: Set<String> = ["textField", "textView", "searchField"]
func verdict(_ rows: [F], _ paths: [[Int]], _ label: String, _ roles: Set<String>, _ id: String? = nil)
  -> (index: Int?, role: String, reason: String, matches: Int) {
    NativeControlPolicy.formVerdict(facts: rows, paths: paths, identifier: id, label: label, editableRoles: roles)
}
let observedPaths = observed.indices.map { [0, 0, $0] }
for (label, index) in [("主机地址", 1), ("端口", 3), ("用户名", 5)] {
    let found = verdict(observed, observedPaths, label, edit, "not-exposed-by-WebKit")
    precondition(found.index == index && found.role == "textField" && found.reason == "matched" && found.matches == 2,
                 "real static label plus one editable must select the editable")
}
let probe = verdict(observed, observedPaths, "探测主机指纹", ["button"], "ssh-probe")
precondition(probe.index == 7 && probe.role == "button", "probe must resolve its actual button")
precondition(verdict([observed[0]], [[0, 0]], "主机地址", edit).index == nil, "label alone is not a field")
precondition(verdict([observed[6]], [[0, 0]], "探测主机指纹", ["button"]).index == nil,
             "static button text alone is not an action")
precondition(verdict([F(identifier: "", label: "探测主机指纹", role: "textField", value: nil)],
                     [[0]], "探测主机指纹", ["button"]).index == nil, "editable text cannot be a probe button")

let port = F(identifier: "", label: "端口", role: "textField", value: "22")
let arrows = [F(identifier: "", label: "", role: "stepper", value: "0"),
              F(identifier: "", label: "", role: "button", value: nil),
              F(identifier: "", label: "", role: "button", value: nil)]
let direct = [port] + arrows
precondition(verdict(direct, [[0], [0, 0], [0, 0, 0], [0, 0, 1]], "端口", edit).index == 0,
             "actual numeric AXTextField wins over its descendant arrows")
let wrapper = F(identifier: "ssh-port", label: "端口", role: "inputWrapper", value: "22")
let child = F(identifier: "", label: "", role: "textField", value: "22")
let wrapped = [wrapper, child] + arrows
let wrappedPaths = [[0], [0, 0], [0, 1], [0, 1, 0], [0, 1, 1]]
let wrappedResult = verdict(wrapped, wrappedPaths, "端口", edit, "ssh-port")
precondition(wrappedResult.index == 1 && wrappedResult.role == "inputWrapper",
             "numeric wrapper must resolve its one actual editable descendant")
precondition(verdict([wrapper] + arrows, [[0], [0, 0], [0, 0, 0], [0, 0, 1]], "端口", edit, "ssh-port").index == nil,
             "numeric value and two arrows never prove editability")
precondition(verdict([wrapper, child, child], [[0], [0, 0], [0, 1]], "端口", edit, "ssh-port").index == nil,
             "two editable descendants are ambiguous")
precondition(verdict([wrapper, child], [[0], [1, 0]], "端口", edit, "ssh-port").index == nil,
             "another window's editable is not this wrapper's descendant")
precondition(verdict([F(identifier: "", label: "端口", role: "staticText", value: "22")], [[0]], "端口", edit).index == nil,
             "a static value of 22 never proves a numeric input")
for decoration in ["staticText", "other"] {
    let parent = F(identifier: "ssh-port", label: "端口", role: decoration, value: "22")
    precondition(verdict([parent, child], [[0], [0, 0]], "端口", edit, "ssh-port").index == nil,
                 "an arbitrary decoration parent cannot borrow an editable descendant")
}

let identified = [F(identifier: "ssh-host", label: "主机地址", role: "textField", value: nil), observed[1]]
precondition(verdict(identified, [[0, 0], [1, 0]], "主机地址", edit, "ssh-host").index == 0,
             "unique nonempty identifier takes precedence over an unrelated same-label input")
let wrongIdentity = [F(identifier: "ssh-host", label: "主机地址", role: "staticText", value: nil), observed[1]]
precondition(verdict(wrongIdentity, [[0, 0], [1, 0]], "主机地址", edit, "ssh-host").index == nil,
             "a wrong-role identity cannot fall through to another window's same-label field")
precondition(verdict([identified[0], identified[0]], [[0, 0], [0, 1]], "主机地址", edit, "ssh-host").index == nil,
             "duplicate editable identifiers remain ambiguous")
precondition(verdict([observed[1], observed[1]], [[0, 0], [1, 0]], "主机地址", edit).index == nil,
             "same-label editable controls across windows remain ambiguous")
precondition(!NativeFramePolicy.sameOwner(windowPaths: [[0], [0], [1], [0]],
                                        webPaths: [[0, 0], [0, 0], [1, 0], [0, 0]]),
             "four independently selected controls across windows cannot certify a form")
precondition(NativeFramePolicy.sameOwner(windowPaths: Array(repeating: [0], count: 4),
                                       webPaths: Array(repeating: [0, 0], count: 4)))
let moved = [observed[1], observed[0]]
precondition(verdict(moved, [[0, 1], [0, 0]], "主机地址", edit).index == 0,
             "action must re-resolve the current snapshot rather than reuse the diagnostic row index")
'''
        self.compile_and_run(program)

    def assert_current_form_markup(self, repo, controls):
        class SSHMarkup(HTMLParser):
            inside_form = False
            label = None
            probe = None

            def __init__(self):
                super().__init__()
                self.fields = {}
                self.probes = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                identifier = attrs.get("id")
                if tag == "form":
                    self.inside_form = identifier == "ssh-form"
                if not self.inside_form:
                    return
                if tag == "label":
                    self.label = []
                elif tag == "input" and self.label is not None:
                    self.fields.setdefault(identifier, []).append((attrs.get("type", "text"), "".join(self.label).strip()))
                elif tag == "button" and identifier == "ssh-probe":
                    self.probe = (attrs.get("type"), [])

            def handle_data(self, text):
                if self.label is not None:
                    self.label.append(text)
                if self.probe is not None:
                    self.probe[1].append(text)

            def handle_endtag(self, tag):
                if tag == "form":
                    self.inside_form = False
                elif tag == "label":
                    self.label = None
                elif tag == "button" and self.probe is not None:
                    kind, text = self.probe
                    self.probes.append((kind, "".join(text).strip()))
                    self.probe = None

        markup = SSHMarkup()
        markup.feed((repo / "validation/tauri/index.html").read_text())
        for identifier, kind, control in zip(("ssh-host", "ssh-port", "ssh-user"), ("text", "number", "text"), controls):
            self.assertEqual(markup.fields.get(identifier), [(kind, control["visible_name"])], identifier)
        self.assertEqual(markup.fields.get("ssh-password"), [("password", "密码")])
        self.assertEqual(markup.probes, [("button", controls[3]["visible_name"])])

    def test_real_label_samples_and_ambiguity(self):
        program = r'''
import Foundation
typealias F = NativeControlPolicy.Fact
let rows = [
    F(identifier: "", label: "＋ 添加主机", role: "button", value: ""),
    F(identifier: "", label: "添加主机", role: "button", value: ""),
    F(identifier: "", label: "普通 SSH", role: "button", value: ""),
    F(identifier: "", label: "普通 SSH 终端", role: "button", value: ""),
    F(identifier: "", label: "主机地址", role: "textField", value: ""),
    F(identifier: "", label: "端口", role: "numberField", value: "22"),
    F(identifier: "", label: "用户名", role: "textField", value: ""),
    F(identifier: "", label: "探测主机指纹", role: "button", value: ""),
    F(identifier: "", label: "我已通过可信渠道独立核对以上指纹。", role: "checkBox", value: "0"),
    F(identifier: "", label: "密码", role: "secureTextField", value: ""),
    F(identifier: "", label: "连接 / 重新连接", role: "button", value: ""),
    F(identifier: "", label: "取消连接", role: "button", value: ""),
    F(identifier: "", label: "重新核对主机指纹", role: "button", value: ""),
    F(identifier: "", label: "取消连接，保留旧信任", role: "button", value: ""),
    F(identifier: "", label: "打开键盘", role: "button", value: ""),
    F(identifier: "", label: "断开连接", role: "button", value: "")
]
func pick(_ label: String, _ id: String? = nil, _ roles: Set<String> = ["button"]) -> Int? {
    NativeControlPolicy.select(rows, identifier: id, label: label, roles: roles)
}
precondition(pick("添加主机") == 1)
precondition(pick("普通 SSH 终端", "add-ssh") == 3)
precondition(pick("未知") == nil)
precondition(pick("不存在", "") == nil)
precondition(pick("端口", "ssh-port", ["numberField"]) == 5)
precondition(pick("密码", "ssh-password", ["secureTextField"]) == 9)
precondition(pick("我已通过可信渠道独立核对以上指纹。", nil, ["checkBox"]) == 8)
precondition(NativeControlPolicy.select([F(identifier: "", label: "我已通过可信渠道独立核对以上指纹。",
    role: "staticText", value: "1")], identifier: nil, label: "我已通过可信渠道独立核对以上指纹。", roles: ["checkBox"]) == nil)
precondition(pick("重新核对主机指纹") == 12)
precondition(pick("取消连接，保留旧信任") == 13)
let duplicate = rows + [F(identifier: "", label: "添加主机", role: "button", value: "")]
precondition(NativeControlPolicy.select(duplicate, identifier: nil, label: "添加主机", roles: ["button"]) == nil)
let idDuplicates = rows + [F(identifier: "target", label: "x", role: "button", value: ""),
                           F(identifier: "target", label: "y", role: "button", value: "")]
precondition(NativeControlPolicy.select(idDuplicates, identifier: "target", label: "添加主机", roles: ["button"]) == nil)
let wrongRole = rows + [F(identifier: "target", label: "other", role: "textField", value: "")]
precondition(NativeControlPolicy.select(wrongRole, identifier: "target", label: "添加主机", roles: ["button"]) == nil)
let mixedDuplicate = wrongRole + [F(identifier: "target", label: "other", role: "button", value: "")]
precondition(NativeControlPolicy.select(mixedDuplicate, identifier: "target", label: "添加主机", roles: ["button"]) == nil)
precondition(NativeControlPolicy.queryChoice(identifierCount: 1, labelCount: 1) == .identifier)
precondition(NativeControlPolicy.queryChoice(identifierCount: 2, labelCount: 1) == .ambiguous)
precondition(NativeControlPolicy.queryChoice(identifierCount: 0, labelCount: 1) == .label)
precondition(NativeControlPolicy.queryChoice(identifierCount: 0, labelCount: 2) == .ambiguous)
precondition(NativeControlPolicy.queryChoice(identifierCount: 0, labelCount: 0) == .none)
precondition(NativeControlPolicy.valueText(NSNumber(value: 0)) == "0")
precondition(NativeControlPolicy.valueText(NSNumber(value: 1)) == "1")
precondition(NativeControlPolicy.valueText(NSNumber(value: 22)) == "22")
precondition(NativeControlPolicy.isPortEditingCandidate(role: 999, stepper: 1, button: 2, value: NSNumber(value: 22)))
precondition(!NativeControlPolicy.isPortEditingCandidate(role: 1, stepper: 1, button: 2, value: "22"))
precondition(!NativeControlPolicy.isPortEditingCandidate(role: 2, stepper: 1, button: 2, value: "22"))
precondition(!NativeControlPolicy.isPortEditingCandidate(role: 999, stepper: 1, button: 2, value: "23"))
precondition(NativeControlPolicy.clearCount(NSNumber(value: 22), placeholder: nil, secure: false) == 2)
precondition(NativeControlPolicy.clearCount("请输入主机地址", placeholder: "请输入主机地址", secure: false) == 0)
precondition(NativeControlPolicy.clearCount("请输入主机地址", placeholder: nil, secure: false) == nil)
precondition(NativeControlPolicy.clearCount("输入密码", placeholder: "输入密码", secure: true) == 0)
precondition(NativeControlPolicy.clearCount("••••", placeholder: nil, secure: true) == nil)
precondition(!NativeControlPolicy.credentialEmpty("••••", placeholder: nil))
precondition(!NativeControlPolicy.credentialEmpty("密码", placeholder: nil))
precondition(NativeControlPolicy.credentialEmpty("密码", placeholder: "密码"))
let unknown = NSObject()
precondition(NativeControlPolicy.valueText(nil) == "")
precondition(NativeControlPolicy.valueText(unknown) == nil)
precondition(!NativeControlPolicy.credentialEmpty(unknown, placeholder: nil))
precondition(NativeControlPolicy.clearCount(unknown, placeholder: nil, secure: true) == nil)
precondition(NativeControlPolicy.clearCount(unknown, placeholder: nil, secure: false) == nil)
precondition(!NativeControlPolicy.isPortEditingCandidate(role: 999, stepper: 1, button: 2, value: unknown))
'''
        self.compile_and_run(program)


if __name__ == "__main__":
    unittest.main()
