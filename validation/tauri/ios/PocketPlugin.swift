import Foundation
import Tauri
import UIKit

private struct KeyArgs: Decodable {
    let handle: String
    let payload: String
}
private struct DocumentArgs: Decodable { let data: String }

// The only key material returned to Rust is a public key or a signature.
final class PocketPlugin: Plugin {
    private let worker = DispatchQueue(label: "dev.herdr.pocket.ios.keys")
    private let keys = PocketKeyBridge(backend: AppleKeychainSeedBackend())
    private var scanning = false // main queue only
    private let documents = PocketDocumentPicker()

    @objc public func openDocument(_ invoke: Invoke) {
        DispatchQueue.main.async { [self] in
            guard var presenter = self.manager.viewController else { invoke.reject("document_unavailable"); return }
            while let next = presenter.presentedViewController { presenter = next }
            guard presenter.viewIfLoaded?.window != nil else { invoke.reject("document_unavailable"); return }
            self.documents.open(presenter: presenter) { result in
                switch result {
                case .failure: invoke.reject("document_unavailable")
                case .success(let data):
                    if let data = data { invoke.resolve(["data": data.base64EncodedString()]) }
                    else { invoke.resolve([String: String]()) }
                }
            }
        }
    }

    @objc public func saveDocument(_ invoke: Invoke) {
        DispatchQueue.main.async { [self] in
            guard let args = try? invoke.parseArgs(DocumentArgs.self), args.data.utf8.count <= 87448,
                  let bytes = Data(base64Encoded: args.data), !bytes.isEmpty, bytes.count <= PocketDocumentIO.limit,
                  var presenter = self.manager.viewController else { invoke.reject("document_unavailable"); return }
            while let next = presenter.presentedViewController { presenter = next }
            guard presenter.viewIfLoaded?.window != nil else { invoke.reject("document_unavailable"); return }
            self.documents.save(bytes, presenter: presenter) { result in
                switch result {
                case .failure: invoke.reject("document_unavailable")
                case .success(let value): invoke.resolve(["saved": value != nil])
                }
            }
        }
    }

    @objc public func create(_ invoke: Invoke) {
        worker.async {
            do {
                let created = try self.keys.create()
                invoke.resolve(["handle": created.handle, "publicKey": created.publicKey])
            } catch { invoke.reject("device_key_unavailable") }
        }
    }

    @objc public func publicKey(_ invoke: Invoke) {
        worker.async {
            do {
                let args = try invoke.parseArgs(KeyArgs.self)
                invoke.resolve(["publicKey": try self.keys.publicKey(args.handle)])
            } catch { invoke.reject("device_key_unavailable") }
        }
    }

    @objc public func sign(_ invoke: Invoke) {
        worker.async {
            do {
                let args = try invoke.parseArgs(KeyArgs.self)
                invoke.resolve(["signature": try self.keys.sign(args.handle, base64: args.payload)])
            } catch { invoke.reject("device_key_unavailable") }
        }
    }

    @objc public func delete(_ invoke: Invoke) {
        worker.async {
            do {
                let args = try invoke.parseArgs(KeyArgs.self)
                try self.keys.delete(args.handle)
                invoke.resolve([String: String]())
            } catch { invoke.reject("device_key_unavailable") }
        }
    }

    @objc public func privateConfigRoot(_ invoke: Invoke) {
        worker.async {
            do {
                let base = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                       appropriateFor: nil, create: true)
                var directory = base.appendingPathComponent("HerdrPocketPrivate", isDirectory: true)
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                        attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
                var values = URLResourceValues()
                values.isExcludedFromBackup = true
                try directory.setResourceValues(values)
                invoke.resolve(["path": directory.path])
            } catch { invoke.reject("host_storage_unavailable") }
        }
    }

    @objc public func scan(_ invoke: Invoke) {
        DispatchQueue.main.async { [self] in
            guard !self.scanning, var presenter = self.manager.viewController else {
                invoke.reject("camera_unavailable_or_busy"); return
            }
            while let next = presenter.presentedViewController { presenter = next }
            self.scanning = true
            let scanner = PairScanner()
            scanner.modalPresentationStyle = .fullScreen
            scanner.onFinish = { [weak self] text, error in
                self?.scanning = false
                guard let text = text, error == nil, !text.isEmpty, text.utf8.count <= 2048 else {
                    invoke.reject(error ?? "invalid_public_response"); return
                }
                invoke.resolve(["text": text])
            }
            presenter.present(scanner, animated: true)
        }
    }
}

@_cdecl("init_plugin_herdr_pocket_ios")
public func initPocketPlugin() -> Plugin { PocketPlugin() }
