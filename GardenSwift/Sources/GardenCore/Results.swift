import Foundation

public struct Finding: Decodable, Identifiable, Sendable {
    public let id: String
    public let title: String
    public let severity: String
    public let category: String
    public let path: String
    public let line: Int
    public let description: String?
    public let remediation: String?
    public let snippet: String?
    public let diffStatus: String?
    public let diffHunk: String?
    public let autofix: String?

    public var supportsAutofix: Bool { autofix == "llm" || autofix == "deterministic" }

    enum CodingKeys: String, CodingKey {
        case id, title, severity, category, path, line, description, remediation, snippet, autofix
        case diffStatus = "diff_status", diffHunk = "diff_hunk"
    }
}

public struct Dashboard: Decodable, Sendable {
    public struct Score: Decodable, Sendable {
        public struct Point: Decodable, Identifiable, Sendable {
            public let runID: String
            public let score: Int
            public var id: String { runID }
            enum CodingKeys: String, CodingKey { case score; case runID = "run_id" }
        }
        public struct Priority: Decodable, Identifiable, Sendable {
            public let findingID: String
            public let title: String
            public let expectedGain: Int
            public var id: String { findingID }
            enum CodingKeys: String, CodingKey {
                case title
                case findingID = "finding_id", expectedGain = "expected_gain"
            }
        }
        public let projectID: String?
        public let value: Int
        public let delta: Int?
        public let history: [Point]
        public let top3: [Priority]
        public let note: String?
        public let sprintPlan: JSONValue?

        enum CodingKeys: String, CodingKey {
            case value, delta, history, top3, note
            case projectID = "project_id"
            case sprintPlan = "sprint_plan"
        }
    }

    public let projects: Int
    public let workflows: Int
    public let runs: Int
    public let severityCounts: [String: Int]
    public let score: Score?

    enum CodingKeys: String, CodingKey {
        case projects, workflows, runs, score
        case severityCounts = "findings_by_severity"
    }
}

public struct AIReport: Decodable, Sendable {
    public struct Report: Decodable, Sendable {
        public struct Item: Decodable, Identifiable, Sendable {
            public let findingID: String
            public let explanation: String
            public let impact: String
            public let remediationSteps: [String]
            public var id: String { findingID }

            enum CodingKeys: String, CodingKey {
                case explanation, impact
                case findingID = "finding_id", remediationSteps = "remediation_steps"
            }
        }
        public let summary: String?
        public let findings: [Item]?
        public let globalRecommendations: [String]?

        enum CodingKeys: String, CodingKey {
            case summary, findings
            case globalRecommendations = "global_recommendations"
        }
    }

    public let report: Report?
    public let provider: String?
    public let model: String?
    public let error: String?
    public let validation: JSONValue?
    public let aiGenerated: Bool

    enum CodingKeys: String, CodingKey {
        case report, provider, model, error, validation
        case aiGenerated = "ai_generated"
    }
}

public struct Autofix: Decodable, Identifiable, Sendable {
    public struct Step: Decodable, Sendable {
        public let name: String
        public let ok: Bool
        public let detail: String
    }

    public let id: String
    public let findingID: String
    public let status: String
    public let steps: [Step]
    public let patch: String?
    public let reason: String?
    public let canCreatePR: Bool?
    public let prURL: URL?
    public let prUnavailableReason: String?

    enum CodingKeys: String, CodingKey {
        case id, status, steps, patch, reason
        case findingID = "finding_id", canCreatePR = "can_create_pr"
        case prURL = "pr_url", prUnavailableReason = "pr_unavailable_reason"
    }
}

public struct RunComparison: Decodable, Sendable {
    public let new: [Finding]
    public let fixed: [Finding]
    public let unchanged: [Finding]
}

public enum ReportFormat: String, CaseIterable, Identifiable, Sendable {
    case submission = "submission.json"
    case markdown = "report.md"
    case html = "report.html"
    public var id: Self { self }
}

public struct ScoreHistory: Decodable, Sendable {
    public let points: [Dashboard.Score.Point]
    public let trend: JSONValue?
}

public struct AutofixPullRequest: Decodable, Sendable {
    public let url: URL
    public let number: Int
    public let branch: String
    public let created: Bool
}
