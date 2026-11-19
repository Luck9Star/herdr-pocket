import Foundation

struct MacosS06Fixture: Decodable {
    struct Peer: Decodable {
        let host: String
        let port: Int
        let username: String
        let session: String
        let socketPath: String
        let herdrPath: String
        let expectedHostKey: String
        let fingerprint: String
        let paneId: String
        let terminalId: String
        let marker: String

        var title: String { "\(host) / \(session)" }
        var remoteTitle: String { "\(session) · 远端终端" }
        var binding: String { "\(paneId) · \(terminalId)" }
    }

    let schemaVersion: Int
    let peers: [Peer]

    var hasIndependentTargets: Bool {
        guard schemaVersion == 1, peers.count == 2 else { return false }
        let a = peers[0], b = peers[1]
        return peers.allSatisfy { $0.host == "127.0.0.1" && (1...65535).contains($0.port) } &&
            a.port != b.port && a.fingerprint != b.fingerprint && a.paneId == b.paneId &&
            a.terminalId != b.terminalId && a.session == "s06-a" && b.session == "s06-b" &&
            a.marker == "HPS06A" && b.marker == "HPS06B"
    }
}
