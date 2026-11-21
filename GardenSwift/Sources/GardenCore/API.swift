import Foundation

public struct Workflow: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let graph: Graph?
    public let projectID: String?
    public let version: Int?
    public let workspaceID: String

    enum CodingKeys: String, CodingKey {
        case id, name, graph, version
        case workspaceID = "workspace_id", projectID = "project_id"
    }
}

public struct ScanProject: Decodable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let description: String
    public let sourceMode: String
    public let gitURL: String?
    public let ref: String?
    public let path: String?

    enum CodingKeys: String, CodingKey {
        case id, name, description, ref, path
        case sourceMode = "source_mode", gitURL = "git_url"
    }
}

public struct ProjectDraft: Encodable, Sendable {
    public var name: String
    public var description: String
    public var sourceMode: String
    public var gitURL: String?
    public var ref: String?
    public var path: String?
    public var uploadID: String?

    enum CodingKeys: String, CodingKey {
        case name, description, ref, path
        case sourceMode = "source_mode", gitURL = "git_url", uploadID = "upload_id"
    }

    public init(name: String, description: String, sourceMode: String, gitURL: String? = nil,
                ref: String? = nil, path: String? = nil, uploadID: String? = nil) {
        self.name = name
        self.description = description
        self.sourceMode = sourceMode
        self.gitURL = gitURL
        self.ref = ref
        self.path = path
        self.uploadID = uploadID
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(name, forKey: .name)
        try container.encode(description, forKey: .description)
        try container.encode(sourceMode, forKey: .sourceMode)
        try container.encode(gitURL, forKey: .gitURL)
        try container.encode(ref, forKey: .ref)
        try container.encode(path, forKey: .path)
        if sourceMode == "upload" {
            try container.encodeIfPresent(uploadID, forKey: .uploadID)
        } else {
            try container.encodeNil(forKey: .uploadID)
        }
    }
}

public struct NodeDefinition: Decodable, Identifiable, Sendable {
    public struct Port: Decodable, Sendable {
        public let name: String
        public let type: String
        public let multiple: Bool?
    }

    public let type: String
    public let title: [String: String]
    public let category: String
    public let inputs: [Port]
    public let outputs: [Port]
    public let configSchema: [String: JSONValue]
    public var id: String { type }

    enum CodingKeys: String, CodingKey {
        case type, title, category, inputs, outputs
        case configSchema = "config_schema"
    }
}

public struct Run: Decodable, Identifiable, Sendable {
    public let id: String
    public let status: String
    public let verdict: String?
    public let score: Int?
    public let graphSnapshot: Graph?
    public let artifacts: [Artifact]?
    public let nodes: [NodeResult]?
    public let duration: Int?

    public struct Artifact: Decodable, Identifiable, Sendable {
        public let name: String
        public let size: Int
        public var id: String { name }
    }

    public struct NodeResult: Decodable, Sendable {
        public let nodeID: String
        public let status: String
        public let error: String?
        public let outputSummary: JSONValue?
        enum CodingKeys: String, CodingKey {
            case status, error
            case nodeID = "node_id", outputSummary = "output_summary"
        }
    }
    public let workflowName: String?
    public let createdAt: String?
    public let error: String?

    enum CodingKeys: String, CodingKey {
        case id, status, verdict, score, error, artifacts, nodes
        case duration = "duration_ms"
        case workflowName = "workflow_name", createdAt = "created_at"
        case graphSnapshot = "graph_snapshot"
    }
}

public struct APIError: LocalizedError {
    public let status: Int
    public let message: String
    public var errorDescription: String? { message }
}

public actor GardenAPI {
    private struct Tokens: Codable {
        let access_token: String
        let refresh_token: String
    }

    private struct Credentials: Encodable { let email: String; let password: String }
    private struct Upload: Decodable { let id: String }
    private struct Refresh: Encodable { let refresh_token: String }
    private struct RunSource: Encodable { let project_id: String }
    private struct Draft: Encodable { let name: String; let graph: Graph; let workspace_id: String? }
    private struct GraphCheck: Encodable { let workspace_id: String; let graph: Graph }
    private struct Validation: Decodable { let valid: Bool; let issues: [JSONValue] }
    private struct Catalog: Decodable { let nodes: [NodeDefinition] }
    private struct FindingList: Decodable { let findings: [Finding] }
    private struct RunList: Decodable { let runs: [Run] }
    private struct ErrorEnvelope: Decodable {
        struct Detail: Decodable { let message: String }
        let error: Detail
    }

    private struct TemplateList: Decodable { let templates: [WorkflowTemplate] }
    private struct ResourceID: Decodable { let id: String }
    public private(set) var workspaceID: String?
    private var workspaceQuery: [URLQueryItem] {
        workspaceID.map { [.init(name: "workspace_id", value: $0)] } ?? []
    }

    private let server: URL
    private let session: URLSession
    private let onRefreshToken: (@Sendable (String?) -> Void)?
    private var tokens: Tokens?
    private var refreshTask: Task<Tokens, Error>?

    public init(server: URL, session: URLSession? = nil, onRefreshToken: (@Sendable (String?) -> Void)? = nil) {
        self.server = server
        self.onRefreshToken = onRefreshToken
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        self.session = session ?? URLSession(configuration: configuration)
    }

    private func makeRequest(_ path: String, method: String = "GET", body: Data? = nil, token: String? = nil,
                             query: [URLQueryItem] = [], contentType: String = "application/json") -> URLRequest {
        let url = server.appending(path: "api").appending(path: path).appending(queryItems: query)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        if body != nil { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        return request
    }

    private static func decode<T: Decodable>(_ type: T.Type, data: Data, response: URLResponse) throws -> T {
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let detail = try? JSONDecoder().decode(ErrorEnvelope.self, from: data)
            throw APIError(status: status, message: detail?.error.message ?? "HTTP \(status)")
        }
        return try JSONDecoder().decode(type, from: data)
    }

    private func refresh(after rejectedToken: String) async throws -> String {
        if let current = tokens, current.access_token != rejectedToken { return current.access_token }
        if let refreshTask { return try await refreshTask.value.access_token }
        guard let tokens else { throw APIError(status: 401, message: "Войдите в систему") }
        let body = try JSONEncoder().encode(Refresh(refresh_token: tokens.refresh_token))
        let request = makeRequest("auth/refresh", method: "POST", body: body)
        let task = Task {
            let (data, response) = try await session.data(for: request)
            return try Self.decode(Tokens.self, data: data, response: response)
        }
        refreshTask = task
        defer { refreshTask = nil }
        let renewed = try await task.value
        self.tokens = renewed
        onRefreshToken?(renewed.refresh_token)
        return renewed.access_token
    }

    private func authorizedResponse(_ path: String, method: String = "GET", body: Data? = nil,
                                    query: [URLQueryItem] = [], contentType: String = "application/json") async throws -> (Data, URLResponse) {
        guard let access = tokens?.access_token else { throw APIError(status: 401, message: "Войдите в систему") }
        let response = try await session.data(for: makeRequest(path, method: method, body: body, token: access, query: query, contentType: contentType))
        guard (response.1 as? HTTPURLResponse)?.statusCode == 401 else { return response }
        let newToken = try await refresh(after: access)
        return try await session.data(for: makeRequest(path, method: method, body: body, token: newToken, query: query, contentType: contentType))
    }

    private func send<T: Decodable>(_ path: String, method: String = "GET", body: Data? = nil,
                                    query: [URLQueryItem] = []) async throws -> T {
        let (data, response) = try await authorizedResponse(path, method: method, body: body, query: query)
        return try Self.decode(T.self, data: data, response: response)
    }

    private func download(_ path: String, query: [URLQueryItem] = []) async throws -> Data {
        let (data, response) = try await authorizedResponse(path, query: query)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let details = try? JSONDecoder().decode(ErrorEnvelope.self, from: data)
            throw APIError(status: status, message: details?.error.message ?? "HTTP \(status)")
        }
        return data
    }

    public func dashboard() async throws -> Dashboard { try await send("dashboard", query: workspaceQuery) }
    public func findings(runID: String) async throws -> [Finding] {
        let result: FindingList = try await send("runs/\(runID)/findings")
        return result.findings
    }
    public func report(runID: String) async throws -> AIReport? {
        do { return try await send("runs/\(runID)/ai-report") }
        catch let error as APIError where error.status == 404 { return nil }
    }
    public func generateAutofix(runID: String, findingID: String) async throws -> Autofix {
        try await send("runs/\(runID)/findings/\(findingID)/autofix", method: "POST")
    }
    public func autofixes(runID: String) async throws -> [Autofix] {
        try await send("runs/\(runID)/autofixes")
    }
    public func autofix(id: String) async throws -> Autofix { try await send("autofixes/\(id)") }
    public func patch(id: String) async throws -> Data { try await download("autofixes/\(id)/patch") }
    public func export(runID: String, format: ReportFormat) async throws -> Data {
        try await download("runs/\(runID)/export/\(format.rawValue)")
    }

    public func compare(base: String, head: String) async throws -> RunComparison {
        try await send("runs/compare", query: [.init(name: "base", value: base), .init(name: "head", value: head)])
    }

    public func login(email: String, password: String, register: Bool = false) async throws {
        let body = try JSONEncoder().encode(Credentials(email: email, password: password))
        let (data, response) = try await session.data(for: makeRequest(register ? "auth/register" : "auth/login", method: "POST", body: body))
        let renewed = try Self.decode(Tokens.self, data: data, response: response)
        tokens = renewed
        onRefreshToken?(renewed.refresh_token)
    }

    public func restore(refreshToken: String) async throws {
        let body = try JSONEncoder().encode(Refresh(refresh_token: refreshToken))
        let request = makeRequest("auth/refresh", method: "POST", body: body)
        let (data, response) = try await session.data(for: request)
        let renewed = try Self.decode(Tokens.self, data: data, response: response)
        tokens = renewed
        onRefreshToken?(renewed.refresh_token)
    }

    public func logout() async throws {
        guard let tokens else { return }
        var body = try JSONEncoder().encode(Refresh(refresh_token: tokens.refresh_token))
        var (data, response) = try await session.data(for: makeRequest("auth/logout", method: "POST", body: body, token: tokens.access_token))
        if (response as? HTTPURLResponse)?.statusCode == 401 {
            let access = try await refresh(after: tokens.access_token)
            guard let current = self.tokens else { return }
            body = try JSONEncoder().encode(Refresh(refresh_token: current.refresh_token))
            (data, response) = try await session.data(for: makeRequest("auth/logout", method: "POST", body: body, token: access))
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let details = try? JSONDecoder().decode(ErrorEnvelope.self, from: data)
            throw APIError(status: status, message: details?.error.message ?? "HTTP \(status)")
        }
        self.tokens = nil
        onRefreshToken?(nil)
    }

    public func saveProject(id: String?, draft: ProjectDraft) async throws -> ScanProject {
        let body = try scopedBody(draft)
        if let id { return try await send("projects/\(id)", method: "PATCH", body: body) }
        return try await send("projects", method: "POST", body: body)
    }

    public func uploadArchive(filename: String, data: Data) async throws -> String {
        let boundary = "Garden-" + UUID().uuidString
        let safeFilename = filename.map { char in
            char.isASCII && (char.isLetter || char.isNumber || "._-".contains(char)) ? char : "_"
        }
        var body = Data(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"" +
                         String(safeFilename) + "\"\r\nContent-Type: application/octet-stream\r\n\r\n").utf8)
        body.append(data)
        if let workspaceID {
            body.append(Data(("\r\n--" + boundary +
                              "\r\nContent-Disposition: form-data; name=\"workspace_id\"\r\n\r\n" +
                              workspaceID).utf8))
        }
        body.append(Data(("\r\n--" + boundary + "--\r\n").utf8))
        let (payload, response) = try await authorizedResponse("uploads", method: "POST", body: body,
                                                                contentType: "multipart/form-data; boundary=" + boundary)
        return try Self.decode(Upload.self, data: payload, response: response).id
    }

    public func projects() async throws -> [ScanProject] { try await send("projects", query: workspaceQuery) }
    public func workflows() async throws -> [Workflow] { try await send("workflows", query: workspaceQuery) }
    public func workflow(_ id: String) async throws -> Workflow { try await send("workflows/\(id)") }
    public func catalog() async throws -> [NodeDefinition] {
        let catalog: Catalog = try await send("nodes")
        return catalog.nodes
    }
    public func save(id: String?, name: String, graph: Graph) async throws -> Workflow {
        let body = try JSONEncoder().encode(Draft(name: name, graph: graph, workspace_id: id == nil ? workspaceID : nil))
        if let id { return try await send("workflows/\(id)", method: "PUT", body: body) }
        return try await send("workflows", method: "POST", body: body)
    }
    public func validate(_ graph: Graph, workspaceID: String) async throws -> [JSONValue] {
        let body = try JSONEncoder().encode(GraphCheck(workspace_id: workspaceID, graph: graph))
        let validation: Validation = try await send("workflows/validate", method: "POST", body: body)
        return validation.issues
    }
    public func start(_ id: String, projectID: String? = nil) async throws -> Run {
        let body = try projectID.map { try JSONEncoder().encode(RunSource(project_id: $0)) }
        return try await send("workflows/\(id)/run", method: "POST", body: body)
    }
    public func run(_ id: String) async throws -> Run { try await send("runs/\(id)") }
    public func runs(workflowID: String? = nil, status: String? = nil, since: String? = nil,
                     until: String? = nil, initiator: String? = nil, offset: Int = 0) async throws -> [Run] {
        let filters: [(String, String?)] = [
            ("workflow_id", workflowID), ("status", status), ("since", since),
            ("until", until), ("triggered_by", initiator), ("offset", String(offset))
        ]
        let parameters = filters.compactMap { key, value in value.map { URLQueryItem(name: key, value: $0) } }
        let history: RunList = try await send("runs", query: workspaceQuery + parameters)
        return history.runs
    }
    public func cancel(_ id: String) async throws -> Run { try await send("runs/\(id)/cancel", method: "POST") }

    public func selectWorkspace(_ id: String?) {
        workspaceID = id
    }

    private func scopedBody<T: Encodable>(_ value: T) throws -> Data {
        let encoded = try JSONEncoder().encode(value)
        guard let workspaceID else { return encoded }
        var body = try JSONDecoder().decode([String: JSONValue].self, from: encoded)
        body["workspace_id"] = .string(workspaceID)
        return try JSONEncoder().encode(body)
    }

    public func updateLanguage(_ locale: String) async throws {
        let _: JSONValue = try await send("auth/me", method: "PATCH", body: JSONEncoder().encode(["locale": locale]))
    }

    public func workspaces() async throws -> [Workspace] { try await send("workspaces") }

    public func createWorkspace(name: String, timezone: String) async throws -> Workspace {
        try await send("workspaces", method: "POST", body: JSONEncoder().encode(["name": name, "timezone": timezone]))
    }

    public func members(workspaceID: String) async throws -> JSONValue {
        try await send("workspaces/\(workspaceID)/members")
    }

    public func invite(workspaceID: String, email: String, role: String) async throws -> JSONValue {
        try await send("workspaces/\(workspaceID)/members", method: "POST",
                       body: JSONEncoder().encode(["email": email, "role": role]))
    }

    public func acceptInvitation(_ token: String) async throws -> JSONValue {
        try await send("invitations/accept", method: "POST", body: JSONEncoder().encode(["token": token]))
    }

    public func changeRole(workspaceID: String, userID: String, role: String) async throws -> JSONValue {
        try await send("workspaces/\(workspaceID)/members/\(userID)", method: "PATCH",
                       body: JSONEncoder().encode(["role": role]))
    }

    public func aiSettings() async throws -> [String: JSONValue] {
        try await send("settings/ai", query: workspaceQuery)
    }

    public func saveAISettings(_ settings: [String: JSONValue]) async throws -> [String: JSONValue] {
        try await send("settings/ai", method: "PUT", body: scopedBody(settings))
    }

    public func testAI() async throws -> JSONValue {
        try await send("settings/ai/test", method: "POST", body: scopedBody([String: JSONValue]()))
    }

    public func credentials() async throws -> [PlatformItem] { try await send("credentials", query: workspaceQuery) }

    public func createCredential(name: String, kind: String, value: String) async throws -> PlatformItem {
        try await send("credentials", method: "POST", body: scopedBody(["name": name, "kind": kind, "value": value]))
    }

    public func schedule(workflowID: String) async throws -> JSONValue {
        try await send("workflows/\(workflowID)/schedule")
    }

    public func setSchedule(workflowID: String, enabled: Bool) async throws -> JSONValue {
        try await send("workflows/\(workflowID)/schedule", method: "PUT", body: JSONEncoder().encode(["enabled": enabled]))
    }

    public func templates(search: String, favorites: Bool, category: String = "", author: String = "",
                          mine: Bool = false, minimumRating: Int = 0, sort: String = "new") async throws -> [WorkflowTemplate] {
        var query: [URLQueryItem] = [
            .init(name: "q", value: search), .init(name: "favorites", value: favorites ? "true" : "false"),
            .init(name: "mine", value: mine ? "true" : "false"), .init(name: "sort", value: sort)
        ]
        if !category.isEmpty { query.append(.init(name: "category", value: category)) }
        if !author.isEmpty { query.append(.init(name: "author", value: author)) }
        if minimumRating > 0 { query.append(.init(name: "min_rating", value: String(minimumRating))) }
        let response: TemplateList = try await send("templates", query: query)
        return response.templates
    }

    public func template(id: String) async throws -> WorkflowTemplate { try await send("templates/\(id)") }

    public func publishTemplate(workflowID: String, name: String, description: String, category: String = "Custom",
                                tags: [String] = [], version: String = "1.0.0") async throws -> WorkflowTemplate {
        let fields: [String: JSONValue] = [
            "workflow_id": .string(workflowID), "name": .string(name), "description": .string(description),
            "category": .string(category), "tags": .array(tags.map(JSONValue.string)), "version": .string(version)
        ]
        return try await send("templates", method: "POST", body: JSONEncoder().encode(fields))
    }

    public func setTemplatePublication(id: String, published: Bool) async throws -> WorkflowTemplate {
        try await send("templates/\(id)", method: "PUT", body: JSONEncoder().encode(["published": published]))
    }

    public func setTemplateVisibility(id: String, hidden: Bool) async throws -> WorkflowTemplate {
        try await send("templates/\(id)/hide", method: "POST", body: JSONEncoder().encode(["hidden": hidden]))
    }

    public func isPlatformAdmin() async throws -> Bool {
        let me: [String: JSONValue] = try await send("auth/me")
        guard case .object(let profile) = me["user"] else { return false }
        return profile["is_platform_admin"] == .bool(true)
    }

    public func useTemplate(id: String, name: String, parameters: [String: JSONValue]) async throws -> Workflow {
        let response: ResourceID = try await send("templates/\(id)/use", method: "POST",
            body: scopedBody(["name": .string(name), "params": .object(parameters)] as [String: JSONValue]))
        return try await workflow(response.id)
    }

    private func changeResource(_ path: String, method: String) async throws {
        let (data, response) = try await authorizedResponse(path, method: method)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if !(200..<300).contains(status) {
            let detail = try? JSONDecoder().decode(ErrorEnvelope.self, from: data)
            throw APIError(status: status, message: detail?.error.message ?? "HTTP \(status)")
        }
    }

    public func favoriteTemplate(id: String, favorite: Bool) async throws {
        try await changeResource("templates/\(id)/favorite", method: favorite ? "POST" : "DELETE")
    }

    public func rateTemplate(id: String, stars: Int) async throws -> JSONValue {
        try await send("templates/\(id)/rate", method: "POST", body: JSONEncoder().encode(["stars": stars]))
    }

    public func templateReviews(id: String) async throws -> JSONValue { try await send("templates/\(id)/reviews") }

    public func reviewTemplate(id: String, text: String) async throws -> JSONValue {
        try await send("templates/\(id)/reviews", method: "POST", body: JSONEncoder().encode(["text": text]))
    }

    public func ciTokens() async throws -> [PlatformItem] { try await send("api-tokens", query: workspaceQuery) }

    public func issueCIToken(name: String, workflowID: String) async throws -> PlatformItem {
        try await send("api-tokens", method: "POST", body: scopedBody(["name": name, "workflow_id": workflowID]))
    }

    public func revokeCIToken(id: String) async throws { try await changeResource("api-tokens/\(id)", method: "DELETE") }

    public func ciYAML(workflowID: String, provider: String, branches: String) async throws -> Data {
        try await download("ci/yaml", query: [.init(name: "provider", value: provider),
                                             .init(name: "workflow_id", value: workflowID),
                                             .init(name: "branches", value: branches)])
    }

    public func ciCLI() async throws -> Data { try await download("ci/cli") }

    public func webhookStatus() async throws -> JSONValue { try await send("ci/webhooks/status", query: workspaceQuery) }

    public func generateWorkflow(prompt: String) async throws -> WorkflowProposal {
        try await send("ai/workflows/generate", method: "POST", body: scopedBody(
            ["prompt": .string(prompt), "create": .bool(false)] as [String: JSONValue]
        ))
    }

    public func proposalHistory(workflowID: String) async throws -> JSONValue {
        try await send("ai/workflows/\(workflowID)/chat")
    }

    public func proposeEdit(workflowID: String, message: String) async throws -> WorkflowProposal {
        try await send("ai/workflows/\(workflowID)/chat", method: "POST", body: JSONEncoder().encode(["message": message]))
    }

    public func resolveProposal(workflowID: String, id: String, apply: Bool) async throws -> JSONValue {
        try await send("ai/workflows/\(workflowID)/chat/\(id)/\(apply ? "apply" : "reject")", method: "POST")
    }

    public func allowlist() async throws -> JSONValue { try await send("settings/allowlist", query: workspaceQuery) }

    public func saveAllowlist(_ entries: [[String: JSONValue]]) async throws -> JSONValue {
        try await send("settings/allowlist", method: "PUT", body: scopedBody(["entries": entries]))
    }

    public func updateCredential(id: String, value: String) async throws -> PlatformItem {
        try await send("credentials/\(id)", method: "PUT", body: JSONEncoder().encode(["value": value]))
    }

    public func deleteCredential(id: String) async throws {
        try await changeResource("credentials/\(id)", method: "DELETE")
    }

    public func removeMember(workspaceID: String, userID: String) async throws {
        try await changeResource("workspaces/\(workspaceID)/members/\(userID)", method: "DELETE")
    }

    public func audit(workspaceID: String) async throws -> JSONValue {
        try await send("workspaces/\(workspaceID)/audit")
    }

    public func updateWorkspace(id: String, name: String) async throws -> Workspace {
        try await send("workspaces/\(id)", method: "PATCH", body: JSONEncoder().encode(["name": name]))
    }

    public func updateTemplate(id: String, description: String, version: String) async throws -> WorkflowTemplate {
        try await send("templates/\(id)", method: "PUT", body: JSONEncoder().encode(
            ["description": description, "version": version]
        ))
    }

    public func editReview(templateID: String, id: String, text: String) async throws -> JSONValue {
        try await send("templates/\(templateID)/reviews/\(id)", method: "PUT", body: JSONEncoder().encode(["text": text]))
    }

    public func deleteReview(templateID: String, id: String) async throws {
        try await changeResource("templates/\(templateID)/reviews/\(id)", method: "DELETE")
    }

    public func deleteWorkflow(id: String) async throws { try await changeResource("workflows/\(id)", method: "DELETE") }
    public func deleteProject(id: String) async throws { try await changeResource("projects/\(id)", method: "DELETE") }

    public func scoreHistory(projectID: String, period: String) async throws -> ScoreHistory {
        try await send("projects/\(projectID)/score/history", query: [.init(name: "period", value: period)])
    }

    public func runScore(id: String) async throws -> JSONValue {
        try await send("runs/\(id)/score")
    }

    public func createSprintPlan(runID: String) async throws -> JSONValue {
        try await send("runs/\(runID)/sprint-plan", method: "POST")
    }

    public func artifact(runID: String, name: String) async throws -> Data {
        try await download("runs/\(runID)/artifacts/\(name)")
    }

    public func createAutofixPullRequest(id: String) async throws -> AutofixPullRequest {
        try await send("autofixes/\(id)/pull-request", method: "POST")
    }

    public func events(runID: String, after eventID: Int?, receive: @Sendable (RunEvent) async -> Void) async throws {
        guard let access = tokens?.access_token else { throw APIError(status: 401, message: "Войдите в систему") }
        func request(token: String) -> URLRequest {
            var request = makeRequest("runs/\(runID)/events", token: token)
            request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
            if let eventID { request.setValue(String(eventID), forHTTPHeaderField: "Last-Event-ID") }
            return request
        }
        var (bytes, response) = try await session.bytes(for: request(token: access))
        if (response as? HTTPURLResponse)?.statusCode == 401 {
            let renewed = try await refresh(after: access)
            (bytes, response) = try await session.bytes(for: request(token: renewed))
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else { throw APIError(status: status, message: "Поток событий недоступен (HTTP \(status))") }
        // AsyncBytes.lines may omit blank lines. SSE uses them as frame delimiters.
        var line = Data()
        var parser = EventDecoder()
        for try await byte in bytes {
            try Task.checkCancellation()
            if byte == 10 {
                if line.last == 13 { line.removeLast() }
                if let event = try parser.consume(String(decoding: line, as: UTF8.self)) { await receive(event) }
                line.removeAll(keepingCapacity: true)
            } else {
                line.append(byte)
            }
        }
    }
}
