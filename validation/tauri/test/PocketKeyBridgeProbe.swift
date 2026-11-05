import Foundation
import CryptoKit

// Injected memory backend only; this test never opens the system Keychain.
final class FixtureSeedBackend: SeedBackend {
    var values: [String: Data] = [:]
    var locked = false
    var failReads = false
    func insert(_ seed: Data, handle: String) throws {
        guard !locked else { throw DeviceKeyError.missing }
        values[handle] = seed
    }
    func read(handle: String) throws -> Data {
        guard !locked, !failReads, let seed = values[handle] else { throw DeviceKeyError.missing }
        return seed
    }
    func delete(handle: String) throws {
        guard !locked, values.removeValue(forKey: handle) != nil else { throw DeviceKeyError.missing }
    }
}

@main struct PocketKeyBridgeProbe {
    static func main() throws {
        let backend = FixtureSeedBackend()
        let bridge = PocketKeyBridge(backend: backend)
        let created = try bridge.create()
        let restored = try bridge.publicKey(created.handle)
        precondition(restored == created.publicKey)
        let wire = Data(base64Encoded: String(created.publicKey.split(separator: " ")[1]))!
        let publicKey = try Curve25519.Signing.PublicKey(rawRepresentation: wire.suffix(32))
        let message = Data("isolated bridge fixture".utf8)
        let signature = Data(base64Encoded: try bridge.sign(created.handle, base64: message.base64EncodedString()))!
        precondition(publicKey.isValidSignature(signature, for: message))
        do { _ = try bridge.sign(created.handle, base64: "@@"); fatalError("malformed input accepted") } catch {}
        do { _ = try bridge.sign(created.handle, base64: Data(repeating: 1, count: 65537).base64EncodedString()); fatalError("oversize input accepted") } catch {}
        backend.locked = true
        do { _ = try bridge.sign(created.handle, base64: ""); fatalError("locked key accepted") } catch {}
        backend.locked = false
        try bridge.delete(created.handle)
        do { _ = try bridge.publicKey(created.handle); fatalError("deleted key recreated") } catch {}
        backend.failReads = true
        do { _ = try bridge.create(); fatalError("unreadable new key published") } catch {}
        precondition(backend.values.isEmpty)
        print("iOS key bridge memory fixture passed; system Keychain calls: 0")
    }
}
