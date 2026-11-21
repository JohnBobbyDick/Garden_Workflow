import dagre from '@dagrejs/dagre'
import type { Edge, Node } from '@xyflow/react'
import type { Graph, NodeSpec, NodeStatus } from '../api/types'

export interface FlowNodeData extends Record<string, unknown> {
  nodeType: string
  label: string
  config: Record<string, unknown>
  disabled: boolean
  status?: NodeStatus
  issues?: string[]
  summary?: string
  durationMs?: number | null
  error?: string
  reason?: string
  /** final wave of a finished run: delay of this node's glow, ms */
  finaleDelay?: number
}

export type FlowNode = Node<FlowNodeData, 'aisw'>
export type FlowEdge = Edge<{ count?: number | null; summary?: string; active?: boolean }>

export interface ConnectionLike {
  source: string | null
  sourceHandle?: string | null
  target: string | null
  targetHandle?: string | null
}

export const NODE_WIDTH = 240
export const NODE_HEIGHT = 96

export function graphToFlow(graph: Graph): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodes: FlowNode[] = graph.nodes.map((n) => ({
    id: n.id,
    type: 'aisw',
    position: { x: n.position?.x ?? 0, y: n.position?.y ?? 0 },
    data: { nodeType: n.type, label: n.label ?? '', config: n.config ?? {}, disabled: !!n.disabled },
  }))
  const edges: FlowEdge[] = graph.edges.map((e) => ({
    id: e.id,
    source: e.source,
    sourceHandle: e.source_port,
    target: e.target,
    targetHandle: e.target_port,
  }))
  return { nodes, edges }
}

export function flowToGraph(nodes: FlowNode[], edges: FlowEdge[]): Graph {
  return {
    schema_version: 1,
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.nodeType,
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
      config: n.data.config,
      ...(n.data.label ? { label: n.data.label } : {}),
      ...(n.data.disabled ? { disabled: true } : {}),
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      source_port: e.sourceHandle ?? 'out',
      target: e.target,
      target_port: e.targetHandle ?? 'in',
    })),
  }
}

export function specOf(catalog: NodeSpec[], type: string): NodeSpec | undefined {
  return catalog.find((c) => c.type === type)
}

export function portsCompatible(outType: string, inType: string): boolean {
  return outType === inType || outType === 'any' || inType === 'any'
}

export function wouldCreateCycle(source: string, target: string, edges: { source: string; target: string }[]): boolean {
  // adding source→target creates a cycle iff source is reachable from target
  const next = new Map<string, string[]>()
  for (const e of edges) next.set(e.source, [...(next.get(e.source) ?? []), e.target])
  const stack = [target]
  const seen = new Set<string>()
  while (stack.length) {
    const cur = stack.pop()!
    if (cur === source) return true
    if (seen.has(cur)) continue
    seen.add(cur)
    stack.push(...(next.get(cur) ?? []))
  }
  return false
}

/** Validates a connection; `reason` is an i18n key. */
export function canConnect(c: ConnectionLike, nodes: FlowNode[], edges: FlowEdge[], catalog: NodeSpec[]):
  { ok: boolean; reason?: string } {
  if (!c.source || !c.target) return { ok: false, reason: 'editor.err.incomplete' }
  if (c.source === c.target) return { ok: false, reason: 'editor.err.self' }
  const src = nodes.find((n) => n.id === c.source)
  const dst = nodes.find((n) => n.id === c.target)
  if (!src || !dst) return { ok: false, reason: 'editor.err.incomplete' }
  const sSpec = specOf(catalog, src.data.nodeType)
  const tSpec = specOf(catalog, dst.data.nodeType)
  const outPort = sSpec?.outputs.find((p) => p.name === (c.sourceHandle ?? 'out'))
  const inPort = tSpec?.inputs.find((p) => p.name === (c.targetHandle ?? 'in'))
  if (!outPort || !inPort) return { ok: false, reason: 'editor.err.port' }
  if (edges.some((e) => e.source === c.source && e.target === c.target && (e.sourceHandle ?? 'out') === outPort.name
    && (e.targetHandle ?? 'in') === inPort.name)) return { ok: false, reason: 'editor.err.duplicate' }
  if (!portsCompatible(outPort.type, inPort.type)) return { ok: false, reason: 'editor.err.types' }
  if (!inPort.multiple && edges.some((e) => e.target === c.target && (e.targetHandle ?? 'in') === inPort.name)) {
    return { ok: false, reason: 'editor.err.single_input' }
  }
  if (wouldCreateCycle(c.source, c.target, edges)) return { ok: false, reason: 'editor.err.cycle' }
  return { ok: true }
}

/** Links panel: connect two nodes by picking the first compatible (output, input) port pair. When none fits,
 * returns the most informative refusal (a real candidate's reason beats a missing-port one). */
export function findConnection(source: string, target: string, nodes: FlowNode[], edges: FlowEdge[], catalog: NodeSpec[]):
  { ok: true; connection: { source: string; sourceHandle: string; target: string; targetHandle: string } } | { ok: false; reason: string } {
  const sSpec = specOf(catalog, nodes.find((n) => n.id === source)?.data.nodeType ?? '')
  const tSpec = specOf(catalog, nodes.find((n) => n.id === target)?.data.nodeType ?? '')
  let reason = 'editor.err.port'
  for (const o of sSpec?.outputs ?? []) {
    for (const i of tSpec?.inputs ?? []) {
      const c = { source, sourceHandle: o.name, target, targetHandle: i.name }
      const r = canConnect(c, nodes, edges, catalog)
      if (r.ok) return { ok: true, connection: c }
      if (reason === 'editor.err.port' || r.reason !== 'editor.err.types') reason = r.reason ?? reason
    }
  }
  if (source === target) reason = 'editor.err.self'
  return { ok: false, reason }
}

const ROW_GAP = 140
const COL_GAP = 280

/** Position for a node added from another node's output: right under it, shifted right while the spot is taken. */
export function placeAfter(source: FlowNode, existing: FlowNode[]): { x: number; y: number } {
  const pos = { x: source.position.x, y: source.position.y + ROW_GAP }
  const taken = (x: number, y: number) => existing.some((n) => Math.abs(n.position.x - x) < NODE_WIDTH && Math.abs(n.position.y - y) < 100)
  while (taken(pos.x, pos.y)) pos.x += COL_GAP
  return pos
}

export function autoLayout(nodes: FlowNode[], edges: FlowEdge[]): FlowNode[] {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'TB', nodesep: 48, ranksep: 56, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of nodes) g.setNode(n.id, { width: n.measured?.width ?? NODE_WIDTH, height: n.measured?.height ?? NODE_HEIGHT })
  for (const e of edges) g.setEdge(e.source, e.target)
  dagre.layout(g)
  return nodes.map((n) => {
    const p = g.node(n.id)
    const w = n.measured?.width ?? NODE_WIDTH
    const h = n.measured?.height ?? NODE_HEIGHT
    return { ...n, position: { x: Math.round(p.x - w / 2), y: Math.round(p.y - h / 2) } }
  })
}

export function nextNodeId(type: string, existing: Iterable<string>): string {
  const base = type.split('.').pop()!.replace(/[^a-z0-9]/gi, '_')
  const taken = new Set(existing)
  let i = 1
  while (taken.has(`${base}_${i}`)) i++
  return `${base}_${i}`
}

export interface Fragment {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

export function copyFragment(nodes: FlowNode[], edges: FlowEdge[], ids: string[]): Fragment {
  const set = new Set(ids)
  return {
    nodes: nodes.filter((n) => set.has(n.id)).map((n) => structuredClone({ ...n, selected: false })),
    edges: edges.filter((e) => set.has(e.source) && set.has(e.target)).map((e) => structuredClone(e)),
  }
}

export function pasteFragment(frag: Fragment, existingIds: string[], offset: { x: number; y: number }): Fragment {
  const taken = new Set(existingIds)
  const map = new Map<string, string>()
  const nodes = frag.nodes.map((n) => {
    const id = nextNodeId(n.data.nodeType, taken)
    taken.add(id)
    map.set(n.id, id)
    return { ...structuredClone(n), id, selected: true, position: { x: n.position.x + offset.x, y: n.position.y + offset.y } }
  })
  const edges = frag.edges.map((e, i) => ({
    ...structuredClone(e),
    id: `e_${map.get(e.source)}_${map.get(e.target)}_${i}`,
    source: map.get(e.source)!,
    target: map.get(e.target)!,
  }))
  return { nodes, edges }
}

export function edgeId(c: ConnectionLike): string {
  return `e_${c.source}_${c.sourceHandle ?? 'out'}_${c.target}_${c.targetHandle ?? 'in'}`
}
