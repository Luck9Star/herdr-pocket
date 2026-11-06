import Foundation

func registerHerdrConfigDocuments(messenger: FlutterBinaryMessenger) {
    let picker = PocketDocumentPicker()
    let channel = FlutterMethodChannel(name: "herdr.pocket/config_document", binaryMessenger: messenger)
    channel.setMethodCallHandler { call, result in
        DispatchQueue.main.async {
            let finish: (Result<Data?, Error>) -> Void = { outcome in
                switch outcome {
                case .failure: result(FlutterError(code: "document_unavailable", message: "Document operation unavailable", details: nil))
                case .success(let bytes):
                    if call.method == "open" { result(bytes.map { FlutterStandardTypedData(bytes: $0) }) }
                    else { result(bytes != nil) }
                }
            }
            #if canImport(UIKit)
            guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first(where: { $0.activationState == .foregroundActive }),
                  var presenter = scene.windows.first(where: { $0.isKeyWindow })?.rootViewController else {
                result(FlutterError(code: "document_unavailable", message: "No active window", details: nil)); return
            }
            while let next = presenter.presentedViewController { presenter = next }
            guard presenter.viewIfLoaded?.window != nil else { result(FlutterError(code: "document_unavailable", message: "No active window", details: nil)); return }
            if call.method == "open" { picker.open(presenter: presenter, completion: finish); return }
            if call.method == "save", let bytes = call.arguments as? FlutterStandardTypedData { picker.save(bytes.data, presenter: presenter, completion: finish); return }
            #elseif canImport(AppKit)
            if call.method == "open" { picker.open(completion: finish); return }
            if call.method == "save", let bytes = call.arguments as? FlutterStandardTypedData { picker.save(bytes.data, completion: finish); return }
            #endif
            result(FlutterMethodNotImplemented)
        }
    }
}
