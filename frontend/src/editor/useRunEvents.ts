import { useEffect, useReducer } from 'react'
import { subscribeRunEvents } from '../api/sse'
import type { NodeStatus, RunEvent, RunStatus } from '../api/types'

export interface PortPreview {
  type: string
  summary: string
  count: number | null
  preview: string
}

export interface NodeLive {
  status: NodeStatus
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
  const [state, dispatch] = useReducer(reduceRunEvent, initial)
  useEffect(() => {
    dispatch({ type: '__reset' })
    if (!runId) return
    return subscribeRunEvents(runId, (e) => dispatch(e), () => dispatch({ type: '__end' }))
  }, [runId])
  return state
}
