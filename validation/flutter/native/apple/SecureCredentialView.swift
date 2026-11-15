import Cocoa
import FlutterMacOS

/// A distinct AppKit secure editor per field. Never uses FlutterTextInputPlugin.
final class HerdrSecureTextField: NSSecureTextField, NSTextFieldDelegate {
    private let channel: FlutterMethodChannel
    private var revision = 0
    private var retired = false
    private var updating = false

    init(viewId: Int64, label: String, identifier: String, messenger: FlutterBinaryMessenger) {
        channel = FlutterMethodChannel(name: "herdr.pocket/secure-field/\(viewId)", binaryMessenger: messenger)
        super.init(frame: .zero)
        self.identifier = NSUserInterfaceItemIdentifier(identifier)
        setAccessibilityIdentifier(identifier)
        setAccessibilityLabel(label)
        isBordered = false
        drawsBackground = false
        font = .systemFont(ofSize: 16)
        usesSingleLineMode = true
        isEnabled = false
        delegate = self
        channel.setMethodCallHandler { [weak self] call, result in
            DispatchQueue.main.async {
                guard let self else {
                    result(FlutterError(code: "secure_field_retired", message: nil, details: nil)); return
                }
                self.handle(call, result: result)
            }
        }
    }

    required init?(coder: NSCoder) { fatalError("Use the registered secure field factory") }

    private func wipe() {
        if let editor = currentEditor() as? NSTextView {
            editor.string = ""
            editor.setSelectedRange(NSRange(location: 0, length: 0))
            editor.undoManager?.removeAllActions()
        }
        _ = abortEditing()
        stringValue = ""
    }

    private func handle(_ call: FlutterMethodCall, result: FlutterResult) {
        if call.method == "retire" {
            updating = true; retired = true; wipe(); isEnabled = false; updating = false
            channel.setMethodCallHandler(nil)
            result(nil); return
        }
        guard call.method == "sync" else { result(FlutterMethodNotImplemented); return }
        guard !retired, let args = call.arguments as? [String: Any],
              let next = args["revision"] as? Int, next > 0,
              let enabled = args["enabled"] as? Bool,
              let dark = args["dark"] as? Bool else {
            result(FlutterError(code: "secure_field_unavailable", message: nil, details: nil)); return
        }
        if args["text"] != nil && !(args["text"] is String) {
            result(FlutterError(code: "secure_field_unavailable", message: nil, details: nil)); return
        }
        guard next >= revision else { result(nil); return }
        let text = args["text"] as? String
        let wasEnabled = isEnabled
        revision = next; updating = true
        appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        if !enabled || (!wasEnabled && text == nil) { wipe() }
        else if let text {
            let editor = currentEditor() as? NSTextView
            if text != stringValue || (text.isEmpty && !(editor?.string.isEmpty ?? true)) {
                if text.isEmpty { wipe() }
                else {
                    stringValue = text
                    editor?.string = text
                    editor?.setSelectedRange(NSRange(location: (text as NSString).length, length: 0))
                }
            }
        }
        isEnabled = enabled
        updating = false
        if text == nil && enabled { controlTextDidChange(Notification(name: NSControl.textDidChangeNotification, object: self)) }
        result(nil)
    }

    func controlTextDidBeginEditing(_ notification: Notification) {
        (currentEditor() as? NSTextView)?.allowsUndo = false
    }

    func controlTextDidChange(_ notification: Notification) {
        guard !updating else { return }
        guard !retired, isEnabled else { updating = true; wipe(); updating = false; return }
        channel.invokeMethod("changed", arguments: ["revision": revision, "text": stringValue])
    }

    deinit { channel.setMethodCallHandler(nil) }
}

final class HerdrSecureCredentialFactory: NSObject, FlutterPlatformViewFactory {
    private let messenger: FlutterBinaryMessenger
    init(messenger: FlutterBinaryMessenger) { self.messenger = messenger }
    func createArgsCodec() -> (FlutterMessageCodec & NSObjectProtocol)? { FlutterStandardMessageCodec.sharedInstance() }
    func create(withViewIdentifier viewId: Int64, arguments args: Any?) -> NSView {
        guard let args = args as? [String: Any], let label = args["label"] as? String,
              let identifier = args["identifier"] as? String,
              (identifier == "direct-secret" && label == "密码（仅本次使用）") ||
              (identifier == "direct-passphrase" && label == "私钥口令（可选）") else { return NSView() }
        return HerdrSecureTextField(viewId: viewId, label: label, identifier: identifier, messenger: messenger)
    }
}

func registerHerdrSecureCredentialFields(registrar: FlutterPluginRegistrar) {
    registrar.register(HerdrSecureCredentialFactory(messenger: registrar.messenger), withId: "herdr.pocket/secure-field")
}
