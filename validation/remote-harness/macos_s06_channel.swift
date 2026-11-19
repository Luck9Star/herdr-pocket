import AppKit

// Test-only, session-scoped AppKit IPC. The general pasteboard is never used.
struct MacosS06Channel {
    enum Party: String { case host, test }

    enum Topic: String, CaseIterable {
        case release, testReady, hostReady, request0, response0, request1, response1
        case stopRequested, peersClosed, result

        var writer: Party {
            switch self {
            case .release, .hostReady, .response0, .response1, .peersClosed: return .host
            default: return .test
            }
        }

        var limit: Int {
            switch self {
            case .release: return 4096
            case .testReady, .hostReady: return 36
            case .stopRequested, .peersClosed: return 1
            default: return 2048
            }
        }
    }

    enum Failure: Error { case invalidScope, rejectedMessage, deliveryFailed, cleanupFailed }

    private static let type = NSPasteboard.PasteboardType("dev.herdr.pocket.s06.fixture-message")
    private let nonce: String
    private let party: Party
    private var prefix: Data { Data((nonce + "\n").utf8) }

    init(nonce: String, party: Party) throws {
        let alphabet = Set("0123456789abcdef".utf8)
        guard nonce.utf8.count == 64 && nonce.utf8.allSatisfy(alphabet.contains) else {
            throw Failure.invalidScope
        }
        self.nonce = nonce
        self.party = party
    }

    private func board(_ topic: Topic) -> NSPasteboard {
        NSPasteboard(name: NSPasteboard.Name("dev.herdr.pocket.s06.\(nonce).\(topic.rawValue)"))
    }

    func send(_ topic: Topic, _ data: Data) throws {
        guard topic.writer == party && !data.isEmpty && data.count <= topic.limit else {
            throw Failure.rejectedMessage
        }
        let board = board(topic)
        guard board.types?.isEmpty != false else { throw Failure.rejectedMessage }
        let item = NSPasteboardItem()
        guard item.setData(prefix + data, forType: Self.type), board.writeObjects([item]) else {
            throw Failure.deliveryFailed
        }
    }

    func receive(_ topic: Topic) throws -> Data? {
        guard topic.writer != party else { throw Failure.rejectedMessage }
        guard let wire = board(topic).data(forType: Self.type) else { return nil }
        guard wire.starts(with: prefix) && wire.count > prefix.count && wire.count - prefix.count <= topic.limit else {
            throw Failure.rejectedMessage
        }
        return wire.dropFirst(prefix.count)
    }

    func releaseAll() throws {
        guard party == .host else { throw Failure.rejectedMessage }
        var empty = true
        for topic in Topic.allCases {
            board(topic).releaseGlobally()
            let check = board(topic)
            if check.data(forType: Self.type) != nil { empty = false }
            check.releaseGlobally()
        }
        guard empty else { throw Failure.cleanupFailed }
    }
}
