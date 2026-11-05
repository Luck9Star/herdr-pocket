import AVFoundation
import UIKit

/// iOS camera input only. The caller receives public text and still reviews it.
final class PairScanner: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onFinish: ((String?, String?) -> Void)?
    private let session = AVCaptureSession()
    private let work = DispatchQueue(label: "dev.herdr.pair-camera")
    private lazy var preview = AVCaptureVideoPreviewLayer(session: session)
    private var started = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        preview.videoGravity = .resizeAspectFill
        view.layer.addSublayer(preview)
        let cancel = UIButton(type: .system)
        cancel.setTitle("取消扫描", for: .normal)
        cancel.backgroundColor = .systemBackground
        cancel.layer.cornerRadius = 10
        cancel.translatesAutoresizingMaskIntoConstraints = false
        cancel.addTarget(self, action: #selector(cancelScan), for: .touchUpInside)
        view.addSubview(cancel)
        NSLayoutConstraint.activate([
            cancel.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 16),
            cancel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
            cancel.widthAnchor.constraint(greaterThanOrEqualToConstant: 90),
            cancel.heightAnchor.constraint(greaterThanOrEqualToConstant: 44)
        ])
    }
    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview.frame = view.bounds
    }
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        guard !started else { return }
        started = true
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: startCapture()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] allowed in
                DispatchQueue.main.async {
                    if allowed { self?.startCapture() } else { self?.finish(nil, "camera_permission_denied") }
                }
            }
        default: finish(nil, "camera_permission_denied")
        }
    }
    private func startCapture() {
        guard onFinish != nil else { return }
        work.async { [weak self] in
            guard let self = self else { return }
            guard let camera = AVCaptureDevice.default(for: .video),
                  let input = try? AVCaptureDeviceInput(device: camera), self.session.canAddInput(input) else {
                DispatchQueue.main.async { self.finish(nil, "camera_unavailable") }; return
            }
            self.session.addInput(input)
            let output = AVCaptureMetadataOutput()
            guard self.session.canAddOutput(output) else {
                DispatchQueue.main.async { self.finish(nil, "camera_unavailable") }; return
            }
            self.session.addOutput(output)
            guard output.availableMetadataObjectTypes.contains(.qr) else {
                DispatchQueue.main.async { self.finish(nil, "camera_unavailable") }; return
            }
            output.setMetadataObjectsDelegate(self, queue: .main)
            output.metadataObjectTypes = [.qr]
            self.session.startRunning()
        }
    }
    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard let code = objects.compactMap({ $0 as? AVMetadataMachineReadableCodeObject }).first(where: { $0.type == .qr }),
              let value = code.stringValue else { return }
        guard !value.isEmpty && value.utf8.count <= 2048 else { finish(nil, "invalid_public_response"); return }
        finish(value, nil)
    }
    @objc private func cancelScan() { finish(nil, "scan_cancelled") }
    private func finish(_ text: String?, _ error: String?) {
        guard let callback = onFinish else { return }
        onFinish = nil
        let capture = session
        work.async { if capture.isRunning { capture.stopRunning() } }
        dismiss(animated: true) { callback(text, error) }
    }
}
