import Foundation
import CryptoKit
import Darwin

// Versioned public metadata only. A missing/corrupt catalog is never rebuilt over
// existing bytes. Native CAS rejects a stale writer, including another process.
final class HostCatalogFile {
    private let testDirectory: URL?
    private let namespace: String
    init(testDirectory: URL? = nil, namespace: String = "dev.herdr.host-catalog-v1") {
        precondition(["dev.herdr.host-catalog-v1", "dev.herdr.input-journal-v1"].contains(namespace))
        self.testDirectory = testDirectory; self.namespace = namespace
    }
    private func directory() throws -> URL {
        let base = try testDirectory ?? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        var url = base.appendingPathComponent(namespace, isDirectory: true)
        if FileManager.default.fileExists(atPath: url.path) {
            guard try url.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink != true else { throw DeviceKeyError.invalidHandle }
        }
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        var excluded = URLResourceValues(); excluded.isExcludedFromBackup = true
        try url.setResourceValues(excluded)
        return url
    }
    private func current(_ dir: URL) throws -> Data? {
        let file = dir.appendingPathComponent("catalog.json")
        guard FileManager.default.fileExists(atPath: file.path) else { return nil }
        let props = try file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard props.isRegularFile == true, props.isSymbolicLink != true,
              let size = props.fileSize, (1...262144).contains(size) else { throw DeviceKeyError.invalidHandle }
        let bytes = try Data(contentsOf: file)
        guard (1...262144).contains(bytes.count), String(data: bytes, encoding: .utf8) != nil else { throw DeviceKeyError.invalidHandle }
        return bytes
    }
    private func revision(_ bytes: Data?) -> String {
        guard let bytes else { return "" }
        return SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
    }
    private func locked<T>(_ operation: (URL) throws -> T) throws -> T {
        let dir = try directory(), path = dir.appendingPathComponent("catalog.lock")
        let fd = Darwin.open(path.path, O_CREAT | O_RDWR | O_NOFOLLOW, S_IRUSR | S_IWUSR)
        guard fd >= 0 else { throw DeviceKeyError.invalidHandle }
        defer { Darwin.close(fd) }
        guard flock(fd, LOCK_EX) == 0 else { throw DeviceKeyError.invalidHandle }
        defer { flock(fd, LOCK_UN) }
        return try operation(dir)
    }
    func load() throws -> [String: String] {
        try locked { dir in
            let bytes = try current(dir)
            return ["revision": revision(bytes), "contents": bytes.flatMap { String(data: $0, encoding: .utf8) } ?? ""]
        }
    }
    func save(expected: String, contents: String) throws -> String {
        try locked { dir in
            guard (expected.isEmpty || expected.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil),
                  let bytes = contents.data(using: .utf8), (1...262144).contains(bytes.count),
                  revision(try current(dir)) == expected else { throw DeviceKeyError.invalidHandle }
            var file = dir.appendingPathComponent("catalog.json")
            try bytes.write(to: file, options: .atomic)
            var excluded = URLResourceValues(); excluded.isExcludedFromBackup = true
            try file.setResourceValues(excluded)
            #if os(iOS)
            try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: file.path)
            #endif
            let fd = Darwin.open(file.path, O_RDONLY | O_NOFOLLOW)
            guard fd >= 0 else { throw DeviceKeyError.invalidHandle }
            defer { Darwin.close(fd) }
            guard fsync(fd) == 0 else { throw DeviceKeyError.invalidHandle }
            let parent = Darwin.open(dir.path, O_RDONLY)
            guard parent >= 0 else { throw DeviceKeyError.invalidHandle }
            defer { Darwin.close(parent) }
            guard fsync(parent) == 0 else { throw DeviceKeyError.invalidHandle }
            return revision(bytes)
        }
    }
}

func registerHerdrHostCatalog(messenger: FlutterBinaryMessenger) {
    let channel = FlutterMethodChannel(name: "dev.herdr/host-catalog", binaryMessenger: messenger)
    let worker = DispatchQueue(label: "dev.herdr.host-catalog")
    let store = HostCatalogFile()
    channel.setMethodCallHandler { call, result in
        guard ["load", "save"].contains(call.method) else { result(FlutterMethodNotImplemented); return }
        worker.async {
            do {
                let value: Any
                if call.method == "load" { value = try store.load() }
                else {
                    guard let args = call.arguments as? [String: Any], let expected = args["expected"] as? String,
                          let contents = args["contents"] as? String else { throw DeviceKeyError.invalidHandle }
                    value = try store.save(expected: expected, contents: contents)
                }
                DispatchQueue.main.async { result(value) }
            } catch {
                DispatchQueue.main.async { result(FlutterError(code: "catalog_unavailable", message: "Local host catalog unavailable or changed", details: nil)) }
            }
        }
    }
}
