import type { NodeStatus } from '../api/types'

/* Visual states of a node over a run (spec «Анимации выполнения»): the CSS classes node-<state> in neon.css. */
export type NodeVisual = 'idle' | 'waiting' | 'running' | 'success' | 'failed' | 'skipped'

export function nodeVisualState(status: NodeStatus | undefined, runActive: boolean): NodeVisual {
  switch (status) {
    case 'running': return 'running'
    case 'success': return 'success'
    case 'failed':
    case 'cancelled': return 'failed'
    case 'skipped': return 'skipped'
    default: return runActive ? 'waiting' : 'idle'
  }
}

export const FINALE_STEP_MS = 60

/** Successful nodes in the order they started: the final glow runs over them like a wave. */
export function finaleOrder(nodes: { id: string; status: NodeStatus | undefined; startedAt?: string | null }[]): string[] {
  return nodes
    .map((n, i) => ({ ...n, i, t: n.startedAt ? Date.parse(n.startedAt) : Number.POSITIVE_INFINITY }))
    .filter((n) => n.status === 'success')
    .sort((a, b) => a.t - b.t || a.i - b.i)
    .map((n) => n.id)
}
