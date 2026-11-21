import Foundation

public struct Workspace: Decodable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let role: String?
    public let timezone: String
    public var canManage: Bool { role == "admin" }
}

public struct WorkflowTemplate: Decodable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let description: String
    public let favorite: Bool
    public let rating: Double
    public let usageCount: Int
    public let nodeTypes: [String]
    public let graph: Graph?
    public let parameters: JSONValue?
    public let mine: Bool
    public let author: String?
    public let category: String?
    public let version: String?
    public let published: Bool?
    public let hidden: Bool?

    enum CodingKeys: String, CodingKey {
        case id, name, description, favorite, graph, parameters, mine, category, version, published, hidden
        case author = "author_name"
        case rating = "rating_avg", usageCount = "usage_count", nodeTypes = "node_types"
    }
}

public struct PlatformItem: Decodable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let display: String?
    public let kind: String?
    public let prefix: String?
    public let token: String?
    public let revoked: Bool?
}

public struct WorkflowProposal: Decodable, Sendable {
    public let id: String?
    public let graph: Graph?
    public let content: String?
    public let valid: Bool
    public let issues: [JSONValue]?
    public let diff: JSONValue?

    public var canApply: Bool { valid && graph != nil }
}
