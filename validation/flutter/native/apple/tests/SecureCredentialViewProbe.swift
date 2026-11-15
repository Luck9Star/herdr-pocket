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
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 400, height: 240),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        field.frame = NSRect(x: 20, y: 120, width: 340, height: 40)
        let ordinary = NSTextField(frame: NSRect(x: 20, y: 40, width: 340, height: 40))
        let appKitSecureBaseline = NSSecureTextField(frame: .zero)
        let publicMarker = UUID().uuidString
        ordinary.stringValue = publicMarker
        window.contentView?.addSubview(field); window.contentView?.addSubview(ordinary)
        sync(1, text: "")
        checks["secureClass"] = field is NSSecureTextField
        checks["roleMatchesAppKitSecureBaseline"] = field.accessibilityRole() == appKitSecureBaseline.accessibilityRole()
        checks["subroleMatchesAppKitSecureBaseline"] = field.accessibilitySubrole() == appKitSecureBaseline.accessibilitySubrole()
        checks["labelPreserved"] = field.accessibilityLabel() == "私钥口令（可选）"
        checks["identifierPreserved"] = field.accessibilityIdentifier() == "direct-passphrase"
        checks["emptyFieldCanFocus"] = window.makeFirstResponder(field) && field.currentEditor() != nil
        let editorBefore = window.firstResponder
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
        let rebuilt = factory.create(withViewIdentifier: 8, arguments: ["label": "密码（仅本次使用）", "identifier": "direct-secret"])
        checks["rebuiltFieldStartsEmpty"] = (rebuilt as? NSSecureTextField)?.stringValue.isEmpty == true
        window.close()
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
