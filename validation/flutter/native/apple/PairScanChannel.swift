import UIKit

func registerHerdrPairScanner(messenger: FlutterBinaryMessenger) {
    let channel = FlutterMethodChannel(name: "herdr.pocket/pair_scan", binaryMessenger: messenger)
    var active = false
    channel.setMethodCallHandler { call, result in
        guard call.method == "scan" else { result(FlutterMethodNotImplemented); return }
        guard !active else { result(FlutterError(code: "scan_busy", message: nil, details: nil)); return }
        let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .filter { $0.activationState == .foregroundActive }.flatMap { $0.windows }
        guard var presenter = windows.first(where: { $0.isKeyWindow })?.rootViewController else {
            result(FlutterError(code: "camera_unavailable", message: nil, details: nil)); return
        }
        while let next = presenter.presentedViewController { presenter = next }
        active = true
        let scanner = PairScanner()
        scanner.modalPresentationStyle = .fullScreen
        scanner.onFinish = { text, error in
            active = false
            if let error = error { result(FlutterError(code: error, message: nil, details: nil)) } else { result(text) }
        }
        presenter.present(scanner, animated: true)
    }
}
