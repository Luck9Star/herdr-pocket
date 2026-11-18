import Cocoa
import FlutterMacOS

/// App-owned AX exposure; never reads or rewrites the Flutter semantics root.
private final class HerdrSecureAccessibilityRegistry {
    static let shared = HerdrSecureAccessibilityRegistry()
    private let windows = NSHashTable<NSWindow>.weakObjects()
    private let fields = NSHashTable<HerdrSecureTextField>.weakObjects()
    private var closeObservers: [ObjectIdentifier: NSObjectProtocol] = [:]

    func register(_ window: NSWindow) {
        guard !windows.contains(window) else { return }
        windows.add(window)
        let identity = ObjectIdentifier(window)
        closeObservers[identity] = NotificationCenter.default.addObserver(
            forName: NSWindow.willCloseNotification, object: window, queue: .main) { [weak window] _ in
                guard let window else { return }
                Self.shared.windows.remove(window)
                for field in Self.shared.fields.allObjects where field.window === window { field.retire() }
                if let observer = Self.shared.closeObservers.removeValue(forKey: identity) {
                    NotificationCenter.default.removeObserver(observer)
                }
            }
    }

    func exposed(_ field: HerdrSecureTextField, in window: NSWindow) -> Bool {
        guard windows.contains(window), field.window === window, !field.retired,
              !field.isHiddenOrHasHiddenAncestor, !field.bounds.isEmpty,
              let content = window.contentView else { return false }
        let visible = field.bounds.intersection(field.visibleRect)
        return !visible.isEmpty && !field.convert(visible, to: content).intersection(content.bounds).isEmpty
    }

    func moved(_ field: HerdrSecureTextField, from previous: NSWindow?, to current: NSWindow?) {
        fields.remove(field)
        if current != nil && !field.retired { fields.add(field) }
        if let previous, windows.contains(previous) { NSAccessibility.post(element: previous, notification: .layoutChanged) }
        if let current, current !== previous, windows.contains(current) { NSAccessibility.post(element: current, notification: .layoutChanged) }
    }

    func remove(_ field: HerdrSecureTextField) {
        fields.remove(field)
        if let window = field.window, windows.contains(window) {
            NSAccessibility.post(element: window, notification: .layoutChanged)
        }
    }

    func children(in window: NSWindow, preserving original: [Any]?) -> [Any]? {
        guard windows.contains(window) else { return original }
        var result = original ?? []
        let visible = fields.allObjects.filter { exposed($0, in: window) }.sorted {
            let lhs = $0.convert($0.bounds, to: nil), rhs = $1.convert($1.bounds, to: nil)
            return lhs.maxY == rhs.maxY ? lhs.minX < rhs.minX : lhs.maxY > rhs.maxY
        }
        for field in visible where !result.contains(where: { ($0 as AnyObject) === field }) { result.append(field) }
        return result.isEmpty && original == nil ? nil : result
    }
}

func registerHerdrSecureAccessibilityWindow(_ window: NSWindow) {
    HerdrSecureAccessibilityRegistry.shared.register(window)
}

func herdrSecureAccessibilityChildren(window: NSWindow, preserving original: [Any]?) -> [Any]? {
    HerdrSecureAccessibilityRegistry.shared.children(in: window, preserving: original)
}

/// A distinct AppKit secure editor per field. Never uses FlutterTextInputPlugin.
final class HerdrSecureTextField: NSSecureTextField, NSTextFieldDelegate {
    private let channel: FlutterMethodChannel
    private var revision = 0
    fileprivate var retired = false
    private var updating = false
    private weak var previousAccessibilityWindow: NSWindow?

    init(viewId: Int64, label: String, identifier: String, messenger: FlutterBinaryMessenger) {
        channel = FlutterMethodChannel(name: "herdr.pocket/secure-field/\(viewId)", binaryMessenger: messenger)
        super.init(frame: .zero)
        self.identifier = NSUserInterfaceItemIdentifier(identifier)
        setAccessibilityIdentifier(identifier)
        setAccessibilityLabel(label)
        setAccessibilityElement(true)
        setAccessibilityRole(.textField)
        setAccessibilitySubrole(.secureTextField)
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

    override func viewDidMoveToWindow() {
        let previous = previousAccessibilityWindow
        super.viewDidMoveToWindow()
        previousAccessibilityWindow = window
        HerdrSecureAccessibilityRegistry.shared.moved(self, from: previous, to: window)
    }

    override func accessibilityParent() -> Any? {
        if let window, HerdrSecureAccessibilityRegistry.shared.exposed(self, in: window) { return window }
        return super.accessibilityParent()
    }

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
            retire()
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

    fileprivate func retire() {
        updating = true; retired = true; wipe(); isEnabled = false; updating = false
        HerdrSecureAccessibilityRegistry.shared.remove(self)
        channel.setMethodCallHandler(nil)
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
