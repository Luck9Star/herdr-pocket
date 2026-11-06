import Foundation
#if canImport(UIKit)
import UIKit
import UniformTypeIdentifiers
#elseif canImport(AppKit)
import AppKit
import UniformTypeIdentifiers
#endif

// Only system-selected URLs enter this component. No paths cross the app bridge.
enum PocketDocumentError: Error { case busy, unavailable, invalid, io }
// Cancellation wins until the selected destination enters its final write.
// Once writing begins, do not report cancellation before that write resolves.
final class PocketDocumentLease {
    private let lock = NSLock()
    private var active = true
    private var committing = false
    func cancel() -> Bool { lock.lock(); defer { lock.unlock() }; if committing { return false }; active = false; return true }
    func beginWrite() -> Bool { lock.lock(); defer { lock.unlock() }; guard active else { return false }; committing = true; return true }
    func isActive() -> Bool { lock.lock(); defer { lock.unlock() }; return active }
}
enum PocketDocumentWorker {
    static func run<T>(_ job: @escaping () throws -> T, completion: @escaping (Result<T, Error>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try job() }
            DispatchQueue.main.async { completion(result) }
        }
    }
}
enum PocketDocumentIO {
    static let limit = 65586
    static func read(_ url: URL) throws -> Data {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        var coordinationError: NSError?
        var result: Result<Data, Error> = .failure(PocketDocumentError.io)
        NSFileCoordinator().coordinate(readingItemAt: url, options: [], error: &coordinationError) { chosen in
            do {
                let values = try chosen.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
                guard values.isRegularFile == true, let size = values.fileSize, size > 0, size <= limit else { throw PocketDocumentError.invalid }
                let handle = try FileHandle(forReadingFrom: chosen)
                defer { try? handle.close() }
                var bytes = Data()
                while bytes.count <= limit {
                    let part = handle.readData(ofLength: limit + 1 - bytes.count)
                    if part.isEmpty { break }
                    bytes.append(part)
                }
                guard !bytes.isEmpty, bytes.count <= limit else { throw PocketDocumentError.invalid }
                result = .success(bytes)
            } catch { result = .failure(error) }
        }
        if coordinationError != nil { throw PocketDocumentError.io }
        return try result.get()
    }
    static func write(_ bytes: Data, to url: URL, lease: PocketDocumentLease? = nil) throws {
        guard !bytes.isEmpty, bytes.count <= limit else { throw PocketDocumentError.invalid }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        var coordinationError: NSError?
        var failure: Error?
        NSFileCoordinator().coordinate(writingItemAt: url, options: .forReplacing, error: &coordinationError) { chosen in
            if let lease = lease, !lease.beginWrite() { failure = PocketDocumentError.unavailable; return }
            do { try bytes.write(to: chosen, options: .atomic) } catch { failure = error }
        }
        if coordinationError != nil || failure != nil { throw PocketDocumentError.io }
    }
}

#if canImport(UIKit)
final class PocketDocumentPicker: NSObject, UIDocumentPickerDelegate {
    private var completion: ((Result<Data?, Error>) -> Void)?
    private var isSave = false
    private var temporaryDirectory: URL?
    private weak var picker: UIDocumentPickerViewController?
    private var backgroundObserver: NSObjectProtocol?
    private var operation: UUID?
    deinit { cleanup() }
    func open(presenter: UIViewController, completion: @escaping (Result<Data?, Error>) -> Void) {
        guard self.completion == nil else { completion(.failure(PocketDocumentError.busy)); return }
        self.completion = completion; operation = UUID(); isSave = false
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.data], asCopy: false)
        present(picker, from: presenter)
    }
    func save(_ bytes: Data, presenter: UIViewController, completion: @escaping (Result<Data?, Error>) -> Void) {
        guard self.completion == nil else { completion(.failure(PocketDocumentError.busy)); return }
        guard !bytes.isEmpty, bytes.count <= PocketDocumentIO.limit else { completion(.failure(PocketDocumentError.invalid)); return }
        do {
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent("pocket-export-" + UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.protectionKey: FileProtectionType.complete])
            temporaryDirectory = directory
            let file = directory.appendingPathComponent("herdr-pocket.hpkt")
            try bytes.write(to: file, options: [.atomic, .completeFileProtection])
            self.completion = completion; operation = UUID(); isSave = true
            present(UIDocumentPickerViewController(forExporting: [file], asCopy: true), from: presenter)
        } catch { cleanup(); completion(.failure(PocketDocumentError.io)) }
    }
    private func present(_ picker: UIDocumentPickerViewController, from presenter: UIViewController) {
        picker.delegate = self; picker.allowsMultipleSelection = false; self.picker = picker
        backgroundObserver = NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in self?.finish(.success(nil)) }
        presenter.present(picker, animated: true)
    }
    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        guard controller === picker else { return }
        finish(.success(nil))
    }
    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        guard controller === picker else { return }
        guard urls.count == 1 else { finish(.failure(PocketDocumentError.invalid)); return }
        if isSave { finish(.success(Data())) }
        else {
            guard let operation = operation else { return }
            let url = urls[0]
            PocketDocumentWorker.run({ try PocketDocumentIO.read(url) }) { [weak self] result in
                guard let self = self, self.operation == operation else { return }
                self.finish(result.map { Optional($0) })
            }
        }
    }
    private func finish(_ value: Result<Data?, Error>) {
        guard let done = completion else { return }
        completion = nil; operation = nil; picker?.dismiss(animated: true); cleanup(); done(value)
    }
    private func cleanup() {
        if let observer = backgroundObserver { NotificationCenter.default.removeObserver(observer); backgroundObserver = nil }
        if let directory = temporaryDirectory { try? FileManager.default.removeItem(at: directory); temporaryDirectory = nil }
    }
}
#elseif canImport(AppKit)
final class PocketDocumentPicker {
    private var completion: ((Result<Data?, Error>) -> Void)?
    private var lease: PocketDocumentLease?
    private var operation: UUID?
    private var observer: NSObjectProtocol?
    private func start(_ callback: @escaping (Result<Data?, Error>) -> Void) -> (UUID, PocketDocumentLease)? {
        guard completion == nil else { callback(.failure(PocketDocumentError.busy)); return nil }
        let id=UUID(), token=PocketDocumentLease(); completion=callback; operation=id; lease=token
        observer=NotificationCenter.default.addObserver(forName: NSApplication.willTerminateNotification, object:nil, queue:.main) { [weak self] _ in self?.cancel() }
        return (id,token)
    }
    private func finish(_ result: Result<Data?, Error>, id: UUID) {
        guard operation == id, let done=completion else { return }
        completion=nil; operation=nil; lease=nil
        if let observer=observer { NotificationCenter.default.removeObserver(observer); self.observer=nil }
        done(result)
    }
    private func cancel() {
        guard let id=operation, let lease=lease, lease.cancel() else { return }
        finish(.success(nil),id:id)
    }
    func open(completion: @escaping (Result<Data?, Error>) -> Void) {
        guard let (id,token)=start(completion) else { return }
        let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        panel.begin { [self] response in
            guard self.operation == id else { return }
            guard response == .OK, let url = panel.url else { self.cancel(); return }
            PocketDocumentWorker.run({ try PocketDocumentIO.read(url) }) { result in
                if token.isActive() { self.finish(result.map { Optional($0) },id:id) }
            }
        }
    }
    func save(_ bytes: Data, completion: @escaping (Result<Data?, Error>) -> Void) {
        guard !bytes.isEmpty, bytes.count <= PocketDocumentIO.limit else { completion(.failure(PocketDocumentError.invalid)); return }
        guard let (id,token)=start(completion) else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = "herdr-pocket.hpkt"; panel.canCreateDirectories = true
        panel.begin { [self] response in
            guard self.operation == id else { return }
            guard response == .OK, let url = panel.url else { self.cancel(); return }
            PocketDocumentWorker.run({ try PocketDocumentIO.write(bytes,to:url,lease:token); return Data() }) { result in
                if token.isActive() { self.finish(result.map { Optional($0) },id:id) }
            }
        }
    }
}
#endif
