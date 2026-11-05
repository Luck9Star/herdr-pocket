// Compiled beside the shared DeviceKeys.swift source in generated Apple runners.
// No system Keychain operation happens at registration or class loading.
func registerHerdrDeviceKeys(messenger: FlutterBinaryMessenger) {
    let channel = FlutterMethodChannel(name: "dev.herdr/device-keys", binaryMessenger: messenger)
    let worker = DispatchQueue(label: "dev.herdr.device-keys")
    let store = MobileEd25519Store(backend: AppleKeychainSeedBackend())
    channel.setMethodCallHandler { call, result in
        guard ["create", "public", "sign", "delete"].contains(call.method) else {
            result(FlutterMethodNotImplemented); return
        }
        worker.async {
            do {
                let args = call.arguments as? [String: Any] ?? [:]
                let value: Any?
                if call.method == "create" {
                    value = try store.create()
                } else {
                    guard let handle = args["handle"] as? String else { throw DeviceKeyError.invalidHandle }
                    switch call.method {
                    case "public": value = try store.publicKey(handle)
                    case "sign":
                        guard let payload = args["payload"] as? FlutterStandardTypedData else { throw DeviceKeyError.payloadTooLarge }
                        value = FlutterStandardTypedData(bytes: try store.sign(handle, payload: payload.data))
                    case "delete": try store.delete(handle); value = nil
                    default: throw DeviceKeyError.invalidHandle
                    }
                }
                DispatchQueue.main.async { result(value) }
            } catch {
                DispatchQueue.main.async { result(FlutterError(code: "device_key_unavailable", message: "Protected device key unavailable", details: nil)) }
            }
        }
    }
}
