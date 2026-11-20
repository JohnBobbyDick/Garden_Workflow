import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useInvalidate, useProjects, useWorkflows, useWs } from '../api/hooks'
import type { Graph, Workflow, WorkflowSummary } from '../api/types'
import { StatusBadge } from '../components/domain'
import { Page } from '../components/layout/AppShell'
import { Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Select, Skeleton, Textarea } from '../components/ui'
import { useLang } from '../i18n'
import { fmtRelative } from '../lib/format'
import { toast } from '../store/toast'

export const STARTER_GRAPH: Graph = {
  schema_version: 1,
  nodes: [{ id: 'manual_1', type: 'trigger.manual', position: { x: 0, y: 120 }, config: {} }],
  edges: [],
}

export default function WorkflowsPage() {
  const { t } = useTranslation()
  const lang = useLang()
  const ws = useWs()
  const navigate = useNavigate()
  const workflows = useWorkflows()
  const projects = useProjects()
  const invalidate = useInvalidate()
  const [params, setParams] = useSearchParams()
  const [name, setName] = useState('')
  const [projectId, setProjectId] = useState('')
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [aiPrompt, setAiPrompt] = useState('')
  const [aiIssues, setAiIssues] = useState<string[]>([])

  const generate = async () => {
    setBusy(true)
    setAiIssues([])
    try {
      const r = await api<{ workflow_id: string; needs_input: unknown[] }>('/api/ai/workflows/generate', {
        method: 'POST', json: { workspace_id: ws, prompt: aiPrompt, create: true } })
      if (r.needs_input.length) toast.info(t('assistant.needsInput', { n: r.needs_input.length }))
      await invalidate('workflows')
      navigate(`/workflows/${r.workflow_id}`)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'generation_failed') {
        setAiIssues(((e.details as { issues: { message: string }[] }).issues ?? []).map((i) => i.message))
      }
      toast.error(e instanceof ApiError && e.code === 'ai_not_configured' ? t('assistant.notConfigured') : (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const create = async (graph: Graph = STARTER_GRAPH, wfName = name) => {
    setBusy(true)
    try {
      const wf = await api<Workflow>('/api/workflows', { method: 'POST', json: { workspace_id: ws, name: wfName, graph, project_id: projectId || null } })
      await invalidate('workflows')
      navigate(`/workflows/${wf.id}`)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : t('common.unknownError'))
    } finally {
      setBusy(false)
    }
  }

  const importJson = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text())
      const graph: Graph = parsed.graph ?? parsed
      if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) throw new Error(t('editor.invalidJson'))
      await create(graph, parsed.name ?? file.name.replace(/\.json$/i, ''))
      toast.success(t('editor.imported'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t('editor.invalidJson'))
    }
  }

  const remove = async (w: WorkflowSummary) => {
    if (!window.confirm(t('workflows.deleteConfirm', { name: w.name }))) return
    await api(`/api/workflows/${w.id}`, { method: 'DELETE' })
    await invalidate('workflows')
  }

  return (
    <Page>
      <PageHeader title={t('workflows.title')} actions={<>
        <input ref={fileRef} type="file" accept="application/json,.json" className="hidden" onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])} />
        <Button icon="upload" onClick={() => fileRef.current?.click()}>{t('workflows.import')}</Button>
        <Button icon="sparkles" onClick={() => setParams({ ai: '1' })}>{t('assistant.generate')}</Button>
        <Button icon="plus" variant="primary" onClick={() => setParams({ new: '1' })}>{t('workflows.new')}</Button>
      </>} />
      {workflows.error && <ErrorState error={workflows.error} onRetry={() => workflows.refetch()} />}
      {workflows.isLoading ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>
        : !workflows.data?.length ? (
          <Card><EmptyState icon="workflow" title={t('workflows.empty')} hint={t('workflows.emptyHint')}
            action={<Button icon="plus" variant="primary" onClick={() => setParams({ new: '1' })}>{t('workflows.new')}</Button>} /></Card>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {workflows.data.map((w) => (
              <div key={w.id} className="card flex flex-col p-4 transition-colors hover:border-primary/50">
                <Link to={`/workflows/${w.id}`} className="font-semibold text-fg hover:text-primary">{w.name}</Link>
                <p className="mt-1 line-clamp-2 text-sm text-muted">{w.description || ' '}</p>
                <div className="mt-3 flex items-center gap-2 text-xs text-muted">
                  <span>{w.node_count} {t('workflows.nodes')}</span><span aria-hidden="true">·</span>
                  {w.last_run ? <><StatusBadge status={w.last_run.status} /><span>{fmtRelative(w.last_run.created_at, lang)}</span></>
                    : <span>{t('workflows.neverRun')}</span>}
                </div>
                <div className="mt-3 flex gap-2">
                  <Button size="sm" icon="workflow" onClick={() => navigate(`/workflows/${w.id}`)}>{t('common.open')}</Button>
                  <Button size="sm" variant="ghost" icon="trash" onClick={() => remove(w)}>{t('common.delete')}</Button>
                </div>
              </div>
            ))}
          </div>
        )}
      <Modal open={params.get('new') === '1'} onClose={() => setParams({})} title={t('workflows.new')}
        footer={<><Button onClick={() => setParams({})}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={busy} disabled={!name.trim()} onClick={() => create()}>{t('common.create')}</Button></>}>
        <Field label={t('common.name')} required htmlFor="wf-name">
          <Input id="wf-name" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && name.trim() && create()} />
        </Field>
        <Field label={t('workflows.project')} htmlFor="wf-proj" hint={t('common.optional')}>
          <Select id="wf-proj" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">—</option>
            {(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
      </Modal>
      <Modal open={params.get('ai') === '1'} onClose={() => setParams({})} title={t('assistant.generate')} wide
        footer={<><Button onClick={() => setParams({})}>{t('common.cancel')}</Button>
          <Button variant="primary" icon="sparkles" loading={busy} disabled={aiPrompt.trim().length < 3} onClick={generate}>
            {busy ? t('assistant.generating') : t('assistant.generate')}</Button></>}>
        <Field label={t('assistant.prompt')} htmlFor="ai-prompt">
          <Textarea id="ai-prompt" rows={4} className="font-sans" value={aiPrompt} onChange={(e) => setAiPrompt(e.target.value)} />
        </Field>
        <div className="flex flex-wrap gap-2 text-xs"><span className="text-muted">{t('assistant.examples')}:</span>
          {['Каждый день в 14:00 проверяй код из репозитория на наличие секретов и отправляй отчет на почту',
            'Каждый день в 14:00 проверяй мой Kotlin-проект на секреты и уязвимые зависимости. Если найдёшь Critical или High — отправь уведомление в Telegram.'].map((ex) => (
            <button key={ex} type="button" className="rounded border border-border px-2 py-1 text-left hover:border-primary" onClick={() => setAiPrompt(ex)}>{ex}</button>))}
        </div>
        {aiIssues.length > 0 && <ul role="alert" className="mt-3 space-y-1 text-xs text-danger"><li>{t('assistant.failed')}</li>{aiIssues.map((m, i) => <li key={i}>• {m}</li>)}</ul>}
      </Modal>
    </Page>
  )
}
