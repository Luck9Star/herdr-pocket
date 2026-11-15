import Cocoa
import FlutterMacOS

/// Real Flutter method codec and AppKit controls; no engine, visible window or AX permission.
final class SecureProbeMessenger: NSObject, FlutterBinaryMessenger {
    var handlers: [String: FlutterBinaryMessageHandler] = [:]
    var last: FlutterMethodCall?
    var changedEvents = 0
    private let codec = FlutterStandardMethodCodec.sharedInstance()
    private var nextConnection: Int64 = 0
    private var connections: [Int64: String] = [:]
    func send(onChannel channel: String, message: Data?) {
        if let message { last = codec.decodeMethodCall(message); changedEvents += 1 }
    }
    func send(onChannel channel: String, message: Data?, binaryReply callback: FlutterBinaryReply?) {
        send(onChannel: channel, message: message)
        callback?(codec.encodeSuccessEnvelope(nil))
    }
    func setMessageHandlerOnChannel(_ channel: String, binaryMessageHandler handler: FlutterBinaryMessageHandler?) -> Int64 {
        nextConnection += 1
        handlers[channel] = handler; connections[nextConnection] = channel
        return nextConnection
    }
    func cleanUpConnection(_ connection: Int64) {
        if let channel = connections.removeValue(forKey: connection) { handlers[channel] = nil }
    }
    func call(_ channel: String, _ method: String, _ arguments: Any?) -> Bool {
        guard let handler = handlers[channel] else { return false }
        var replied = false
        handler(codec.encode(FlutterMethodCall(methodName: method, arguments: arguments))) { _ in replied = true }
        let until = Date().addingTimeInterval(2)
        while !replied && Date() < until { RunLoop.main.run(until: Date().addingTimeInterval(0.005)) }
        return replied
    }
}

final class SecureProbeWindow: NSWindow {
    override func accessibilityChildren() -> [Any]? {
        herdrSecureAccessibilityChildren(window: self, preserving: super.accessibilityChildren())
    }
}

@main
struct SecureCredentialViewProbe {
    static func main() {
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.prohibited)
        let messenger = SecureProbeMessenger()
        let factory = HerdrSecureCredentialFactory(messenger: messenger)
        guard let field = factory.create(withViewIdentifier: 7, arguments: [
            "label": "私钥口令（可选）", "identifier": "direct-passphrase"]) as? HerdrSecureTextField else {
            print("{\"passed\":false,\"stage\":\"factory\"}"); exit(1)
        }
        let channel = "herdr.pocket/secure-field/7"
        var checks: [String: Bool] = [:]
        func sync(_ revision: Int, text: String? = nil, enabled: Bool = true) {
            var args: [String: Any] = ["revision": revision, "enabled": enabled, "dark": false]
            if let text { args["text"] = text }
            checks["syncReplied"] = messenger.call(channel, "sync", args)
        }
        let window = SecureProbeWindow(contentRect: NSRect(x: 0, y: 0, width: 400, height: 240),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        field.frame = NSRect(x: 20, y: 120, width: 340, height: 40)
        let ordinary = NSTextField(frame: NSRect(x: 20, y: 40, width: 340, height: 40))
        let publicMarker = UUID().uuidString
        ordinary.stringValue = publicMarker
        let clip = NSClipView(frame: NSRect(x: 0, y: 0, width: 400, height: 240))
        let document = NSView(frame: clip.bounds)
        clip.documentView = document
        window.contentView?.addSubview(clip)
        document.addSubview(field); document.addSubview(ordinary)
        // A real app-owned AX child stands for the published Flutter subtree.
        window.setAccessibilityChildren([ordinary])
        registerHerdrSecureAccessibilityWindow(window)
        func count(_ item: AnyObject) -> Int {
            (window.accessibilityChildren() ?? []).filter { ($0 as AnyObject) === item }.count
        }
        checks["inheritedWindowChildPreserved"] = count(ordinary) == 1
            && (window.accessibilityChildren()?.first as AnyObject?) === ordinary
        checks["secureWindowChildPresent"] = count(field) == 1
        registerHerdrSecureAccessibilityWindow(window)
        checks["secureWindowChildUnique"] = count(field) == 1
        checks["secureWindowParentCorrect"] = (field.accessibilityParent() as AnyObject?) === window
        sync(1, text: "")
        checks["secureClass"] = field is NSSecureTextField
        checks["nativeSecureElementPublished"] = field.isAccessibilityElement()
        checks["nativeSecureRolePublished"] = field.accessibilityRole() == .textField
        checks["nativeSecureSubrolePublished"] = field.accessibilitySubrole() == .secureTextField
        checks["labelPreserved"] = field.accessibilityLabel() == "私钥口令（可选）"
        checks["identifierPreserved"] = field.accessibilityIdentifier() == "direct-passphrase"
        checks["emptyFieldCanFocus"] = window.makeFirstResponder(field) && field.currentEditor() != nil
        let editorBefore = window.firstResponder
        for _ in 0..<3 { _ = window.accessibilityChildren(); _ = field.accessibilityParent() }
        checks["windowQueriesPreserveFocus"] = window.firstResponder === editorBefore
        sync(2, text: "")
        sync(3)
        checks["emptySyncPreservesFocus"] = window.firstResponder === editorBefore && field.currentEditor() != nil
        let parts = [UUID().uuidString, "合成", UUID().uuidString]
        let secret = parts.joined()
        if let editor = field.currentEditor() as? NSTextView {
            for part in parts { editor.insertText(part, replacementRange: NSRange(location: NSNotFound, length: 0)) }
        }
        let changed = messenger.last?.arguments as? [String: Any]
        checks["nativeEditingReachedFlutterWire"] = changed?["text"] as? String == secret
            && changed?["revision"] as? Int == 3 && messenger.changedEvents >= 3
        checks["nativeValueMatchesEdits"] = field.stringValue == secret
        let localAX = field.accessibilityValue() as? String
        // A local AppKit getter is distinct from an external system AX client.
        _ = window.makeFirstResponder(ordinary)
        sync(4)
        checks["metadataKeepsCurrentValue"] = (messenger.last?.arguments as? [String: Any])?["text"] as? String == secret
        sync(5, text: "")
        checks["clearIsEmpty"] = field.stringValue.isEmpty
        checks["clearDoesNotChangeOtherField"] = ordinary.stringValue == publicMarker
        field.isHidden = true
        checks["hiddenFieldExcluded"] = count(field) == 0 && count(ordinary) == 1
        field.isHidden = false
        let frame = field.frame
        field.frame.origin.x = 900
        checks["clippedFieldExcluded"] = count(field) == 0
        field.frame = frame
        field.removeFromSuperview()
        checks["detachedFieldExcluded"] = count(field) == 0
        document.addSubview(field)
        checks["reattachedFieldExposed"] = count(field) == 1
            && (field.accessibilityParent() as AnyObject?) === window
        window.setAccessibilityChildren([ordinary, field])
        checks["preexistingSecureChildDeduplicated"] = count(field) == 1 && count(ordinary) == 1
        window.setAccessibilityChildren([ordinary])
        _ = window.makeFirstResponder(field)
        sync(6, text: "")
        checks["clearedFieldCanFocusAgain"] = field.currentEditor() != nil && field.stringValue.isEmpty
        sync(7, enabled: false)
        let eventsBeforeDisabled = messenger.changedEvents
        field.stringValue = secret
        field.controlTextDidChange(Notification(name: NSControl.textDidChangeNotification, object: field))
        checks["disabledLateEditCannotRestore"] = field.stringValue.isEmpty && messenger.changedEvents == eventsBeforeDisabled
        sync(8)
        checks["reenableStaysEmpty"] = field.stringValue.isEmpty
        // Older commands cannot restore a value after the newer clear.
        sync(2, text: secret)
        checks["staleSyncCannotRestore"] = field.stringValue.isEmpty
        checks["retireReplied"] = messenger.call(channel, "retire", nil)
        let eventsBeforeRetired = messenger.changedEvents
        field.stringValue = secret
        field.controlTextDidChange(Notification(name: NSControl.textDidChangeNotification, object: field))
        checks["retiredLateEditCannotRestore"] = field.stringValue.isEmpty && messenger.changedEvents == eventsBeforeRetired
        checks["channelRetired"] = messenger.handlers[channel] == nil
        checks["retiredFieldNotExposed"] = count(field) == 0 && count(ordinary) == 1
        let rebuilt = factory.create(withViewIdentifier: 8, arguments: ["label": "密码（仅本次使用）", "identifier": "direct-secret"])
        checks["rebuiltFieldStartsEmpty"] = (rebuilt as? NSSecureTextField)?.stringValue.isEmpty == true
        rebuilt.frame = frame
        document.addSubview(rebuilt)
        checks["rebuiltPasswordIsOnlySecureChild"] = count(rebuilt) == 1 && count(field) == 0
            && (rebuilt.accessibilityParent() as AnyObject?) === window
        _ = messenger.call("herdr.pocket/secure-field/8", "sync", ["revision": 1,
            "enabled": true, "dark": false, "text": secret])
        window.close()
        RunLoop.main.run(until: Date().addingTimeInterval(0.01))
        checks["closedWindowNoRegisteredSecureChild"] = count(rebuilt) == 0
        checks["closedWindowClearsNativeValue"] = (rebuilt as? NSSecureTextField)?.stringValue.isEmpty == true
        checks["closedWindowRetiresChannel"] = messenger.handlers["herdr.pocket/secure-field/8"] == nil
        let passed = checks.values.allSatisfy { $0 }
        let result: [String: Any] = ["schemaVersion": 1, "passed": passed, "checks": checks,
            "nativeChangedEvents": messenger.changedEvents,
            "localAccessibilityValueAvailable": localAX != nil,
            "localAccessibilityValueContainsSecret": localAX?.contains(secret) ?? false,
            "localRoleAvailable": field.accessibilityRole() != nil,
            "localSubroleAvailable": field.accessibilitySubrole() != nil,
            "systemAXVerified": false, "liveDartEngineVerified": false, "visibleWindowShown": false]
        let bytes = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(data: bytes, encoding: .utf8)!)
        if !passed { exit(1) }
    }
}
