"""Pure Swift policy tests using macOS AX labels, not iOS device evidence."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


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
        case window = 3, webView = 4
    }
    var taps = 0
    var inputs: [String] = []
    var inputValue: String?
    var forcedReadback: String?
    func coordinate(withNormalizedOffset: CGVector) -> XCUICoordinate { XCUICoordinate(element: self) }
    func tap() { taps += 1 }
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
    func tap() { element.tap() }
    func press(forDuration: Double, thenDragTo: XCUICoordinate) { }
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
struct Query {
    let allElementsBoundByIndex: [XCUIElement] = []
    var firstMatch: XCUIElement { XCUIElement() }
}
struct App {
    let frame: CGRect
    var webViews: Query { Query() }
    var keyboards: Query { Query() }
}
struct Rejected: Error { let reason: String }
final class Observations {
    var trees: [[Observed]]
    var liveSnapshots: [Snapshot]
    var liveReads = 0
    var resolved: [Observed] = []
    init(_ trees: [[Observed]], liveSnapshots: [Snapshot] = []) {
        self.trees = trees
        self.liveSnapshots = liveSnapshots
    }
    func next(_ fallback: [Observed]) -> [Observed] {
        trees.isEmpty ? fallback : trees.removeFirst()
    }
    func live(_ fallback: LiveControl) -> LiveControl {
        liveReads += 1
        return LiveControl(snapshot: liveSnapshots.isEmpty ? fallback.snapshot : liveSnapshots.removeFirst(),
                           hittable: fallback.hittable, element: fallback.element)
    }
}
struct Adapter {
    let app: App
    let current: LiveControl
    let rows: [Observed]
    let blockers: [CGRect]
    var observations: Observations? = nil
    var nativePhase: String { "fixture" }
    func require(_ condition: Bool, _ reason: String) throws {
        if !condition { throw Rejected(reason: reason) }
    }
    func nativeOcclusions() -> [CGRect] { blockers }
    func post(_ topic: String, _ payload: [String: Any]) throws { }
    func role(_ type: XCUIElement.ElementType) -> String { type == .textField ? "textField" : "other" }
    func observedNodes() throws -> [Observed] { observations?.next(rows) ?? rows }
    func resolveByPath(_ row: Observed) -> Observed {
        observations?.resolved.append(row)
        return row
    }
    func liveControl(_ row: Observed) -> LiveControl? {
        if [.window, .webView].contains(row.snapshot.elementType) {
            return LiveControl(snapshot: row.snapshot, hittable: true, element: Element())
        }
        let live = observations?.live(current) ?? current
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
    func revealCurrent() throws -> LiveControl { try reveal(current.element) }
    func fillPort(_ text: String) throws { try fillForm("port", text) }
    func scope(_ item: Snapshot, _ rows: [Observed], _ page: Observed) throws -> NativeViewPolicy.Scope {
        try pageScope(item, rows, page)
    }
''' + "\n".join(self.production_method(signature) for signature in (
            "func formTargets(_ tree:", "func formSelection(_ tree:", "func formControl(_ name:",
            "func sameIdentity(_ lhs:", "func liveOnPath(_ row:", "func controlScope(_ row:",
            "func canInteract(_ current:", "func needsScroll(_ owner:", "func scrollToControl(_ owner:",
            "func controlIdentityRows(_ current:", "func controlOwner(_ current:",
            "func controlVisibleFrame(_ owner:", "func reveal(_ item:", "func tapForm(_ name:",
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
func formRows(_ port: Snapshot, portPath: [Int] = [0, 0, 1]) -> [Observed] {
    [row(snapshot(label: "主机地址"), path: [0, 0, 0]), row(port, path: portPath),
     row(snapshot(label: "用户名"), path: [0, 0, 2]),
     row(snapshot(.button, label: "探测主机指纹"), path: [0, 0, 3]),
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
               hittable: Bool = true, allowed: Bool, reason: String) {
    let current = snapshot(frame: frame)
    let element = Element()
    let candidate = Adapter(app: App(frame: screen), current: LiveControl(snapshot: current, hittable: hittable, element: element),
                            rows: formRows(snapshot(frame: treeFrame ?? frame)), blockers: blockers)
    var rejected = false
    do { try candidate.tapPort() } catch { rejected = true }
    check((element.taps == 1) == allowed && rejected != allowed, reason)
}
expectTap(movedFrame, treeFrame: oldFrame, blockers: [], allowed: true,
          reason: "fresh unique geometry after keyboard movement permits the actual tap adapter")
let keyboard = CGRect(x: 0, y: 400, width: 390, height: 444)
expectTap(movedFrame, treeFrame: oldFrame, blockers: [keyboard], allowed: false,
          reason: "a later tree moving the control behind the keyboard must invalidate an older visible live frame")
expectTap(oldFrame, treeFrame: movedFrame, blockers: [keyboard], allowed: false,
          reason: "a later visible tree cannot authorize a tap until live geometry is refreshed")
expectTap(oldFrame, blockers: [keyboard], allowed: false,
          reason: "a keyboard-covered control must never be tapped")
expectTap(CGRect(x: 24, y: 380, width: 342, height: 42), blockers: [keyboard], allowed: false,
          reason: "a partly keyboard-covered control must never be tapped")
expectTap(CGRect(x: 24, y: -5, width: 342, height: 42), blockers: [], allowed: false,
          reason: "a partly offscreen control must never be tapped")
expectTap(movedFrame, blockers: [], hittable: false, allowed: false,
          reason: "a non-hittable control must never be tapped")
expectTap(.zero, blockers: [], allowed: false,
          reason: "a structurally owned control with invalid geometry must never be tapped")
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
let revealSnapshots = Observations([], liveSnapshots: [snapshot(), moved, moved, moved])
let revealing = Adapter(app: App(frame: screen),
                        current: LiveControl(snapshot: moved, hittable: true, element: Element()),
                        rows: formRows(moved), blockers: [keyboard], observations: revealSnapshots)
var revealed: LiveControl?
do { revealed = try revealing.revealCurrent() } catch { }
check(revealed?.snapshot.frame == movedFrame && revealSnapshots.liveReads >= 4,
      "the actual generic reveal path must refresh both its queried and path-bound live geometry")
let writeElement = Element()
let writeSnapshots = Observations([], liveSnapshots: [moved, moved, snapshot(), moved, moved])
let writing = Adapter(app: App(frame: screen),
                      current: LiveControl(snapshot: moved, hittable: true, element: writeElement),
                      rows: formRows(moved), blockers: [keyboard], observations: writeSnapshots)
var writeSucceeded = true
do { try writing.fillPort("2222") } catch { writeSucceeded = false }
check(writeSucceeded && writeElement.inputs == ["2222"] && writeSnapshots.liveReads >= 5,
      "the actual fill entry must wait for keyboard geometry to stabilize and type exactly once")
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
        for name, digest in evidence["build"]["source_sha256"].items():
            self.assertEqual(hashlib.sha256((repo / name).read_bytes()).hexdigest(), digest, name)
        controls = evidence["controls"]
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
