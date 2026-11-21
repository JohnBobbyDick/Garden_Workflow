import Foundation
import GardenCore
import SwiftUI
import UniformTypeIdentifiers

enum PlatformPage: String, Identifiable {
    case spaces = "Рабочие пространства", templates = "Шаблоны", tools = "CI/CD"
    case assistant = "AI-ассистент", settings = "Настройки", schedule = "Расписание"
    var id: Self { self }
}

struct PlatformView: View {
    let page: PlatformPage
    let api: GardenAPI
    let model: GardenModel
    let onOpen: (Workflow) -> Void
    let onDraft: (Graph) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var busy = false
    @State private var error: String?
    @State private var status: String?
    @State private var name = ""
    @State private var secondary = ""
    @State private var message = ""
    @State private var role = "developer"
    @State private var output: JSONValue?
    @State private var revealed: String?

    @State private var search = ""
    @State private var favorites = false
    @State private var templates: [WorkflowTemplate] = []
    @State private var template: WorkflowTemplate?
    @State private var parameters = "{}"
    @State private var rating = 5
    @State private var reviews: JSONValue?
    @State private var proposal: WorkflowProposal?
    @State private var patching = false

    @State private var credentialValue = ""
    @State private var credentialKind = "generic"
    @State private var credentials: [PlatformItem] = []
    @State private var settings: [String: JSONValue] = [:]
    @State private var settingsLoaded = false
    @State private var tokens: [PlatformItem] = []
    @State private var provider = "github"
    @State private var scope = ""
    @State private var branches = "main"
    @State private var export = LocalExport()
    @State private var exportName = "workflow.yml"
    @State private var exporting = false
    @State private var scheduleEnabled = false
    @State private var revokeCandidate: PlatformItem?
    @State private var credentialCandidate: PlatformItem?
    @State private var credentialEdit: String?
    @State private var removeUserID: String?
    @State private var templateVersion = "1.0.1"
    @State private var reviewID: String?
    @State private var deleteReviewID: String?
    @State private var authorFilter = ""
    @State private var categoryFilter = ""
    @State private var publishCategory = "Custom"
    @State private var publishName = ""
    @State private var tags = ""
    @State private var ownTemplates = false
    @State private var minimumRating = 0
    @State private var templateOrder = "new"
    @State private var platformAdmin = false
    private let templateCategories = ["Secrets", "SAST", "SCA", "Full Security Audit", "CI/CD", "Notifications", "Custom"]
    @State private var allowDraft = "[]"
    @State private var allowLoaded = false
    @State private var applyAllowlist = false
    @State private var auditLog: JSONValue?

    var body: some View {
        NavigationStack {
            Form {
                Group {
                    switch page {
                    case .spaces: spaces
                    case .templates: library
                    case .tools: ci
                    case .assistant: assistant
                    case .settings: preferences
                    case .schedule: schedules
                    }
                }.disabled(busy)
                if busy { ProgressView() }
                if let status { Text(status).foregroundStyle(.green) }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle(LocalizedStringKey(page.rawValue))
            .toolbar { Button("Закрыть") { dismiss() }.disabled(busy) }
            .task { await run { try await load() } }
            .interactiveDismissDisabled(busy)
            .fileExporter(isPresented: $exporting, document: export, contentType: .data,
                          defaultFilename: exportName) { result in
                if case .failure(let failure) = result { error = failure.localizedDescription }
            }
            .confirmationDialog("Отозвать токен CI?", isPresented: Binding(
                get: { revokeCandidate != nil }, set: { if !$0 { revokeCandidate = nil } }
            ), titleVisibility: .visible, presenting: revokeCandidate) { token in
                Button("Отозвать", role: .destructive) {
                    revokeCandidate = nil
                    Task { await run { try await api.revokeCIToken(id: token.id); tokens = try await api.ciTokens() } }
                }
            }
            .confirmationDialog("Удалить секрет из рабочего пространства?", isPresented: Binding(
                get: { credentialCandidate != nil }, set: { if !$0 { credentialCandidate = nil } }
            ), titleVisibility: .visible, presenting: credentialCandidate) { credential in
                Button("Удалить секрет", role: .destructive) {
                    credentialCandidate = nil
                    Task { await run { try await api.deleteCredential(id: credential.id); credentials = try await api.credentials() } }
                }
            }
            .confirmationDialog("Исключить участника?", isPresented: Binding(
                get: { removeUserID != nil }, set: { if !$0 { removeUserID = nil } }
            ), titleVisibility: .visible, presenting: removeUserID) { userID in
                Button("Исключить", role: .destructive) {
                    removeUserID = nil
                    guard let id = model.workspaceID else { return }
                    Task { await run { try await api.removeMember(workspaceID: id, userID: userID); output = try await api.members(workspaceID: id) } }
                }
            }
            .confirmationDialog("Удалить отзыв?", isPresented: Binding(
                get: { deleteReviewID != nil }, set: { if !$0 { deleteReviewID = nil } }
            ), titleVisibility: .visible, presenting: deleteReviewID) { id in
                Button("Удалить отзыв", role: .destructive) {
                    deleteReviewID = nil
                    guard let template else { return }
                    Task { await run {
                        try await api.deleteReview(templateID: template.id, id: id)
                        reviews = try await api.templateReviews(id: template.id)
                    } }
                }
            }
            .confirmationDialog("Заменить список разрешённых репозиториев?", isPresented: $applyAllowlist,
                                titleVisibility: .visible) {
                Button("Сохранить список") {
                    Task { await run {
                        let entries = try JSONDecoder().decode([[String: JSONValue]].self, from: Data(allowDraft.utf8))
                        reviews = try await api.saveAllowlist(entries)
                        status = "Список сохранён."
                    } }
                }
            }
        }
        .frame(idealWidth: 730, idealHeight: 690)
    }

    private var spaces: some View {
        Group {
            Section("Выбрать пространство") {
                ForEach(model.workspaces) { workspace in
                    Button {
                        Task {
                            await model.switchWorkspace(workspace)
                            if model.workspaceID == workspace.id {
                                auditLog = nil
                                await run { output = try await api.members(workspaceID: workspace.id) }
                            } else { error = model.message }
                        }
                    } label: {
                        Label(workspace.name + " · " + (workspace.role ?? "viewer"),
                              systemImage: workspace.id == model.workspaceID ? "checkmark.circle.fill" : "circle")
                    }
                }
            }
            Section("Создать или присоединиться") {
                TextField("Название пространства", text: $name)
                Button("Создать") {
                    Task { await run {
                        let workspace = try await api.createWorkspace(name: name, timezone: TimeZone.current.identifier)
                        model.workspaces = try await api.workspaces()
                        await model.switchWorkspace(workspace)
                        name = ""
                        output = try await api.members(workspaceID: workspace.id)
                    } }
                }.disabled(name.isEmpty)
                SecureField("Токен приглашения", text: $secondary)
                Button("Принять приглашение") {
                    Task { await run {
                        _ = try await api.acceptInvitation(secondary)
                        secondary = ""
                        model.workspaces = try await api.workspaces()
                    } }
                }.disabled(secondary.isEmpty)
            }
            if let id = model.workspaceID {
                Section("Участники") {
                    ForEach(Array(objects(output, key: "members").enumerated()), id: \.offset) { _, member in
                        if let userID = member["user_id"]?.string {
                            LabeledContent(member["display_name"]?.string ?? userID, value: member["role"]?.string ?? "")
                            if isAdmin {
                                Menu("Роль и доступ") {
                                    ForEach(["viewer", "developer", "admin"], id: \.self) { role in
                                        Button(role) { Task { await run {
                                            _ = try await api.changeRole(workspaceID: id, userID: userID, role: role)
                                            output = try await api.members(workspaceID: id)
                                            model.workspaces = try await api.workspaces()
                                        } } }
                                    }
                                    Button("Исключить участника", role: .destructive) { removeUserID = userID }
                                }
                            }
                        }
                    }
                    if isAdmin {
                        TextField("E-mail участника", text: $message)
                        Picker("Роль", selection: $role) {
                            ForEach(["viewer", "developer", "admin"], id: \.self) { Text($0).tag($0) }
                        }
                        Button("Пригласить") { Task { await run {
                            let invitation = try await api.invite(workspaceID: id, email: message, role: role)
                            if case .object(let fields) = invitation { revealed = fields["invite_token"]?.string }
                            output = try await api.members(workspaceID: id)
                            message = ""
                        } } }.disabled(message.isEmpty)
                        if let revealed { Text(revealed).textSelection(.enabled) }
                    }
                    ForEach(Array(objects(output, key: "invitations").enumerated()), id: \.offset) { _, item in
                        LabeledContent(item["email"]?.string ?? "", value: "Приглашение · " + (item["role"]?.string ?? ""))
                    }
                }
                if isAdmin {
                    Section("Управление пространством") {
                        TextField("Новое название", text: $search)
                        Button("Переименовать") { Task { await run {
                            _ = try await api.updateWorkspace(id: id, name: search)
                            model.workspaces = try await api.workspaces()
                            search = ""
                        } } }.disabled(search.isEmpty)
                        Button("Журнал аудита") { Task { await run { auditLog = try await api.audit(workspaceID: id) } } }
                        if let auditLog { code(formatted(auditLog)) }
                    }
                }
            }
        }
    }

    private var library: some View {
        Group {
            Section("Каталог") {
                TextField("Поиск по названию", text: $search)
                Toggle("Только избранные", isOn: $favorites)
                DisclosureGroup("Фильтры") {
                    Picker("Категория", selection: $categoryFilter) {
                        Text("Все").tag("")
                        ForEach(templateCategories, id: \.self) { Text($0).tag($0) }
                    }
                    TextField("Автор", text: $authorFilter)
                    Toggle("Только мои", isOn: $ownTemplates)
                    Stepper("Минимальная оценка: \(minimumRating)", value: $minimumRating, in: 0...5)
                    Picker("Сортировка", selection: $templateOrder) {
                        Text("Новые").tag("new")
                        Text("Популярные").tag("popular")
                        Text("По рейтингу").tag("rating")
                    }
                }
                Button("Найти") { Task { await run { try await loadTemplates() } } }
                ForEach(templates) { item in
                    Button {
                        Task { await run {
                            template = try await api.template(id: item.id)
                            reviews = try await api.templateReviews(id: item.id)
                            parameters = "{}"
                            reviewID = nil
                            message = ""
                            name = item.name
                        } }
                    } label: {
                        LabeledContent(item.name, value: "\(item.rating.formatted()) ★ · \(item.usageCount)")
                    }
                }
            }
            if let template {
                Section(template.name) {
                    Text(template.description)
                    if let author = template.author { LabeledContent("Автор", value: author) }
                    if let category = template.category { LabeledContent("Категория", value: category) }
                    if let version = template.version { LabeledContent("Версия", value: version) }
                    Text(template.nodeTypes.joined(separator: " → ")).foregroundStyle(.secondary)
                    if let graph = template.graph {
                        GraphMiniMap(graph: graph)
                        DisclosureGroup("Структура графа") { code(formatted(graph)) }
                    }
                    if let requirements = template.parameters {
                        DisclosureGroup("Параметры шаблона") { code(formatted(requirements)) }
                    }
                    TextField("Название копии", text: $name)
                    TextField("Параметры (JSON)", text: $parameters, axis: .vertical)
                        .font(.system(.body, design: .monospaced))
                    Button("Использовать шаблон") {
                        Task { await run {
                            let fields = try JSONDecoder().decode([String: JSONValue].self, from: Data(parameters.utf8))
                            let workflow = try await api.useTemplate(id: template.id, name: name, parameters: fields)
                            onOpen(workflow)
                            dismiss()
                        } }
                    }.disabled(name.isEmpty)
                    Button(template.favorite ? "Убрать из избранного" : "В избранное") {
                        Task { await run {
                            try await api.favoriteTemplate(id: template.id, favorite: !template.favorite)
                            self.template = try await api.template(id: template.id)
                            try await loadTemplates()
                        } }
                    }
                    Stepper("Оценка: \(rating)", value: $rating, in: 1...5)
                    Button("Поставить оценку") { Task { await run {
                        _ = try await api.rateTemplate(id: template.id, stars: rating)
                        self.template = try await api.template(id: template.id)
                        try await loadTemplates()
                    } } }
                    ForEach(Array(objects(reviews).enumerated()), id: \.offset) { _, review in
                        LabeledContent(review["author"]?.string ?? "Отзыв", value: review["text"]?.string ?? "")
                        if review["mine"] == .bool(true), let id = review["id"]?.string {
                            Button("Изменить свой отзыв") {
                                reviewID = id
                                message = review["text"]?.string ?? ""
                            }
                            Button("Удалить отзыв", role: .destructive) { deleteReviewID = id }
                        }
                    }
                    TextField("Отзыв", text: $message, axis: .vertical)
                    Button(reviewID == nil ? "Оставить отзыв" : "Сохранить отзыв") { Task { await run {
                        if let reviewID {
                            _ = try await api.editReview(templateID: template.id, id: reviewID, text: message)
                        } else {
                            _ = try await api.reviewTemplate(id: template.id, text: message)
                        }
                        reviewID = nil
                        message = ""
                        reviews = try await api.templateReviews(id: template.id)
                    } } }.disabled(message.isEmpty)
                    if platformAdmin {
                        Button(template.hidden == true ? "Показать шаблон" : "Скрыть шаблон") {
                            Task { await run {
                                self.template = try await api.setTemplateVisibility(id: template.id, hidden: template.hidden != true)
                                try await loadTemplates()
                            } }
                        }
                    }
                    if template.mine {
                        Button(template.published == true ? "Снять с публикации" : "Опубликовать шаблон") {
                            Task { await run {
                                self.template = try await api.setTemplatePublication(id: template.id, published: template.published != true)
                                try await loadTemplates()
                            } }
                        }
                        TextField("Описание новой версии", text: $secondary)
                        TextField("Версия", text: $templateVersion)
                        Button("Обновить свой шаблон") { Task { await run {
                            self.template = try await api.updateTemplate(id: template.id, description: secondary, version: templateVersion)
                            try await loadTemplates()
                        } } }.disabled(templateVersion.isEmpty)
                    }
                }
            }
            if let workflow = model.workflow {
                Section("Опубликовать сохранённый сценарий") {
                    TextField("Название", text: $publishName, prompt: Text(workflow.name))
                    TextField("Описание шаблона", text: $secondary)
                    TextField("Теги через запятую", text: $tags)
                    Picker("Категория", selection: $publishCategory) {
                        ForEach(templateCategories, id: \.self) { Text($0).tag($0) }
                    }
                    Button("Опубликовать «\(workflow.name)»") { Task { await run {
                        let tagList = tags.split(separator: ",").prefix(20).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                        template = try await api.publishTemplate(workflowID: workflow.id,
                            name: publishName.isEmpty ? workflow.name : publishName,
                            description: secondary, category: publishCategory, tags: tagList)
                        secondary = ""
                        try await loadTemplates()
                    } } }.disabled(model.unsaved)
                }
            }
        }
    }

    private var ci: some View {
        Group {
            Section("Конфигурация пайплайна") {
                Picker("Сценарий", selection: $scope) {
                    Text("Выберите сценарий").tag("")
                    ForEach(model.workflows) { Text($0.name).tag($0.id) }
                }
                Picker("Провайдер", selection: $provider) {
                    Text("GitHub Actions").tag("github")
                    Text("GitLab CI").tag("gitlab")
                }
                if provider == "github" { TextField("Ветки через запятую", text: $branches) }
                Button("Скачать YAML") { Task { await run {
                    export = LocalExport(data: try await api.ciYAML(workflowID: scope, provider: provider, branches: branches))
                    exportName = provider == "github" ? "security.yml" : ".gitlab-ci.yml"
                    exporting = true
                } } }.disabled(scope.isEmpty)
                Button("Скачать CLI") { Task { await run {
                    export = LocalExport(data: try await api.ciCLI())
                    exportName = "aisw_ci.py"
                    exporting = true
                } } }
            }
            Section("Токены CI") {
                ForEach(tokens) { token in
                    HStack {
                        Text(token.name)
                        Text(token.prefix ?? "").foregroundStyle(.secondary)
                        Spacer()
                        if token.revoked != true {
                            Button("Отозвать", role: .destructive) { revokeCandidate = token }
                        }
                    }
                }
                TextField("Название токена", text: $name)
                Button("Выпустить токен для выбранного сценария") { Task { await run {
                    let token = try await api.issueCIToken(name: name, workflowID: scope)
                    revealed = token.token
                    name = ""
                    tokens = try await api.ciTokens()
                } } }.disabled(name.isEmpty || scope.isEmpty)
                if let revealed {
                    Text("Токен показан один раз.").font(.caption)
                    Text(revealed).textSelection(.enabled)
                    Button("Скрыть токен") { self.revealed = nil }
                }
            }
            Section("Доставки вебхуков") {
                Button("Обновить") { Task { await run { output = try await api.webhookStatus() } } }
                if let output { code(formatted(output)) }
            }
        }
    }

    private var assistant: some View {
        Group {
            Section("Сценарий по описанию") {
                TextField("Что должен делать сценарий?", text: $message, axis: .vertical)
                Button("Сгенерировать черновик") { Task { await run {
                    proposal = try await api.generateWorkflow(prompt: message)
                    patching = false
                } } }.disabled(message.count < 3)
                if let workflow = model.workflow {
                    Button("Предложить правку сохранённого графа") { Task { await run {
                        proposal = try await api.proposeEdit(workflowID: workflow.id, message: message)
                        patching = true
                    } } }.disabled(message.isEmpty || model.unsaved)
                    Button("Загрузить историю") { Task { await run {
                        output = try await api.proposalHistory(workflowID: workflow.id)
                    } } }
                    if let output { DisclosureGroup("История AI-правок") { code(formatted(output)) } }
                }
            }
            if let proposal {
                Section("Предпросмотр") {
                    if let content = proposal.content { Text(content) }
                    if let diff = proposal.diff { DisclosureGroup("Изменения") { code(formatted(diff)) } }
                    if let issues = proposal.issues, !issues.isEmpty {
                        DisclosureGroup("Проверка графа") { code(formatted(issues)) }
                    }
                    if let graph = proposal.graph {
                        Text("\(graph.nodes.count) нод · \(graph.edges.count) связей")
                        DisclosureGroup("Граф") { code(formatted(graph)) }
                    }
                    if patching, let workflow = model.workflow, let id = proposal.id {
                        Button("Применить проверенную правку") { Task { await run {
                            _ = try await api.resolveProposal(workflowID: workflow.id, id: id, apply: true)
                            onOpen(try await api.workflow(workflow.id))
                            dismiss()
                        } } }.disabled(!proposal.canApply || model.unsaved)
                        Button("Отклонить") { Task { await run {
                            _ = try await api.resolveProposal(workflowID: workflow.id, id: id, apply: false)
                            self.proposal = nil
                        } } }
                    } else {
                        Button("Открыть черновик в редакторе") {
                            if let graph = proposal.graph { onDraft(graph); dismiss() }
                        }.disabled(!proposal.canApply)
                    }
                }
            }
        }
    }

    private var preferences: some View {
        Group {
            Section("AI-провайдер") {
                if settingsLoaded {
                    Toggle("Включён", isOn: flag("enabled"))
                    Picker("Провайдер", selection: string("provider")) {
                        Text("OpenAI-compatible").tag("openai_compat")
                        Text("Ollama").tag("ollama")
                    }
                    TextField("Базовый URL", text: string("base_url"))
                    TextField("Модель", text: string("model"))
                    Picker("Ключ провайдера", selection: string("credential_id")) {
                        Text("Без ключа").tag("")
                        ForEach(credentials.filter { $0.kind == "llm_api_key" }) { Text($0.name).tag($0.id) }
                    }
                    .onChange(of: settings["credential_id"]) { _, value in
                        if value == .string("") { settings["credential_id"] = .null }
                    }
                    Toggle("Локальный провайдер", isOn: flag("allow_local"))
                    Button("Сохранить настройки") { Task { await run {
                        settings = try await api.saveAISettings(settings.filter { !["hints", "providers"].contains($0.key) })
                        status = "Настройки AI сохранены."
                    } } }.disabled(!isAdmin)
                    Button("Проверить сохранённое подключение") { Task { await run { output = try await api.testAI() } } }
                    if let output { code(formatted(output)) }
                }
            }
            Section("Хранилище секретов") {
                ForEach(credentials) { item in
                    LabeledContent(item.name, value: item.display ?? "")
                    if isAdmin {
                        Menu("Действия с секретом") {
                            Button("Заменить значение") { credentialValue = ""; credentialEdit = item.id }
                            Button("Удалить", role: .destructive) { credentialCandidate = item }
                        }
                    }
                }
                if isAdmin {
                    TextField("Название", text: $name)
                    Picker("Тип", selection: $credentialKind) {
                        ForEach(["generic", "telegram", "smtp", "webhook_secret", "repo_token", "repo_write_token", "llm_api_key"], id: \.self) {
                            Text($0).tag($0)
                        }
                    }
                    SecureField("Значение", text: $credentialValue)
                    Button(credentialEdit == nil ? "Сохранить новый секрет" : "Заменить значение") { Task { await run {
                        if let id = credentialEdit {
                            _ = try await api.updateCredential(id: id, value: credentialValue)
                        } else {
                            _ = try await api.createCredential(name: name, kind: credentialKind, value: credentialValue)
                        }
                        credentialValue = ""
                        name = ""
                        credentialEdit = nil
                        credentials = try await api.credentials()
                    } } }.disabled((credentialEdit == nil && name.isEmpty) || credentialValue.isEmpty)
                    if credentialEdit != nil {
                        Button("Отменить замену") { credentialEdit = nil; credentialValue = "" }
                    }
                }
            }
            Section("Разрешённые источники") {
                Button("Загрузить allowlist") { Task { await run {
                    reviews = try await api.allowlist()
                    allowDraft = formatted(objects(reviews, key: "entries"))
                    allowLoaded = true
                } } }
                if let reviews, isAdmin && allowLoaded {
                    if !objects(reviews, key: "platform").isEmpty {
                        DisclosureGroup("Список платформы") { code(formatted(objects(reviews, key: "platform"))) }
                    }
                    TextField("Записи рабочего пространства · JSON", text: $allowDraft, axis: .vertical)
                        .font(.system(.body, design: .monospaced))
                    Button("Сохранить allowlist") { applyAllowlist = true }
                } else if let reviews { code(formatted(reviews)) }
            }
            Section("Оформление") { ThemePicker(); LanguagePicker(api: api) }
        }
    }

    private var schedules: some View {
        Group {
            if let workflow = model.workflow {
                Section(workflow.name) {
                    Text("Cron и часовой пояс задаются в параметрах ноды расписания.")
                        .foregroundStyle(.secondary)
                    ForEach(Array(objects(output, key: "schedules").enumerated()), id: \.offset) { _, row in
                        LabeledContent(row["cron"]?.string ?? "Расписание", value: row["timezone"]?.string ?? "")
                        if let next = row["next_run_at"]?.string { Text(next).font(.caption) }
                    }
                    if objects(output, key: "schedules").isEmpty {
                        Text("У сценария нет настроенной ноды расписания.")
                    } else {
                        Toggle("Расписание включено", isOn: $scheduleEnabled)
                        Button("Сохранить") { Task { await run {
                            output = try await api.setSchedule(workflowID: workflow.id, enabled: scheduleEnabled)
                        } } }
                    }
                }
            } else { Text("Откройте сохранённый сценарий.") }
        }
    }

    private var isAdmin: Bool { model.workspaces.first { $0.id == model.workspaceID }?.canManage == true }

    private func load() async throws {
        switch page {
        case .spaces:
            model.workspaces = try await api.workspaces()
            if let id = model.workspaceID { output = try await api.members(workspaceID: id) }
        case .templates:
            try await loadTemplates()
            platformAdmin = (try? await api.isPlatformAdmin()) == true
        case .tools:
            scope = model.workflow?.id ?? ""
            tokens = try await api.ciTokens()
        case .assistant: break
        case .settings:
            settings = try await api.aiSettings()
            settingsLoaded = true
            credentials = try await api.credentials()
        case .schedule:
            if let id = model.workflow?.id {
                output = try await api.schedule(workflowID: id)
                scheduleEnabled = objects(output, key: "schedules").contains { $0["enabled"] == .bool(true) }
            }
        }
    }

    private func loadTemplates() async throws {
        templates = try await api.templates(search: search, favorites: favorites, category: categoryFilter,
                                            author: authorFilter, mine: ownTemplates, minimumRating: minimumRating, sort: templateOrder)
    }

    private func run(_ operation: @MainActor () async throws -> Void) async {
        guard !busy else { return }
        busy = true
        error = nil
        status = nil
        defer { busy = false }
        do { try await operation() }
        catch is CancellationError { }
        catch { self.error = error.localizedDescription }
    }

    private func flag(_ key: String) -> Binding<Bool> {
        Binding(get: { settings[key] == .bool(true) }, set: { settings[key] = .bool($0) })
    }

    private func string(_ key: String) -> Binding<String> {
        Binding(get: { settings[key]?.string ?? "" }, set: { settings[key] = .string($0) })
    }

    private func objects(_ value: JSONValue?, key: String? = nil) -> [[String: JSONValue]] {
        let rows: JSONValue?
        if let key, case .object(let object) = value { rows = object[key] }
        else { rows = value }
        guard case .array(let items) = rows else { return [] }
        return items.compactMap { item in if case .object(let values) = item { return values }; return nil }
    }

    private func code(_ value: String) -> some View {
        Text(verbatim: value).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
    }
}

struct ThemePicker: View {
    @AppStorage("appearance") private var appearance = "Системная"
    var body: some View {
        Picker("Тема", selection: $appearance) {
            ForEach(["Системная", "Светлая", "Тёмная"], id: \.self) { Text(LocalizedStringKey($0)).tag($0) }
        }
    }
}

struct LocalExport: FileDocument {
    static let readableContentTypes: [UTType] = [.data]
    var data = Data()
    init(data: Data = Data()) { self.data = data }
    init(configuration: ReadConfiguration) throws { data = configuration.file.regularFileContents ?? Data() }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper { FileWrapper(regularFileWithContents: data) }
}

struct LanguagePicker: View {
    let api: GardenAPI
    @AppStorage("language") private var language = "ru"
    @State private var error: String?

    var body: some View {
        Picker("Язык", selection: $language) {
            Text(verbatim: "Русский").tag("ru")
            Text(verbatim: "English").tag("en")
        }
        .onChange(of: language) { _, value in
            Task {
                do { try await api.updateLanguage(value); error = nil }
                catch { self.error = error.localizedDescription }
            }
        }
        if let error { Text(error).font(.caption).foregroundStyle(.red) }
    }
}
