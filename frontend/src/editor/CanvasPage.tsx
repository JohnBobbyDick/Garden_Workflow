import {
  Background, BackgroundVariant, Controls, MiniMap, ReactFlow, ReactFlowProvider, addEdge, useReactFlow,
  type Connection, type EdgeChangeset, type FinalConnectionState, type IsValidConnection, type NodeChangeset,
} from '@xyflow/react'
import clsx from 'clsx'
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useCatalog, useCustomNodes, useInvalidate, useProjects, useRun, useWorkflow, useWs } from '../api/hooks'
import type { Catalog, Graph, ValidationIssue, Workflow } from '../api/types'
import { StatusBadge } from '../components/domain'
import { Button, ErrorState, Spinner } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { useLang } from '../i18n'
import { fmtDuration } from '../lib/format'
import { defaultsOf } from '../lib/schemaForm'
import { PublishDialog } from '../pages/TemplatesPage'
import { toast } from '../store/toast'
import { useWorkspaceUi } from '../store/workspace'
import { SET_SOURCE_EVENT } from '../workspace/NewCheckDialog'
import { AiAssistant } from './AiAssistant'
import { useCompactWorkspace } from '../workspace/useCompactWorkspace'
import { HeaderButton, InlineName, OverflowMenu, sourceLabel, TriggerSwitch, type TriggerKind } from './CanvasHeader'
import { EditorContext } from './EditorContext'
import {
  autoLayout, canConnect, copyFragment, edgeId, findConnection, flowToGraph, graphToCanvas, graphToFlow, nextNodeId, pasteFragment, placeAfter,
  specOf, type FlowEdge, type FlowNode, type Fragment,
} from './graphModel'
import { History } from './history'
import { Inspector } from './Inspector'
import { NodeCard } from './NodeCard'
import { DRAG_MIME } from './Palette'
import { QuickAdd } from './QuickAdd'
import { useAutosave } from './useAutosave'
import { FINALE_STEP_MS, finaleOrder } from './runAnimation'
import './neon.css'
import { useRunEvents } from './useRunEvents'

const nodeTypes = { aisw: NodeCard }
type Snapshot = { nodes: FlowNode[]; edges: FlowEdge[] }
const CLIP_KEY = 'aisw.clipboard'

function clean(nodes: FlowNode[]): FlowNode[] {
  return nodes.map(({ selected: _s, dragging: _d, ...n }) => ({ ...n, data: { ...n.data, status: undefined, issues: undefined } }))
}

function isTyping(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
}

function Canvas({ workflow, catalog }: { workflow: Workflow; catalog: Catalog }) {
  const { t } = useTranslation()
  const lang = useLang()
  const ws = useWs()
  const rf = useReactFlow()
  const nav = useNavigate()
  const invalidate = useInvalidate()
  const [params, setParams] = useSearchParams()
  const { inspectorCollapsed: desktopCollapsed, toggleInspector: toggleDesktopInspector, setInspectorCollapsed, setLastWorkflow } = useWorkspaceUi()
  const compact = useCompactWorkspace()
  const [mobilePanel, setMobilePanel] = useState(false)
  const inspectorCollapsed = compact ? !mobilePanel : desktopCollapsed
  const toggleInspector = () => compact ? setMobilePanel(!mobilePanel) : toggleDesktopInspector()
  const customNodes = useCustomNodes(workflow.workspace_id).data
  const project = useProjects().data?.find((p) => p.id === workflow.project_id)
  const [nodes, setNodes] = useState<FlowNode[]>([])
  const [edges, setEdges] = useState<FlowEdge[]>([])
  const [dirty, setDirty] = useState(false)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [busy, setBusy] = useState<'validate' | 'run' | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; id: string } | null>(null)
  const [assistant, setAssistant] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [quick, setQuick] = useState<{ from?: string } | null>(null)
  const closeQuick = useCallback(() => setQuick(null), [])
  const [, bump] = useState(0)
  const history = useRef(new History<Snapshot>(100))
  const state = useRef<Snapshot>({ nodes: [], edges: [] })
  const lastEdit = useRef<{ id: string; at: number }>({ id: '', at: 0 })
  const lastReason = useRef<{ reason?: string; at: number }>({ at: 0 })
  const fileRef = useRef<HTMLInputElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const runId = params.get('run')
  useEffect(() => setMobilePanel(!!runId), [runId, workflow.id])
  const runMode = runId !== null
  const live = useRunEvents(runId ?? workflow.last_run?.id ?? null)
  const shownRun = useRun(runId ?? workflow.last_run?.id ?? undefined, true)
  state.current = { nodes, edges }

  useEffect(() => { setLastWorkflow(workflow.id) }, [workflow.id, setLastWorkflow])
  // final wave: when a live run ends successfully, a glow runs over the successful nodes in start order
  const [finale, setFinale] = useState<Record<string, number>>({})
  const prevStatus = useRef(live.status)
  const finaleTimer = useRef<number | null>(null)
  useEffect(() => {
    const was = prevStatus.current
    prevStatus.current = live.status
    if (live.status !== 'success' || !was || !['queued', 'running'].includes(was)) return
    const order = finaleOrder(Object.entries(live.nodes).map(([id, n]) => ({ id, status: n.status, startedAt: n.startedAt })))
    setFinale(Object.fromEntries(order.map((id, i) => [id, i * FINALE_STEP_MS])))
    if (finaleTimer.current) window.clearTimeout(finaleTimer.current)
    finaleTimer.current = window.setTimeout(() => setFinale({}), order.length * FINALE_STEP_MS + 900)
  }, [live.status, live.nodes])
  useEffect(() => () => { if (finaleTimer.current) window.clearTimeout(finaleTimer.current) }, [])
  useEffect(() => {  // the SSE stream ended → the run row is final: refresh results and the checks list
    if (live.ended || (live.status && !['queued', 'running'].includes(live.status))) {
      void shownRun.refetch()
      void invalidate('workflows', 'runs')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live.ended, live.status])

  // initial load: graphs created by API / AI / starters may have no positions → lay them out (top to bottom)
  useEffect(() => {
    const flow = graphToCanvas(workflow.graph)
    setNodes(flow.nodes)
    setEdges(flow.edges)
    setDirty(false)
    history.current.clear()
    window.setTimeout(() => rf.fitView({ padding: 0.2, maxZoom: 1.1 }), 80)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow.id])

  const save = useCallback(async () => {
    try {
      const graph = flowToGraph(state.current.nodes, state.current.edges)
      await api(`/api/workflows/${workflow.id}`, { method: 'PUT', json: { graph } })
      if (JSON.stringify(graph) === JSON.stringify(flowToGraph(state.current.nodes, state.current.edges))) setDirty(false)
      void invalidate('workflow', 'workflows')
      return true
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : t('common.unknownError'))
      return false
    }
  }, [invalidate, t, workflow.id])
  const revision = useMemo(() => JSON.stringify(flowToGraph(nodes, edges)), [nodes, edges])
  const autosave = useAutosave(save, dirty, 800, revision)

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault() }
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

  const addNode = useCallback((paletteType: string, at?: { x: number; y: number }, from?: string) => {
    const custom = customNodes?.find((n) => `custom.${n.id}` === paletteType)
    const type = custom ? 'logic.map_fields' : paletteType
    const spec = specOf(catalog.nodes, type)
    if (!spec) return
    const id = nextNodeId(type, state.current.nodes.map((n) => n.id))
    const source = from ? state.current.nodes.find((n) => n.id === from) : undefined
    let pos = at
    if (!pos && source) pos = placeAfter(source, state.current.nodes)
    if (!pos) {
      const box = boxRef.current?.getBoundingClientRect()
      const c = rf.screenToFlowPosition({ x: (box?.left ?? 0) + (box?.width ?? 800) / 2, y: (box?.top ?? 0) + (box?.height ?? 600) / 2 })
      pos = { x: Math.round(c.x - 120), y: Math.round(c.y - 40) }
    }
    const node: FlowNode = { id, type: 'aisw', position: pos, selected: true,
      data: { nodeType: type, label: custom?.name ?? '',
        config: custom ? { fields: { ...custom.fields } } : defaultsOf(spec.config_schema), disabled: false } }
    change(() => {
      const nextNodes = [...state.current.nodes.map((n) => ({ ...n, selected: false })), node]
      setNodes(nextNodes)
      if (source) {
        const r = findConnection(source.id, id, nextNodes, state.current.edges, catalog.nodes)
        if (r.ok) setEdges((es) => addEdge({ ...r.connection, id: edgeId(r.connection) }, es))
        else toast.info(t(r.reason))
      }
    })
    if (!at) {  // keep the new node in view: pan smoothly to it at the current zoom
      const p = pos
      window.setTimeout(() => rf.setCenter(p.x + 120, p.y + 50, { zoom: rf.getZoom(), duration: 300 }), 30)
    }
  }, [catalog.nodes, customNodes, change, rf, t])

  const onDrop = useCallback((e: DragEvent) => {
    e.preventDefault()
    const type = e.dataTransfer.getData(DRAG_MIME)
    if (type) {
      const p = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY })
      addNode(type, { x: Math.round(p.x - 120), y: Math.round(p.y - 40) })
    }
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
    change(() => { setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), ...frag.nodes]); setEdges((es) => [...es, ...frag.edges]) })
  }, [change])
  const duplicate = useCallback((ids = selectedIds()) => {
    if (!ids.length) return
    const frag = pasteFragment(copyFragment(state.current.nodes, state.current.edges, ids), state.current.nodes.map((n) => n.id), { x: 40, y: 40 })
    change(() => { setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), ...frag.nodes]); setEdges((es) => [...es, ...frag.edges]) })
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
      if (!silent) { if (r.valid) toast.success(t('editor.valid')); else toast.error(t('editor.invalid', { n: r.issues.length })) }
      return r.valid
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : t('common.unknownError'))
      return false
    } finally { setBusy(null) }
  }, [t, ws])

  const showRun = useCallback((id: string | null) => {
    setParams((p) => { const n = new URLSearchParams(p); if (id) n.set('run', id); else n.delete('run'); return n })
  }, [setParams])

  const run = useCallback(async () => {
    if (!(await autosave.flush())) return
    if (!(await validate(true))) { toast.error(t('canvas.fixBeforeRun')); return }
    setBusy('run')
    try {
      const r = await api<{ id: string }>(`/api/workflows/${workflow.id}/run`, { method: 'POST', json: {} })
      setMenu(null)
      setQuick(null)
      setAssistant(false)
      setNodes((ns) => ns.map((n) => ({ ...n, selected: false })))
      showRun(r.id)
      void invalidate('workflows')
    } catch (e) {
      if (e instanceof ApiError && e.code === 'invalid_graph') setIssues(e.details as ValidationIssue[])
      toast.error(e instanceof ApiError ? e.message : t('common.unknownError'))
    } finally { setBusy(null) }
  }, [autosave, invalidate, showRun, t, validate, workflow.id])

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
    } catch { toast.error(t('editor.invalidJson')) }
  }
  const layout = () => {
    change(() => setNodes((ns) => autoLayout(ns, state.current.edges)))
    requestAnimationFrame(() => rf.fitView({ padding: 0.25, duration: 300 }))
  }
  const rename = async (name: string) => {
    try { await api(`/api/workflows/${workflow.id}`, { method: 'PUT', json: { name } }); void invalidate('workflow', 'workflows') }
    catch (e) { toast.error(e instanceof ApiError ? e.message : t('common.unknownError')) }
  }
  const deleteCheck = async () => {
    if (!window.confirm(t('canvas.confirmDelete', { name: workflow.name }))) return
    try { await api(`/api/workflows/${workflow.id}`, { method: 'DELETE' }); setLastWorkflow(null); await invalidate('workflows'); nav('/') }
    catch (e) { toast.error(e instanceof ApiError ? e.message : t('common.unknownError')) }
  }
  const replaceTrigger = (type: TriggerKind, config: Record<string, unknown>) => {
    const trig = state.current.nodes.find((n) => n.data.nodeType.startsWith('trigger.'))
    if (trig) change(() => setNodes((ns) => ns.map((n) => (n.id === trig.id ? { ...n, data: { ...n.data, nodeType: type, config } } : n))))
  }
  useEffect(() => {  // «Сменить источник» from the dialog: write the new source into every source.repo node
    const onSource = (e: Event) => {
      const config = (e as CustomEvent<Record<string, unknown>>).detail
      change(() => setNodes((ns) => ns.map((n) => (n.data.nodeType === 'source.repo' ? { ...n, data: { ...n.data, config: { ...config } } } : n))))
    }
    window.addEventListener(SET_SOURCE_EVENT, onSource)
    return () => window.removeEventListener(SET_SOURCE_EVENT, onSource)
  }, [change])
  const fullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void boxRef.current?.requestFullscreen?.()
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); void autosave.flush(); return }
      if (isTyping(e)) return
      const k = e.key.toLowerCase()
      if (e.key === 'Tab' && !mod && !e.shiftKey && !document.querySelector('[role=dialog]')) { e.preventDefault(); setQuick((q) => (q ? null : {})) }
      else if (mod && k === 'z' && !e.shiftKey) { e.preventDefault(); undo() }
      else if (mod && (k === 'y' || (k === 'z' && e.shiftKey))) { e.preventDefault(); redo() }
      else if (mod && k === 'c') copy()
      else if (mod && k === 'v') paste()
      else if (mod && k === 'd') { e.preventDefault(); duplicate() }
      else if (e.key === 'Escape') setMenu(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [autosave, copy, duplicate, paste, redo, undo])

  const issueMap = useMemo(() => {
    const m: Record<string, string[]> = {}
    for (const i of issues) if (i.node_id) (m[i.node_id] ??= []).push(i.message)
    return m
  }, [issues])
  const displayNodes = useMemo(() => nodes.map((n) => {
    const ln = live.nodes[n.id]
    return { ...n, data: { ...n.data, issues: issueMap[n.id],
      status: runMode ? ln?.status : undefined, durationMs: ln?.durationMs, summary: ln?.summary,
      error: runMode ? ln?.error : undefined, reason: runMode ? ln?.reason : undefined, finaleDelay: finale[n.id] } }
  }), [nodes, live.nodes, runMode, issueMap, finale])
  const displayEdges = useMemo(() => edges.map((e) => {
    if (!runMode) return { ...e, className: undefined, label: undefined }
    const d = live.edges[e.id]
    const tgt = live.nodes[e.target]?.status
    return { ...e, className: d ? (tgt === 'running' || tgt === 'pending' ? 'edge-active' : 'edge-done') : tgt === 'skipped' ? 'edge-skipped' : '',
      label: d ? (d.count !== null && d.count !== undefined ? String(d.count) : '✓') : undefined }
  }), [edges, live.edges, live.nodes, live.status, runMode])

  const selected = nodes.filter((n) => n.selected)
  const one = selected.length === 1 ? selected[0] : null
  const srcNode = nodes.find((n) => n.data.nodeType === 'source.repo')
  const trigNode = nodes.find((n) => n.data.nodeType.startsWith('trigger.'))
  const src = sourceLabel(srcNode, project, t)
  const totalMs = live.startedAt && live.finishedAt ? new Date(live.finishedAt).getTime() - new Date(live.startedAt).getTime() : null
  const globalIssues = issues.filter((i) => !i.node_id)
  const running = live.status === 'running' || live.status === 'queued'
  const quickFrom = quick?.from ? nodes.find((n) => n.id === quick.from) : undefined

  return (
    <EditorContext.Provider value={{ catalog: catalog.nodes, lang, runMode, onQuickAdd: (from) => setQuick({ from }) }}>
      <div className="flex h-full flex-col">
        <header className="flex min-h-14 shrink-0 flex-wrap items-center gap-1 border-b border-border bg-surface px-2 py-1.5 sm:gap-2 sm:px-3 xl:flex-nowrap">
          <InlineName value={workflow.name} onSave={rename} />
          <button type="button" onClick={() => setParams((p) => { const n = new URLSearchParams(p); n.set('source', '1'); return n })}
            title={t('canvas.changeSource')} className="flex h-8 min-w-0 max-w-[280px] items-center gap-1.5 rounded-chip border border-border px-2.5 text-[13px] hover:bg-soft disabled:opacity-60">
            <Icon name={src.icon} size={14} className="shrink-0 text-muted" /><span className="truncate">{src.text}</span>
          </button>
          <TriggerSwitch node={trigNode} readOnly={false} onChange={replaceTrigger} />
          <div className="hidden flex-1 xl:block" />
          <span className="hidden text-[12px] text-muted lg:inline" aria-live="polite">
            {autosave.pending || dirty ? t('canvas.saving') : t('editor.saved')}
          </span>
          <HeaderButton icon="undo" onClick={undo} disabled={!history.current.canUndo} title="Ctrl+Z" ariaLabel={t('editor.undo')} />
          <HeaderButton icon="redo" onClick={redo} disabled={!history.current.canRedo} title="Ctrl+Y" ariaLabel={t('editor.redo')} />
          {(selected.length > 0 || !nodes.length) && <>
            <HeaderButton icon="layout" onClick={layout}>{t('canvas.layout')}</HeaderButton>
            <HeaderButton icon="plus" onClick={() => { setMobilePanel(false); setQuick((q) => (q ? null : {})) }} active={!!quick} title="Tab">{t('canvas.nodes')}</HeaderButton>
            <HeaderButton icon="sparkles" onClick={() => {
              if (inspectorCollapsed) {
                if (compact) setMobilePanel(true)
                else setInspectorCollapsed(false)
                setAssistant(true)
              } else setAssistant(!assistant)
            }} active={assistant}>AI</HeaderButton>
          </>}
          <input ref={fileRef} type="file" accept=".json,application/json" className="hidden" onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])} />
          <OverflowMenu items={[
            { key: 'validate', icon: 'shield-check', label: t('editor.validate'), onClick: () => void validate() },
            { key: 'import', icon: 'upload', label: t('editor.importJson'), onClick: () => fileRef.current?.click() },
            { key: 'export', icon: 'download', label: t('editor.export'), onClick: exportJson },
            { key: 'publish', icon: 'template', label: t('templates.publish'), onClick: () => void autosave.flush().then((ok) => ok && setPublishing(true)) },
            { key: 'ci', icon: 'ci', label: t('ws.panel.ci'), onClick: () => nav({ search: '?panel=ci' }) },
            { key: 'delete', icon: 'trash', label: t('canvas.deleteCheck'), onClick: () => void deleteCheck(), danger: true },
          ]} />
          <Button variant="primary" icon="play" loading={busy === 'run'} disabled={running} onClick={run}>{t('editor.run')}</Button>
          <HeaderButton icon="chevron-right" onClick={toggleInspector} ariaLabel={inspectorCollapsed ? t('canvas.showInspector') : t('canvas.hideInspector')}
            title={inspectorCollapsed ? t('canvas.showInspector') : t('canvas.hideInspector')} />
        </header>
        {globalIssues.length > 0 && (
          <div role="alert" className="border-b border-danger/30 bg-danger-soft px-4 py-1.5 text-[13px] text-danger">{globalIssues.map((i) => i.message).join(' · ')}</div>
        )}
        <div className="relative flex min-h-0 flex-1">
          <div ref={boxRef} className={clsx('canvas-area relative min-w-0 flex-1 bg-surface-2', runMode && running && 'is-running')}
            onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }} onDrop={onDrop}>
            <ReactFlow<FlowNode, FlowEdge>
              nodes={displayNodes} edges={displayEdges} nodeTypes={nodeTypes}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onConnectEnd={onConnectEnd}
              isValidConnection={isValidConnection} onNodeDragStart={() => record()}
              onNodeClick={() => {
                setAssistant(false)
                setQuick(null)
                if (compact) setMobilePanel(true)
                else setInspectorCollapsed(false)
              }}
              onNodeContextMenu={(e, n) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, id: n.id }) }}
              onPaneClick={() => { setMenu(null); setQuick(null) }}
              nodesConnectable elementsSelectable
              deleteKeyCode={['Delete', 'Backspace']} multiSelectionKeyCode={['Shift', 'Control', 'Meta']}
              panOnDrag={[1, 2]} selectionOnDrag panActivationKeyCode="Space" panOnScroll={false}
              snapToGrid snapGrid={[16, 16]} fitView minZoom={0.2} maxZoom={2}
              defaultEdgeOptions={{ type: 'smoothstep' }}
            >
              <Background variant={BackgroundVariant.Dots} gap={16} size={1.2} color="rgb(var(--grid))" />
              <MiniMap pannable zoomable className="hidden xl:block" style={{ width: 150, height: 100 }} nodeColor={(n) => {
                const s = (n.data as FlowNode['data']).status
                return s === 'success' ? 'rgb(var(--primary))' : s === 'failed' ? 'rgb(var(--danger))' : s === 'running' ? 'rgb(var(--edge))' : 'rgb(var(--muted))'
              }} />
              <Controls showFitView showInteractive={false}>
                <button type="button" className="react-flow__controls-button" onClick={fullscreen} title={t('wf.fullscreen')} aria-label={t('wf.fullscreen')}>
                  <Icon name="maximize" size={12} />
                </button>
              </Controls>
            </ReactFlow>
            {runMode && (
              <div className="run-banner absolute left-1/2 top-3 z-10 flex w-max max-w-[calc(100%-16px)] -translate-x-1/2 flex-wrap items-center justify-center gap-x-3 gap-y-1 rounded-chip border border-border bg-surface/95 px-3 py-1.5 text-[13px] shadow-pop">
                {live.status ? <StatusBadge status={live.status} /> : <Spinner size={14} />}
                {totalMs !== null && <span className="text-muted">{t('editor.totalTime')}: {fmtDuration(totalMs, lang)}</span>}
                {live.error && <span className="max-w-[320px] truncate text-danger" title={live.error}>{live.error}</span>}
              </div>
            )}
            {nodes.length <= 2 && !runMode && !quick && (
              <div className="pointer-events-none absolute inset-x-0 bottom-16 mx-auto w-fit rounded-chip border border-border bg-surface/90 px-3 py-2 text-[13px] text-muted">
                {t('canvas.emptyHint')}
              </div>
            )}
            <QuickAdd workspaceId={workflow.workspace_id} open={!!quick} onClose={closeQuick} categories={catalog.categories}
              fromLabel={quickFrom ? (quickFrom.data.label || specOf(catalog.nodes, quickFrom.data.nodeType)?.title[lang]) : undefined}
              onAdd={(type) => { addNode(type, undefined, quick?.from); setQuick(null) }} />
            {menu && (
              <div role="menu" className="card fixed z-50 w-48 py-1 text-sm shadow-pop" style={{ left: menu.x, top: menu.y }}>
                {[
                  { k: 'duplicate', icon: 'copy', fn: () => duplicate([menu.id]) },
                  { k: 'copy', icon: 'copy', fn: () => copy([menu.id]) },
                  { k: 'paste', icon: 'file-down', fn: paste },
                  { k: nodes.find((n) => n.id === menu.id)?.data.disabled ? 'enable' : 'disable', icon: 'power', fn: () => toggleDisabled(menu.id) },
                  { k: 'deleteNode', icon: 'trash', fn: () => remove([menu.id]) },
                ].map((it) => (
                  <button key={it.k} role="menuitem" type="button" className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-soft"
                    onClick={() => { it.fn(); setMenu(null) }}>
                    <Icon name={it.icon} size={14} />{t(`editor.${it.k}`)}
                  </button>
                ))}
              </div>
            )}
          </div>
          {!inspectorCollapsed && (
            <aside className="w-[380px] max-w-full shrink-0 max-lg:absolute max-lg:inset-y-0 max-lg:right-0 max-lg:z-10 max-lg:shadow-pop border-l border-border bg-surface" aria-label={t('canvas.inspector')}>
              {assistant ? (
                <div className="h-full overflow-y-auto">
                  <AiAssistant key={workflow.id} workflowId={workflow.id} selectedNodeId={one?.id} dirty={dirty} onSaveFirst={autosave.flush} onApplied={(g) => {
                    const flow = graphToCanvas(g)
                    record()
                    setNodes(flow.nodes)
                    setEdges(flow.edges)
                    setDirty(false)
                    void invalidate('workflow', 'workflows')
                    window.setTimeout(() => rf.fitView({ padding: 0.2, duration: 300 }), 80)
                  }} />
                </div>
              ) : (
                <Inspector node={one} spec={one ? specOf(catalog.nodes, one.data.nodeType) : undefined}
                  issues={one ? issues.filter((i) => i.node_id === one.id) : []}
                  live={one ? live.nodes[one.id] : undefined} run={shownRun.data}
                  onChange={(patch) => one && updateNode(one.id, patch)} onDelete={() => one && remove([one.id])}
                  onToggle={() => one && toggleDisabled(one.id)} onCloseRun={toggleInspector} />
              )}
            </aside>
          )}
        </div>
      </div>
      {publishing && <PublishDialog workflowId={workflow.id} defaultName={workflow.name} onClose={() => setPublishing(false)} />}
    </EditorContext.Provider>
  )
}

export default function CanvasPage() {
  const { id } = useParams()
  const wf = useWorkflow(id)
  const catalog = useCatalog()
  if (wf.error || catalog.error) return <div className="p-6"><ErrorState error={wf.error ?? catalog.error} onRetry={() => { void wf.refetch(); void catalog.refetch() }} /></div>
  if (!wf.data || !catalog.data) return <div className="flex h-full items-center justify-center"><Spinner size={28} /></div>
  return (
    <ReactFlowProvider>
      <Canvas key={wf.data.id} workflow={wf.data} catalog={catalog.data} />
    </ReactFlowProvider>
  )
}
