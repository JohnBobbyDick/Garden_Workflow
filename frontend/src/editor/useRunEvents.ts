import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useReducer } from 'react'
import { subscribeRunEvents } from '../api/sse'
import type { NodeStatus, Run, RunEvent, RunStatus } from '../api/types'

export interface PortPreview {
  type: string
  summary: string
  count: number | null
  preview: string
}

export interface NodeLive {
  status: NodeStatus
  startedAt?: string | null
  durationMs?: number | null
  error?: string
  summary?: string
  reason?: string
  logs: { level: string; message: string; at: string }[]
  inputs?: Record<string, PortPreview | PortPreview[]>
  outputs?: Record<string, PortPreview>
}

export interface LiveRun {
  status: RunStatus | null
  error: string | null
  nodes: Record<string, NodeLive>
  edges: Record<string, { count: number | null; summary: string }>
  startedAt: string | null
  finishedAt: string | null
  ended: boolean
  lastEventId: number
}

const initial: LiveRun = { status: null, error: null, nodes: {}, edges: {}, startedAt: null, finishedAt: null, ended: false, lastEventId: 0 }

export function reduceRunEvent(s: LiveRun, e: RunEvent | { type: '__reset' } | { type: '__end' }): LiveRun {
  if (e.type === '__reset') return initial
  if (e.type === '__end') return { ...s, ended: true }
  const ev = e as RunEvent
  if (ev.id <= s.lastEventId) return s
  const next = { ...s, lastEventId: ev.id }
  const d = ev.data as Record<string, unknown>
  const node = (id: string): NodeLive => next.nodes[id] ?? { status: 'pending', logs: [] }
  switch (ev.type) {
    case 'run.status': {
      const st = d.status as RunStatus
      next.status = st
      if (st === 'running' && !next.startedAt) next.startedAt = ev.at
      if (['success', 'failed', 'cancelled'].includes(st)) { next.finishedAt = ev.at; next.error = (d.error as string) ?? null }
      return next
    }
    case 'node.status':
      next.nodes = { ...next.nodes, [ev.node_id!]: { ...node(ev.node_id!), status: d.status as NodeStatus,
        startedAt: d.status === 'running' ? ev.at : node(ev.node_id!).startedAt,
        durationMs: (d.duration_ms as number) ?? node(ev.node_id!).durationMs, error: d.error as string | undefined,
        summary: (d.summary as string) ?? node(ev.node_id!).summary, reason: d.reason as string | undefined } }
      return next
    case 'node.log':
      next.nodes = { ...next.nodes, [ev.node_id!]: { ...node(ev.node_id!),
        logs: [...node(ev.node_id!).logs, { level: d.level as string, message: d.message as string, at: ev.at }] } }
      return next
    case 'node.input':
      next.nodes = { ...next.nodes, [ev.node_id!]: { ...node(ev.node_id!), inputs: d.ports as NodeLive['inputs'] } }
      return next
    case 'node.output':
      next.nodes = { ...next.nodes, [ev.node_id!]: { ...node(ev.node_id!), outputs: d.ports as NodeLive['outputs'] } }
      return next
    case 'edge.data':
      next.edges = { ...next.edges, [d.edge_id as string]: { count: d.count as number | null, summary: d.summary as string } }
      return next
    default:
      return next
  }
}

export function useRunEvents(runId: string | null): LiveRun {
  const qc = useQueryClient()
  const [state, dispatch] = useReducer(reduceRunEvent, initial)
  useEffect(() => {
    dispatch({ type: '__reset' })
    if (!runId) return
    const runKey = ['run', runId]
    return subscribeRunEvents(runId, (e) => {
      dispatch(e)
      if (e.type !== 'node.status' || e.data.status !== 'success') return
      const run = qc.getQueryData<Run>(runKey)
      if (!run || !['running', 'queued'].includes(run.status)) return
      const type = run.graph_snapshot?.nodes.find((n) => n.id === e.node_id)?.type
      if (type?.startsWith('scanner.')) void qc.invalidateQueries({ queryKey: ['findings', runId, 'live'] })
      if (type === 'ai.report') void qc.invalidateQueries({ queryKey: runKey })
    }, () => {
      dispatch({ type: '__end' })
      void qc.invalidateQueries({ queryKey: runKey })
    })
  }, [runId, qc])
  return state
}
