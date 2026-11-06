import Foundation

@main
struct InputJournalProbe {
    static func main() throws {
        let base = FileManager.default.temporaryDirectory.appendingPathComponent("herdr-journal-probe-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: base) }
        let journal = InputJournalFile(testDirectory: base)
        var checks = 0
        func check(_ value: Bool) throws { guard value else { throw DeviceKeyError.invalidHandle }; checks += 1 }
        func rejects(_ operation: () throws -> Void) throws {
            var failed = false; do { try operation() } catch { failed = true }; try check(failed)
        }
        var fields: [String: Any] = ["schemaVersion":1,"requestId":String(repeating:"a",count:32),"host":"127.0.0.1","port":2222,
            "username":"fixture","hostFingerprint":"SHA256:" + String(repeating:"A",count:43),"session":"probe",
            "socketPath":"/tmp/fixture/herdr/sessions/probe/herdr.sock","paneId":"w1:p1","terminalId":"term_abcd",
            "generation":1,"createdAt":"2026-11-05T00:00:00.000Z"]
        func wire(_ values: [String: Any]) throws -> String {
            String(data:try JSONSerialization.data(withJSONObject:values,options:[.sortedKeys]),encoding:.utf8)!
        }
        let record = try wire(fields)
        try check(try journal.read() == nil)
        try journal.prepare(record:record)
        try check(try InputJournalFile(testDirectory:base).read() == record)
        try rejects { try journal.prepare(record:record) }
        fields["requestId"] = String(repeating:"b",count:32)
        try rejects { try journal.clear(record:wire(fields)) }
        try check(try journal.read() == record)
        fields["body"] = "MUST NEVER BE STORED"
        try rejects { try journal.prepare(record:wire(fields)) }
        fields.removeValue(forKey:"body")
        fields["username"] = "fixture\ncontrol"
        try rejects { try journal.prepare(record:wire(fields)) }
        try rejects { try journal.prepare(record:"{\"schemaVersion\":1," + record.dropFirst()) }
        try journal.clear(record:record); try check(try journal.read() == nil)
        fields["username"] = "fixture"
        let second = try wire(fields); try journal.prepare(record:second)
        try check(try journal.read() == second)
        let catalog = HostCatalogFile(testDirectory:base)
        try check(try catalog.load()["contents"] == "")
        try journal.clear(record:second)
        fields["schemaVersion"] = 2
        fields["route"] = "easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001"
        let routed = try wire(fields); try journal.prepare(record:routed)
        try check(try journal.read() == routed)
        try rejects { try journal.clear(record:second) }
        try journal.clear(record:routed)
        fields["route"] = "easy-tier:0123456789abcdef0123456789abcdef:03:a0000000-0000-4000-8000-000000000001"
        try rejects { try journal.prepare(record:wire(fields)) }
        fields["route"] = "easy-tier:0123456789abcdef0123456789abcdef:2147483648:a0000000-0000-4000-8000-000000000001"
        try rejects { try journal.prepare(record:wire(fields)) }
        fields["route"] = NSNull()
        let nullRoute = try wire(fields); try journal.prepare(record:nullRoute)
        try check(try journal.read() == nullRoute); try journal.clear(record:nullRoute)
        print("{\"checks\":\(checks),\"scope\":\"temporary public unknown-write marker; no command content, Flutter channel or system key store execution\"}")
    }
}
