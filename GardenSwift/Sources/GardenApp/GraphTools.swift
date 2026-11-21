import CryptoKit
import Foundation
import GardenCore
import SwiftUI
import UniformTypeIdentifiers

struct GraphDraft: Codable {
    let title: String
    let graph: Graph
    let version: Int?
}

enum GraphDraftStore {
    private static func file(for key: String) throws -> URL {
        let base = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                               appropriateFor: nil, create: false)
        let directory = base.appending(path: "GardenSecurity/Drafts")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let hash = SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined()
        return directory.appending(path: hash + ".json")
    }

    static func save(_ draft: GraphDraft, key: String) throws {
        let url = try file(for: key)
        try JSONEncoder().encode(draft).write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }

    static func load(key: String) -> GraphDraft? {
        guard let url = try? file(for: key), let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(GraphDraft.self, from: data)
    }

    static func remove(key: String) {
        if let url = try? file(for: key) { try? FileManager.default.removeItem(at: url) }
    }
}

struct EditorDrag: Codable {
    let kind: String
    let node: String
    let port: String?

    var text: String {
        guard let encoded = try? JSONEncoder().encode(self) else { return "" }
        return "garden:" + encoded.base64EncodedString()
    }

    static func decode(_ value: String?) -> Self? {
        guard let value, value.hasPrefix("garden:"),
              let data = Data(base64Encoded: String(value.dropFirst(7))) else { return nil }
        return try? JSONDecoder().decode(Self.self, from: data)
    }
}

extension JSONValue {
    var objectValue: [String: JSONValue]? {
        if case .object(let value) = self { return value }
        return nil
    }

    var arrayValue: [JSONValue]? {
        if case .array(let value) = self { return value }
        return nil
    }
}

struct NodeParameterForm: View {
    let schema: [String: JSONValue]
    let credentials: [PlatformItem]
    let api: GardenAPI?
    @Environment(\.locale) private var locale
    @Binding var values: [String: JSONValue]
    @State private var invalid: Set<String> = []

    private var fields: [String: JSONValue] { schema["properties"]?.objectValue ?? [:] }
    private var requiredNames: [String] { schema["required"]?.arrayValue?.compactMap(\.string) ?? [] }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(fields.keys.sorted(), id: \.self) { key in
                if let definition = fields[key]?.objectValue {
                    let english = locale.identifier.hasPrefix("en")
                    let title = ((english ? definition["x-title-en"]?.string : nil) ?? definition["title"]?.string ?? key)
                        + (requiredNames.contains(key) ? " *" : "")
                    VStack(alignment: .leading, spacing: 5) {
                        field(key: key, title: title, schema: definition)
                        if let description = (english ? definition["x-description-en"]?.string : nil) ?? definition["description"]?.string {
                            Text(description).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    if invalid.contains(key) { Text("Проверьте значение поля «\(title)».").font(.caption).foregroundStyle(.red) }
                }
            }
        }.labelStyle(.titleAndIcon)
    }

    @ViewBuilder
    private func field(key: String, title: String, schema: [String: JSONValue]) -> some View {
        let type = schema["type"]?.string ?? schema["anyOf"]?.arrayValue?.first?.objectValue?["type"]?.string ?? "string"
        if let options = schema["enum"]?.arrayValue {
            Picker(title, selection: Binding(
                get: { options.firstIndex(of: values[key] ?? .null) ?? -1 },
                set: { values[key] = options.indices.contains($0) ? options[$0] : nil }
            )) {
                Text("Выберите значение").tag(-1)
                ForEach(options.indices, id: \.self) { index in
                    Text(options[index].string ?? formatted(options[index])).tag(index)
                }
            }
        } else if type == "boolean" {
            Toggle(title, isOn: Binding(get: { values[key] == .bool(true) }, set: { values[key] = .bool($0) }))
        } else if schema["credential_ref"] == .bool(true) || schema["x-widget"]?.string == "credential" {
            let kind = schema["x-credential-kind"]?.string
            Picker(title, selection: Binding(
                get: { values[key]?.string ?? "" },
                set: { values[key] = $0.isEmpty ? nil : .string($0) }
            )) {
                Text("Без секрета").tag("")
                ForEach(credentials.filter { kind == nil || $0.kind == kind }) { item in Text(item.name).tag(item.id) }
            }
        } else if schema["x-widget"]?.string == "upload", let api {
            ArchiveParameterField(title: title, value: values[key]?.string, api: api) { values[key] = .string($0) }
        } else if schema["x-widget"]?.string == "password" {
            SecureField(title, text: Binding(get: { values[key]?.string ?? "" }, set: { values[key] = .string($0) }))
        } else if ["expression", "textarea", "template"].contains(schema["x-widget"]?.string ?? "") {
            TextField(title, text: Binding(get: { values[key]?.string ?? "" }, set: { values[key] = .string($0) }), axis: .vertical)
        } else if type == "array", schema["items"]?.objectValue?["type"]?.string == "string" {
            TextField(title + " · по одному на строку", text: Binding(
                get: { (values[key]?.arrayValue?.compactMap(\.string) ?? []).joined(separator: "\n") },
                set: { text in values[key] = .array(text.split(separator: "\n").map { .string(String($0)) }) }
            ), axis: .vertical)
        } else if type == "string" {
            TextField(title, text: Binding(get: { values[key]?.string ?? "" }, set: { values[key] = .string($0) }))
                .textFieldStyle(.roundedBorder)
            if schema["x-widget"]?.string == "cron" || key.lowercased().contains("cron") {
                CronShortcuts(value: values[key]?.string) { values[key] = .string($0) }
            }
        } else {
            JSONField(title: title, initial: values[key].map { formatted($0) } ?? "") { value in
                guard !value.isEmpty else { values[key] = nil; invalid.remove(key); return }
                guard let parsed = try? JSONDecoder().decode(JSONValue.self, from: Data(value.utf8)) else {
                    invalid.insert(key)
                    return
                }
                let correct: Bool
                switch (type, parsed) {
                case ("integer", .integer), ("number", .number), ("number", .integer), ("array", .array), ("object", .object):
                    correct = true
                default: correct = false
                }
                if correct { values[key] = parsed; invalid.remove(key) } else { invalid.insert(key) }
            }
        }
    }
}

private struct CronShortcuts: View {
    let value: String?
    let set: (String) -> Void

    var body: some View {
        Menu("Шаблоны Cron") {
            Button("Каждый час") { set("0 * * * *") }
            Button("Ежедневно в 09:00") { set("0 9 * * *") }
            Button("По будням в 09:00") { set("0 9 * * 1-5") }
        }
        if let value {
            let fields = value.split(separator: " ")
            if fields.count == 5 {
                Text("Cron: минута · час · день месяца · месяц · день недели").font(.caption)
                if let minute = Int(fields[0]), let hour = Int(fields[1]), fields[2] == "*",
                   fields[3] == "*", fields[4] == "*" {
                    Text("Ежедневно в \(hour):\(String(format: "%02d", minute))").font(.caption)
                }
            } else { Text("Cron должен содержать пять полей.").font(.caption).foregroundStyle(.red) }
        }
    }
}

private struct ArchiveParameterField: View {
    let title: String
    let value: String?
    let api: GardenAPI
    let update: (String) -> Void
    @State private var choosing = false
    @State private var uploading = false
    @State private var error: String?

    var body: some View {
        Text(title)
        if let value { Text(value).font(.caption).textSelection(.enabled) }
        Button("Выбрать архив…") { choosing = true }.disabled(uploading)
        if uploading { ProgressView() }
        if let error { Text(error).foregroundStyle(.red).font(.caption) }
        Color.clear.frame(height: 0).fileImporter(isPresented: $choosing, allowedContentTypes: [.archive, .zip, .data]) { result in
            Task {
                uploading = true
                self.error = nil
                defer { uploading = false }
                do {
                    let url = try result.get()
                    let data = try readArchive(url)
                    update(try await api.uploadArchive(filename: url.lastPathComponent, data: data))
                } catch { self.error = error.localizedDescription }
            }
        }
    }
}

func readArchive(_ url: URL) throws -> Data {
    let suffixes = [".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"]
    let maxSize = 50 * 1024 * 1024
    guard suffixes.contains(where: { url.lastPathComponent.lowercased().hasSuffix($0) }) else {
        throw ArchiveSelectionError.format
    }
    let scoped = url.startAccessingSecurityScopedResource()
    defer { if scoped { url.stopAccessingSecurityScopedResource() } }
    let attributes = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
    guard attributes.isRegularFile == true, let size = attributes.fileSize, size > 0, size <= maxSize else {
        throw ArchiveSelectionError.size
    }
    let handle = try FileHandle(forReadingFrom: url)
    defer { try? handle.close() }
    let data = try handle.read(upToCount: maxSize + 1) ?? Data()
    guard !data.isEmpty && data.count <= maxSize else { throw ArchiveSelectionError.size }
    return data
}

private enum ArchiveSelectionError: LocalizedError {
    case format, size

    var errorDescription: String? {
        switch self {
        case .format: "Выберите архив ZIP или TAR."
        case .size: "Выберите непустой архив размером до 50 МБ."
        }
    }
}

private struct JSONField: View {
    let title: String
    let onChange: (String) -> Void
    @State private var text: String

    init(title: String, initial: String, onChange: @escaping (String) -> Void) {
        self.title = title
        self.onChange = onChange
        _text = State(initialValue: initial)
    }

    var body: some View {
        TextField(title, text: $text).textFieldStyle(.roundedBorder)
            .onChange(of: text) { _, value in onChange(value) }
    }
}

struct GraphMiniMap: View {
    let graph: Graph
    var body: some View {
        Canvas { context, size in
            let xs = graph.nodes.map(\.position.x), ys = graph.nodes.map(\.position.y)
            let minX = min(xs.min() ?? 0, 0), minY = min(ys.min() ?? 0, 0)
            let width = max(200, (xs.max() ?? 0) - minX + 180)
            let height = max(100, (ys.max() ?? 0) - minY + 61)
            let scale = min((size.width - 16) / width, (size.height - 16) / height)
            for node in graph.nodes {
                let rect = CGRect(x: 8 + (node.position.x - minX) * scale, y: 8 + (node.position.y - minY) * scale,
                                  width: 180 * scale, height: 61 * scale)
                context.fill(Path(roundedRect: rect, cornerRadius: 2), with: .color(.green.opacity(0.65)))
            }
        }
        .frame(width: 135, height: 81)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 9))
        .accessibilityLabel("Миникарта сценария")
    }
}

#if canImport(Security)
import Security

enum SessionKeychain {
    private static func query(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "GardenSecurity.RefreshToken",
         kSecAttrAccount as String: account]
    }

    static func read(_ account: String) -> String? {
        var request = query(account)
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        request[kSecReturnData as String] = true
        var result: CFTypeRef?
        guard SecItemCopyMatching(request as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(decoding: data, as: UTF8.self)
    }

    @discardableResult
    static func store(_ token: String?, for account: String) -> OSStatus {
        let base = query(account)
        guard let token else { return SecItemDelete(base as CFDictionary) }
        let data = Data(token.utf8)
        let update = SecItemUpdate(base as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if update != errSecItemNotFound { return update }
        var item = base
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        return SecItemAdd(item as CFDictionary, nil)
    }
}
#endif
