import Foundation
import GardenCore

actor CollectedEvents {
    var events: [RunEvent] = []
    func add(_ event: RunEvent) { events.append(event) }
}

let env = ProcessInfo.processInfo.environment
guard let address = env["GARDEN_TEST_SERVER"], let server = URL(string: address),
      let host = server.host, ["127.0.0.1", "localhost", "::1"].contains(host),
      let trainingPath = env["GARDEN_TEST_FIXTURES"] else {
    fatalError("Set GARDEN_TEST_SERVER to an isolated loopback API and GARDEN_TEST_FIXTURES to organizer-training.")
}
let fixtures = URL(fileURLWithPath: trainingPath, isDirectory: true)
let api = GardenAPI(server: server)
let email = "swift-smoke-" + UUID().uuidString.prefix(8).lowercased() + "@example.com"
try await api.login(email: email, password: UUID().uuidString, register: true)
let workspaces = try await api.workspaces()
guard let workspace = workspaces.first else { fatalError("No workspace returned") }
await api.selectWorkspace(workspace.id)
let catalog = try await api.catalog()
let project = try await api.saveProject(id: nil, draft: .init(
    name: "Swift integration training fixture", description: "", sourceMode: "path",
    path: fixtures.appending(path: "training-project").path
))

let types = ["trigger.manual", "source.repo", "scanner.secrets", "scanner.sca", "scanner.sast", "logic.merge", "ai.report"]
var graph = Graph()
graph.nodes = try types.enumerated().map { index, type in
    guard let node = catalog.first(where: { $0.type == type }) else { throw URLError(.cannotParseResponse) }
    return Graph.Node(type: type, label: node.title["ru"] ?? type, position: .init(x: 0, y: Double(index * 100)))
}
graph.nodes[3].config["database_path"] = .string(fixtures.appending(path: "vulnerability-database/vulnerabilities.json").path)
graph.edges = [(0,1), (1,2), (1,3), (1,4), (2,5), (3,5), (4,5), (5,6)].map { from, to in
    Graph.Edge(source: graph.nodes[from].id, sourcePort: "out", target: graph.nodes[to].id, targetPort: "in")
}
let issues = try await api.validate(graph, workspaceID: workspace.id)
precondition(issues.isEmpty, "Graph validation failed: \(issues)")
let workflow = try await api.save(id: nil, name: "Swift smoke", graph: graph)
precondition(workflow.workspaceID == workspace.id)
let run = try await api.start(workflow.id, projectID: project.id)
let stream = CollectedEvents()
try await api.events(runID: run.id, after: nil) { await stream.add($0) }
let received = await stream.events
let completed = try await api.run(run.id)
precondition(completed.status == "success", "Run failed: \(completed.error ?? completed.status)")
precondition(received.contains { $0.type == "node.status" })
precondition(received.contains { $0.type == "edge.data" })
let found = try await api.findings(runID: run.id)
precondition(found.count == 15, "Unexpected number of findings: \(found.count)")
let ai = try await api.report(runID: run.id)
precondition(ai?.report?.summary?.isEmpty == false)
if let candidate = found.first(where: { $0.autofix == "deterministic" }) {
    let fix = try await api.generateAutofix(runID: run.id, findingID: candidate.id)
    precondition(fix.status == "validated", "Patch did not validate: \(fix.status) / \(fix.reason ?? "")")
    let diff = try await api.patch(id: fix.id)
    precondition(!diff.isEmpty)
    print("Deterministic AutoFix validated and patch exported. No PR requested.")
} else { fatalError("Expected a deterministic AutoFix candidate") }
let dashboard = try await api.dashboard()
precondition(dashboard.runs == 1)
let yaml = try await api.ciYAML(workflowID: workflow.id, provider: "github", branches: "main")
precondition(String(decoding: yaml, as: UTF8.self).contains(workflow.id))
let report = try await api.export(runID: run.id, format: .submission)
precondition(!report.isEmpty)
let template = try await api.publishTemplate(workflowID: workflow.id, name: "Swift integration test", description: "Local test")
let published = try await api.templates(search: "Swift integration test", favorites: false)
precondition(published.contains { $0.id == template.id })
try await api.favoriteTemplate(id: template.id, favorite: true)
let favoriteRows = try await api.templates(search: "Swift integration test", favorites: true)
precondition(favoriteRows.contains { $0.id == template.id })
if let endpoint = env["GARDEN_TEST_LLM"] {
    guard let host = URL(string: endpoint)?.host, ["localhost", "127.0.0.1", "::1"].contains(host) else {
        fatalError("GARDEN_TEST_LLM must point to a loopback test provider.")
    }
    let key = try await api.createCredential(name: "Test provider", kind: "llm_api_key", value: "fixture-only-value")
    let settings = try await api.saveAISettings([
        "enabled": .bool(true), "provider": .string("openai_compat"),
        "base_url": .string(endpoint), "model": .string("test-model"),
        "allow_local": .bool(true), "credential_id": .string(key.id)
    ])
    precondition(settings["enabled"] == .bool(true))
    let draftProposal = try await api.generateWorkflow(prompt: "Build a workflow for the training fixture")
    guard let proposedGraph = draftProposal.graph, draftProposal.canApply else { fatalError("No AI graph") }
    let savedAI = try await api.save(id: nil, name: "AI smoke", graph: proposedGraph)
    let edit = try await api.proposeEdit(workflowID: savedAI.id, message: "Rename the trigger")
    guard let editID = edit.id, edit.canApply else { fatalError("No AI edit") }
    _ = try await api.resolveProposal(workflowID: savedAI.id, id: editID, apply: true)
    let changedGraph = try await api.workflow(savedAI.id)
    precondition(changedGraph.graph?.nodes.first { $0.id == "t" }?.label == "Проверка по кнопке")
    let rejected = try await api.proposeEdit(workflowID: savedAI.id, message: "Rename the trigger again")
    guard let rejectedID = rejected.id else { fatalError("No second edit") }
    _ = try await api.resolveProposal(workflowID: savedAI.id, id: rejectedID, apply: false)
    let retainedGraph = try await api.workflow(savedAI.id)
    precondition(retainedGraph.graph?.nodes.first { $0.id == "t" }?.label == "Проверка по кнопке")
    try await api.deleteCredential(id: key.id)
    print("Local test LLM: generated workflow, applied and rejected AI edits")
}
let ciToken = try await api.issueCIToken(name: "Smoke CI key", workflowID: workflow.id)
precondition(ciToken.token?.isEmpty == false)
try await api.revokeCIToken(id: ciToken.id)
let keyStatus = try await api.ciTokens()
precondition(keyStatus.first { $0.id == ciToken.id }?.revoked == true)
print("CI token lifecycle verified")
try await api.logout()
print("FastAPI smoke passed: workspace, catalog, fixture project, saved graph, SSE (\(received.count) events), findings (\(found.count)), dashboard, export, CI YAML, templates and logout")
