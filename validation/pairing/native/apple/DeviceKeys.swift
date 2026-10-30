// Compile-only system backend; executable tests inject MemorySeedBackend.
import Foundation
import CryptoKit
import Security
import LocalAuthentication

enum DeviceKeyError: Error { case missing, invalidHandle, payloadTooLarge, osStatus(OSStatus) }

// Internal native boundary; never bridge these seed operations to Dart/JS.
protocol SeedBackend {
    func insert(_ seed: Data, handle: String) throws
    func read(handle: String) throws -> Data
    func delete(handle: String) throws
}

final class AppleKeychainSeedBackend: SeedBackend {
    private let service = "org.herdr-pocket.validation.device-key.v1"
    private func query(_ handle: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: handle,
         kSecAttrSynchronizable as String: false,
         kSecUseDataProtectionKeychain as String: true]
    }
    func insert(_ seed: Data, handle: String) throws {
        var attributes = query(handle)
        attributes[kSecValueData as String] = seed
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(attributes as CFDictionary, nil)
        guard status == errSecSuccess else { throw DeviceKeyError.osStatus(status) }
    }
    func read(handle: String) throws -> Data {
        var attributes = query(handle)
        attributes[kSecReturnData as String] = true
        attributes[kSecMatchLimit as String] = kSecMatchLimitOne
        let context = LAContext()
        context.interactionNotAllowed = true
        attributes[kSecUseAuthenticationContext as String] = context
        var result: CFTypeRef?
        let status = SecItemCopyMatching(attributes as CFDictionary, &result)
        guard status == errSecSuccess else { throw DeviceKeyError.osStatus(status) }
        guard let data = result as? Data, data.count == 32 else { throw DeviceKeyError.missing }
        return data
    }
    func delete(handle: String) throws {
        let status = SecItemDelete(query(handle) as CFDictionary)
        guard status == errSecSuccess else { throw DeviceKeyError.osStatus(status) }
    }
}

// App-facing API exposes only local handle, OpenSSH public key and signatures.
// Ed25519 executes in CryptoKit software, NOT Secure Enclave.
final class MobileEd25519Store {
    private let backend: SeedBackend
    init(backend: SeedBackend) { self.backend = backend }
    private func checked(_ handle: String) throws -> String {
        guard UUID(uuidString: handle) != nil else { throw DeviceKeyError.invalidHandle }
        return handle
    }
    private func key(_ handle: String) throws -> Curve25519.Signing.PrivateKey {
        try Curve25519.Signing.PrivateKey(rawRepresentation: backend.read(handle: checked(handle)))
    }
    func create() throws -> String {
        let handle = UUID().uuidString
        let key = Curve25519.Signing.PrivateKey()
        try backend.insert(key.rawRepresentation, handle: handle)
        return handle
    }
    func publicKey(_ handle: String) throws -> String {
        let bytes = try key(handle).publicKey.rawRepresentation
        // RFC4253 string("ssh-ed25519") + string(32-byte public key).
        var wire = Data([0, 0, 0, 11])
        wire.append(Data("ssh-ed25519".utf8))
        wire.append(Data([0, 0, 0, 32]))
        wire.append(bytes)
        return "ssh-ed25519 " + wire.base64EncodedString()
    }
    func sign(_ handle: String, payload: Data) throws -> Data {
        guard payload.count <= 65536 else { throw DeviceKeyError.payloadTooLarge }
        return try key(handle).signature(for: payload)
    }
    func delete(_ handle: String) throws { try backend.delete(handle: checked(handle)) }
}
