import { Background, BackgroundVariant, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useCatalog, useCredentials, useWs } from '../api/hooks'
import type { Graph } from '../api/types'
import { Page } from '../components/layout/AppShell'
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Select, Skeleton, Textarea } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { EditorContext } from '../editor/EditorContext'
import { autoLayout, graphToFlow } from '../editor/graphModel'
import { NodeCard } from '../editor/NodeCard'
import { useLang } from '../i18n'
import { fmtDate } from '../lib/format'
import { toast } from '../store/toast'

interface Param { name: string; type: 'string' | 'credential' | 'array'; kind?: string | null; description: string; required: boolean; default?: unknown }
interface Tpl { id: string; name: string; description: string; category: string; tags: string[]; version: string; author_name: string;
  builtin: boolean; usage_count: number; rating_avg: number; rating_count: number; favorite: boolean; mine: boolean; published: boolean;
  node_types: string[]; created_at: string; graph?: Graph; parameters?: Param[]; my_rating?: number | null }
interface Review { id: string; text: string; author: string; mine: boolean; created_at: string }

const nodeTypes = { aisw: NodeCard }

function Stars({ value, onRate, label }: { value: number; onRate?: (n: number) => void; label: string }) {
  return (
    <span className="inline-flex items-center" aria-label={`${label}: ${value.toFixed(1)}`}>
      {[1, 2, 3, 4, 5].map((n) => onRate ? (
        <button key={n} type="button" onClick={() => onRate(n)} aria-label={`${label} ${n}`}
          className={n <= Math.round(value) ? 'text-warning' : 'text-border'}>★</button>
      ) : (  // read-only stars live inside clickable cards: no nested buttons
        <span key={n} aria-hidden="true" className={n <= Math.round(value) ? 'text-warning' : 'text-border'}>★</span>
      ))}
    </span>
  )
}

function Preview({ graph }: { graph: Graph }) {
  const catalog = useCatalog()
  const lang = useLang()
  const flow = useMemo(() => { const f = graphToFlow(graph); return { nodes: autoLayout(f.nodes, f.edges), edges: f.edges.map((e) => ({ ...e, type: 'smoothstep' })) } }, [graph])
  return (
    <EditorContext.Provider value={{ catalog: catalog.data?.nodes ?? [], lang, runMode: false }}>
      <div className="h-72 overflow-hidden rounded-field border border-border">
        <ReactFlowProvider>
          <ReactFlow defaultNodes={flow.nodes} edges={flow.edges} nodeTypes={nodeTypes} fitView deleteKeyCode={null} nodesConnectable={false} elementsSelectable={false}>
            <Background variant={BackgroundVariant.Dots} gap={16} size={1.2} color="rgb(var(--border))" />
          </ReactFlow>
        </ReactFlowProvider>
      </div>
    </EditorContext.Provider>
  )
}

function TemplateDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation()
  const lang = useLang()
  const ws = useWs()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const creds = useCredentials()
  const tq = useQuery({ queryKey: ['template', id], queryFn: () => api<Tpl>(`/api/templates/${id}`) })
  const rq = useQuery({ queryKey: ['reviews', id], queryFn: () => api<Review[]>(`/api/templates/${id}/reviews`) })
  const [values, setValues] = useState<Record<string, string>>({})
  const [name, setName] = useState('')
  const [review, setReview] = useState('')
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const refresh = () => { void qc.invalidateQueries({ queryKey: ['template', id] }); void qc.invalidateQueries({ queryKey: ['templates'] }) }
  const tpl = tq.data
  const run = async (fn: () => Promise<unknown>) => { try { await fn() } catch (e) { toast.error(e instanceof ApiError ? e.message : String(e)) } }
  const use = () => run(async () => {
    const r = await api<{ id: string }>(`/api/templates/${id}/use`, { method: 'POST', json: { workspace_id: ws, name: name || undefined, params: values } })
    toast.success(t('templates.created'))
    navigate(`/c/${r.id}`)
  })
  return (
    <Modal open onClose={onClose} title={tpl?.name ?? '…'} wide>
      {!tpl ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <Badge tone="primary">{tpl.category}</Badge><span>{tpl.author_name}</span><span>v{tpl.version}</span>
            <span>{tpl.usage_count} {t('templates.uses')}</span><Stars value={tpl.rating_avg} label="rating" /><span>({tpl.rating_count})</span>
            <button type="button" className={tpl.favorite ? 'text-warning' : ''} aria-pressed={tpl.favorite}
              onClick={() => run(async () => { await api(`/api/templates/${id}/favorite`, { method: tpl.favorite ? 'DELETE' : 'POST' }); refresh() })}>
              ♥ {t('templates.favorites')}</button>
            {tpl.mine && <Button size="sm" onClick={() => run(async () => { await api(`/api/templates/${id}`, { method: 'PUT', json: { published: !tpl.published } }); refresh() })}>
              {tpl.published ? t('templates.unpublish') : t('templates.republish')}</Button>}
          </div>
          <p className="text-sm">{tpl.description}</p>
          <div className="flex flex-wrap gap-1">{tpl.tags.map((g) => <Badge key={g}>#{g}</Badge>)}</div>
          {tpl.graph && <Preview key={tpl.id} graph={tpl.graph} />}
          <div className="text-xs text-muted">{t('templates.nodes')}: {tpl.node_types.join(', ')}</div>
          <Card title={t('templates.params')}>
            <p className="mb-3 text-xs text-muted">{t('templates.paramsHint')}</p>
            <Field label={t('templates.newName')} htmlFor="tpl-name"><Input id="tpl-name" value={name} placeholder={tpl.name} onChange={(e) => setName(e.target.value)} /></Field>
            {(tpl.parameters ?? []).map((p) => (
              <Field key={p.name} label={`${p.description || p.name} (${p.name})`} htmlFor={`p-${p.name}`} required={p.required}>
                {p.type === 'credential' ? (
                  <Select id={`p-${p.name}`} value={values[p.name] ?? ''} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}>
                    <option value="">{t('editor.credentialNone')}</option>
                    {(creds.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name} · {c.kind}</option>)}
                  </Select>
                ) : <Input id={`p-${p.name}`} value={values[p.name] ?? ''} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} />}
              </Field>
            ))}
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" icon="folder-git" onClick={() => navigate({ search: `?new=1&template=${id}` })}>{t('templates.useForRepo')}</Button>
              <Button icon="play" onClick={use}>{t('templates.use')}</Button>
            </div>
          </Card>
          <Card title={t('templates.reviews')}>
            <div className="mb-3 flex items-center gap-2 text-sm">{t('templates.rate')}:
              <Stars value={tpl.my_rating ?? 0} label={t('templates.rate')} onRate={(n) => run(async () => { await api(`/api/templates/${id}/rate`, { method: 'POST', json: { stars: n } }); refresh() })} /></div>
            <ul className="mb-3 space-y-2">
              {(rq.data ?? []).map((r) => (
                <li key={r.id} className="rounded-field bg-surface-2 p-2 text-sm">
                  <div className="mb-1 flex justify-between text-xs text-muted"><span>{r.author} · {fmtDate(r.created_at, lang)}</span>
                    {r.mine && <span className="flex gap-2">
                      <button type="button" onClick={() => setEditing({ id: r.id, text: r.text })}>{t('common.edit')}</button>
                      <button type="button" onClick={() => run(async () => { await api(`/api/templates/${id}/reviews/${r.id}`, { method: 'DELETE' }); void rq.refetch() })}>{t('common.delete')}</button>
                    </span>}</div>
                  {editing?.id === r.id ? (
                    <div className="flex gap-2"><Input value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} />
                      <Button size="sm" onClick={() => run(async () => { await api(`/api/templates/${id}/reviews/${r.id}`, { method: 'PUT', json: { text: editing.text } }); setEditing(null); void rq.refetch() })}>{t('common.save')}</Button></div>
                  ) : r.text}
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <Textarea aria-label={t('templates.addReview')} placeholder={t('templates.addReview')} value={review} onChange={(e) => setReview(e.target.value)} className="min-h-[40px] font-sans" />
              <Button disabled={!review.trim()} onClick={() => run(async () => { await api(`/api/templates/${id}/reviews`, { method: 'POST', json: { text: review } }); setReview(''); void rq.refetch() })}>{t('common.add')}</Button>
            </div>
          </Card>
        </div>
      )}
    </Modal>
  )
}

export default function TemplatesPage() {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const [category, setCategory] = useState('')
  const [minRating, setMinRating] = useState('')
  const [scope, setScope] = useState<'' | 'favorites' | 'mine' | 'system'>('')
  const [sort, setSort] = useState('new')
  const [open, setOpen] = useState<string | null>(null)
  const params = new URLSearchParams({ sort, ...(q && { q }), ...(category && { category }), ...(minRating && { min_rating: minRating }),
    ...(scope === 'favorites' && { favorites: 'true' }), ...(scope === 'mine' && { mine: 'true' }), ...(scope === 'system' && { author: 'System' }) })
  const list = useQuery({ queryKey: ['templates', params.toString()], queryFn: () => api<{ templates: Tpl[]; categories: string[] }>(`/api/templates?${params}`) })
  return (
    <Page wide>
      <PageHeader title={t('templates.title')} />
      <Card className="mb-4">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <div className="relative lg:col-span-2"><span className="absolute left-2.5 top-2.5 text-muted"><Icon name="search" size={15} /></span>
            <Input className="pl-8" aria-label={t('common.search')} placeholder={t('templates.search')} value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <Select aria-label={t('templates.category')} value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">{t('templates.allCategories')}</option>{(list.data?.categories ?? []).map((c) => <option key={c}>{c}</option>)}</Select>
          <Select aria-label={t('templates.minRating')} value={minRating} onChange={(e) => setMinRating(e.target.value)}>
            <option value="">{t('templates.anyRating')}</option>{[4, 3, 2].map((n) => <option key={n} value={n}>{t('templates.minRating')} {n}★</option>)}</Select>
          <div className="flex gap-2">
            <Select aria-label="scope" value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
              <option value="">{t('common.all')}</option><option value="favorites">{t('templates.favorites')}</option>
              <option value="mine">{t('templates.mine')}</option><option value="system">{t('templates.system')}</option></Select>
            <Select aria-label="sort" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="new">{t('templates.sortNew')}</option><option value="popular">{t('templates.sortPopular')}</option><option value="rating">{t('templates.sortRating')}</option></Select>
          </div>
        </div>
      </Card>
      {list.error && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
      {list.isLoading ? <div className="grid gap-3 md:grid-cols-3">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-40" />)}</div>
        : !list.data?.templates.length ? <Card><EmptyState icon="template" title={t('templates.empty')} /></Card> : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {list.data.templates.map((tpl) => (
              <button key={tpl.id} type="button" onClick={() => setOpen(tpl.id)} className="card flex flex-col p-4 text-left transition-colors hover:border-primary/50">
                <div className="flex items-start justify-between gap-2"><span className="font-semibold">{tpl.name}</span>{tpl.favorite && <span className="text-warning">♥</span>}</div>
                <div className="mt-1 flex flex-wrap gap-1"><Badge tone="primary">{tpl.category}</Badge>{tpl.builtin && <Badge>{t('templates.system')}</Badge>}</div>
                <p className="mt-2 line-clamp-3 text-sm text-muted">{tpl.description}</p>
                <div className="mt-auto flex items-center gap-2 pt-3 text-xs text-muted">
                  <Stars value={tpl.rating_avg} label="rating" /><span>{tpl.rating_avg.toFixed(1)}</span><span>·</span>
                  <span>{tpl.usage_count} {t('templates.uses')}</span><span>·</span><span>{tpl.author_name}</span></div>
              </button>
            ))}
          </div>
        )}
      {open && <TemplateDetail id={open} onClose={() => setOpen(null)} />}
    </Page>
  )
}

export function PublishDialog({ workflowId, defaultName, onClose }: { workflowId: string; defaultName: string; onClose: () => void }) {
  const { t } = useTranslation()
  const [f, setF] = useState({ name: defaultName, description: '', category: 'Full Security Audit', tags: '', version: '1.0.0' })
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setBusy(true)
    try {
      await api('/api/templates', { method: 'POST', json: { workflow_id: workflowId, ...f, tags: f.tags.split(',').map((x) => x.trim()).filter(Boolean) } })
      toast.success(t('templates.published'))
      onClose()
    } catch (e) { toast.error(e instanceof ApiError ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <Modal open onClose={onClose} title={t('templates.publish')} footer={<><Button onClick={onClose}>{t('common.cancel')}</Button>
      <Button variant="primary" loading={busy} disabled={!f.name} onClick={submit}>{t('templates.publish')}</Button></>}>
      <Field label={t('common.name')} htmlFor="pub-n" required><Input id="pub-n" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
      <Field label={t('common.description')} htmlFor="pub-d"><Textarea id="pub-d" className="font-sans" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      <Field label={t('templates.category')} htmlFor="pub-c"><Select id="pub-c" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
        {['Secrets', 'SAST', 'SCA', 'Full Security Audit', 'CI/CD', 'Notifications', 'Custom'].map((c) => <option key={c}>{c}</option>)}</Select></Field>
      <Field label={t('templates.tags')} htmlFor="pub-t"><Input id="pub-t" value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} /></Field>
      <Field label={t('templates.version')} htmlFor="pub-v"><Input id="pub-v" value={f.version} onChange={(e) => setF({ ...f, version: e.target.value })} /></Field>
      <p className="text-xs text-muted">{t('templates.paramsHint')}</p>
    </Modal>
  )
}
