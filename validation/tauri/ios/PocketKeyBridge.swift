import Foundation

// Internal adapter: never returns the seed held by MobileEd25519Store.
final class PocketKeyBridge {
    private let keys: MobileEd25519Store
    init(backend: SeedBackend) { keys = MobileEd25519Store(backend: backend) }
    func create() throws -> (handle: String, publicKey: String) {
        let handle = try keys.create()
        do { return (handle, try keys.publicKey(handle)) }
        catch { try? keys.delete(handle); throw error }
    }
    func publicKey(_ handle: String) throws -> String { try keys.publicKey(handle) }
    func sign(_ handle: String, base64: String) throws -> String {
        guard let payload = Data(base64Encoded: base64), payload.base64EncodedString() == base64,
              payload.count <= 65536 else { throw DeviceKeyError.payloadTooLarge }
        let signature = try keys.sign(handle, payload: payload)
        guard signature.count == 64 else { throw DeviceKeyError.missing }
        return signature.base64EncodedString()
    }
    func delete(_ handle: String) throws { try keys.delete(handle) }
}
