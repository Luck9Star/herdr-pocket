import Foundation

@main
struct HostCatalogProbe {
    static func main() throws {
        let base = FileManager.default.temporaryDirectory.appendingPathComponent("herdr-catalog-probe-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: base) }
        let store = HostCatalogFile(testDirectory: base)
        var checks = 0
        func check(_ value: Bool) throws { guard value else { throw DeviceKeyError.invalidHandle }; checks += 1 }
        func rejects(_ operation: () throws -> Void) throws {
            var rejected = false
            do { try operation() } catch { rejected = true }
            try check(rejected)
        }
        let initial = try store.load()
        try check(initial["contents"] == "" && initial["revision"] == "")
        let text = "{\"schemaVersion\":1,\"profiles\":[],\"pendingCreation\":null}"
        let revision = try store.save(expected: "", contents: text)
        try check(revision.count == 64)
        let restarted = HostCatalogFile(testDirectory: base)
        let restored = try restarted.load()
        try check(restored["revision"] == revision && restored["contents"] == text)
        try rejects { _ = try store.save(expected: "", contents: "{}") }
        try check(try store.load()["contents"] == text)
        try rejects { _ = try store.save(expected: revision, contents: String(repeating: "x", count: 262145)) }
        let directory = base.appendingPathComponent("dev.herdr.host-catalog-v1")
        let file = directory.appendingPathComponent("catalog.json")
        try Data([0xff, 0xfe, 0x00]).write(to: file)
        try rejects { _ = try store.load() }
        try FileManager.default.removeItem(at: file)
        let victim = base.appendingPathComponent("protected-fixture")
        try Data("UNCHANGED".utf8).write(to: victim)
        try FileManager.default.createSymbolicLink(at: file, withDestinationURL: victim)
        try rejects { _ = try store.load() }
        try rejects { _ = try store.save(expected: "", contents: "{}") }
        try check(try String(contentsOf: victim, encoding: .utf8) == "UNCHANGED")
        try FileManager.default.removeItem(at:file)
        let missing = base.appendingPathComponent("absent-target")
        try FileManager.default.createSymbolicLink(at:file,withDestinationURL:missing)
        try rejects { _ = try store.load() }
        try rejects { _ = try store.save(expected:"",contents:"{}") }
        try check(try FileManager.default.destinationOfSymbolicLink(atPath:file.path) == missing.path)
        try check(!FileManager.default.fileExists(atPath:missing.path))
        print("{\"checks\":\(checks),\"scope\":\"temporary public metadata files; Flutter channel and system key stores NOT RUN\"}")
    }
}
