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

        struct PublicProfile: Encodable {
            let version = 1
            let type = "herdr-connection-profile"
            let provider = "direct"
            let host: String
            let port: Int
            let username: String
            let session: String
            let socketPath: String
            let herdrPath: String
            let expectedHostKey: String
        }

        var publicProfile: PublicProfile {
            PublicProfile(host: host, port: port, username: username, session: session,
                          socketPath: socketPath, herdrPath: herdrPath, expectedHostKey: expectedHostKey)
        }

        var profilePreview: String {
            """
            待预览（尚未信任）
            主机 \(host):\(port)
            账号 \(username)
            网络 \(publicProfile.provider)
            会话 \(session)
            socket \(socketPath)
            herdr \(herdrPath)
            主机指纹 \(fingerprint)
            """
        }
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

enum MacosS06CreationState: String {
    case requestReady, validationFailed, intentSaveFailed, deviceCreationUnknown, handleSaveUnknown
    case publicKeyReadUnknown, profileSaveUnknown, bridgeUnavailable, observationConflict, unresolved

    private static let unknownSuffix = "未完成 · 设备安全存储不可用或创建结果未知 · 请核验原身份，不会重放创建"
    static let uiMessages: [String: Self] = [
        "等待主机审查 · 授权结果未知；公开请求有效 600 秒": .requestReady,
        "核对后，交给主机确认": .requestReady,
        "状态 awaiting-host · 主机授权 unknown": .requestReady,
        "复制当前公开请求": .requestReady,
        "核验连接资料未完成 · 未创建设备身份": .validationFailed,
        "保存创建意图未完成 · 未创建设备身份": .intentSaveFailed,
        "创建设备身份" + unknownSuffix: .deviceCreationUnknown,
        "保存本机密钥引用" + unknownSuffix: .handleSaveUnknown,
        "读取设备公钥" + unknownSuffix: .publicKeyReadUnknown,
        "保存主机资料" + unknownSuffix: .profileSaveUnknown,
        "此平台的设备安全存储桥不可用 · 设备配对已禁用，可返回手动隔离实验": .bridgeUnavailable,
    ]

    static func classify(_ visibleTexts: [String]) -> Self? {
        let states = Set(visibleTexts.compactMap { uiMessages[$0] })
        return states.count > 1 ? .observationConflict : states.first
    }

    var failureCode: String? {
        switch self {
        case .requestReady: return nil
        case .validationFailed: return "public_pair_target_validation_failed"
        case .intentSaveFailed: return "public_pair_creation_intent_failed"
        case .deviceCreationUnknown: return "public_pair_device_creation_unknown"
        case .handleSaveUnknown: return "public_pair_created_handle_save_unknown"
        case .publicKeyReadUnknown: return "public_pair_device_public_key_unknown"
        case .profileSaveUnknown: return "public_pair_profile_save_unknown"
        case .bridgeUnavailable: return "public_pair_storage_bridge_unavailable"
        case .observationConflict: return "public_pair_creation_observations_conflict"
        case .unresolved: return "public_pair_creation_unresolved"
        }
    }
}
