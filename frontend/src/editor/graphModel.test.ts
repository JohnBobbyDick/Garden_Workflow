import { describe, expect, it } from 'vitest'
import { catalog } from '../test/fixtures'
import { autoLayout, canConnect, copyFragment, flowToGraph, graphToFlow, pasteFragment } from './graphModel'
import type { Graph } from '../api/types'

const graph: Graph = {
  schema_version: 1,
  nodes: [
    { id: 't', type: 'trigger.manual', position: { x: 0, y: 0 }, config: {} },
    { id: 'src', type: 'source.repo', position: { x: 200, y: 0 }, config: {}, label: 'Код' },
    { id: 'sast', type: 'scanner.sast', position: { x: 400, y: 0 }, config: {} },
    { id: 'm', type: 'logic.merge', position: { x: 600, y: 0 }, config: {} },
  ],
  edges: [
    { id: 'e1', source: 't', source_port: 'out', target: 'src', target_port: 'in' },
    { id: 'e2', source: 'src', source_port: 'out', target: 'sast', target_port: 'in' },
  ],
}

describe('graph <-> flow', () => {
  it('roundtrips nodes, edges, ports and config', () => {
    const { nodes, edges } = graphToFlow(graph)
    expect(nodes).toHaveLength(4)
    expect(edges[0]).toMatchObject({ source: 't', sourceHandle: 'out', target: 'src', targetHandle: 'in' })
    const back = flowToGraph(nodes, edges)
    expect(back.nodes.map((n) => n.id)).toEqual(['t', 'src', 'sast', 'm'])
    expect(back.nodes[1].label).toBe('Код')
    expect(back.edges).toEqual(graph.edges)
  })
})

describe('canConnect', () => {
  const { nodes, edges } = graphToFlow(graph)
  it('accepts compatible ports', () => {
    expect(canConnect({ source: 'sast', sourceHandle: 'out', target: 'm', targetHandle: 'in' }, nodes, edges, catalog).ok).toBe(true)
  })
  it('rejects incompatible types', () => {
    const r = canConnect({ source: 't', sourceHandle: 'out', target: 'sast', targetHandle: 'in' }, nodes, edges, catalog)
    expect(r).toEqual({ ok: false, reason: 'editor.err.types' })
  })
  it('rejects cycles', () => {
    const r = canConnect({ source: 'sast', sourceHandle: 'out', target: 'src', targetHandle: 'in' }, nodes, edges, catalog)
    expect(r.ok).toBe(false)
  })
  it('rejects duplicates and self loops', () => {
    expect(canConnect({ source: 't', sourceHandle: 'out', target: 'src', targetHandle: 'in' }, nodes, edges, catalog).reason).toBe('editor.err.duplicate')
    expect(canConnect({ source: 'm', sourceHandle: 'out', target: 'm', targetHandle: 'in' }, nodes, edges, catalog).reason).toBe('editor.err.self')
  })
  it('rejects a second edge into a single input but allows multiple inputs', () => {
    const extra = [...nodes, { ...nodes[1], id: 'src2' }]
    expect(canConnect({ source: 't', sourceHandle: 'out', target: 'src2', targetHandle: 'in' }, extra, edges, catalog).ok).toBe(true)
    const r = canConnect({ source: 'src2', sourceHandle: 'out', target: 'sast', targetHandle: 'in' }, extra, edges, catalog)
    expect(r.reason).toBe('editor.err.single_input')
  })
  it('any is compatible with everything', () => {
    const g = graphToFlow({ ...graph, nodes: [...graph.nodes, { id: 'if', type: 'logic.if_else', position: { x: 0, y: 0 }, config: {} }] })
    expect(canConnect({ source: 'm', sourceHandle: 'out', target: 'if', targetHandle: 'in' }, g.nodes, g.edges, catalog).ok).toBe(true)
  })
})

describe('layout and clipboard', () => {
  it('auto-layout orders nodes left to right by dependency', () => {
    const { nodes, edges } = graphToFlow(graph)
    const laid = autoLayout(nodes, edges)
    const x = Object.fromEntries(laid.map((n) => [n.id, n.position.x]))
    expect(x.t).toBeLessThan(x.src)
    expect(x.src).toBeLessThan(x.sast)
  })
  it('copy/paste remaps ids and keeps internal edges only', () => {
    const { nodes, edges } = graphToFlow(graph)
    const frag = copyFragment(nodes, edges, ['src', 'sast'])
    expect(frag.edges).toHaveLength(1)
    const pasted = pasteFragment(frag, nodes.map((n) => n.id), { x: 40, y: 40 })
    expect(pasted.nodes.map((n) => n.id)).not.toContain('src')
    expect(pasted.edges[0].source).toBe(pasted.nodes[0].id)
    expect(pasted.nodes[0].position.x).toBe(240)
  })
})
