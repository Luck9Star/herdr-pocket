import Foundation
private var bridgeCallbacks = 0
@main struct DocumentIOProbe {
    static func main() throws {
        let dir=FileManager.default.temporaryDirectory.appendingPathComponent("pocket-document-probe-" + UUID().uuidString, isDirectory:true)
        try FileManager.default.createDirectory(at:dir,withIntermediateDirectories:false)
        defer { try? FileManager.default.removeItem(at:dir) }
        let path=dir.appendingPathComponent("archive.hpkt")
        let bytes=Data(repeating:0x42,count:PocketDocumentIO.limit)
        try PocketDocumentIO.write(bytes,to:path)
        let loaded = try PocketDocumentIO.read(path)
        precondition(loaded == bytes)
        let cancelled = PocketDocumentLease()
        precondition(cancelled.cancel())
        do { try PocketDocumentIO.write(Data([1]), to:path, lease:cancelled); fatalError("cancelled write accepted") } catch {}
        let unchanged = try PocketDocumentIO.read(path)
        precondition(unchanged == bytes)
        let committing = PocketDocumentLease()
        precondition(committing.beginWrite())
        precondition(!committing.cancel())
        var workerComplete = false
        PocketDocumentWorker.run({
            precondition(!Thread.isMainThread)
            return try PocketDocumentIO.read(path)
        }) { result in
            precondition(Thread.isMainThread)
            precondition((try? result.get()) == bytes)
            workerComplete = true
        }
        let deadline = Date().addingTimeInterval(10)
        while !workerComplete && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.01)) }
        precondition(workerComplete)
        pocketDocumentMacSave(nil, 0, { _, _, status, _ in
            precondition(Thread.isMainThread && status == 2)
            bridgeCallbacks += 1
        }, nil)
        precondition(bridgeCallbacks == 1)
        try Data(repeating:1,count:PocketDocumentIO.limit+1).write(to:path)
        do { _ = try PocketDocumentIO.read(path); fatalError("oversize accepted") } catch {}
        do { try PocketDocumentIO.write(Data(),to:path); fatalError("empty accepted") } catch {}
        try Data().write(to:path)
        do { _ = try PocketDocumentIO.read(path); fatalError("empty accepted") } catch {}
        print("bounded temporary-file checks passed")
    }
}
