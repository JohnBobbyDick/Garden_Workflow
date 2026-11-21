import Foundation

public enum JSONValue: Codable, Equatable, Sendable {
    case null, bool(Bool), integer(Int64), number(Double), string(String)
    case array([JSONValue]), object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Int64.self) { self = .integer(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([JSONValue].self) { self = .array(value) }
        else { self = .object(try container.decode([String: JSONValue].self)) }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let value): try container.encode(value)
        case .integer(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }

    public var string: String? {
        if case .string(let value) = self { return value }
        return nil
    }
}

private struct GraphKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil
    init(_ key: String) { stringValue = key }
    init?(stringValue: String) { self.init(stringValue) }
    init?(intValue: Int) { return nil }
}

private extension KeyedDecodingContainer where Key == GraphKey {
    func extras(excluding fields: [String]) throws -> [String: JSONValue] {
        let known = Set(fields)
        return try Dictionary(uniqueKeysWithValues: allKeys.filter { !known.contains($0.stringValue) }.map {
            ($0.stringValue, try decode(JSONValue.self, forKey: $0))
        })
    }
}

private extension KeyedEncodingContainer where Key == GraphKey {
    mutating func writeExtras(_ fields: [String: JSONValue]) throws {
        for (key, value) in fields { try encode(value, forKey: GraphKey(key)) }
    }
}

public struct Graph: Codable, Equatable, Sendable {
    public struct Node: Codable, Equatable, Identifiable, Sendable {
        public struct Position: Codable, Equatable, Sendable {
            public var x: Double
            public var y: Double

            public init(x: Double, y: Double) { self.x = x; self.y = y }
        }

        public var id: String
        public var type: String
        public var position: Position
        public var config: [String: JSONValue]
        public var label: String
        public var disabled: Bool?
        private var extensions: [String: JSONValue] = [:]

        public init(type: String, label: String, position: Position, config: [String: JSONValue] = [:]) {
            id = UUID().uuidString
            self.type = type
            self.label = label
            self.position = position
            self.config = config
        }

        public init(from decoder: Decoder) throws {
            let fields = try decoder.container(keyedBy: GraphKey.self)
            id = try fields.decode(String.self, forKey: .init("id"))
            type = try fields.decode(String.self, forKey: .init("type"))
            position = try fields.decodeIfPresent(Position.self, forKey: .init("position")) ?? .init(x: 0, y: 0)
            config = try fields.decodeIfPresent([String: JSONValue].self, forKey: .init("config")) ?? [:]
            label = try fields.decodeIfPresent(String.self, forKey: .init("label")) ?? ""
            disabled = try fields.decodeIfPresent(Bool.self, forKey: .init("disabled"))
            extensions = try fields.extras(excluding: ["id", "type", "position", "config", "label", "disabled"])
        }

        public func encode(to encoder: Encoder) throws {
            var fields = encoder.container(keyedBy: GraphKey.self)
            try fields.writeExtras(extensions)
            try fields.encode(id, forKey: .init("id"))
            try fields.encode(type, forKey: .init("type"))
            try fields.encode(position, forKey: .init("position"))
            try fields.encode(config, forKey: .init("config"))
            try fields.encode(label, forKey: .init("label"))
            try fields.encodeIfPresent(disabled, forKey: .init("disabled"))
        }
    }

    public struct Edge: Codable, Equatable, Identifiable, Sendable {
        public var id: String
        public var source: String
        public var sourcePort: String
        public var target: String
        public var targetPort: String

        private var extensions: [String: JSONValue] = [:]

        public init(source: String, sourcePort: String, target: String, targetPort: String) {
            id = UUID().uuidString
            self.source = source
            self.sourcePort = sourcePort
            self.target = target
            self.targetPort = targetPort
        }

        public init(from decoder: Decoder) throws {
            let fields = try decoder.container(keyedBy: GraphKey.self)
            id = try fields.decodeIfPresent(String.self, forKey: .init("id")) ?? UUID().uuidString
            source = try fields.decode(String.self, forKey: .init("source"))
            target = try fields.decode(String.self, forKey: .init("target"))
            sourcePort = try fields.decodeIfPresent(String.self, forKey: .init("source_port")) ?? "out"
            targetPort = try fields.decodeIfPresent(String.self, forKey: .init("target_port")) ?? "in"
            extensions = try fields.extras(excluding: ["id", "source", "source_port", "target", "target_port"])
        }

        public func encode(to encoder: Encoder) throws {
            var fields = encoder.container(keyedBy: GraphKey.self)
            try fields.writeExtras(extensions)
            try fields.encode(id, forKey: .init("id"))
            try fields.encode(source, forKey: .init("source"))
            try fields.encode(target, forKey: .init("target"))
            try fields.encode(sourcePort, forKey: .init("source_port"))
            try fields.encode(targetPort, forKey: .init("target_port"))
        }
    }

    public var schemaVersion = 1
    public var nodes: [Node] = []
    public var edges: [Edge] = []

    private var extensions: [String: JSONValue] = [:]

    public init() {}

    public init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: GraphKey.self)
        schemaVersion = try fields.decodeIfPresent(Int.self, forKey: .init("schema_version")) ?? 1
        nodes = try fields.decodeIfPresent([Node].self, forKey: .init("nodes")) ?? []
        edges = try fields.decodeIfPresent([Edge].self, forKey: .init("edges")) ?? []
        extensions = try fields.extras(excluding: ["schema_version", "nodes", "edges"])
    }

    public func encode(to encoder: Encoder) throws {
        var fields = encoder.container(keyedBy: GraphKey.self)
        try fields.writeExtras(extensions)
        try fields.encode(schemaVersion, forKey: .init("schema_version"))
        try fields.encode(nodes, forKey: .init("nodes"))
        try fields.encode(edges, forKey: .init("edges"))
    }

}

public struct RunEvent: Decodable, Identifiable, Sendable {
    public let id: Int
    public let type: String
    public let nodeID: String?
    public let data: [String: JSONValue]

    enum CodingKeys: String, CodingKey {
        case id, type, data
        case nodeID = "node_id"
    }
}

public struct EventDecoder: Sendable {
    private var lines: [String] = []
    public init() {}

    public mutating func consume(_ line: String) throws -> RunEvent? {
        if line.isEmpty {
            guard !lines.isEmpty else { return nil }
            defer { lines.removeAll(keepingCapacity: true) }
            return try JSONDecoder().decode(RunEvent.self, from: Data(lines.joined(separator: "\n").utf8))
        }
        if line.hasPrefix("data:") {
            var value = line.dropFirst(5)
            if value.first == " " { value = value.dropFirst() }
            lines.append(String(value))
        }
        return nil
    }
}

public enum GraphImportError: LocalizedError, Equatable {
    case unsupportedVersion, tooManyEntries, duplicateNode, duplicateEdge, missingEndpoint, invalidPosition

    public var errorDescription: String? {
        switch self {
        case .unsupportedVersion: "Версия графа не поддерживается."
        case .tooManyEntries: "Граф превышает размер, поддерживаемый редактором."
        case .duplicateNode: "Идентификатор ноды встречается дважды."
        case .duplicateEdge: "Идентификатор связи встречается дважды."
        case .missingEndpoint: "Связь ссылается на отсутствующую ноду."
        case .invalidPosition: "Координаты ноды выходят за пределы полотна."
        }
    }
}

extension Graph {
    public func validateImport() throws {
        guard schemaVersion == 1 else { throw GraphImportError.unsupportedVersion }
        guard nodes.count <= 200 && edges.count <= 20_000 else { throw GraphImportError.tooManyEntries }
        let nodeIDs = Set(nodes.map(\.id))
        guard nodeIDs.count == nodes.count else { throw GraphImportError.duplicateNode }
        guard Set(edges.map(\.id)).count == edges.count else { throw GraphImportError.duplicateEdge }
        guard edges.allSatisfy({ nodeIDs.contains($0.source) && nodeIDs.contains($0.target) }) else {
            throw GraphImportError.missingEndpoint
        }
        let bounds = -50_000.0...50_000.0
        guard nodes.allSatisfy({ bounds.contains($0.position.x) && bounds.contains($0.position.y) }) else {
            throw GraphImportError.invalidPosition
        }
    }

    public func createsCycle(source: String, target: String) -> Bool {
        let outgoing = Dictionary(grouping: edges, by: \.source)
        var pending = [target]
        var visited = Set<String>()
        while let next = pending.popLast() {
            if next == source { return true }
            if visited.insert(next).inserted {
                pending.append(contentsOf: (outgoing[next] ?? []).map(\.target))
            }
        }
        return false
    }
}
