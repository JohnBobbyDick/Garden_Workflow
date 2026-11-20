import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../api/client'
import type { Graph, ValidationIssue } from '../api/types'
import { Badge, Button, Textarea } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { toast } from '../store/toast'

interface ChatMsg { id: string; role: 'user' | 'assistant'; content: string; status: string }
interface Proposal { id: string; content: string; valid: boolean; status: string; issues: ValidationIssue[]; graph: Graph
  diff: { added_nodes?: string[]; removed_nodes?: string[]; changed_nodes?: string[]; added_edges?: string[][]; removed_edges?: string[][] } }

export function AiAssistant({ workflowId, dirty, onSaveFirst, onApplied }: {
  workflowId: string; dirty: boolean; onSaveFirst: () => Promise<boolean>; onApplied: (g: Graph) => void
}) {
  const { t } = useTranslation()
  const history = useQuery({ queryKey: ['chat', workflowId], queryFn: () => api<ChatMsg[]>(`/api/ai/workflows/${workflowId}/chat`) })
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const send = async () => {
    if (dirty && !(await onSaveFirst())) return
    setBusy(true)
    try {
      const p = await api<Proposal>(`/api/ai/workflows/${workflowId}/chat`, { method: 'POST', json: { message: text } })
      setProposal(p)
      setText('')
      void history.refetch()
    } catch (e) {
      toast.error(e instanceof ApiError && e.code === 'ai_not_configured' ? t('assistant.notConfigured') : (e as Error).message)
    } finally { setBusy(false) }
  }
  const decide = async (apply: boolean) => {
    if (!proposal) return
    try {
      const r = await api<{ graph: Graph }>(`/api/ai/workflows/${workflowId}/chat/${proposal.id}/${apply ? 'apply' : 'reject'}`, { method: 'POST' })
      if (apply) { onApplied(r.graph); toast.success(t('assistant.applied')) }
      setProposal(null)
      void history.refetch()
    } catch (e) { toast.error((e as Error).message) }
  }
  const d = proposal?.diff ?? {}
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border p-3 font-semibold"><Icon name="sparkles" size={16} />{t('assistant.title')}</div>
      <div className="flex-1 space-y-2 overflow-y-auto p-3" aria-live="polite">
        {(history.data ?? []).map((m) => (
          <div key={m.id} className={m.role === 'user' ? 'ml-6 rounded-lg bg-primary/15 p-2 text-sm' : 'mr-6 rounded-lg bg-surface-2 p-2 text-sm'}>
            {m.content || '—'} <Badge className="ml-1">{m.status}</Badge>
          </div>
        ))}
        {proposal && (
          <div className="rounded-lg border border-primary/50 p-3 text-sm">
            <div className="mb-2 font-medium">{t('assistant.proposal')}</div>
            <p className="mb-2 text-muted">{proposal.content}</p>
            {proposal.valid ? (
              <ul className="mb-3 space-y-1 text-xs">
                {d.added_nodes?.map((n) => <li key={`a${n}`} className="text-success">+ {t('assistant.added')}: {n}</li>)}
                {d.changed_nodes?.map((n) => <li key={`c${n}`} className="text-warning">~ {t('assistant.changed')}: {n}</li>)}
                {d.removed_nodes?.map((n) => <li key={`r${n}`} className="text-danger">− {t('assistant.removed')}: {n}</li>)}
                {!!d.added_edges?.length && <li className="text-success">+ {d.added_edges.length} {t('assistant.edges')}</li>}
                {!!d.removed_edges?.length && <li className="text-danger">− {d.removed_edges.length} {t('assistant.edges')}</li>}
              </ul>
            ) : (
              <ul role="alert" className="mb-3 space-y-1 text-xs text-danger"><li>{t('assistant.invalidProposal')}</li>
                {proposal.issues.map((i, k) => <li key={k}>• {i.message}</li>)}</ul>
            )}
            <div className="flex gap-2">
              <Button size="sm" variant="primary" disabled={!proposal.valid} onClick={() => decide(true)}>{t('assistant.apply')}</Button>
              <Button size="sm" onClick={() => decide(false)}>{t('assistant.reject')}</Button>
            </div>
          </div>
        )}
      </div>
      <div className="border-t border-border p-3">
        <Textarea aria-label={t('assistant.chatPlaceholder')} placeholder={t('assistant.chatPlaceholder')} value={text}
          onChange={(e) => setText(e.target.value)} className="font-sans" onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && text.trim()) void send() }} />
        <Button className="mt-2 w-full" variant="primary" icon="send" loading={busy} disabled={!text.trim()} onClick={send}>{t('assistant.send')}</Button>
      </div>
    </div>
  )
}
