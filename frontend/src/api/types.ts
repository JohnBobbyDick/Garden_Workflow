export type Lang = 'ru' | 'en'
export type I18nText = { ru: string; en: string }
export type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type RunStatus = 'queued' | 'running' | 'success' | 'failed' | 'cancelled'
export type NodeStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped' | 'cancelled'

export interface PortSpec {
  name: string
  type: string
  required: boolean
  multiple: boolean
  title: I18nText
}

export interface JsonSchemaProp {
  type?: string | string[]
  title?: string
  description?: string
  enum?: unknown[]
  default?: unknown
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  minItems?: number
  pattern?: string
  items?: JsonSchemaProp
  credential_ref?: boolean
  [key: string]: unknown
}

export interface JsonSchema {
  type: string
  properties?: Record<string, JsonSchemaProp>
  required?: string[]
  [key: string]: unknown
}

export interface NodeSpec {
  type: string
  category: string
  title: I18nText
  description: I18nText
  icon: string
  inputs: PortSpec[]
  outputs: PortSpec[]
  branch_outputs: string[]
  config_schema: JsonSchema
}

export interface Catalog {
  nodes: NodeSpec[]
  port_types: string[]
  categories: { id: string; title: I18nText }[]
}

export interface GraphNode {
  id: string
  type: string
  position: { x: number; y: number }
  config: Record<string, unknown>
  label?: string
  disabled?: boolean
}

export interface GraphEdge {
  id: string
  source: string
  source_port: string
  target: string
  target_port: string
}

export interface Graph {
  schema_version: number
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface ValidationIssue {
  code: string
  message: string
  node_id?: string | null
  edge_id?: string | null
  field?: string | null
}

export interface Workspace {
  id: string
  name: string
  role: 'admin' | 'developer' | 'viewer'
  timezone: string
}

export interface User {
  id: string
  email: string
  display_name: string
  locale: Lang
  is_platform_admin: boolean
}

export interface WorkflowSummary {
  id: string
  workspace_id: string
  name: string
  description: string
  project_id: string | null
  version: number
  forked_from: string | null
  created_at: string
  updated_at: string
  node_count: number
  last_run: { id: string; status: RunStatus; created_at: string } | null
}

export interface Workflow extends WorkflowSummary {
  graph: Graph
}

export interface RunSummary {
  total?: number
  by_severity?: Partial<Record<Severity, number>>
  by_category?: Record<string, number>
  max_severity?: Severity | null
}

export interface NodeRunInfo {
  node_id: string
  node_type: string
  status: NodeStatus
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  error: string | null
  output_summary: { summary?: string; reason?: string; ports?: string[] }
}

export interface Run {
  id: string
  workspace_id: string
  workflow_id: string | null
  workflow_name: string | null
  project_id: string | null
  status: RunStatus
  trigger_type: string
  triggered_by: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  error: string | null
  summary: RunSummary
  gate: 'pass' | 'fail' | null
  verdict: Record<string, unknown> | null
  score: number | null
  score_delta: number | null
  graph_snapshot?: Graph
  nodes?: NodeRunInfo[]
  artifacts?: { name: string; content_type: string; size: number; url: string; node_id: string | null }[]
  notifications?: { node_id: string; channel: string; status: string; detail: string; at: string }[]
  source?: Record<string, unknown>
}

export interface Location {
  path: string
  line: number
  end_line?: number | null
}

export interface Finding {
  id: string
  category: 'SECRET' | 'SAST' | 'SCA'
  class: string
  rule_id: string
  title: string
  description: string
  remediation: string
  severity: Severity
  severity_reason: string
  confidence: number
  path: string
  line: number
  end_line: number
  snippet: string
  cwe?: string
  alternate_locations?: Location[]
  group?: string
  artifact?: string
  version?: string
  advisory_id?: string
  aliases?: string[]
  fixed_versions?: string[]
  cvss?: { score?: number; vector?: string }
  masked_value?: string
  diff_status?: 'new' | 'existing'
  diff_hunk?: string
  introduced_in_commit?: string
  author?: string
  autofix?: 'llm' | 'deterministic' | 'none'
  official: boolean
}

export interface AIFix {
  path: string
  start_line: number
  end_line: number
  before: string
  after: string
}

export interface AIItem {
  finding_id: string
  explanation: string
  impact: string
  remediation_steps: string[]
  safe_version?: string | null
  fix?: AIFix
  source?: string
}

export interface AIReportResponse {
  id: string
  provider: string | null
  model: string | null
  language: Lang
  ai_generated: boolean
  error: string | null
  report: { summary: string; priority_order: string[]; findings: AIItem[]; global_recommendations: string[] }
  validation: {
    checks: { check: string; status: string; details: string }[]
    metrics: Record<string, unknown>
    flags: Record<string, boolean>
  }
  usage: Record<string, number>
  created_at: string
}

export interface RunEvent {
  id: number
  type: string
  node_id: string | null
  data: Record<string, unknown>
  at: string
}

export interface Credential {
  id: string
  name: string
  kind: string
  display: string
  created_at: string
}

export interface Project {
  id: string
  name: string
  description: string
  source_mode: 'upload' | 'git_url' | 'path'
  git_url: string | null
  ref: string | null
  path: string | null
  subdir: string | null
  upload_id: string | null
  created_at: string
}
