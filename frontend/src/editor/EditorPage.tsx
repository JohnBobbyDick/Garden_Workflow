import {
  Background, BackgroundVariant, Controls, MiniMap, ReactFlow, ReactFlowProvider, addEdge, useReactFlow,
  type Connection, type EdgeChangeset, type FinalConnectionState, type IsValidConnection, type NodeChangeset,
} from '@xyflow/react'
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useCatalog, useInvalidate, useWorkflow, useWs } from '../api/hooks'
import type { Catalog, Graph, ValidationIssue, Workflow } from '../api/types'
import { StatusBadge } from '../components/domain'
import { Page } from '../components/layout/AppShell'
import { Badge, Button, ErrorState, Spinner } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { useLang } from '../i18n'
import { fmtDuration } from '../lib/format'
import { defaultsOf } from '../lib/schemaForm'
import { toast } from '../store/toast'
import { EditorContext } from './EditorContext'
import {
  autoLayout, canConnect, copyFragment, edgeId, flowToGraph, graphToFlow, nextNodeId, pasteFragment, specOf,
  type FlowEdge, type FlowNode, type Fragment,
} from './graphModel'
import { History } from './history'
import { NodeCard } from './NodeCard'
import { DRAG_MIME, Palette } from './Palette'
import { ConfigPanel, RunNodePanel } from './SidePanel'
import { useRunEvents } from './useRunEvents'
import { AiAssistant } from './AiAssistant'
import { PublishDialog } from '../pages/TemplatesPage'

const nodeTypes = { aisw: NodeCard }
type Snapshot = { nodes: FlowNode[]; edges: FlowEdge[] }
const DRAFT_KEY = (id: string) => `aisw.draft.${id}`
const CLIP_KEY = 'aisw.clipboard'

function clean(nodes: FlowNode[]): FlowNode[] {
  return nodes.map(({ selected: _s, dragging: _d, ...n }) => ({ ...n, data: { ...n.data, status: undefined, issues: undefined } }))
}

function isTyping(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
}

function EditorInner({ workflow, catalog }: { workflow: Workflow; catalog: Catalog }) {
  const { t } = useTranslation()
  const lang = useLang()
  const ws = useWs()
  const rf = useReactFlow()
  const invalidate = useInvalidate()
  const [nodes, setNodes] = useState<FlowNode[]>([])
  const [edges, setEdges] = useState<FlowEdge[]>([])
  const [dirty, setDirty] = useState(false)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [busy, setBusy] = useState<'save' | 'validate' | 'run' | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; id: string } | null>(null)
  const [assistant, setAssistant] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [, bump] = useState(0)
  const history = useRef(new History<Snapshot>(100))
  const state = useRef<Snapshot>({ nodes: [], edges: [] })
  const lastEdit = useRef<{ id: string; at: number }>({ id: '', at: 0 })
  const lastReason = useRef<{ reason?: string; at: number }>({ at: 0 })
  const fileRef = useRef<HTMLInputElement>(null)
  const live = useRunEvents(runId)
  const runMode = runId !== null
  state.current = { nodes, edges }

  // initial load + draft restore
  useEffect(() => {
    const raw = localStorage.getItem(DRAFT_KEY(workflow.id))
    let graph: Graph = workflow.graph
    if (raw) {
      try {
        const draft = JSON.parse(raw) as { graph: Graph; savedAt: string; version: number }
        if (draft.version === workflow.version && draft.savedAt > workflow.updated_at) {
          graph = draft.graph
          setDirty(true)
          toast.info(t('editor.draftRestored'))
        }
      } catch {
        localStorage.removeItem(DRAFT_KEY(workflow.id))
      }
    }
    const flow = graphToFlow(graph)
    // graphs created via API / AI generation may have no positions → lay them out
    const distinct = new Set(flow.nodes.map((n) => `${n.position.x},${n.position.y}`))
    if (flow.nodes.length > 1 && distinct.size < flow.nodes.length) flow.nodes = autoLayout(flow.nodes, flow.edges)
    setNodes(flow.nodes)
    setEdges(flow.edges)
    history.current.clear()
    window.setTimeout(() => rf.fitView({ padding: 0.2, maxZoom: 1.1 }), 80)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow.id])

  // draft autosave
  useEffect(() => {
    if (!dirty) return
    const h = window.setTimeout(() => localStorage.setItem(DRAFT_KEY(workflow.id), JSON.stringify({
      graph: flowToGraph(nodes, edges), savedAt: new Date().toISOString(), version: workflow.version,
    })), 600)
    return () => window.clearTimeout(h)
  }, [nodes, edges, dirty, workflow.id, workflow.version])

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault() } }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const record = useCallback(() => {
    history.current.push({ nodes: clean(state.current.nodes), edges: state.current.edges })
    bump((x) => x + 1)
  }, [])

  const change = useCallback((fn: () => void) => { record(); fn(); setDirty(true) }, [record])

  const onNodesChange = useCallback((changes: NodeChangeset<FlowNode>) => {
    const list = changes.toArray()
    if (list.some((c) => c.type === 'remove')) { record(); setDirty(true) }
    if (list.some((c) => c.type === 'position' && c.dragging === false)) setDirty(true)
    setNodes((ns) => changes.applyTo(ns))
  }, [record])

  const onEdgesChange = useCallback((changes: EdgeChangeset<FlowEdge>) => {
    if (changes.toArray().some((c) => c.type === 'remove')) { record(); setDirty(true) }
    setEdges((es) => changes.applyTo(es))
  }, [record])

  const isValidConnection: IsValidConnection<FlowEdge> = useCallback((c) => {
    const r = canConnect(c, state.current.nodes, state.current.edges, catalog.nodes)
    if (!r.ok) lastReason.current = { reason: r.reason, at: Date.now() }
    return r.ok
  }, [catalog.nodes])

  const onConnect = useCallback((c: Connection) => {
    const r = canConnect(c, state.current.nodes, state.current.edges, catalog.nodes)
    if (!r.ok) { toast.error(t(r.reason!)); return }
    change(() => setEdges((es) => addEdge({ ...c, id: edgeId(c) }, es)))
  }, [catalog.nodes, change, t])

  const onConnectEnd = useCallback((event: MouseEvent | TouchEvent, s: FinalConnectionState) => {
    const last = lastReason.current
    lastReason.current = { at: 0 }
    if (s.isValid) return
    // explain why a drop on a handle was refused (types, cycle, duplicate, single input…)
    const pt = 'changedTouches' in event ? event.changedTouches[0] : event
    const handle = document.elementFromPoint(pt.clientX, pt.clientY)?.closest('.react-flow__handle.target')
    const from = 'fromNode' in s ? s.fromNode : null
    if (handle && from) {
      const r = canConnect({ source: from.id, sourceHandle: s.fromHandle?.id ?? null,
        target: handle.getAttribute('data-nodeid'), targetHandle: handle.getAttribute('data-handleid') },
      state.current.nodes, state.current.edges, catalog.nodes)
      if (!r.ok) { toast.error(t(r.reason!)); return }
    }
    if (last.reason && Date.now() - last.at < 1500) toast.error(t(last.reason))
  }, [catalog.nodes, t])

  const addNode = useCallback((type: string, at?: { x: number; y: number }) => {
    const spec = specOf(catalog.nodes, type)
    if (!spec) return
    const box = document.querySelector('.react-flow')?.getBoundingClientRect()
    const pos = at ?? rf.screenToFlowPosition({ x: (box?.left ?? 0) + (box?.width ?? 800) / 2, y: (box?.top ?? 0) + (box?.height ?? 600) / 2 })
    const id = nextNodeId(type, state.current.nodes.map((n) => n.id))
    change(() => setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), {
      id, type: 'aisw', position: { x: Math.round(pos.x - 120), y: Math.round(pos.y - 40) }, selected: true,
      data: { nodeType: type, label: '', config: defaultsOf(spec.config_schema), disabled: false },
    }]))
  }, [catalog.nodes, change, rf])

  const onDrop = useCallback((e: DragEvent) => {
    e.preventDefault()
    const type = e.dataTransfer.getData(DRAG_MIME)
    if (type) addNode(type, rf.screenToFlowPosition({ x: e.clientX, y: e.clientY }))
  }, [addNode, rf])

  const updateNode = useCallback((id: string, patch: Partial<FlowNode['data']>) => {
    const now = Date.now()
    if (lastEdit.current.id !== id || now - lastEdit.current.at > 1500) record()
    lastEdit.current = { id, at: now }
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)))
    setDirty(true)
  }, [record])

  const selectedIds = () => state.current.nodes.filter((n) => n.selected).map((n) => n.id)

  const copy = useCallback((ids = selectedIds()) => {
    if (!ids.length) return
    localStorage.setItem(CLIP_KEY, JSON.stringify(copyFragment(state.current.nodes, state.current.edges, ids)))
    toast.success(t('common.copied'))
  }, [t])

  const paste = useCallback(() => {
    const raw = localStorage.getItem(CLIP_KEY)
    if (!raw) return
    const frag = pasteFragment(JSON.parse(raw) as Fragment, state.current.nodes.map((n) => n.id), { x: 40, y: 40 })
    change(() => {
      setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), ...frag.nodes])
      setEdges((es) => [...es, ...frag.edges])
    })
  }, [change])

  const duplicate = useCallback((ids = selectedIds()) => {
    if (!ids.length) return
    const frag = pasteFragment(copyFragment(state.current.nodes, state.current.edges, ids), state.current.nodes.map((n) => n.id), { x: 40, y: 40 })
    change(() => {
      setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), ...frag.nodes])
      setEdges((es) => [...es, ...frag.edges])
    })
  }, [change])

  const remove = useCallback((ids: string[]) => {
    change(() => {
      setNodes((ns) => ns.filter((n) => !ids.includes(n.id)))
      setEdges((es) => es.filter((e) => !ids.includes(e.source) && !ids.includes(e.target)))
    })
  }, [change])

  const toggleDisabled = useCallback((id: string) => {
    change(() => setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, disabled: !n.data.disabled } } : n))))
  }, [change])

  const undo = useCallback(() => {
    const prev = history.current.undo({ nodes: clean(state.current.nodes), edges: state.current.edges })
    if (prev) { setNodes(prev.nodes); setEdges(prev.edges); setDirty(true); bump((x) => x + 1) }
  }, [])
  const redo = useCallback(() => {
    const next = history.current.redo({ nodes: clean(state.current.nodes), edges: state.current.edges })
    if (next) { setNodes(next.nodes); setEdges(next.edges); setDirty(true); bump((x) => x + 1) }
  }, [])

  const validate = useCallback(async (silent = false) => {
    setBusy('validate')
    try {
      const r = await api<{ valid: boolean; issues: ValidationIssue[] }>('/api/workflows/validate', {
        method: 'POST', json: { workspace_id: ws, graph: flowToGraph(state.current.nodes, state.current.edges) } })
      setIssues(r.issues)
      if (!silent) {
        if (r.valid) toast.success(t('editor.valid'))
        else toast.error(t('editor.invalid', { n: r.issues.length }))
      }
      return r.valid
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : t('common.unknownError'))
      return false
    } finally {
      setBusy(null)
    }
  }, [t, ws])

  const save = useCallback(async () => {
    setBusy('save')
    try {
      await api(`/api/workflows/${workflow.id}`, { method: 'PUT', json: { graph: flowToGraph(state.current.nodes, state.current.edges) } })
      localStorage.removeItem(DRAFT_KEY(workflow.id))
      setDirty(false)
      await invalidate('workflow', 'workflows')
      toast.success(t('editor.saved'))
      return true
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : t('common.unknownError'))
      return false
    } finally {
      setBusy(null)
    }
  }, [invalidate, t, workflow.id])

  const run = useCallback(async () => {
    if (dirty && !(await save())) return
    if (!(await validate(true))) { toast.error(t('editor.invalid', { n: '…' })); return }
    setBusy('run')
    try {
      const r = await api<{ id: string }>(`/api/workflows/${workflow.id}/run`, { method: 'POST', json: {} })
      setRunId(r.id)
      setMenu(null)
      toast.info(t('editor.runStarted'))
    } catch (e) {
      if (e instanceof ApiError && e.code === 'invalid_graph') setIssues(e.details as ValidationIssue[])
      toast.error(e instanceof ApiError ? e.message : t('common.unknownError'))
    } finally {
      setBusy(null)
    }
  }, [dirty, save, t, validate, workflow.id])

  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ name: workflow.name, graph: flowToGraph(nodes, edges) }, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${workflow.name.replace(/[^\w.-]+/g, '_')}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const importJson = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text())
      const graph: Graph = parsed.graph ?? parsed
      if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) throw new Error()
      const flow = graphToFlow(graph)
      change(() => { setNodes(flow.nodes); setEdges(flow.edges) })
      requestAnimationFrame(() => rf.fitView({ padding: 0.25 }))
      toast.success(t('editor.imported'))
    } catch {
      toast.error(t('editor.invalidJson'))
    }
  }

  const layout = () => {
    change(() => setNodes((ns) => autoLayout(ns, state.current.edges)))
    requestAnimationFrame(() => rf.fitView({ padding: 0.25, duration: 300 }))
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); if (!runMode) void save(); return }
      if (isTyping(e) || runMode) return
      const k = e.key.toLowerCase()
      if (mod && k === 'z' && !e.shiftKey) { e.preventDefault(); undo() }
      else if (mod && (k === 'y' || (k === 'z' && e.shiftKey))) { e.preventDefault(); redo() }
      else if (mod && k === 'c') copy()
      else if (mod && k === 'v') paste()
      else if (mod && k === 'd') { e.preventDefault(); duplicate() }
      else if (e.key === 'Escape') setMenu(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [copy, duplicate, paste, redo, runMode, save, undo])

  const issueMap = useMemo(() => {
    const m: Record<string, string[]> = {}
    for (const i of issues) if (i.node_id) (m[i.node_id] ??= []).push(i.message)
    return m
  }, [issues])

  const displayNodes = useMemo(() => nodes.map((n) => {
    const ln = live.nodes[n.id]
    return { ...n, data: { ...n.data, issues: runMode ? undefined : issueMap[n.id],
      status: runMode ? (ln?.status ?? 'pending') : undefined, durationMs: ln?.durationMs, summary: ln?.summary } }
  }), [nodes, live.nodes, runMode, issueMap])

  const displayEdges = useMemo(() => edges.map((e) => {
    if (!runMode) return { ...e, className: undefined, label: undefined }
    const d = live.edges[e.id]
    const tgt = live.nodes[e.target]?.status
    return { ...e, className: d ? (tgt === 'running' || live.status === 'running' ? 'edge-active' : '') : tgt === 'skipped' ? 'edge-skipped' : '',
      label: d ? (d.count !== null && d.count !== undefined ? String(d.count) : '✓') : undefined }
  }), [edges, live.edges, live.nodes, live.status, runMode])

  const selected = nodes.filter((n) => n.selected)
  const one = selected.length === 1 ? selected[0] : null
  const totalMs = live.startedAt && live.finishedAt ? new Date(live.finishedAt).getTime() - new Date(live.startedAt).getTime() : null
  const globalIssues = issues.filter((i) => !i.node_id)

  return (
    <EditorContext.Provider value={{ catalog: catalog.nodes, lang, runMode }}>
      <div className="flex h-full flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-2">
          <Link to="/workflows" className="rounded p-1.5 text-muted hover:bg-surface-2" aria-label={t('common.back')}><Icon name="chevron-right" className="rotate-180" /></Link>
          <h1 className="mr-2 max-w-[260px] truncate font-semibold" title={workflow.name}>{workflow.name}</h1>
          {dirty ? <Badge tone="warning">{t('editor.unsaved')}</Badge> : <Badge tone="success">{t('editor.saved')}</Badge>}
          <div className="flex-1" />
          {!runMode ? (
            <>
              <Button size="sm" variant="ghost" icon="undo" onClick={undo} disabled={!history.current.canUndo} title="Ctrl+Z" aria-label={t('editor.undo')} />
              <Button size="sm" variant="ghost" icon="redo" onClick={redo} disabled={!history.current.canRedo} title="Ctrl+Y" aria-label={t('editor.redo')} />
              <Button size="sm" variant="ghost" icon="layout" onClick={layout}>{t('editor.layout')}</Button>
              <input ref={fileRef} type="file" accept=".json,application/json" className="hidden" onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])} />
              <Button size="sm" variant="ghost" icon="upload" onClick={() => fileRef.current?.click()}>{t('editor.importJson')}</Button>
              <Button size="sm" variant="ghost" icon="download" onClick={exportJson}>{t('editor.export')}</Button>
              <Button size="sm" variant="ghost" icon="template" onClick={async () => { if (!dirty || await save()) setPublishing(true) }}>{t('templates.publish')}</Button>
              <Button size="sm" icon="sparkles" aria-pressed={assistant} onClick={() => setAssistant((a) => !a)}>{t('editor.assistant')}</Button>
              <Button size="sm" icon="shield-check" loading={busy === 'validate'} onClick={() => validate()}>{t('editor.validate')}</Button>
              <Button size="sm" icon="save" loading={busy === 'save'} onClick={save} title="Ctrl+S">{t('editor.save')}</Button>
              <Button size="sm" variant="primary" icon="play" loading={busy === 'run'} onClick={run}>{t('editor.run')}</Button>
            </>
          ) : (
            <>
              {live.status && <StatusBadge status={live.status} />}
              {totalMs !== null && <span className="text-sm text-muted">{t('editor.totalTime')}: {fmtDuration(totalMs, lang)}</span>}
              <Link className="text-sm text-primary hover:underline" to={`/runs/${runId}`}>{t('editor.openRun')}</Link>
              <Button size="sm" icon="workflow" onClick={() => setRunId(null)}>{t('editor.backToEdit')}</Button>
            </>
          )}
        </div>
        {globalIssues.length > 0 && !runMode && (
          <div role="alert" className="border-b border-danger/40 bg-danger/10 px-4 py-1.5 text-xs text-danger">
            {globalIssues.map((i) => i.message).join(' · ')}
          </div>
        )}
        {runMode && live.error && <div role="alert" className="border-b border-danger/40 bg-danger/10 px-4 py-1.5 text-xs text-danger">{live.error}</div>}
        <div className="flex min-h-0 flex-1">
          {!runMode && <Palette categories={catalog.categories} onAdd={(type) => addNode(type)} />}
          <div className="relative min-w-0 flex-1" onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }} onDrop={onDrop}>
            <ReactFlow<FlowNode, FlowEdge>
              nodes={displayNodes} edges={displayEdges} nodeTypes={nodeTypes}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onConnectEnd={onConnectEnd}
              isValidConnection={isValidConnection} onNodeDragStart={() => record()}
              onBeforeDelete={async () => !runMode}
              onNodeContextMenu={(e, n) => { e.preventDefault(); if (!runMode) setMenu({ x: e.clientX, y: e.clientY, id: n.id }) }}
              onPaneClick={() => setMenu(null)}
              nodesDraggable={!runMode} nodesConnectable={!runMode} elementsSelectable
              deleteKeyCode={runMode ? null : ['Delete', 'Backspace']} multiSelectionKeyCode={['Shift', 'Control', 'Meta']}
              panOnDrag={[1, 2]} selectionOnDrag panActivationKeyCode="Space" panOnScroll={false}
              snapToGrid snapGrid={[16, 16]} fitView minZoom={0.2} maxZoom={2}
              defaultEdgeOptions={{ type: 'smoothstep' }}
            >
              <Background variant={BackgroundVariant.Dots} gap={16} size={1.2} color="rgb(var(--border))" />
              <MiniMap pannable zoomable nodeColor={(n) => {
                const s = (n.data as FlowNode['data']).status
                return s === 'success' ? 'rgb(var(--success))' : s === 'failed' ? 'rgb(var(--danger))' : s === 'running' ? 'rgb(var(--info))' : 'rgb(var(--muted))'
              }} />
              <Controls />
            </ReactFlow>
            {nodes.length <= 1 && !runMode && (
              <div className="pointer-events-none absolute inset-x-0 top-6 mx-auto w-fit rounded-lg border border-border bg-surface/90 px-3 py-2 text-sm text-muted">
                {t('editor.dropHint')}
              </div>
            )}
            <div className="pointer-events-none absolute bottom-2 left-1/2 hidden -translate-x-1/2 text-[11px] text-muted lg:block">{t('editor.hotkeys')}</div>
            {menu && (
              <div role="menu" className="card fixed z-50 w-48 py-1 text-sm" style={{ left: menu.x, top: menu.y }}>
                {[
                  { k: 'duplicate', icon: 'copy', fn: () => duplicate([menu.id]) },
                  { k: 'copy', icon: 'copy', fn: () => copy([menu.id]) },
                  { k: 'paste', icon: 'file-down', fn: paste },
                  { k: nodes.find((n) => n.id === menu.id)?.data.disabled ? 'enable' : 'disable', icon: 'power', fn: () => toggleDisabled(menu.id) },
                  { k: 'deleteNode', icon: 'trash', fn: () => remove([menu.id]) },
                ].map((it) => (
                  <button key={it.k} role="menuitem" type="button" className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-2"
                    onClick={() => { it.fn(); setMenu(null) }}>
                    <Icon name={it.icon} size={14} />{t(`editor.${it.k}`)}
                  </button>
                ))}
              </div>
            )}
          </div>
          <aside className="hidden w-[340px] shrink-0 overflow-y-auto border-l border-border bg-surface md:block" aria-label={t('editor.settings')}>
            {assistant && !runMode ? <AiAssistant workflowId={workflow.id} dirty={dirty} onSaveFirst={save} onApplied={(g) => {
              const flow = graphToFlow(g)
              const distinct = new Set(flow.nodes.map((n) => `${n.position.x},${n.position.y}`))
              change(() => {
                setNodes(distinct.size < flow.nodes.length ? autoLayout(flow.nodes, flow.edges) : flow.nodes)
                setEdges(flow.edges)
              })
              setDirty(false)
              localStorage.removeItem(DRAFT_KEY(workflow.id))
              window.setTimeout(() => rf.fitView({ padding: 0.2, duration: 300 }), 80)
            }} /> : one ? (runMode ? <RunNodePanel node={one} live={live.nodes[one.id]} />
              : <ConfigPanel node={one} spec={specOf(catalog.nodes, one.data.nodeType)} issues={issues.filter((i) => i.node_id === one.id)}
                onChange={(patch) => updateNode(one.id, patch)} />)
              : <div className="p-6 text-center text-sm text-muted">{t('editor.selectNode')}</div>}
          </aside>
        </div>
      </div>
      {publishing && <PublishDialog workflowId={workflow.id} defaultName={workflow.name} onClose={() => setPublishing(false)} />}
    </EditorContext.Provider>
  )
}

export default function EditorPage() {
  const { id } = useParams()
  const wf = useWorkflow(id)
  const catalog = useCatalog()
  if (wf.error || catalog.error) return <Page><ErrorState error={wf.error ?? catalog.error} onRetry={() => { void wf.refetch(); void catalog.refetch() }} /></Page>
  if (!wf.data || !catalog.data) return <div className="flex h-full items-center justify-center"><Spinner size={28} /></div>
  return (
    <ReactFlowProvider>
      <EditorInner workflow={wf.data} catalog={catalog.data} />
    </ReactFlowProvider>
  )
}
