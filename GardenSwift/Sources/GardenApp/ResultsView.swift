import Charts
import Foundation
import GardenCore
import SwiftUI
import UniformTypeIdentifiers

struct DashboardView: View {
    let api: GardenAPI
    @State private var dashboard: Dashboard?
    @State private var error: String?
    @State private var revision = 0
    @State private var period = "30d"
    @State private var customHistory: ScoreHistory?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if let dashboard {
                    Section("Рабочее пространство") {
                        LabeledContent("Проекты", value: "\(dashboard.projects)")
                        LabeledContent("Сценарии", value: "\(dashboard.workflows)")
                        LabeledContent("Запуски", value: "\(dashboard.runs)")
                    }
                    Section("Находки по критичности") {
                        ForEach(["CRITICAL", "HIGH", "MEDIUM", "LOW"], id: \.self) { severity in
                            LabeledContent(severity, value: "\(dashboard.severityCounts[severity, default: 0])")
                        }
                    }
                    Section("Security Score") {
                        if let score = dashboard.score {
                            Text("\(score.value) / 100").font(.largeTitle.bold()).foregroundStyle(.green)
                            if let delta = score.delta { Text("Изменение · \(delta.formatted(.number.sign(strategy: .always())))").foregroundStyle(.secondary) }
                            if score.projectID != nil {
                                Picker("Период", selection: $period) {
                                    Text("7 дней").tag("7d")
                                    Text("30 дней").tag("30d")
                                    Text("90 дней").tag("90d")
                                }.pickerStyle(.segmented)
                            }
                            let points = customHistory?.points ?? score.history
                            if !points.isEmpty {
                                Chart {
                                    ForEach(Array(points.enumerated()), id: \.element.id) { index, point in
                                        LineMark(x: .value("Запуск", index + 1), y: .value("Балл", point.score))
                                        PointMark(x: .value("Запуск", index + 1), y: .value("Балл", point.score))
                                    }
                                }.chartYScale(domain: 0...100).frame(height: 210)
                            }
                            if let note = score.note { Text(note).foregroundStyle(.secondary) }
                            ForEach(score.top3) { item in
                                LabeledContent(item.title, value: "+\(item.expectedGain)")
                            }
                            if case .object(let plan) = score.sprintPlan,
                               case .object(let report) = plan["plan"],
                               let summary = report["summary"]?.string {
                                Text(summary)
                            }
                        } else {
                            Text("Security Score появится после завершённой проверки с оценкой.")
                                .foregroundStyle(.secondary)
                        }
                    }
                } else if error == nil {
                    ProgressView()
                }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("Дашборд")
            .toolbar {
                Button("Обновить", systemImage: "arrow.clockwise") { revision += 1 }
                Button("Закрыть") { dismiss() }
            }
            .task(id: period) {
                guard let projectID = dashboard?.score?.projectID else { return }
                do { customHistory = try await api.scoreHistory(projectID: projectID, period: period) }
                catch is CancellationError { }
                catch { if !Task.isCancelled { self.error = error.localizedDescription } }
            }
            .task(id: revision) {
                error = nil
                do { dashboard = try await api.dashboard(); customHistory = nil; period = "30d" }
                catch is CancellationError { }
                catch { if !Task.isCancelled { self.error = error.localizedDescription } }
            }
        }
        .frame(idealWidth: 650, idealHeight: 650)
    }
}

struct RunResultsView: View {
    let api: GardenAPI
    let run: GardenCore.Run
    let history: [GardenCore.Run]
    @Environment(\.dismiss) private var dismiss
    @State private var findings: [Finding] = []
    @State private var report: AIReport?
    @State private var reportError: String?
    @State private var fixes: [String: Autofix] = [:]
    @State private var filter = FindingFilter.all
    @State private var baseID = ""
    @State private var comparison: RunComparison?
    @State private var error: String?
    @State private var loading = true
    @State private var action = false
    @State private var document = ExportDocument()
    @State private var exportName = "report.md"
    @State private var exporting = false
    @State private var scoreDetails: JSONValue?
    @State private var sprintPlan: JSONValue?
    @State private var prCandidate: Autofix?
    @State private var createdPRs: [String: URL] = [:]
    @State private var severity = "Все"
    @State private var sortByFile = false

    private enum FindingFilter: String, CaseIterable, Identifiable {
        case all = "Все", new = "Новые", existing = "Существующие"
        var id: Self { self }

        func matches(_ finding: Finding) -> Bool {
            switch self {
            case .all: true
            case .new: finding.diffStatus == "new"
            case .existing: finding.diffStatus == "existing"
            }
        }
    }

    var body: some View {
        NavigationStack {
            List {
                Section("Запуск") {
                    LabeledContent("Статус", value: run.status)
                    if let verdict = run.verdict { LabeledContent("Вердикт PR", value: verdict) }
                    if let score = run.score { LabeledContent("Security Score", value: "\(score) / 100") }
                    if let duration = run.duration {
                        LabeledContent("Продолжительность", value: (Double(duration) / 1000).formatted(.number.precision(.fractionLength(1))) + " с")
                    }
                    if let failure = run.error { Text(failure).foregroundStyle(.red) }
                    Menu("Экспорт отчёта") {
                        ForEach(ReportFormat.allCases) { format in
                            Button(format.rawValue) {
                                Task { await perform { try await export(format) } }
                            }
                        }
                    }
                    .disabled(action)
                }
                if let artifacts = run.artifacts, !artifacts.isEmpty {
                    Section("Артефакты") {
                        ForEach(artifacts) { item in
                            Button(item.name, systemImage: "arrow.down.document") {
                                Task { await perform {
                                    document = ExportDocument(data: try await api.artifact(runID: run.id, name: item.name))
                                    exportName = item.name
                                    exporting = true
                                } }
                            }.disabled(action)
                        }
                    }
                }
                if run.score != nil {
                    Section("Security Score") {
                        Button("Детали оценки") { Task { await perform { scoreDetails = try await api.runScore(id: run.id) } } }
                            .disabled(action)
                        if let scoreDetails { code(formatted(scoreDetails)) }
                        Button("Сформировать план на спринт") { Task { await perform {
                            sprintPlan = try await api.createSprintPlan(runID: run.id)
                        } } }.disabled(action)
                        if let sprintPlan, let plan = sprintPlan.objectValue?["plan"] {
                            if let summary = plan.objectValue?["summary"]?.string { Text(summary) }
                            DisclosureGroup("План и оценка результата") { code(formatted(plan)) }
                        }
                    }
                }
                Section("Находки") {
                    Picker("Изменения", selection: $filter) {
                        ForEach(FindingFilter.allCases) { Text(LocalizedStringKey($0.rawValue)).tag($0) }
                    }.pickerStyle(.segmented)
                    if loading { ProgressView() }
                    Picker("Критичность", selection: $severity) {
                        ForEach(["Все", "CRITICAL", "HIGH", "MEDIUM", "LOW"], id: \.self) { Text($0).tag($0) }
                    }
                    Toggle("По файлу и строке", isOn: $sortByFile)
                    let filtered = findings.filter { filter.matches($0) && (severity == "Все" || $0.severity == severity) }
                    let visible = sortByFile ? filtered.sorted { ($0.path, $0.line) < ($1.path, $1.line) } : filtered
                    if !loading && visible.isEmpty { Text("Нет находок для выбранного фильтра.").foregroundStyle(.secondary) }
                    ForEach(visible) { finding in
                        DisclosureGroup {
                            findingDetails(finding)
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(finding.title).font(.headline)
                                Text("\(finding.category) · \(finding.severity) · \(finding.path):\(finding.line)")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                Section("AI-отчёт") {
                    if let report {
                        Text(report.aiGenerated ? "Отчёт модели" : "Отчёт анализаторов")
                            .font(.caption).foregroundStyle(.secondary)
                        if let summary = report.report?.summary { Text(summary) }
                        ForEach(Array((report.report?.globalRecommendations ?? []).enumerated()), id: \.offset) { _, item in
                            Label(item, systemImage: "checkmark.circle")
                        }
                        if let validation = report.validation {
                            DisclosureGroup("Проверка достоверности") { code(formatted(validation)) }
                        }
                        if let error = report.error { Text(error).foregroundStyle(.secondary) }
                    } else if let reportError {
                        Text(reportError).foregroundStyle(.red)
                    } else if !loading {
                        Text("У этого запуска пока нет AI-отчёта.").foregroundStyle(.secondary)
                    }
                }
                if !history.filter({ $0.id != run.id }).isEmpty {
                    Section("Сравнение запусков") {
                        Picker("Базовый запуск", selection: $baseID) {
                            Text("Выберите запуск").tag("")
                            ForEach(history.filter { $0.id != run.id }) { item in
                                Text(item.createdAt ?? String(item.id.prefix(8))).tag(item.id)
                            }
                        }
                        .onChange(of: baseID) { _, _ in comparison = nil }
                        Button("Сравнить") {
                            let base = baseID
                            Task {
                                await perform {
                                    let result = try await api.compare(base: base, head: run.id)
                                    if baseID == base { comparison = result }
                                }
                            }
                        }.disabled(baseID.isEmpty || action)
                        if let comparison {
                            comparisonGroup("Новые", items: comparison.new)
                            comparisonGroup("Устранённые", items: comparison.fixed)
                            comparisonGroup("Без изменений", items: comparison.unchanged)
                        }
                    }
                }
                if action { ProgressView() }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("Результаты запуска")
            .toolbar { Button("Закрыть") { dismiss() } }
            .task { await load() }
            .confirmationDialog("Создать PR/MR с проверенным патчем?", isPresented: Binding(
                get: { prCandidate != nil }, set: { if !$0 { prCandidate = nil } }
            ), titleVisibility: .visible, presenting: prCandidate) { fix in
                Button("Создать PR/MR") {
                    prCandidate = nil
                    Task { await perform {
                        let result = try await api.createAutofixPullRequest(id: fix.id)
                        createdPRs[fix.id] = result.url
                    } }
                }
            } message: { _ in
                Text("Сервер создаст ветку и отправит исправление в разрешённый репозиторий.")
            }
            .fileExporter(isPresented: $exporting, document: document, contentType: .data,
                          defaultFilename: exportName) { result in
                if case .failure(let failure) = result { error = failure.localizedDescription }
            }
        }
        .frame(idealWidth: 780, idealHeight: 720)
    }

    private func code(_ text: String) -> some View {
        ScrollView(.horizontal) {
            Text(verbatim: text).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                .padding(8)
        }
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder
    private func findingDetails(_ finding: Finding) -> some View {
        if let description = finding.description, !description.isEmpty { Text(description) }
        if let remediation = finding.remediation, !remediation.isEmpty { Text(remediation).foregroundStyle(.secondary) }
        if let snippet = finding.snippet, !snippet.isEmpty { code(snippet) }
        if let hunk = finding.diffHunk, !hunk.isEmpty {
            DisclosureGroup("Изменённый участок") { code(hunk) }
        }
        if let detail = report?.report?.findings?.first(where: { $0.findingID == finding.id }) {
            DisclosureGroup("Пояснение AI") {
                Text(detail.explanation)
                Text(detail.impact).foregroundStyle(.secondary)
                ForEach(Array(detail.remediationSteps.enumerated()), id: \.offset) { _, step in Text(step) }
            }
        }
        if let fix = fixes[finding.id] {
            DisclosureGroup("AutoFix · \(fix.status)") {
                if let reason = fix.reason { Text(reason).foregroundStyle(.secondary) }
                ForEach(Array(fix.steps.enumerated()), id: \.offset) { _, step in
                    VStack(alignment: .leading) {
                        Label(step.name, systemImage: step.ok ? "checkmark.circle" : "xmark.circle")
                        Text(step.detail).font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let patch = fix.patch, !patch.isEmpty {
                    code(patch)
                    Button("Скачать .patch", systemImage: "arrow.down.document") {
                        Task {
                            await perform {
                                document = ExportDocument(data: try await api.patch(id: fix.id))
                                exportName = "autofix-\(fix.id.prefix(8)).patch"
                                exporting = true
                            }
                        }
                    }.disabled(action)
                }
                if let url = createdPRs[fix.id] ?? fix.prURL, ["https", "http"].contains(url.scheme ?? "") {
                    Link("Открыть PR/MR", destination: url)
                } else if fix.canCreatePR == true && fix.status == "validated" {
                    Button("Создать PR/MR") { prCandidate = fix }.disabled(action)
                }
                if let reason = fix.prUnavailableReason { Text(reason).foregroundStyle(.secondary) }
            }
        }
        if finding.supportsAutofix && run.status == "success" {
            Button(fixes[finding.id] == nil ? "Подготовить AutoFix" : "Повторить AutoFix", systemImage: "wrench") {
                Task {
                    await perform {
                        let fix = try await api.generateAutofix(runID: run.id, findingID: finding.id)
                        fixes[finding.id] = fix
                    }
                }
            }.disabled(action)
        }
    }

    private func comparisonGroup(_ title: String, items: [Finding]) -> some View {
        DisclosureGroup("\(title) · \(items.count)") {
            ForEach(items) { item in
                Text("\(item.severity) · \(item.title)")
            }
        }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        async let reportRequest: () = loadReport()
        do {
            findings = try await api.findings(runID: run.id)
            let rows = try await api.autofixes(runID: run.id)
            fixes = Dictionary(rows.map { ($0.findingID, $0) }, uniquingKeysWith: { first, _ in first })
            for (findingID, fix) in fixes where fix.status == "validated" {
                do { fixes[findingID] = try await api.autofix(id: fix.id) }
                catch { if Task.isCancelled { throw error } }
            }
        } catch is CancellationError { }
        catch { if !Task.isCancelled { self.error = error.localizedDescription } }
        await reportRequest
    }

    private func loadReport() async {
        do { report = try await api.report(runID: run.id) }
        catch is CancellationError { }
        catch { if !Task.isCancelled { reportError = error.localizedDescription } }
    }

    private func perform(_ operation: @MainActor () async throws -> Void) async {
        guard !action else { return }
        action = true
        error = nil
        defer { action = false }
        do { try await operation() }
        catch { self.error = error.localizedDescription }
    }

    private func export(_ format: ReportFormat) async throws {
        document = ExportDocument(data: try await api.export(runID: run.id, format: format))
        exportName = format.rawValue
        exporting = true
    }
}

private struct ExportDocument: FileDocument {
    static let readableContentTypes: [UTType] = [.data]
    var data = Data()

    init(data: Data = Data()) { self.data = data }
    init(configuration: ReadConfiguration) throws { data = configuration.file.regularFileContents ?? Data() }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper { FileWrapper(regularFileWithContents: data) }
}

struct ProjectsView: View {
    let api: GardenAPI
    let model: GardenModel
    @Environment(\.dismiss) private var dismiss
    @State private var draft: ProjectEditorState?
    @State private var deleteCandidate: ScanProject?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                if model.projects.isEmpty {
                    Text("Добавьте проект, чтобы выбрать его при запуске сценария.")
                        .foregroundStyle(.secondary)
                }
                ForEach(model.projects) { project in
                    Button {
                        draft = ProjectEditorState(project: project)
                    } label: {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(project.name).font(.headline)
                            Text(project.gitURL ?? project.path ?? "Архив").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .contextMenu {
                        Button("Удалить проект", role: .destructive) { deleteCandidate = project }
                    }
                }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .confirmationDialog("Удалить проект?", isPresented: Binding(
                get: { deleteCandidate != nil }, set: { if !$0 { deleteCandidate = nil } }
            ), titleVisibility: .visible, presenting: deleteCandidate) { project in
                Button("Удалить проект", role: .destructive) {
                    deleteCandidate = nil
                    Task {
                        do {
                            try await api.deleteProject(id: project.id)
                            model.projects.removeAll { $0.id == project.id }
                            if model.projectID == project.id { model.projectID = "" }
                        } catch { self.error = error.localizedDescription }
                    }
                }
            }
            .navigationTitle("Проекты")
            .toolbar {
                Button("Добавить проект", systemImage: "plus") { draft = ProjectEditorState() }
                Button("Закрыть") { dismiss() }
            }
            .sheet(item: $draft) { state in
                ProjectEditor(api: api, initial: state) { model.updateProject($0) }
            }
        }
        .frame(idealWidth: 620, idealHeight: 520)
    }
}

private enum ProjectSource: String, CaseIterable, Identifiable {
    case git = "git_url", archive = "upload", hostPath = "path"
    var id: Self { self }
    var title: String {
        switch self {
        case .git: "Git-репозиторий"
        case .archive: "Архив"
        case .hostPath: "Путь на сервере"
        }
    }
}

private struct ProjectEditorState: Identifiable {
    let id = UUID()
    let project: ScanProject?
    var name: String
    var description: String
    var source: ProjectSource
    var url: String
    var ref: String
    var path: String

    init(project: ScanProject? = nil) {
        self.project = project
        name = project?.name ?? ""
        description = project?.description ?? ""
        source = ProjectSource(rawValue: project?.sourceMode ?? "") ?? .git
        url = project?.gitURL ?? ""
        ref = project?.ref ?? ""
        path = project?.path ?? ""
    }
}

private struct ProjectEditor: View {
    let api: GardenAPI
    let onSave: (ScanProject) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var state: ProjectEditorState
    @State private var archiveURL: URL?
    @State private var uploadedID: String?
    @State private var choosing = false
    @State private var saving = false
    @State private var error: String?

    init(api: GardenAPI, initial: ProjectEditorState, onSave: @escaping (ScanProject) -> Void) {
        self.api = api
        self.onSave = onSave
        _state = State(initialValue: initial)
    }

    private var canSave: Bool {
        guard !state.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        switch state.source {
        case .git: return !state.url.isEmpty
        case .archive: return archiveURL != nil || state.project?.sourceMode == ProjectSource.archive.rawValue
        case .hostPath: return !state.path.isEmpty
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                TextField("Название", text: $state.name)
                TextField("Описание", text: $state.description)
                Picker("Источник", selection: $state.source) {
                    ForEach(ProjectSource.allCases) { item in Text(LocalizedStringKey(item.title)).tag(item) }
                }
                switch state.source {
                case .git:
                    TextField("URL Git-репозитория", text: $state.url)
                    TextField("Ветка или тег", text: $state.ref)
                case .archive:
                    Button(archiveURL?.lastPathComponent ?? "Выбрать архив…") { choosing = true }
                case .hostPath:
                    TextField("Путь в файловой системе сервера", text: $state.path)
                }
                if saving { ProgressView() }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .disabled(saving)
            .navigationTitle(state.project == nil ? "Новый проект" : "Настройки проекта")
            .toolbar {
                Button("Отмена") { dismiss() }.disabled(saving)
                Button("Сохранить") { Task { await save() } }.disabled(!canSave || saving)
            }
            .interactiveDismissDisabled(saving)
            .fileImporter(isPresented: $choosing, allowedContentTypes: [.archive, .zip, .data]) { result in
                do {
                    archiveURL = try result.get()
                    uploadedID = nil
                } catch { self.error = error.localizedDescription }
            }
        }
        .frame(idealWidth: 540, idealHeight: 390)
    }

    private func save() async {
        guard canSave && !saving else { return }
        saving = true
        error = nil
        defer { saving = false }
        do {
            if state.source == .archive, uploadedID == nil, let archiveURL {
                let data = try readArchive(archiveURL)
                uploadedID = try await api.uploadArchive(filename: archiveURL.lastPathComponent, data: data)
            }
            let draft = ProjectDraft(
                name: state.name.trimmingCharacters(in: .whitespacesAndNewlines),
                description: state.description,
                sourceMode: state.source.rawValue,
                gitURL: state.source == .git ? state.url : nil,
                ref: state.source == .git && !state.ref.isEmpty ? state.ref : nil,
                path: state.source == .hostPath ? state.path : nil,
                uploadID: state.source == .archive ? uploadedID : nil
            )
            let project = try await api.saveProject(id: state.project?.id, draft: draft)
            onSave(project)
            dismiss()
        } catch { self.error = error.localizedDescription }
    }
}

struct RunHistoryView: View {
    let api: GardenAPI
    let workflows: [Workflow]
    let onSelect: (GardenCore.Run) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var workflow = ""
    @State private var status = ""
    @State private var initiator = ""
    @State private var filterDates = false
    @State private var since = Calendar.current.date(byAdding: .day, value: -7, to: Date()) ?? Date()
    @State private var until = Date()
    @State private var runs: [GardenCore.Run] = []
    @State private var busy = false
    @State private var error: String?
    @State private var hasNext = false

    var body: some View {
        NavigationStack {
            List {
                Section("Фильтры") {
                    Picker("Сценарий", selection: $workflow) {
                        Text("Все сценарии").tag("")
                        ForEach(workflows) { Text($0.name).tag($0.id) }
                    }
                    Picker("Статус", selection: $status) {
                        Text("Все статусы").tag("")
                        ForEach(["queued", "running", "success", "failed", "cancelled"], id: \.self) { Text($0).tag($0) }
                    }
                    TextField("ID инициатора", text: $initiator)
                    Toggle("Ограничить периодом", isOn: $filterDates)
                    if filterDates {
                        DatePicker("С", selection: $since)
                        DatePicker("По", selection: $until)
                    }
                    Button("Применить фильтры") { Task { await load(append: false) } }
                        .disabled(busy || (filterDates && since > until))
                }
                Section("Запуски") {
                    ForEach(runs) { run in
                        Button {
                            onSelect(run)
                            dismiss()
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(run.workflowName ?? String(run.id.prefix(8))).font(.headline)
                                Text([run.createdAt, run.verdict ?? run.status].compactMap { $0 }.joined(separator: " · "))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                    if !busy && runs.isEmpty { Text("Запуски не найдены.").foregroundStyle(.secondary) }
                    if hasNext { Button("Загрузить ещё") { Task { await load(append: true) } }.disabled(busy) }
                }
                if busy { ProgressView() }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("История запусков")
            .toolbar { Button("Закрыть") { dismiss() } }
            .task { await load(append: false) }
        }.frame(idealWidth: 645, idealHeight: 660)
    }

    private func load(append: Bool) async {
        guard !busy else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            let dates = ISO8601DateFormatter()
            let rows = try await api.runs(workflowID: workflow.isEmpty ? nil : workflow,
                                          status: status.isEmpty ? nil : status,
                                          since: filterDates ? dates.string(from: since) : nil,
                                          until: filterDates ? dates.string(from: until) : nil,
                                          initiator: initiator.isEmpty ? nil : initiator,
                                          offset: append ? runs.count : 0)
            if append { runs += rows } else { runs = rows }
            hasNext = rows.count >= 50
        } catch is CancellationError { }
        catch { self.error = error.localizedDescription }
    }
}
