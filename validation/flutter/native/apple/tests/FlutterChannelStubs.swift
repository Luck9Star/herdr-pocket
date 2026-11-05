import Foundation
protocol FlutterBinaryMessenger {}
typealias FlutterResult = (Any?) -> Void
struct FlutterMethodCall { var method: String; var arguments: Any? }
struct FlutterStandardTypedData { var data: Data; init(bytes: Data) { data = bytes } }
struct FlutterError { init(code: String, message: String?, details: Any?) {} }
let FlutterMethodNotImplemented: Any = 0
class FlutterMethodChannel {
 init(name: String, binaryMessenger: FlutterBinaryMessenger) {}
 func setMethodCallHandler(_ handler: ((FlutterMethodCall, @escaping FlutterResult) -> Void)?) {}
}
