#if canImport(AppKit)
import AppKit
import Foundation

private let pocketMacPicker = PocketDocumentPicker()
typealias PocketDocumentCallback = @convention(c) (UnsafePointer<UInt8>?, Int, Int32, UnsafeMutableRawPointer?) -> Void

private func deliver(_ outcome: Result<Data?, Error>, callback: PocketDocumentCallback, context: UnsafeMutableRawPointer?) {
    switch outcome {
    case .failure: callback(nil, 0, 2, context)
    case .success(nil): callback(nil, 0, 0, context)
    case .success(let data?):
        data.withUnsafeBytes { bytes in callback(bytes.bindMemory(to: UInt8.self).baseAddress, data.count, 1, context) }
    }
}
@_cdecl("pocket_document_mac_open")
func pocketDocumentMacOpen(_ callback: @escaping PocketDocumentCallback, _ context: UnsafeMutableRawPointer?) {
    pocketMacPicker.open { deliver($0, callback:callback, context:context) }
}
@_cdecl("pocket_document_mac_save")
func pocketDocumentMacSave(_ ptr: UnsafePointer<UInt8>?, _ length: Int, _ callback: @escaping PocketDocumentCallback, _ context: UnsafeMutableRawPointer?) {
    guard let ptr=ptr, length > 0, length <= PocketDocumentIO.limit else { callback(nil,0,2,context); return }
    let bytes=Data(bytes:ptr,count:length)
    pocketMacPicker.save(bytes) { deliver($0, callback:callback, context:context) }
}
#endif
