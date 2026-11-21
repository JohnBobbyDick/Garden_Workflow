import Foundation
import GardenCore
import SwiftUI
import UniformTypeIdentifiers

@main
struct GardenApp: App {
    @AppStorage("appearance") private var appearance = "Системная"
    @AppStorage("language") private var language = "ru"
    var body: some Scene {
        WindowGroup("Garden Security") {
            GardenView()
                .environment(\.locale, Locale(identifier: language))
                .preferredColorScheme(appearance == "Светлая" ? .light : appearance == "Тёмная" ? .dark : nil)
        }
    }
}

enum EditorMode: String, CaseIterable, Identifiable {
    case editing = "Редактирование"
    case execution = "Выполнение"
    var id: Self { self }
}

@MainActor @Observable
final class GardenModel {
    var api: GardenAPI?
    var workspaces: [Workspace] = []
    var workspaceID: String?
    var workflows: [Workflow] = []
    var catalog: [NodeDefinition] = []
    var projects: [ScanProject] = []
    var projectID = ""
    var history: [GardenCore.Run] = []
    var workflow: Workflow?
    var graph = Graph()
    var name = ""
    var mode = EditorMode.editing
    var selected: String?
    var run: GardenCore.Run?
    var events: [RunEvent] = []
    var message = ""
    var busy = false
    var watching = false
    var undoStack: [Graph] = []
    var redoStack: [Graph] = []
    var serverAccountKey = ""
    var credentials: [PlatformItem] = []
    var paletteSearch = ""
    var selectedNodes: Set<String> = []
    var validationNodes: Set<String> = []
    var validationEdges: Set<String> = []
    var multiSelect = false
    var clipboardNodes: [Graph.Node] = []
    var clipboardEdges: [Graph.Edge] = []

    var draftKey: String? {
        guard let workspaceID, !serverAccountKey.isEmpty, !name.isEmpty else { return nil }
        return serverAccountKey + "|" + workspaceID + "|" + (workflow?.id ?? "new")
    }

    func editGraph(_ edit: (inout Graph) -> Void) {
        guard mode == .editing, !busy else { return }
        let old = graph
        edit(&graph)
        guard graph != old else { return }
        validationNodes = []
        validationEdges = []
        undoStack.append(old)
        if undoStack.count > 50 { undoStack.removeFirst() }
        redoStack.removeAll()
    }

    func undo() {
        guard let old = undoStack.popLast() else { return }
        redoStack.append(graph)
        graph = old
        selectedNodes.formIntersection(graph.nodes.map(\.id))
    }

    func redo() {
        guard let next = redoStack.popLast() else { return }
        undoStack.append(graph)
        graph = next
        selectedNodes.formIntersection(graph.nodes.map(\.id))
    }

    func persistDraft() {
        guard let key = draftKey, unsaved else { return }
        do { try GraphDraftStore.save(.init(title: name, graph: graph, version: workflow?.version), key: key) }
        catch { message = "Черновик не сохранён: " + error.localizedDescription }
    }

    func restoreDraft() {
        guard let key = draftKey, let draft = GraphDraftStore.load(key: key) else { return }
        guard draft.version == workflow?.version else {
            message = "Серверная версия изменилась. Прежний локальный черновик оставлен на диске."
            return
        }
        name = draft.title
        graph = draft.graph
        message = "Локальный черновик восстановлен."
    }

    func removeNodes(_ ids: Set<String>) {
        editGraph { graph in
            graph.nodes.removeAll { ids.contains($0.id) }
            graph.edges.removeAll { ids.contains($0.source) || ids.contains($0.target) }
        }
        selectedNodes.subtract(ids)
    }

    func copyNodes(_ ids: Set<String>) {
        clipboardNodes = graph.nodes.filter { ids.contains($0.id) }
        clipboardEdges = graph.edges.filter { ids.contains($0.source) && ids.contains($0.target) }
    }

    func pasteNodes() {
        let idMap = Dictionary(uniqueKeysWithValues: clipboardNodes.map { ($0.id, UUID().uuidString) })
        editGraph { graph in
            graph.nodes += clipboardNodes.compactMap { node in
                guard let id = idMap[node.id] else { return nil }
                var copy = node
                copy.id = id
                copy.position.x += 32
                copy.position.y += 32
                return copy
            }
            graph.edges += clipboardEdges.compactMap { edge in
                guard let from = idMap[edge.source], let to = idMap[edge.target] else { return nil }
                return Graph.Edge(source: from, sourcePort: edge.sourcePort, target: to, targetPort: edge.targetPort)
            }
        }
    }

    func connectPorts(from: String, output: String, to: String, input: String) -> String? {
        guard let source = graph.nodes.first(where: { $0.id == from }),
              let target = graph.nodes.first(where: { $0.id == to }),
              let outputSpec = catalog.first(where: { $0.type == source.type })?.outputs.first(where: { $0.name == output }),
              let inputSpec = catalog.first(where: { $0.type == target.type })?.inputs.first(where: { $0.name == input }),
              outputSpec.type == inputSpec.type || outputSpec.type == "any" || inputSpec.type == "any" else {
            return "Типы портов несовместимы."
        }
        if graph.edges.contains(where: { $0.source == from && $0.target == to && $0.sourcePort == output && $0.targetPort == input }) {
            return "Эта связь уже есть."
        }
        if inputSpec.multiple != true && graph.edges.contains(where: { $0.target == to && $0.targetPort == input }) {
            return "Вход уже занят."
        }
        if graph.createsCycle(source: from, target: to) { return "Связь создаёт цикл." }
        editGraph { $0.edges.append(.init(source: from, sourcePort: output, target: to, targetPort: input)) }
        return nil
    }

    var visibleGraph: Graph { mode == .execution ? (run?.graphSnapshot ?? graph) : graph }
    var selectedNode: Graph.Node? { visibleGraph.nodes.first { $0.id == selected } }
    var unsaved: Bool { workflow?.graph != graph || workflow?.name != name }

    func perform(_ action: @MainActor () async throws -> Void) async {
        guard !busy else { return }
        busy = true
        message = ""
        defer { busy = false }
        do { try await action() }
        catch { message = error.localizedDescription }
    }

    func connect(server: String, email: String, password: String, register: Bool, remember: Bool, resume: Bool = false) async {
        await perform {
            guard let url = URL(string: server), let host = url.host,
                  url.scheme == "https" || (url.scheme == "http" && ["localhost", "127.0.0.1", "::1"].contains(host)) else {
                message = "Укажите HTTPS-адрес сервера или локальный адрес на этом Mac."
                return
            }
            let account = url.absoluteString + "|" + email.lowercased()
            if !remember { SessionKeychain.store(nil, for: account) }
            let client = GardenAPI(server: url, onRefreshToken: { token in
                if remember { SessionKeychain.store(token, for: account) }
            })
            serverAccountKey = account
            if resume {
                guard let token = SessionKeychain.read(account) else { return }
                do { try await client.restore(refreshToken: token) }
                catch let error as APIError where error.status == 401 {
                    SessionKeychain.store(nil, for: account)
                    throw error
                }
            } else {
                try await client.login(email: email, password: password, register: register)
            }
            let workspaces = try await client.workspaces()
            self.workspaces = workspaces
            workspaceID = workspaces.first?.id
            await client.selectWorkspace(workspaceID)
            async let list = client.workflows()
            async let definitions = client.catalog()
            async let available = client.projects()
            let (loaded, nodes, projects) = try await (list, definitions, available)
            self.projects = projects
            workflows = loaded
            catalog = nodes
            api = client
        }
    }

    func switchWorkspace(_ workspace: Workspace) async {
        await perform {
            guard let api, !watching else { return }
            let previous = workspaceID
            await api.selectWorkspace(workspace.id)
            do {
                async let workflows = api.workflows()
                async let projects = api.projects()
                let (nextWorkflows, nextProjects) = try await (workflows, projects)
                self.workflows = nextWorkflows
                self.projects = nextProjects
                workspaceID = workspace.id
                credentials = []
                clipboardNodes = []
                clipboardEdges = []
                history = []
                newWorkflow()
            } catch {
                await api.selectWorkspace(previous)
                throw error
            }
        }
    }

    func adopt(_ workflow: Workflow) {
        self.workflow = workflow
        undoStack = []
        redoStack = []
        selectedNodes = []
        graph = workflow.graph ?? Graph()
        name = workflow.name
        projectID = workflow.projectID ?? ""
        mode = .editing
        run = nil
        events = []
        selected = nil
        if let index = workflows.firstIndex(where: { $0.id == workflow.id }) {
            workflows[index] = workflow
        } else { workflows.insert(workflow, at: 0) }
    }

    func logout() async {
        await perform {
            guard let api else { return }
            try await api.logout()
            self.api = nil
            newWorkflow()
            serverAccountKey = ""
            credentials = []
            clipboardNodes = []
            clipboardEdges = []
            workflows = []
            catalog = []
            history = []
            projects = []
            workspaces = []
            workspaceID = nil
        }
    }

    func updateProject(_ item: ScanProject) {
        if let index = projects.firstIndex(where: { $0.id == item.id }) {
            projects[index] = item
        } else {
            projects.insert(item, at: 0)
        }
    }

    func open(_ item: Workflow) async {
        await perform {
            guard let api else { return }
            let detail = try await api.workflow(item.id)
            try detail.graph?.validateImport()
            adopt(detail)
            restoreDraft()
        }
    }

    func newWorkflow() {
        workflow = nil
        undoStack = []
        redoStack = []
        selectedNodes = []
        projectID = ""
        graph = Graph()
        name = "Новый сценарий"
        selected = nil
        run = nil
        events = []
        mode = .editing
    }

    func add(_ node: NodeDefinition, at point: CGPoint? = nil, showInspector: Bool = true) {
        let count = graph.nodes.count
        let position = Graph.Node.Position(x: point.map { max(0, $0.x) } ?? Double(20 + count % 3 * 214),
                                           y: point.map { max(0, $0.y) } ?? Double(20 + count / 3 * 90))
        let defaults: [String: JSONValue]
        if case .object(let properties) = node.configSchema["properties"] {
            defaults = properties.compactMapValues {
                guard case .object(let property) = $0 else { return nil }
                return property["default"]
            }
        } else { defaults = [:] }
        let new = Graph.Node(type: node.type, label: node.title["ru"] ?? node.type, position: position, config: defaults)
        editGraph { $0.nodes.append(new) }
        if showInspector { selected = new.id }
    }

    func save() async {
        await perform {
            guard let api else { return }
            let key = draftKey
            let saved = try await api.save(id: workflow?.id, name: name, graph: graph)
            workflow = saved
            graph = saved.graph ?? graph
            name = saved.name
            if let index = workflows.firstIndex(where: { $0.id == saved.id }) {
                workflows[index] = saved
            } else {
                workflows.insert(saved, at: 0)
            }
            if let key { GraphDraftStore.remove(key: key) }
            message = "Сценарий сохранён."
        }
    }

    func validate() async {
        await perform {
            guard let api, let workspace = workflow?.workspaceID ?? workspaceID else { return }
            let issues = try await api.validate(graph, workspaceID: workspace)
            validationNodes = Set(issues.compactMap { $0.objectValue?["node_id"]?.string })
            validationEdges = Set(issues.compactMap { $0.objectValue?["edge_id"]?.string })
            message = issues.isEmpty ? "Граф валиден." : issues.map { issue in
                if case .object(let fields) = issue { return fields["message"]?.string ?? formatted(issue) }
                return formatted(issue)
            }.joined(separator: "\n")
        }
    }

    func reloadHistory() async {
        await perform {
            guard let api else { return }
            history = try await api.runs()
        }
    }

    func start() async {
        await perform {
            guard let api, let workflow, !unsaved else { return }
            run = try await api.start(workflow.id, projectID: projectID.isEmpty ? nil : projectID)
            events = []
        }
    }

    func selectRun(_ item: GardenCore.Run) {
        run = item
        events = []
        selected = nil
        mode = .execution
    }

    func watch(runID: String) async {
        guard let api else { return }
        watching = true
        defer { if run?.id == runID { watching = false } }
        var lastID: Int?
        let terminal = ["success", "failed", "cancelled"]
        do {
            for attempt in 0..<4 {
                try Task.checkCancellation()
                let latest = try await api.run(runID)
                guard run?.id == runID else { return }
                run = latest
                do {
                    try await api.events(runID: runID, after: lastID) { [weak self] event in
                        await self?.append(event, runID: runID)
                    }
                    try Task.checkCancellation()
                    guard run?.id == runID else { return }
                    let finished = try await api.run(runID)
                    guard run?.id == runID else { return }
                    run = finished
                    if terminal.contains(finished.status) { return }
                } catch {
                    if Task.isCancelled { return }
                    if attempt == 3 { throw error }
                }
                lastID = events.last?.id
                try await Task.sleep(for: .seconds(attempt + 1))
            }
            if run?.id == runID { message = "Связь с потоком событий прервалась. Выберите запуск в истории повторно." }
        } catch {
            if !Task.isCancelled && run?.id == runID { message = error.localizedDescription }
        }
    }

    private func append(_ event: RunEvent, runID: String) {
        guard run?.id == runID, event.id > (events.last?.id ?? 0) else { return }
        events.append(event)
    }

    func cancel() async {
        await perform {
            guard let api, let run else { return }
            _ = try await api.cancel(run.id)
            message = "Запрошена отмена запуска."
        }
    }

    func status(for node: Graph.Node) -> String? {
        events.last { $0.nodeID == node.id && $0.type == "node.status" }?.data["status"]?.string
            ?? run?.nodes?.first { $0.nodeID == node.id }?.status
    }
}

func formatted<T: Encodable>(_ value: T) -> String {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    return (try? encoder.encode(value)).map { String(decoding: $0, as: UTF8.self) } ?? ""
}

struct GardenView: View {
    @State private var model = GardenModel()
    @AppStorage("serverAddress") private var server = "http://localhost:8080"
    @AppStorage("accountEmail") private var email = ""
    @AppStorage("rememberSession") private var remember = false
    @State private var triedRestore = false
    @State private var password = ""
    @State private var isNew = false
    @State private var watchID: String?
    @State private var dashboardOpen = false
    @State private var projectsOpen = false
    @State private var register = false
    @State private var resultRun: GardenCore.Run?
    @State private var platformPage: PlatformPage?
    @State private var zoom = 1.0
    @State private var gridSnap = true
    @State private var showMiniMap = true
    @State private var exportingGraph = false
    @State private var importingGraph = false
    @State private var graphFile = LocalExport()
    @State private var paletteOpen = false
    @State private var historyOpen = false
    @State private var workflowDelete = false
    @State private var canvasOnly = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if model.api == nil { login }
            else if canvasOnly { editor }
            else {
                HStack {
                    Text("Garden Security").font(.title2.bold())
                    Spacer()
                    Button("Дашборд", systemImage: "chart.bar.xaxis") { dashboardOpen = true }
                    Menu("Рабочая область", systemImage: "ellipsis.circle") {
                        Button("Проекты") { projectsOpen = true }
                        ForEach([PlatformPage.spaces, .templates, .assistant, .schedule, .tools, .settings]) { page in
                            Button(LocalizedStringKey(page.rawValue)) { platformPage = page }.disabled(model.watching || model.busy)
                        }
                        Button("Выйти") {
                            Task { await model.logout(); isNew = false }
                        }.disabled(model.busy || model.watching)
                    }.labelStyle(.iconOnly)
                    if model.busy { ProgressView().controlSize(.small) }
                }
                controls
                editor
            }
            if !model.message.isEmpty {
                ScrollView { Text(model.message).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled) }
                    .frame(maxHeight: 82)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding()
        .tint(.green)
        .task {
            guard !triedRestore else { return }
            triedRestore = true
            if remember && !email.isEmpty {
                await model.connect(server: server, email: email, password: "", register: false, remember: true, resume: true)
            }
        }
        .task(id: watchID) {
            if let watchID { await model.watch(runID: watchID) }
        }
        .onChange(of: model.graph) { _, _ in model.persistDraft() }
        .onChange(of: model.name) { _, _ in model.persistDraft() }
        .fileExporter(isPresented: $exportingGraph, document: graphFile, contentType: .json,
                      defaultFilename: "workflow.json") { result in
            if case .failure(let error) = result { model.message = error.localizedDescription }
        }
        .fileImporter(isPresented: $importingGraph, allowedContentTypes: [.json]) { result in
            do {
                let url = try result.get()
                let scoped = url.startAccessingSecurityScopedResource()
                defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                let file = try FileHandle(forReadingFrom: url)
                defer { try? file.close() }
                let data = try file.read(upToCount: 8 * 1024 * 1024 + 1) ?? Data()
                guard data.count <= 8 * 1024 * 1024 else { throw GraphImportError.tooManyEntries }
                let imported = try JSONDecoder().decode(Graph.self, from: data)
                try imported.validateImport()
                if model.workflow == nil && !isNew { model.newWorkflow(); isNew = true }
                model.editGraph { $0 = imported }
            } catch { model.message = error.localizedDescription }
        }
        .sheet(isPresented: $paletteOpen) { paletteSheet }
        .sheet(isPresented: $historyOpen) {
            if let api = model.api {
                RunHistoryView(api: api, workflows: model.workflows) { item in
                    model.selectRun(item)
                    watchID = item.id
                }
            }
        }
        .confirmationDialog("Удалить сохранённый сценарий?", isPresented: $workflowDelete, titleVisibility: .visible) {
            Button("Удалить сценарий", role: .destructive) {
                Task {
                    await model.perform {
                        guard let api = model.api, let workflow = model.workflow else { return }
                        try await api.deleteWorkflow(id: workflow.id)
                        if let key = model.draftKey { GraphDraftStore.remove(key: key) }
                        model.workflows.removeAll { $0.id == workflow.id }
                        model.newWorkflow()
                        isNew = false
                    }
                }
            }
        }
        .onChange(of: model.run?.id) { _, value in watchID = value }
        .sheet(isPresented: $dashboardOpen) {
            if let api = model.api { DashboardView(api: api) }
        }
        .sheet(item: $platformPage) { page in
            if let api = model.api {
                PlatformView(page: page, api: api, model: model) {
                    model.adopt($0)
                    isNew = false
                } onDraft: { graph in
                    model.newWorkflow()
                    model.graph = graph
                    isNew = true
                }
            }
        }
        .sheet(isPresented: $projectsOpen) {
            if let api = model.api { ProjectsView(api: api, model: model) }
        }
        .sheet(item: $resultRun) { run in
            if let api = model.api { RunResultsView(api: api, run: run, history: model.history) }
        }
    }

    private var login: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(register ? "Регистрация в Garden Security" : "Вход в Garden Security").font(.title.bold())
            TextField("Адрес сервера", text: $server)
            TextField("Электронная почта", text: $email)
            SecureField("Пароль", text: $password)
            Toggle("Запомнить сеанс", isOn: $remember)
            Button(register ? "Создать аккаунт" : "Войти") {
                Task {
                    await model.connect(server: server, email: email, password: password, register: register, remember: remember)
                    if model.api != nil { password = "" }
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(model.busy || email.isEmpty || password.count < (register ? 10 : 1))
            Button(register ? "Уже есть аккаунт" : "Создать аккаунт") { register.toggle() }
                .disabled(model.busy)
        }
        .textFieldStyle(.roundedBorder)
        .frame(maxWidth: 440)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 8) {
            ScrollView(.horizontal) {
                HStack {
                    Menu("Сценарии") {
                        ForEach(model.workflows) { item in
                            Button(item.name) { Task { await model.open(item); isNew = false } }
                        }
                    }
                    Button("Новый сценарий") { model.newWorkflow(); model.restoreDraft(); isNew = true }
                    if model.workflow != nil || isNew {
                        TextField("Название", text: $model.name).frame(width: 185)
                            .disabled(model.mode == .execution)
                    }
                }.disabled(model.watching || model.busy)
            }
            Picker("Режим", selection: $model.mode) {
                ForEach(EditorMode.allCases) { Text(LocalizedStringKey($0.rawValue)).tag($0) }
            }.pickerStyle(.segmented)
            ScrollView(.horizontal) {
                HStack {
                    if model.mode == .editing {
                        Button("Палитра нод", systemImage: "square.grid.2x2") { paletteOpen = true }
                            .disabled(model.workflow == nil && !isNew)
                        Button("Отменить правку", systemImage: "arrow.uturn.backward") { model.undo() }
                            .labelStyle(.iconOnly).keyboardShortcut("z", modifiers: .command).disabled(model.undoStack.isEmpty)
                        Button("Вернуть правку", systemImage: "arrow.uturn.forward") { model.redo() }
                            .labelStyle(.iconOnly).keyboardShortcut("z", modifiers: [.command, .shift]).disabled(model.redoStack.isEmpty)
                        graphMenu
                        Button("Сохранить") { Task { await model.save(); isNew = model.workflow == nil } }
                            .disabled(!model.unsaved || model.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        Button("Проверить граф") { Task { await model.validate() } }
                            .disabled(model.workflow == nil && !isNew)
                    } else {
                        Picker("Проект", selection: $model.projectID) {
                            Text("По сценарию").tag("")
                            ForEach(model.projects) { item in Text(item.name).tag(item.id) }
                        }.frame(minWidth: 150)
                        .disabled(model.watching)
                        Button("Запустить") { Task { await model.start() } }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.workflow == nil || model.unsaved || model.watching)
                        Button("Отменить") { Task { await model.cancel() } }.disabled(!model.watching)
                        Button("История запусков") { historyOpen = true }
                        if let run = model.run {
                            Text(run.verdict ?? run.status).font(.headline)
                            Button("Результаты") {
                                Task {
                                    await model.reloadHistory()
                                    resultRun = run
                                }
                            }.disabled(!["success", "failed", "cancelled"].contains(run.status))
                        }
                    }
                }.disabled(model.busy)
            }
        }
    }

    private var graphMenu: some View {
        Menu("Граф") {
            Toggle("Привязка к сетке", isOn: $gridSnap)
            Toggle("Миникарта", isOn: $showMiniMap)
            Toggle("Выбрать несколько нод", isOn: $model.multiSelect)
            Button("Копировать выбранные") { model.copyNodes(model.selectedNodes) }
                .disabled(model.selectedNodes.isEmpty)
            Button("Вставить скопированные") { model.pasteNodes() }.disabled(model.clipboardNodes.isEmpty)
            Button("Удалить выбранные", role: .destructive) { model.removeNodes(model.selectedNodes) }
                .disabled(model.selectedNodes.isEmpty)
            Button("Авто-раскладка") {
                model.editGraph { graph in
                    var level: [String: Int] = [:]
                    for _ in 0..<graph.nodes.count {
                        for edge in graph.edges {
                            level[edge.target] = min(graph.nodes.count, max(level[edge.target, default: 0], level[edge.source, default: 0] + 1))
                        }
                    }
                    var columns: [Int: Int] = [:]
                    for index in graph.nodes.indices {
                        let row = level[graph.nodes[index].id, default: 0]
                        let column = columns[row, default: 0]
                        graph.nodes[index].position = .init(x: Double(20 + column * 235), y: Double(20 + row * 110))
                        columns[row] = column + 1
                    }
                }
            }
            Button("Удалить сохранённый сценарий", role: .destructive) { workflowDelete = true }
                .disabled(model.workflow == nil || model.watching)
            Button("Импорт JSON…") { importingGraph = true }
            Button("Экспорт JSON…") {
                graphFile = LocalExport(data: Data(formatted(model.graph).utf8))
                exportingGraph = true
            }
        }
    }

    private var paletteSheet: some View {
        NavigationStack {
            List {
                let entries = model.catalog.filter {
                    model.paletteSearch.isEmpty || ($0.title["ru"] ?? $0.type).localizedCaseInsensitiveContains(model.paletteSearch) ||
                    $0.type.localizedCaseInsensitiveContains(model.paletteSearch)
                }
                let groups = Dictionary(grouping: entries, by: \.category)
                ForEach(groups.keys.sorted(), id: \.self) { category in
                    Section(category) {
                        ForEach(groups[category] ?? []) { item in
                            Button(item.title["ru"] ?? item.type) {
                                model.add(item, showInspector: false)
                                paletteOpen = false
                            }
                        }
                    }
                }
            }
            .searchable(text: $model.paletteSearch, prompt: "Найти ноду")
            .navigationTitle("Палитра нод")
            .toolbar { Button("Закрыть") { paletteOpen = false } }
        }.frame(idealWidth: 480, idealHeight: 580)
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Button("Уменьшить", systemImage: "minus.magnifyingglass") { zoom = max(0.45, zoom - 0.15) }.labelStyle(.iconOnly)
                Button("\(Int(zoom * 100))%") { zoom = 1 }
                Button("Увеличить", systemImage: "plus.magnifyingglass") { zoom = min(2, zoom + 0.15) }.labelStyle(.iconOnly)
                if model.unsaved && (!model.name.isEmpty || !model.graph.nodes.isEmpty) {
                    Text("Черновик").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button(canvasOnly ? "Выйти из полноэкранного режима" : "Во весь экран",
                       systemImage: canvasOnly ? "arrow.down.right.and.arrow.up.left" : "arrow.up.left.and.arrow.down.right") {
                    canvasOnly.toggle()
                }
                .labelStyle(.iconOnly)
                .keyboardShortcut(.escape, modifiers: [])
            }
            if !canvasOnly && model.mode == .editing && (!model.name.isEmpty || model.workflow != nil) {
                ScrollView(.horizontal) {
                    HStack {
                        ForEach(model.catalog.filter { item in
                            model.paletteSearch.isEmpty || (item.title["ru"] ?? item.type).localizedCaseInsensitiveContains(model.paletteSearch)
                        }) { item in
                            Text(item.title["ru"] ?? item.type)
                                .font(.caption)
                                .padding(.horizontal, 8).padding(.vertical, 5)
                                .background(.green.opacity(0.13), in: Capsule())
                                .draggable(EditorDrag(kind: "node", node: item.type, port: nil).text)
                                .accessibilityHint("Перетащите на полотно")
                        }
                    }
                }
            }
            ScrollView([.horizontal, .vertical]) {
                let graph = model.visibleGraph
                let width = max(620, (graph.nodes.map(\.position.x).max() ?? 0) + 210)
                let height = max(430, (graph.nodes.map(\.position.y).max() ?? 0) + 100)
                GraphCanvas(graph: graph, selection: model.selected, selectedNodes: model.selectedNodes,
                            editing: model.mode == .editing, catalog: model.catalog, status: model.status,
                            invalidNodes: model.mode == .editing ? model.validationNodes : [],
                            invalidEdges: model.mode == .editing ? model.validationEdges : [],
                            flashingEdges: Set(model.events.suffix(12).compactMap { $0.type == "edge.data" ? $0.data["edge_id"]?.string : nil }),
                            select: { id in
                    if model.multiSelect && model.mode == .editing {
                        if model.selectedNodes.contains(id) { model.selectedNodes.remove(id) }
                        else { model.selectedNodes.insert(id) }
                    } else { model.selected = id }
                }, move: { id, offset in
                    guard let index = model.graph.nodes.firstIndex(where: { $0.id == id }) else { return }
                    model.editGraph { graph in
                        let x = max(0, graph.nodes[index].position.x + offset.width)
                        let y = max(0, graph.nodes[index].position.y + offset.height)
                        graph.nodes[index].position.x = gridSnap ? (x / 16).rounded() * 16 : x
                        graph.nodes[index].position.y = gridSnap ? (y / 16).rounded() * 16 : y
                    }
                }, onPort: { source, output, target, input in
                    if let error = model.connectPorts(from: source, output: output, to: target, input: input) {
                        model.message = error
                        return false
                    }
                    return true
                }, addNode: { type, location in
                    guard let definition = model.catalog.first(where: { $0.type == type }) else { return false }
                    model.add(definition, at: location, showInspector: false)
                    return true
                }, onCopy: { model.copyNodes([$0]) }, onDuplicate: { id in
                    model.copyNodes([id]); model.pasteNodes()
                }, onToggle: { id in
                    if let index = model.graph.nodes.firstIndex(where: { $0.id == id }) {
                        model.editGraph { $0.nodes[index].disabled = $0.nodes[index].disabled != true }
                    }
                }, onRemove: { model.removeNodes([$0]) })
                .frame(width: width, height: height)
                .scaleEffect(zoom, anchor: .topLeading)
                .frame(width: width * zoom, height: height * zoom, alignment: .topLeading)
            }
            .background(.green.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
            .scrollIndicators(.visible)
            .overlay(alignment: .bottomTrailing) {
                if showMiniMap && !model.visibleGraph.nodes.isEmpty {
                    GraphMiniMap(graph: model.visibleGraph).padding(8).allowsHitTesting(false)
                }
            }
        }
        .sheet(item: Binding(get: { model.selectedNode }, set: { if $0 == nil { model.selected = nil } })) { node in
            NodeInspector(model: model, node: node)
        }
    }
}

private struct GraphCanvas: View {
    let graph: Graph
    let selection: String?
    let selectedNodes: Set<String>
    let editing: Bool
    let catalog: [NodeDefinition]
    let status: (Graph.Node) -> String?
    let invalidNodes: Set<String>
    let invalidEdges: Set<String>
    let flashingEdges: Set<String>
    let select: (String) -> Void
    let move: (String, CGSize) -> Void
    let onPort: (String, String, String, String) -> Bool
    let addNode: (String, CGPoint) -> Bool
    let onCopy: (String) -> Void
    let onDuplicate: (String) -> Void
    let onToggle: (String) -> Void
    let onRemove: (String) -> Void

    var body: some View {
        ZStack(alignment: .topLeading) {
            Canvas { context, size in
                for x in stride(from: 8.0, to: min(Double(size.width), 2048), by: 16) {
                    for y in stride(from: 8.0, to: min(Double(size.height), 1536), by: 16) {
                        context.fill(Path(ellipseIn: CGRect(x: x, y: y, width: 1, height: 1)), with: .color(.green.opacity(0.35)))
                    }
                }
                let nodes = Dictionary(graph.nodes.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
                for edge in graph.edges {
                    guard let from = nodes[edge.source], let to = nodes[edge.target] else { continue }
                    let start = CGPoint(x: from.position.x + 90, y: from.position.y + 61)
                    let end = CGPoint(x: to.position.x + 90, y: to.position.y)
                    var path = Path()
                    path.move(to: start)
                    path.addLine(to: CGPoint(x: start.x, y: (start.y + end.y) / 2))
                    path.addLine(to: CGPoint(x: end.x, y: (start.y + end.y) / 2))
                    path.addLine(to: end)
                    context.stroke(path, with: .color(invalidEdges.contains(edge.id) ? .red : flashingEdges.contains(edge.id) ? .orange : .green),
                                   lineWidth: flashingEdges.contains(edge.id) ? 4 : 2)
                }
            }
            ForEach(graph.nodes) { node in
                let definition = catalog.first { $0.type == node.type }
                NodeCard(node: node, status: invalidNodes.contains(node.id) ? "Ошибка графа" : status(node), selected: selection == node.id || selectedNodes.contains(node.id),
                         editing: editing, onSelect: { select(node.id) }, onMove: { move(node.id, $0) },
                         definition: definition, onPort: onPort)
                    .contextMenu {
                        if editing {
                            Button("Копировать") { onCopy(node.id) }
                            Button("Дублировать") { onDuplicate(node.id) }
                            Button(node.disabled == true ? "Включить" : "Отключить") { onToggle(node.id) }
                            Button("Удалить", role: .destructive) { onRemove(node.id) }
                        }
                    }
            }
            if graph.nodes.isEmpty {
                Text("Откройте сценарий или добавьте ноду на полотно.")
                    .foregroundStyle(.secondary).padding()
            }
        }
        .dropDestination(for: String.self) { values, location in
            guard editing, let payload = EditorDrag.decode(values.first), payload.kind == "node" else { return false }
            return addNode(payload.node, location)
        }
    }
}

private struct NodeCard: View {
    let node: Graph.Node
    let status: String?
    let selected: Bool
    let editing: Bool
    let onSelect: () -> Void
    let onMove: (CGSize) -> Void
    let definition: NodeDefinition?
    let onPort: (String, String, String, String) -> Bool
    @State private var focusedPort: String?
    @GestureState private var offset = CGSize.zero

    var body: some View {
        Button(action: onSelect) {
            VStack(alignment: .leading) {
                Text(node.label.isEmpty ? node.type : node.label).bold().lineLimit(1)
                Text(status ?? node.type).font(.caption).lineLimit(1).foregroundStyle(.secondary)
            }
            .frame(width: 156, height: 49, alignment: .leading)
            .padding(.horizontal, 12).padding(.vertical, 6)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
            .overlay {
                RoundedRectangle(cornerRadius: 10).strokeBorder(
                    (status == "failed" || status == "Ошибка графа") ? Color.red : selected ? Color.green : Color.secondary.opacity(0.3),
                    lineWidth: selected ? 2 : 1
                )
            }
        }
        .buttonStyle(.plain)
        .simultaneousGesture(DragGesture(minimumDistance: 8)
            .updating($offset) { event, state, _ in if editing { state = event.translation } }
            .onEnded { if editing { onMove($0.translation) } })
        .opacity(node.disabled == true ? 0.55 : 1)
        .overlay(alignment: .top) {
            if editing, let definition {
                HStack(spacing: 9) {
                    ForEach(definition.inputs, id: \.name) { port in
                        Circle().fill(focusedPort == port.name ? .orange : .green.opacity(0.8))
                            .frame(width: 14, height: 14)
                            .accessibilityLabel("Вход " + port.name)
                            .help("Вход " + port.name)
                            .dropDestination(for: String.self) { values, _ in
                                guard let src = EditorDrag.decode(values.first), src.kind == "port", let output = src.port else { return false }
                                return onPort(src.node, output, node.id, port.name)
                            } isTargeted: { active in focusedPort = active ? port.name : nil }
                    }
                }.offset(y: -7)
            }
        }
        .overlay(alignment: .bottom) {
            if editing, let definition {
                HStack(spacing: 9) {
                    ForEach(definition.outputs, id: \.name) { port in
                        Circle().fill(.green).frame(width: 14, height: 14)
                            .accessibilityLabel("Выход " + port.name)
                            .help("Выход " + port.name)
                            .draggable(EditorDrag(kind: "port", node: node.id, port: port.name).text)
                    }
                }.offset(y: 7)
            }
        }
        .offset(x: node.position.x + offset.width, y: node.position.y + offset.height)
    }
}

private struct NodeInspector: View {
    @Environment(\.dismiss) private var dismiss
    let model: GardenModel
    let node: Graph.Node
    @State private var draft = ""
    @State private var formValues: [String: JSONValue] = [:]
    @State private var rawJSON = false
    @State private var target = ""
    @State private var sourcePort = ""
    @State private var targetPort = ""
    @State private var error = ""

    private var sources: [NodeDefinition.Port] {
        model.catalog.first { $0.type == node.type }?.outputs ?? []
    }
    private var targets: [NodeDefinition.Port] {
        guard let type = model.graph.nodes.first(where: { $0.id == target })?.type else { return [] }
        return model.catalog.first { $0.type == type }?.inputs ?? []
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(node.label.isEmpty ? node.type : node.label).font(.title2.bold())
                Spacer()
                Button("Готово") { dismiss() }
            }
            if model.mode == .execution {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(model.status(for: node) ?? "Статус ожидается").font(.headline)
                        if let saved = model.run?.nodes?.first(where: { $0.nodeID == node.id }) {
                            if let error = saved.error { Text(error).foregroundStyle(.red) }
                            if let summary = saved.outputSummary {
                                DisclosureGroup("Выход ноды") { Text(formatted(summary)).textSelection(.enabled) }
                            }
                        }
                        ForEach(model.events.filter { event in
                            event.nodeID == node.id || (event.type == "edge.data" &&
                                model.visibleGraph.edges.contains { edge in
                                    event.data["edge_id"]?.string == edge.id && (edge.source == node.id || edge.target == node.id)
                                })
                        }) { event in
                            Text(event.type).font(.headline)
                            Text(formatted(event.data)).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                Toggle("Редактировать JSON", isOn: $rawJSON)
                    .onChange(of: rawJSON) { _, enabled in
                        if enabled { draft = formatted(formValues) }
                        else if let decoded = try? JSONDecoder().decode([String: JSONValue].self, from: Data(draft.utf8)) {
                            formValues = decoded
                        }
                    }
                if rawJSON {
                    TextEditor(text: $draft).font(.system(.body, design: .monospaced)).frame(minHeight: 120)
                } else if let schema = model.catalog.first(where: { $0.type == node.type })?.configSchema {
                    ScrollView {
                        NodeParameterForm(schema: schema, credentials: model.credentials, api: model.api, values: $formValues)
                    }.frame(minHeight: 95, maxHeight: 270)
                }
                Button("Сохранить параметры") {
                    do {
                        let config = rawJSON ? try JSONDecoder().decode([String: JSONValue].self, from: Data(draft.utf8)) : formValues
                        if let index = model.graph.nodes.firstIndex(where: { $0.id == node.id }) {
                            model.editGraph { $0.nodes[index].config = config }
                            error = ""
                        }
                    } catch { self.error = error.localizedDescription }
                }
                Picker("Выход", selection: $sourcePort) {
                    Text("Выберите порт").tag("")
                    ForEach(sources, id: \.name) { Text($0.name).tag($0.name) }
                }
                Picker("Нода назначения", selection: $target) {
                    Text("Выберите ноду").tag("")
                    ForEach(model.graph.nodes.filter { $0.id != node.id }) { Text($0.label).tag($0.id) }
                }.onChange(of: target) { _, _ in targetPort = "" }
                Picker("Вход", selection: $targetPort) {
                    Text("Выберите порт").tag("")
                    ForEach(targets, id: \.name) { Text($0.name).tag($0.name) }
                }
                Button("Соединить") { connectPorts() }
                    .disabled(sourcePort.isEmpty || target.isEmpty || targetPort.isEmpty)
                ForEach(model.graph.edges.filter { $0.source == node.id }) { edge in
                    HStack {
                        Text("\(edge.sourcePort) → \(model.graph.nodes.first { $0.id == edge.target }?.label ?? edge.target) / \(edge.targetPort)")
                        Spacer()
                        Button("Удалить связь", role: .destructive) { model.editGraph { $0.edges.removeAll { $0.id == edge.id } } }
                    }
                }
                Button("Удалить ноду", role: .destructive) {
                    model.removeNodes([node.id])
                    dismiss()
                }
                if !error.isEmpty { Text(error).foregroundStyle(.red) }
            }
        }
        .padding()
        .frame(idealWidth: 510, minHeight: 420)
        .onAppear { draft = formatted(node.config); formValues = node.config }
        .task {
            if model.mode == .editing, let api = model.api {
                if let rows = try? await api.credentials() { model.credentials = rows }
            }
        }
    }

    private func connectPorts() {
        error = model.connectPorts(from: node.id, output: sourcePort, to: target, input: targetPort) ?? ""
    }
}
