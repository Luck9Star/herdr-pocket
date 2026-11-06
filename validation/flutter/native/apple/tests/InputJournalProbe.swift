import Foundation

@main
struct InputJournalProbe {
    static func main() throws {
        if CommandLine.arguments.count == 4, CommandLine.arguments[1] == "owner" {
            let directory = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
            let record = String(data: Data(base64Encoded: CommandLine.arguments[3])!, encoding: .utf8)!
            let store = InputJournalFile(testDirectory: directory)
            _ = try store.prepare(record: record)
            print("READY"); fflush(stdout)
            _ = readLine()
            return
        }
        let base = FileManager.default.temporaryDirectory.appendingPathComponent("herdr-journal-probe-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: base) }
        let journal = InputJournalFile(testDirectory: base)
        let sibling = InputJournalFile(testDirectory: base.appendingPathComponent(".", isDirectory: true))
        let disk = HostCatalogFile(testDirectory: base, namespace: "dev.herdr.input-journal-v1")
        var checks = 0
        func check(_ value: Bool) throws { guard value else { throw DeviceKeyError.invalidHandle }; checks += 1 }
        func rejects(_ operation: () throws -> Void) throws {
            var failed = false; do { try operation() } catch { failed = true }; try check(failed)
        }
        var fields: [String: Any] = ["schemaVersion":1,"requestId":String(repeating:"a",count:32),"host":"host.invalid","port":22,
            "username":"fixture","hostFingerprint":"SHA256:" + String(repeating:"A",count:43),"session":"probe",
            "socketPath":"/tmp/fixture/herdr/sessions/probe/herdr.sock","paneId":"w1:p1","terminalId":"term_abcd",
            "generation":1,"createdAt":"2026-11-05T00:00:00.000Z"]
        func wire(_ values: [String: Any]) throws -> String {
            String(data:try JSONSerialization.data(withJSONObject:values,options:[.sortedKeys]),encoding:.utf8)!
        }
        func rawWrite(_ text: String) throws {
            let old = try disk.load(); _ = try disk.save(expected: old["revision"]!, contents: text)
        }
        let original = try wire(fields)
        try check(try journal.readAll().isEmpty)
        try rawWrite(original)
        try check(try journal.read() == original && journal.readAll() == [original])
        fields["paneId"] = "w1:p2"; fields["terminalId"] = "term_abce"; fields["requestId"] = String(repeating:"b",count:32)
        let second = try wire(fields), secondLease = try sibling.prepare(record: second)
        try check(secondLease.range(of:"^[a-f0-9]{32}$",options:.regularExpression) != nil)
        try check(try journal.readAll() == [original,second])
        try rejects { _ = try journal.read() }; try rejects { try journal.clear(record: original) }
        try rejects { try journal.resolve(record: second) }
        let changedRequest = second.replacingOccurrences(of:String(repeating:"b",count:32),with:String(repeating:"c",count:32))
        try rejects { _ = try journal.prepare(record: changedRequest) }
        try rejects { try journal.complete(record: changedRequest, lease: secondLease) }
        try rejects { try journal.abandon(record: changedRequest, lease: secondLease) }
        try rejects { try journal.complete(record: second, lease: String(repeating:"0",count:32)) }
        try rejects { try journal.abandon(record: second, lease: String(repeating:"0",count:32)) }
        try journal.resolve(record: original)
        try sibling.abandon(record: second, lease: secondLease)
        try check(try journal.readAll() == [second])
        try rejects { _ = try journal.prepare(record: second) }
        try rejects { _ = try journal.prepare(record: changedRequest) }
        try rejects { try journal.resolve(record: changedRequest) }
        try journal.resolve(record: second)
        let oldLease = try journal.prepare(record: original)
        try journal.complete(record: original, lease: oldLease)
        let newLease = try sibling.prepare(record: original)
        try check(oldLease != newLease)
        try rejects { try journal.complete(record: original, lease: oldLease) }
        try rejects { try journal.abandon(record: original, lease: oldLease) }
        try journal.complete(record: original, lease: newLease)
        let group = DispatchGroup(), queue = DispatchQueue(label:"journal-probe-concurrent",attributes:.concurrent)
        let resultLock = NSLock(); var winners: [String] = []
        for _ in 0..<8 { group.enter(); queue.async {
            defer { group.leave() }
            if let token = try? InputJournalFile(testDirectory:base).prepare(record:original) {
                resultLock.lock(); winners.append(token); resultLock.unlock()
            }
        } }
        group.wait(); try check(winners.count == 1)
        try journal.abandon(record:original,lease:winners[0]); try journal.resolve(record:original)
        // Composed and decomposed spellings are distinct SSH usernames and
        // must remain byte-distinct both in endpoint keys and raw ownership.
        fields["paneId"] = "w1:p1"; fields["terminalId"] = "term_abcd"; fields["requestId"] = String(repeating:"d",count:32)
        fields["username"] = "caf\u{e9}"; let composed = try wire(fields)
        fields["username"] = "cafe\u{301}"; fields["requestId"] = String(repeating:"e",count:32)
        let decomposed = try wire(fields)
        let composedLease = try journal.prepare(record:composed), decomposedLease = try sibling.prepare(record:decomposed)
        let unicodeRows = try journal.readAll()
        try check(unicodeRows.count == 2 && unicodeRows.map { Data($0.utf8) } == [Data(composed.utf8), Data(decomposed.utf8)])
        let wrongRaw = composed.replacingOccurrences(of:"caf\u{e9}",with:"cafe\u{301}")
        try rejects { try journal.complete(record:wrongRaw,lease:composedLease) }
        try journal.abandon(record:composed,lease:composedLease); try sibling.abandon(record:decomposed,lease:decomposedLease)
        try rejects { try journal.resolve(record:wrongRaw) }
        try journal.resolve(record:composed); try journal.resolve(record:decomposed)
        fields["username"] = "fixture"
        fields["paneId"] = "w1:p1"; fields["terminalId"] = "term_abcd"; fields["schemaVersion"] = 2; fields["route"] = NSNull()
        let nullRoute = try wire(fields), nullLease = try journal.prepare(record: nullRoute)
        try rejects { _ = try sibling.prepare(record: original) } // v1 and null route share an endpoint.
        try journal.complete(record: nullRoute, lease: nullLease)
        fields["route"] = "easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001"
        let routed = try wire(fields), legacyLease = try journal.prepare(record:original), routedLease = try sibling.prepare(record:routed)
        try check(try journal.readAll().count == 2)
        try journal.complete(record:original,lease:legacyLease); try sibling.complete(record:routed,lease:routedLease)
        var leases: [(String,String)] = []
        fields["schemaVersion"] = 1; fields.removeValue(forKey:"route")
        for n in 0..<32 {
            fields["paneId"] = "w1:p\(n)"; fields["terminalId"] = "term_\(String(n+1,radix:16))"
            let raw = try wire(fields); leases.append((raw,try journal.prepare(record:raw)))
        }
        try check(try journal.readAll().count == 32)
        fields["paneId"] = "w1:p99"; fields["terminalId"] = "term_ff"
        try rejects { _ = try journal.prepare(record: wire(fields)) }
        for (raw,lease) in leases { try journal.complete(record:raw,lease:lease) }
        try check(try journal.readAll().isEmpty)
        try rejects { _ = try journal.prepare(record: original.replacingOccurrences(of:"\"schemaVersion\":1",with:"\"schemaVersion\":1.0")) }
        try rejects { _ = try journal.prepare(record: original.replacingOccurrences(of:"\"port\":22",with:"\"port\":22.0")) }
        try rejects { _ = try journal.prepare(record: "{\"schemaVersion\":1," + original.dropFirst()) }
        try rawWrite("{\"schemaVersion\":3,\"records\":[],\"records\":[]}")
        try rejects { _ = try journal.readAll() }
        try rawWrite("{\"schemaVersion\":3.0,\"records\":[]}")
        try rejects { _ = try journal.readAll() }
        try rawWrite("{\"schemaVersion\":4,\"records\":[]}")
        try rejects { _ = try journal.readAll() }
        let duplicate = try JSONSerialization.data(withJSONObject:["schemaVersion":3,"records":[original,original]],options:[.sortedKeys])
        try rawWrite(String(data:duplicate,encoding:.utf8)!)
        try rejects { _ = try journal.readAll() }
        let duplicateTarget = try JSONSerialization.data(withJSONObject:["schemaVersion":3,"records":[original,original.replacingOccurrences(of:String(repeating:"a",count:32),with:String(repeating:"c",count:32))]],options:[.sortedKeys])
        try rawWrite(String(data:duplicateTarget,encoding:.utf8)!)
        try rejects { _ = try journal.readAll() }
        try rawWrite("{}")
        let beforeOversize = try disk.load()
        try rejects { _ = try disk.save(expected:beforeOversize["revision"]!,contents:String(repeating:"x",count:262145)) }
        try check(try disk.load()["contents"] == "{}")
        let linkBase = base.appendingPathComponent("symlink",isDirectory:true)
        let linkDir = linkBase.appendingPathComponent("dev.herdr.input-journal-v1",isDirectory:true)
        try FileManager.default.createDirectory(at:linkDir,withIntermediateDirectories:true)
        let target = base.appendingPathComponent("owner-target"); try Data("fixture".utf8).write(to:target)
        try FileManager.default.createSymbolicLink(at:linkDir.appendingPathComponent("owner.lock"),withDestinationURL:target)
        try rejects { _ = try InputJournalFile(testDirectory:linkBase).readAll() }
        // A dangling catalog symlink is corruption, not a missing journal.
        // Neither read nor mutation may overwrite it or its target.
        let danglingBase = base.appendingPathComponent("dangling",isDirectory:true)
        let danglingDir = danglingBase.appendingPathComponent("dev.herdr.input-journal-v1",isDirectory:true)
        try FileManager.default.createDirectory(at:danglingDir,withIntermediateDirectories:true)
        let danglingLink = danglingDir.appendingPathComponent("catalog.json")
        let absentTarget = danglingBase.appendingPathComponent("missing-target")
        try FileManager.default.createSymbolicLink(at:danglingLink,withDestinationURL:absentTarget)
        let dangling = InputJournalFile(testDirectory:danglingBase)
        try rejects { _ = try dangling.readAll() }
        try rejects { _ = try dangling.prepare(record:original) }
        try check((try FileManager.default.destinationOfSymbolicLink(atPath:danglingLink.path)) == absentTarget.path)
        try check(!FileManager.default.fileExists(atPath:absentTarget.path))
        let missing = InputJournalFile(testDirectory:base.appendingPathComponent("truly-absent",isDirectory:true))
        try check(try missing.readAll().isEmpty)
        let danglingHostBase = base.appendingPathComponent("dangling-host",isDirectory:true)
        let danglingHostDir = danglingHostBase.appendingPathComponent("dev.herdr.host-catalog-v1",isDirectory:true)
        try FileManager.default.createDirectory(at:danglingHostDir,withIntermediateDirectories:true)
        let danglingHost = danglingHostDir.appendingPathComponent("catalog.json")
        try FileManager.default.createSymbolicLink(at:danglingHost,withDestinationURL:absentTarget)
        let host = HostCatalogFile(testDirectory:danglingHostBase)
        try rejects { _ = try host.load() }
        try rejects { _ = try host.save(expected:"",contents:"{}") }
        try check((try FileManager.default.destinationOfSymbolicLink(atPath:danglingHost.path)) == absentTarget.path)
        // An owner that has observed a persisted table must not interpret a
        // later missing file as a new installation or erase pending state.
        let removedBase = base.appendingPathComponent("removed-after-prepare",isDirectory:true)
        let removed = InputJournalFile(testDirectory:removedBase)
        try check(try removed.readAll().isEmpty)
        let removedLease = try removed.prepare(record:original)
        try removed.abandon(record:original,lease:removedLease)
        let removedFile = removedBase.appendingPathComponent("dev.herdr.input-journal-v1/catalog.json")
        try FileManager.default.removeItem(at:removedFile)
        try rejects { _ = try removed.readAll() }
        try rejects { _ = try InputJournalFile(testDirectory:removedBase).readAll() }
        try rejects { _ = try removed.prepare(record:original) }
        try check(!FileManager.default.fileExists(atPath:removedFile.path))
        let readOnlyBase = base.appendingPathComponent("removed-after-legacy-read",isDirectory:true)
        let legacyDisk = HostCatalogFile(testDirectory:readOnlyBase, namespace:"dev.herdr.input-journal-v1")
        _ = try legacyDisk.save(expected:"",contents:original)
        let reader = InputJournalFile(testDirectory:readOnlyBase)
        try check(try reader.readAll().map { Data($0.utf8) } == [Data(original.utf8)])
        try FileManager.default.removeItem(at:readOnlyBase.appendingPathComponent("dev.herdr.input-journal-v1/catalog.json"))
        try rejects { _ = try reader.readAll() }
        // Real subprocess holds the owner lock while a second process refuses
        // access. Process exit releases ownership, never the pending marker.
        let processBase = base.appendingPathComponent("subprocess",isDirectory:true)
        try FileManager.default.createDirectory(at:processBase,withIntermediateDirectories:true)
        let process = Process(); process.executableURL = URL(fileURLWithPath:CommandLine.arguments[0])
        process.arguments = ["owner",processBase.path,Data(original.utf8).base64EncodedString()]
        let input = Pipe(), output = Pipe(); process.standardInput = input; process.standardOutput = output
        try process.run()
        var ready = Data()
        while let byte = try output.fileHandleForReading.read(upToCount:1), !byte.isEmpty {
            ready.append(byte); if byte == Data([10]) { break }
        }
        try check(String(data:ready,encoding:.utf8) == "READY\n")
        let recovering = InputJournalFile(testDirectory:processBase)
        try rejects { _ = try recovering.readAll() }
        try input.fileHandleForWriting.write(contentsOf:Data("\n".utf8)); try input.fileHandleForWriting.close()
        process.waitUntilExit(); try check(process.terminationStatus == 0)
        try check(try recovering.readAll() == [original]); try recovering.resolve(record:original)
        try check(try recovering.readAll().isEmpty)
        print("{\"checks\":\(checks),\"scope\":\"real Swift journal, temporary files and subprocess; Flutter and mobile device not exercised\"}")
    }
}
