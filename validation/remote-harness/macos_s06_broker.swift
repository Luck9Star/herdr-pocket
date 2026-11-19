import Foundation

@main
struct MacosS06Broker {
    static func input(limit: Int) throws -> Data {
        var payload = Data()
        while payload.count <= limit {
            guard let piece = try FileHandle.standardInput.read(upToCount: limit + 1 - payload.count),
                  !piece.isEmpty else { break }
            payload.append(piece)
        }
        return payload
    }

    static func main() {
        do {
            let args = Array(CommandLine.arguments.dropFirst())
            guard (3...4).contains(args.count), let party = MacosS06Channel.Party(rawValue: args[0]) else {
                throw MacosS06Channel.Failure.invalidScope
            }
            let channel = try MacosS06Channel(nonce: args[1], party: party)
            if args.count == 3 && args[2] == "releaseAll" {
                try channel.releaseAll()
                return
            }
            guard args.count == 4, let topic = MacosS06Channel.Topic(rawValue: args[3]) else {
                throw MacosS06Channel.Failure.rejectedMessage
            }
            switch args[2] {
            case "send":
                try channel.send(topic, input(limit: topic.limit))
            case "receive":
                if let payload = try channel.receive(topic) {
                    FileHandle.standardOutput.write(payload)
                }
            default:
                throw MacosS06Channel.Failure.rejectedMessage
            }
        } catch {
            // Never print the channel identifier or wire payload.
            exit(2)
        }
    }
}
