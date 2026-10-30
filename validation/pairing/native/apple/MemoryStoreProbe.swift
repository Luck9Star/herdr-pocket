import Foundation
import CryptoKit

// No AppleKeychainSeedBackend instance is constructed or called in this probe.
final class MemorySeedBackend: SeedBackend {
    var locked = false
    private var values: [String: Data] = [:]
    func insert(_ seed: Data, handle: String) throws {
        guard !locked else { throw DeviceKeyError.missing }
        guard values[handle] == nil else { throw DeviceKeyError.invalidHandle }
        values[handle] = seed
    }
    func read(handle: String) throws -> Data {
        guard !locked, let value = values[handle] else { throw DeviceKeyError.missing }
        return value
    }
    func delete(handle: String) throws {
        guard !locked, values.removeValue(forKey: handle) != nil else { throw DeviceKeyError.missing }
    }
}

@main struct Probe {
    static func main() throws {
        let backend = MemorySeedBackend()
        let store = MobileEd25519Store(backend: backend)
        let handle = try store.create()
        let key = try store.publicKey(handle)
        let wire = Data(base64Encoded: String(key.split(separator: " ")[1]))!
        let publicKey = try Curve25519.Signing.PublicKey(rawRepresentation: wire.suffix(32))
        let message = Data("isolated-probe".utf8)
        let signature = try store.sign(handle, payload: message)
        guard publicKey.isValidSignature(signature, for: message) else { fatalError("signature") }
        backend.locked = true
        do { _ = try store.sign(handle, payload: message); fatalError("locked storage accepted") }
        catch DeviceKeyError.missing { }
        backend.locked = false
        try store.delete(handle)
        do { _ = try store.publicKey(handle); fatalError("deleted key regenerated") }
        catch DeviceKeyError.missing { }
        print("{\"scope\":\"CryptoKit-memory-double-only\",\"signVerify\":true,\"lockedReject\":true,\"deleteReject\":true,\"systemKeychainCalls\":0}")
    }
}
