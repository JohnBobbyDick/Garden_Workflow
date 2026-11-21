import Foundation
import GardenCore

let data = Data(#"{"schema_version":1,"nodes":[{"id":"a","type":"trigger.manual","position":{"x":12,"y":5},"config":{"enabled":true,"filters":["*.kt",null]},"label":"Start"}],"edges":[]}"#.utf8)
let graph = try JSONDecoder().decode(Graph.self, from: data)
precondition(graph.nodes[0].config["enabled"] == .bool(true))
precondition(graph.nodes[0].config["filters"] == .array([.string("*.kt"), .null]))
let encoded = try JSONEncoder().encode(graph)
let decoded = try JSONDecoder().decode(Graph.self, from: encoded)
precondition(decoded == graph)

var parser = EventDecoder()
for line in [": keepalive", "", "id: 42", "event: node.status", #"data: {"id":42,"type":"node.status","node_id":"a","data":{"status":"running"}}"#] {
    let event = try parser.consume(line)
    precondition(event == nil)
}
let event = try parser.consume("")
precondition(event?.id == 42)
precondition(event?.nodeID == "a")
precondition(event?.data["status"] == .string("running"))
print("Graph round trip and SSE event decoding passed")

let findingJSON = Data(#"{"id":"f1","title":"Проверка","severity":"HIGH","category":"SCA","path":"build.gradle.kts","line":3,"description":"Описание","remediation":"Обновить","snippet":"","diff_status":"new","autofix":"deterministic"}"#.utf8)
let finding = try JSONDecoder().decode(Finding.self, from: findingJSON)
precondition(finding.diffStatus == "new" && finding.supportsAutofix)

let dashboardJSON = Data(#"{"workspace_id":"w","projects":2,"workflows":4,"runs":9,"findings_by_severity":{"HIGH":2},"score":{"run_id":"r","value":81,"delta":19,"history":[{"run_id":"r","score":81}],"top3":[],"note":"История"}}"#.utf8)
let dashboard = try JSONDecoder().decode(Dashboard.self, from: dashboardJSON)
precondition(dashboard.score?.history.first?.score == 81 && dashboard.severityCounts["HIGH"] == 2)

let patchJSON = Data(#"{"id":"p","finding_id":"f1","status":"validated","patch":"diff --git","steps":[{"name":"recheck","ok":true,"detail":"ok"}],"can_create_pr":false,"pr_unavailable_reason":"write_forbidden"}"#.utf8)
let patch = try JSONDecoder().decode(Autofix.self, from: patchJSON)
precondition(patch.steps.first?.ok == true && patch.canCreatePR == false)
print("Finding, dashboard and AutoFix API contracts passed")

final class ContractProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url else { return }
        let auth = request.value(forHTTPHeaderField: "Authorization")
        let response: (Int, String)
        switch (request.httpMethod, url.path, auth) {
        case ("POST", "/api/auth/login", nil):
            response = (200, #"{"access_token":"testing","refresh_token":"refresh"}"#)
        case ("POST", "/api/auth/register", nil):
            response = (201, #"{"access_token":"testing","refresh_token":"refresh"}"#)
        case ("POST", "/api/auth/logout", "Bearer testing"):
            response = (204, "")
        case ("POST", "/api/uploads", "Bearer testing"):
            precondition(request.value(forHTTPHeaderField: "Content-Type")?.hasPrefix("multipart/form-data; boundary=") == true)
            response = (201, #"{"id":"u"}"#)
        case ("POST", "/api/projects", "Bearer testing"):
            response = (201, #"{"id":"project","name":"Учебный","description":"","source_mode":"upload"}"#)
        case ("GET", "/api/dashboard", "Bearer testing"):
            response = (200, #"{"projects":2,"workflows":4,"runs":9,"findings_by_severity":{},"score":null}"#)
        case ("GET", "/api/runs/a/findings", "Bearer testing"):
            response = (200, #"{"findings":[]}"#)
        case ("GET", "/api/runs/a/ai-report", "Bearer testing"):
            response = (404, #"{"error":{"message":"Отчёт отсутствует"}}"#)
        case ("GET", "/api/runs/compare", "Bearer testing"):
            let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems
            precondition(query == [.init(name: "base", value: "a"), .init(name: "head", value: "b")])
            response = (200, #"{"new":[],"fixed":[],"unchanged":[]}"#)
        case ("GET", "/api/autofixes/p/patch", "Bearer testing"):
            response = (200, "diff --git")
        default:
            response = (500, #"{"error":{"message":"Unexpected test request"}}"#)
        }
        if let result = HTTPURLResponse(url: url, statusCode: response.0, httpVersion: "HTTP/1.1", headerFields: nil) {
            client?.urlProtocol(self, didReceive: result, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(response.1.utf8))
            client?.urlProtocolDidFinishLoading(self)
        }
    }

    override func stopLoading() {}
}

let configuration = URLSessionConfiguration.ephemeral
configuration.protocolClasses = [ContractProtocol.self]
let client = GardenAPI(server: URL(string: "https://test.invalid")!, session: URLSession(configuration: configuration))
try await client.login(email: "test@example.invalid", password: "test-only")
let liveDashboard = try await client.dashboard()
let results = try await client.findings(runID: "a")
let noReport = try await client.report(runID: "a")
let comparison = try await client.compare(base: "a", head: "b")
let patchFile = try await client.patch(id: "p")
precondition(liveDashboard.runs == 9 && results.isEmpty && noReport == nil)
precondition(comparison.fixed.isEmpty && String(decoding: patchFile, as: UTF8.self) == "diff --git")
print("Authenticated results HTTP routes, query parameters, missing report and patch export passed")


try await client.login(email: "test@example.invalid", password: "test-only", register: true)
let uploadID = try await client.uploadArchive(filename: "example.zip", data: Data([1, 2, 3]))
let draft = ProjectDraft(name: "Учебный", description: "", sourceMode: "upload", uploadID: uploadID)
let project = try await client.saveProject(id: nil, draft: draft)
precondition(uploadID == "u" && project.sourceMode == "upload")
let gitDraft = ProjectDraft(name: "Учебный", description: "", sourceMode: "git_url", gitURL: "https://example.invalid/project")
let encodedDraft = try JSONSerialization.jsonObject(with: JSONEncoder().encode(gitDraft)) as? [String: Any]
precondition(encodedDraft?["ref"] is NSNull && encodedDraft?["upload_id"] is NSNull)
try await client.logout()
do {
    _ = try await client.dashboard()
    preconditionFailure("Expected logout to clear access token")
} catch let error as APIError { precondition(error.status == 401) }
print("Registration, logout, multipart upload and project contract passed")

let workspaceJSON = Data(#"{"id":"w","name":"Команда","role":"admin","timezone":"Europe/Moscow"}"#.utf8)
let workspace = try JSONDecoder().decode(Workspace.self, from: workspaceJSON)
precondition(workspace.canManage)
let templateJSON = Data(#"{"id":"t","name":"Базовый","description":"","favorite":false,"node_types":["trigger.manual"],"rating_avg":4.5,"usage_count":3,"mine":false}"#.utf8)
let template = try JSONDecoder().decode(WorkflowTemplate.self, from: templateJSON)
precondition(template.nodeTypes == ["trigger.manual"] && template.rating == 4.5)
print("Workspace and template contracts passed")

let invalidGraph = Data(#"{"schema_version":1,"nodes":[{"id":"duplicate","type":"trigger.manual","position":{"x":0,"y":0},"config":{},"label":"A"},{"id":"duplicate","type":"trigger.manual","position":{"x":0,"y":0},"config":{},"label":"B"}],"edges":[]}"#.utf8)
let invalid = try JSONDecoder().decode(Graph.self, from: invalidGraph)
do {
    try invalid.validateImport()
    preconditionFailure("Duplicate graph node IDs must be rejected before editing")
} catch let error as GraphImportError { precondition(error == .duplicateNode) }

var connected = Graph()
let source = Graph.Node(type: "trigger.manual", label: "Source", position: .init(x: 0, y: 0))
let target = Graph.Node(type: "logic.if_else", label: "Target", position: .init(x: 0, y: 100))
connected.nodes = [source, target]
connected.edges.append(.init(source: source.id, sourcePort: "out", target: target.id, targetPort: "in"))
precondition(!connected.createsCycle(source: source.id, target: target.id))
precondition(connected.createsCycle(source: target.id, target: source.id))
try connected.validateImport()
print("Graph import validation and cycle prevention passed")

let openDraft = Data(#"{"graph":{"nodes":[{"id":"ai-start","type":"trigger.manual","position":{"x":20,"y":40},"metadata":{"color":"green"}}],"edges":[],"metadata":{"owner":"team"}},"valid":true}"#.utf8)
let aiDraft = try JSONDecoder().decode(WorkflowProposal.self, from: openDraft)
precondition(aiDraft.canApply && aiDraft.graph?.nodes.first?.label == "")
let savedDraft = try JSONEncoder().encode(aiDraft.graph)
let savedAsJSON = try JSONDecoder().decode(JSONValue.self, from: savedDraft)
guard case .object(let draftObject) = savedAsJSON else { fatalError("Missing graph object") }
precondition(draftObject["metadata"] == .object(["owner": .string("team")]))
guard case .array(let draftNodes) = draftObject["nodes"], case .object(let draftNode) = draftNodes.first else {
    fatalError("Missing draft node")
}
precondition(draftNode["metadata"] == .object(["color": .string("green")]))
print("AI drafts without labels and backend extension fields passed")
