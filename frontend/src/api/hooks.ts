import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useUi } from '../store/ui'
import { api, withWs } from './client'
import type {
  AIReportResponse, Catalog, Credential, Finding, Graph, Project, Run, User, ValidationIssue, Workflow,
  WorkflowSummary, Workspace,
} from './types'

export function useWs(): string | null {
  return useUi((s) => s.workspaceId)
}

export function useMe(enabled = true) {
  return useQuery({
    queryKey: ['me'], enabled,
    queryFn: () => api<{ user: User; workspaces: Workspace[] }>('/api/auth/me'),
  })
}

export function useCatalog() {
  return useQuery({ queryKey: ['nodes'], queryFn: () => api<Catalog>('/api/nodes'), staleTime: 5 * 60_000 })
}

export function useWorkflows() {
  const ws = useWs()
  return useQuery({ queryKey: ['workflows', ws], queryFn: () => api<WorkflowSummary[]>(withWs('/api/workflows', ws)) })
}

export function useWorkflow(id: string | undefined) {
  return useQuery({ queryKey: ['workflow', id], enabled: !!id, queryFn: () => api<Workflow>(`/api/workflows/${id}`) })
}

export function useProjects() {
  const ws = useWs()
  return useQuery({ queryKey: ['projects', ws], queryFn: () => api<Project[]>(withWs('/api/projects', ws)) })
}

export interface RunFilters {
  workflow_id?: string
  status?: string
  trigger_type?: string
  since?: string
  until?: string
  limit?: number
}

export function useRuns(filters: RunFilters = {}, refetchMs?: number) {
  const ws = useWs()
  const qs = new URLSearchParams(Object.entries(filters).filter(([, v]) => v).map(([k, v]) => [k, String(v)]))
  return useQuery({
    queryKey: ['runs', ws, filters], refetchInterval: refetchMs,
    queryFn: () => api<{ runs: Run[] }>(withWs(`/api/runs?${qs}`, ws)).then((r) => r.runs),
  })
}

export function useRun(id: string | undefined, live = false) {
  return useQuery({
    queryKey: ['run', id], enabled: !!id,
    queryFn: () => api<Run>(`/api/runs/${id}`),
    refetchInterval: (q) => (live && q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 2000 : false),
  })
}

export function useRunFindings(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ['findings', id], enabled: !!id && enabled,
    queryFn: () => api<{ findings: Finding[]; official_min_confidence: number }>(`/api/runs/${id}/findings`),
  })
}

export function useAiReport(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ['ai-report', id], enabled: !!id && enabled, retry: false,
    queryFn: () => api<AIReportResponse>(`/api/runs/${id}/ai-report`),
  })
}

export function useCredentials() {
  const ws = useWs()
  return useQuery({ queryKey: ['credentials', ws], queryFn: () => api<Credential[]>(withWs('/api/credentials', ws)) })
}

export function useValidateGraph() {
  const ws = useWs()
  return useMutation({
    mutationFn: (graph: Graph) =>
      api<{ valid: boolean; issues: ValidationIssue[] }>('/api/workflows/validate', { method: 'POST', json: { graph, workspace_id: ws } }),
  })
}

export function useInvalidate() {
  const qc = useQueryClient()
  return (...keys: string[]) => Promise.all(keys.map((k) => qc.invalidateQueries({ queryKey: [k] })))
}
