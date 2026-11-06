import Foundation
import CoreFoundation

final class InputJournalFile {
    private let storage: HostCatalogFile
    init(testDirectory: URL? = nil) { storage = HostCatalogFile(testDirectory: testDirectory, namespace: "dev.herdr.input-journal-v1") }
    private let fields: Set<String> = ["schemaVersion","requestId","host","port","username","hostFingerprint","session","socketPath","paneId","terminalId","generation","createdAt"]
    private func validate(_ record: String) throws {
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
              version.doubleValue == Double(version.intValue), (1...2).contains(version.intValue) else { throw DeviceKeyError.invalidHandle }
        let expected = version.intValue == 1 ? fields : fields.union(["route"])
        guard colons == expected.count, Set(obj.keys) == expected else { throw DeviceKeyError.invalidHandle }
        func integer(_ name: String, _ low: Int, _ high: Int) throws {
            guard let value = obj[name] as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
                  value.doubleValue == Double(value.int64Value), value.int64Value >= low, value.int64Value <= high else { throw DeviceKeyError.invalidHandle }
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
    }
    func read() throws -> String? {
        let text = try storage.load()["contents"] ?? ""
        if text.isEmpty || text == "{}" { return nil }
        try validate(text); return text
    }
    func prepare(record: String) throws {
        try validate(record); let old = try storage.load()
        guard ["","{}"].contains(old["contents"] ?? "") else { throw DeviceKeyError.invalidHandle }
        _ = try storage.save(expected: old["revision"] ?? "", contents: record)
    }
    func clear(record: String) throws {
        try validate(record); let old = try storage.load()
        guard old["contents"] == record else { throw DeviceKeyError.invalidHandle }
        _ = try storage.save(expected: old["revision"] ?? "", contents: "{}")
    }
}

func registerHerdrInputJournal(messenger: FlutterBinaryMessenger) {
    let channel = FlutterMethodChannel(name: "herdr.pocket/input_journal", binaryMessenger: messenger)
    let worker = DispatchQueue(label: "dev.herdr.input-journal")
    let store = InputJournalFile()
    channel.setMethodCallHandler { call, result in
        guard ["read","prepare","clear"].contains(call.method) else { result(FlutterMethodNotImplemented); return }
        worker.async {
            do {
                let value: Any?
                if call.method == "read" { value = try store.read() }
                else {
                    guard let args = call.arguments as? [String: Any], let record = args["record"] as? String else { throw DeviceKeyError.invalidHandle }
                    if call.method == "prepare" { try store.prepare(record: record) } else { try store.clear(record: record) }
                    value = nil
                }
                DispatchQueue.main.async { result(value) }
            } catch {
                DispatchQueue.main.async { result(FlutterError(code:"input_journal_unavailable",message:"Public input marker unavailable or changed",details:nil)) }
            }
        }
    }
}
