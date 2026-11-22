import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../api/client'
import type { Graph, ValidationIssue } from '../api/types'
import { Badge, Button, Textarea } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { toast } from '../store/toast'

interface ChatMsg { id: string; role: 'user' | 'assistant'; content: string; status: string }
type EdgeChange = [string, string | null, string, string | null]
interface Proposal extends ChatMsg {
  graph: Partial<Graph> | null; valid: boolean; needs_input: { node_id: string; field: string }[]; issues: ValidationIssue[]
  stale: boolean; original_message: string | null; selected_node_id: string | null; user_message_id: string | null
  diff: { added_nodes?: string[]; removed_nodes?: string[]; changed_nodes?: string[]; added_edges?: EdgeChange[]; removed_edges?: EdgeChange[] }
}

function ProposalChanges({ proposal }: { proposal: Proposal }) {
  const { t } = useTranslation()
  const { diff, needs_input, issues } = proposal
  const changed = new Set([...(diff.added_nodes ?? []), ...(diff.changed_nodes ?? [])])
  const nodes = proposal.graph?.nodes?.filter(node => changed.has(node.id)) ?? []
  return <>
    <ul className="space-y-1 text-xs">
      {diff.added_nodes?.map((n) => <li key={`a${n}`} className="text-success">+ {t('assistant.added')}: {n}</li>)}
      {diff.changed_nodes?.map((n) => <li key={`c${n}`} className="text-warning">~ {t('assistant.changed')}: {n}</li>)}
      {diff.removed_nodes?.map((n) => <li key={`r${n}`} className="text-danger">− {t('assistant.removed')}: {n}</li>)}
      {(['added_edges', 'removed_edges'] as const).map((kind) => diff[kind]?.map(([from, out, to, input]) =>
        <li key={JSON.stringify([kind, from, out, to, input])} className={kind === 'added_edges' ? 'text-success' : 'text-danger'}>
          {kind === 'added_edges' ? '+' : '−'} {[from, out].filter(Boolean).join('.')} → {[to, input].filter(Boolean).join('.')}
        </li>))}
    </ul>
    {!!nodes.length && <details className="text-xs">
      <summary className="cursor-pointer">{t('assistant.nodeSettings')}</summary>
      {nodes.map(node => <div key={node.id} className="mt-2">
        <p className="font-semibold">{node.label || node.id} · {node.type}</p>
        <pre className="mt-1 whitespace-pre-wrap rounded-field bg-surface p-2">{JSON.stringify(node.config, null, 2)}</pre>
      </div>)}
    </details>}
    {!proposal.valid && proposal.status === 'failed' && <p className="text-xs text-danger">{t('assistant.invalidProposal')}</p>}
    {!!issues.length && <ul className="text-xs text-warning">{issues.map((issue, i) => <li key={i}>{issue.message}</li>)}</ul>}
    {!!needs_input.length && <p className="text-xs text-warning">
      {t('editor.needsInput')} · {needs_input.map(n => `${n.node_id}.${n.field}`).join(', ')}
    </p>}
  </>
}

export function AiAssistant({ workflowId, dirty, onSaveFirst, onApplied, selectedNodeId }: {
  workflowId: string; dirty: boolean; onSaveFirst: () => Promise<boolean>; onApplied: (g: Graph) => void; selectedNodeId?: string
}) {
  const { t } = useTranslation()
  const client = useQueryClient()
  const path = `/api/ai/workflows/${workflowId}/chat`
  const historyKey = ['chat', workflowId]
  const history = useQuery({ queryKey: historyKey, queryFn: () => api<ChatMsg[]>(path) })
  const [openId, setOpenId] = useState<string | null>(null)
  const detailKey = (id: string | null) => ['chat-proposal', workflowId, id]
  const detail = useQuery({ queryKey: detailKey(openId), enabled: !!openId, retry: false,
    queryFn: () => api<Proposal>(`${path}/${openId}`) })
  const [text, setText] = useState('')
  const [repeat, setRepeat] = useState<{ text: string; target: string | null } | null>(null)
  const [action, setAction] = useState<'send' | 'apply' | 'reject' | null>(null)
  const [error, setError] = useState('')
  const composer = useRef<HTMLTextAreaElement>(null)
  const draft = repeat?.text ?? text
  const target = repeat ? repeat.target : selectedNodeId
  const proposal = detail.data
  const generated = useRef<string | null>(null)
  const openMessage = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (proposal && generated.current === proposal.id) {
      openMessage.current?.scrollIntoView?.({ block: 'nearest' })
      generated.current = null
    }
  }, [proposal])

  const send = async () => {
    const message = draft.trim()
    if (action || !message) return
    setAction('send')
    setError('')
    try {
      if (dirty && !(await onSaveFirst())) return
      const p = await api<Proposal>(path, { method: 'POST', json: { message, ...(target ? { selected_node_id: target } : {}) } })
      client.setQueryData(detailKey(p.id), p)
      generated.current = p.id
      setOpenId(p.id)
      if (repeat) setRepeat(null)
      else setText('')
      void history.refetch()
    } catch (e) {
      setError(e instanceof ApiError && e.code === 'ai_not_configured' ? t('assistant.notConfigured') : (e as Error).message)
    } finally { setAction(null) }
  }

  const decide = async (decision: 'apply' | 'reject') => {
    if (!proposal || proposal.status !== 'proposed' || action) return
    setAction(decision)
    setError('')
    try {
      if (decision === 'apply' && !(await onSaveFirst())) return
      const r = await api<{ graph: Graph }>(`${path}/${proposal.id}/${decision}`, { method: 'POST' })
      const status = decision === 'apply' ? 'applied' : 'rejected'
      client.setQueryData(detailKey(proposal.id), { ...proposal, status, stale: false })
      client.setQueryData<ChatMsg[]>(historyKey, (rows) => rows?.map(m =>
        m.id === proposal.id || m.id === proposal.user_message_id ? { ...m, status } : m))
      if (decision === 'apply') { onApplied(r.graph); toast.success(t('assistant.applied')) }
      void history.refetch()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'proposal_stale') {
        client.setQueryData(detailKey(proposal.id), { ...proposal, stale: true })
      } else {
        setError((e as Error).message)
        if (e instanceof ApiError && e.code === 'not_applicable') {
          void detail.refetch()
          void history.refetch()
        }
      }
    } finally { setAction(null) }
  }

  const rows = history.data ?? []
  const messages = proposal && !rows.some(m => m.id === proposal.id) ? [...rows, proposal] : rows
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col [overflow-wrap:anywhere]">
      <div className="flex items-center gap-2 border-b border-border p-3 font-semibold"><Icon name="sparkles" size={16} />{t('assistant.title')}</div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3" aria-live="polite">
        {history.isPending && <p className="text-xs text-muted">{t('common.loading')}</p>}
        {history.isError && <div role="alert" className="text-sm text-danger">{history.error.message}
          <Button size="sm" onClick={() => history.refetch()}>{t('common.retry')}</Button>
        </div>}
        {messages.map((m) => {
          const open = openId === m.id
          const p = open ? proposal : undefined
          const status = m.status === 'proposed' ? p?.status ?? m.status : m.status
          return <div key={m.id} ref={open ? openMessage : undefined} className={m.role === 'user' ? 'ml-4 rounded-field bg-primary/15 p-2 text-sm' : 'mr-4 space-y-2 rounded-field bg-surface-2 p-2 text-sm'}>
            {m.content && <p className="whitespace-pre-wrap">{m.content}</p>}
            {m.role === 'assistant' && <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{t(`assistant.status.${status}`, { defaultValue: status })}</Badge>
                <Button size="sm" disabled={!!action} aria-expanded={open} onClick={() => { setError(''); setOpenId(open ? null : m.id) }}>
                  {t(open ? 'assistant.hideProposal' : 'assistant.review')}
                </Button>
              </div>
              {open && detail.isPending && <p className="text-xs text-muted">{t('common.loading')}</p>}
              {open && detail.isError && <div role="alert" className="space-y-1 text-xs text-danger"><p>{detail.error.message}</p>
                <Button size="sm" onClick={() => detail.refetch()}>{t('common.retry')}</Button>
              </div>}
              {p && <div className="space-y-2 border-t border-border pt-2">
                <ProposalChanges proposal={p} />
                {status === 'proposed' && !detail.isError && <>
                  {p.stale && <p className="text-xs text-warning">{t('assistant.stale')}</p>}
                  <div className="flex flex-wrap gap-2">
                    {p.stale && p.original_message && <Button size="sm" disabled={!!action} onClick={() => {
                      if (!p.original_message) return
                      setRepeat({ text: p.original_message, target: p.selected_node_id ?? null })
                      setError('')
                      composer.current?.focus()
                    }}>{t('assistant.refreshProposal')}</Button>}
                    {p.valid && !p.stale && <Button size="sm" variant="primary" disabled={!!action || detail.isFetching} onClick={() => decide('apply')}>{t('assistant.apply')}</Button>}
                    <Button size="sm" disabled={!!action || detail.isFetching} onClick={() => decide('reject')}>{t('assistant.reject')}</Button>
                  </div>
                </>}
              </div>}
            </>}
          </div>
        })}
      </div>
      <div className="shrink-0 space-y-2 border-t border-border p-3">
        {repeat && <div className="flex flex-wrap items-center justify-between gap-1 text-xs">{t('assistant.refreshDraft')}
          <Button size="sm" disabled={!!action} onClick={() => { setRepeat(null); setError('') }}>{t('common.cancel')}</Button>
        </div>}
        {target && <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
          <span>{t('assistant.target', { node: target })}</span>
          {repeat && <Button size="sm" disabled={!!action} onClick={() => setRepeat({ ...repeat, target: null })}>{t('assistant.clearTarget')}</Button>}
        </div>}
        <Textarea ref={composer} aria-label={t('assistant.chatPlaceholder')} placeholder={t('assistant.chatPlaceholder')} value={draft}
          disabled={!!action} onChange={(e) => repeat ? setRepeat({ ...repeat, text: e.target.value }) : setText(e.target.value)}
          className="font-sans" onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void send() } }} />
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <Button className="w-full" variant="primary" icon="send" loading={action === 'send'} disabled={!draft.trim() || !!action} onClick={send}>{t('assistant.send')}</Button>
      </div>
    </div>
  )
}
