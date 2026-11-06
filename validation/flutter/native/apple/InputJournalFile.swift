import Foundation
import CoreFoundation
import Security
import Darwin

final class InputJournalFile {
    private let storage: HostCatalogFile
    private let testDirectory: URL?
    // Swift String equality is canonically equivalent; SSH identity and
    // original marker ownership instead require exact UTF-8 bytes.
    private struct Endpoint: Hashable { let fields: [Data]; let port: Int }
    private struct Active: Equatable { let raw: Data, lease: String }
    private final class Owner {
        let fd: Int32
        let lock = NSRecursiveLock()
        var active: [Endpoint: Active] = [:]
        var knownStore = false
        init(_ fd: Int32) { self.fd = fd }
        deinit { flock(fd, LOCK_UN); Darwin.close(fd) }
    }
    private static let registryLock = NSLock()
    // Strong process-lifetime ownership makes Activity/engine replacement and
    // Swift object deinit unable to discard another live send's active lease.
    private static var owners: [String: Owner] = [:]
    init(testDirectory: URL? = nil) {
        self.testDirectory = testDirectory
        storage = HostCatalogFile(testDirectory: testDirectory, namespace: "dev.herdr.input-journal-v1")
    }
    private func owner() throws -> Owner {
        let base = try testDirectory ?? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        let directory = base.appendingPathComponent("dev.herdr.input-journal-v1", isDirectory: true)
        if FileManager.default.fileExists(atPath: directory.path),
           try directory.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink == true { throw DeviceKeyError.invalidHandle }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let key = directory.resolvingSymlinksInPath().standardizedFileURL.path
        Self.registryLock.lock(); defer { Self.registryLock.unlock() }
        if let existing = Self.owners[key] { return existing }
        let path = directory.appendingPathComponent("owner.lock").path
        let fd = Darwin.open(path, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, S_IRUSR | S_IWUSR)
        guard fd >= 0 else { throw DeviceKeyError.invalidHandle }
        var info = stat()
        guard fstat(fd, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
              flock(fd, LOCK_EX | LOCK_NB) == 0 else { Darwin.close(fd); throw DeviceKeyError.invalidHandle }
        let result = Owner(fd); Self.owners[key] = result; return result
    }
    private func withOwner<T>(_ work: (Owner) throws -> T) throws -> T {
        let state = try owner(); state.lock.lock(); defer { state.lock.unlock() }
        return try work(state)
    }
    private func lease() throws -> String {
        var bytes = [UInt8](repeating: 0, count: 16)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw DeviceKeyError.invalidHandle }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }
    private let fields: Set<String> = ["schemaVersion","requestId","host","port","username","hostFingerprint","session","socketPath","paneId","terminalId","generation","createdAt"]
    private func validate(_ record: String) throws -> Endpoint {
        let data = Data(record.utf8)
        guard (1...8192).contains(data.count) else { throw DeviceKeyError.invalidHandle }
        var quoted = false, escaped = false, colons = 0, braces = 0
        for char in record {
            if quoted {
                if escaped { escaped = false } else if char == "\\" { escaped = true } else if char == "\"" { quoted = false }
            } else {
                if char == "\"" { quoted = true }
                else if char == ":" { colons += 1 }
                else if char == "{" || char == "}" { braces += 1 }
                else if char == "[" || char == "]" { throw DeviceKeyError.invalidHandle }
            }
        }
        guard !quoted, braces == 2,
              let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let version = obj["schemaVersion"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(),
              !["f", "d"].contains(String(cString: version.objCType)),
              version.doubleValue == Double(version.intValue), (1...2).contains(version.intValue) else { throw DeviceKeyError.invalidHandle }
        let expected = version.intValue == 1 ? fields : fields.union(["route"])
        guard colons == expected.count, Set(obj.keys) == expected else { throw DeviceKeyError.invalidHandle }
        func integer(_ name: String, _ low: Int, _ high: Int) throws {
            guard let value = obj[name] as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
                  !["f", "d"].contains(String(cString: value.objCType)), value.doubleValue == Double(value.int64Value), value.int64Value >= low, value.int64Value <= high else { throw DeviceKeyError.invalidHandle }
        }
        func text(_ name: String, _ max: Int, _ pattern: String? = nil) throws -> String {
            guard let value = obj[name] as? String, !value.isEmpty, value.count <= max,
                  !value.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
                  pattern == nil || value.range(of: "^(?:" + pattern! + ")$", options: .regularExpression) != nil else { throw DeviceKeyError.invalidHandle }
            return value
        }
        try integer("schemaVersion",1,2); try integer("port",1,65535); try integer("generation",1,2147483647)
        if version.intValue == 2, !(obj["route"] is NSNull) {
            let route = try text("route",256,"easy-tier:[a-f0-9]{32}:[1-9][0-9]{0,9}:[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")
            let parts = route.split(separator: ":")
            guard parts.count == 4, let revision = Int64(parts[2]), revision <= 2147483647 else { throw DeviceKeyError.invalidHandle }
        }
        _ = try text("requestId",32,"[a-f0-9]{32}"); _ = try text("host",253,"[A-Za-z0-9:.\\[\\]_-]+")
        let user = try text("username",128); guard !user.hasPrefix("-"), user.rangeOfCharacter(from: .whitespacesAndNewlines) == nil else { throw DeviceKeyError.invalidHandle }
        _ = try text("hostFingerprint",100,"SHA256:[A-Za-z0-9+/]{43}")
        let session = try text("session",64,"[A-Za-z0-9_-]+"); guard session != "default" else { throw DeviceKeyError.invalidHandle }
        let socket = try text("socketPath",1024)
        guard socket.hasPrefix("/"), !socket.split(separator:"/",omittingEmptySubsequences:false).dropFirst().contains(where: { $0.isEmpty || $0 == "." || $0 == ".." }) else { throw DeviceKeyError.invalidHandle }
        _ = try text("paneId",128,"[A-Za-z0-9:_-]+")
        _ = try text("terminalId",128,"term_[0-9a-f]{1,123}")
        _ = try text("createdAt",40,"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z")
        let route = version.intValue == 1 || obj["route"] is NSNull ? "system" : obj["route"] as! String
        let fields = [route, obj["host"] as! String, user, obj["hostFingerprint"] as! String, session, socket,
            obj["paneId"] as! String, obj["terminalId"] as! String].map { Data($0.utf8) }
        return Endpoint(fields: fields, port: (obj["port"] as! NSNumber).intValue)
    }
    private struct Loaded { let revision: String, records: [String], legacy: Bool }
    private func load() throws -> Loaded {
        let saved = try storage.load(), text = saved["contents"] ?? ""
        let revision = saved["revision"] ?? ""
        let state = try owner()
        if revision.isEmpty {
            guard !state.knownStore else { throw DeviceKeyError.invalidHandle }
        } else { state.knownStore = true }
        if text.isEmpty || text == "{}" { return Loaded(revision: revision, records: [], legacy: true) }
        guard let data = text.data(using: .utf8),
              let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let version = obj["schemaVersion"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(),
              !["f", "d"].contains(String(cString: version.objCType)) else { throw DeviceKeyError.invalidHandle }
        if version.intValue != 3 || version.doubleValue != 3 {
            _ = try validate(text); return Loaded(revision: revision, records: [text], legacy: true)
        }
        var quoted = false, escaped = false, colons = 0, braces = 0, brackets = 0
        for c in text {
            if quoted { if escaped { escaped = false } else if c == "\\" { escaped = true } else if c == "\"" { quoted = false } }
            else if c == "\"" { quoted = true }
            else if c == ":" { colons += 1 } else if c == "{" || c == "}" { braces += 1 }
            else if c == "[" || c == "]" { brackets += 1 }
        }
        guard !quoted, colons == 2, braces == 2, brackets == 2, Set(obj.keys) == ["schemaVersion", "records"],
              let records = obj["records"] as? [String], records.count <= 32 else { throw DeviceKeyError.invalidHandle }
        let keys = try records.map(validate)
        guard Set(records.map { Data($0.utf8) }).count == records.count, Set(keys).count == keys.count else { throw DeviceKeyError.invalidHandle }
        return Loaded(revision: revision, records: records, legacy: false)
    }
    private func save(_ old: Loaded, _ records: [String]) throws {
        guard records.count <= 32 else { throw DeviceKeyError.invalidHandle }
        let data = try JSONSerialization.data(withJSONObject: ["schemaVersion":3,"records":records], options: [.sortedKeys])
        guard (1...262144).contains(data.count), let text = String(data: data, encoding: .utf8) else { throw DeviceKeyError.invalidHandle }
        // The atomic replacement may succeed even when a later sync fails.
        // A subsequent missing file is then unknown, not a new empty store.
        try owner().knownStore = true
        _ = try storage.save(expected: old.revision, contents: text)
    }
    func readAll() throws -> [String] { try withOwner { _ in try load().records } }
    func prepare(record: String) throws -> String {
        try withOwner { state in
            let key = try validate(record), old = try load()
            guard state.active[key] == nil, old.records.count < 32,
                  try !old.records.contains(where: { try validate($0) == key }) else { throw DeviceKeyError.invalidHandle }
            let token = try lease(); try save(old, old.records + [record]); state.active[key] = Active(raw: Data(record.utf8), lease: token)
            return token
        }
    }
    func complete(record: String, lease: String) throws {
        try withOwner { state in
            let key = try validate(record)
            guard state.active[key] == Active(raw: Data(record.utf8), lease: lease) else { throw DeviceKeyError.invalidHandle }
            let old = try load(); guard old.records.filter({ Data($0.utf8) == Data(record.utf8) }).count == 1 else { throw DeviceKeyError.invalidHandle }
            try save(old, old.records.filter { Data($0.utf8) != Data(record.utf8) }); state.active.removeValue(forKey: key)
        }
    }
    func abandon(record: String, lease: String) throws {
        try withOwner { state in
            let key = try validate(record)
            guard state.active[key] == Active(raw: Data(record.utf8), lease: lease) else { throw DeviceKeyError.invalidHandle }
            state.active.removeValue(forKey: key)
        }
    }
    func resolve(record: String) throws {
        try withOwner { state in
            let key = try validate(record), old = try load()
            guard state.active[key] == nil, old.records.filter({ Data($0.utf8) == Data(record.utf8) }).count == 1 else { throw DeviceKeyError.invalidHandle }
            try save(old, old.records.filter { Data($0.utf8) != Data(record.utf8) })
        }
    }
    func read() throws -> String? {
        try withOwner { _ in let old = try load(); guard old.legacy else { throw DeviceKeyError.invalidHandle }; return old.records.first }
    }
    func clear(record: String) throws {
        try withOwner { state in
            let key = try validate(record), old = try load()
            guard old.legacy, state.active[key] == nil, old.records.count == 1, Data(old.records[0].utf8) == Data(record.utf8) else { throw DeviceKeyError.invalidHandle }
            _ = try storage.save(expected: old.revision, contents: "{}")
        }
    }
}

func registerHerdrInputJournal(messenger: FlutterBinaryMessenger) {
    let channel = FlutterMethodChannel(name: "herdr.pocket/input_journal", binaryMessenger: messenger)
    let worker = DispatchQueue(label: "dev.herdr.input-journal")
    let store = InputJournalFile()
    channel.setMethodCallHandler { call, result in
        guard ["read","readAll","prepare","complete","abandon","resolve","clear"].contains(call.method) else { result(FlutterMethodNotImplemented); return }
        worker.async {
            do {
                let value: Any?
                if call.method == "read" { value = try store.read() }
                else if call.method == "readAll" { value = try store.readAll() }
                else {
                    guard let args = call.arguments as? [String: Any], let record = args["record"] as? String else { throw DeviceKeyError.invalidHandle }
                    switch call.method {
                    case "prepare": value = try store.prepare(record: record)
                    case "complete": guard let lease = args["lease"] as? String else { throw DeviceKeyError.invalidHandle }; try store.complete(record: record, lease: lease); value = nil
                    case "abandon": guard let lease = args["lease"] as? String else { throw DeviceKeyError.invalidHandle }; try store.abandon(record: record, lease: lease); value = nil
                    case "resolve": try store.resolve(record: record); value = nil
                    case "clear": try store.clear(record: record); value = nil
                    default: throw DeviceKeyError.invalidHandle
                    }
                }
                DispatchQueue.main.async { result(value) }
            } catch {
                DispatchQueue.main.async { result(FlutterError(code:"input_journal_unavailable",message:"Public input marker unavailable or changed",details:nil)) }
            }
        }
    }
}
