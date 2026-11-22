import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, downloadFile } from '../api/client'
import type { Finding } from '../api/types'
import { useOpenRecheck } from '../results/FixedProjectActions'
import { toast } from '../store/toast'
import { Badge, Button } from './ui'
import { Icon } from './ui/Icon'

export interface AutofixStep { name: string; ok: boolean; detail: string }
export interface Autofix {
  id: string; run_id: string; finding_id: string; kind: 'llm' | 'deterministic'; status: 'validated' | 'rejected'
  reason: string | null; provider: string | null; model: string | null; patch: string | null; pr_url: string | null
  steps: AutofixStep[]; can_create_pr: boolean | null; pr_unavailable_reason: string | null
  proposal: { explanation?: string; requires_config?: { name: string; description: string }[]; notes?: string[]
    self_check?: { before: number; after: number; finding_gone: boolean; new_findings: string[] }; attempts?: number }
}
export interface Coverage { available: number; total: number; text: string }

export function useAutofixCoverage() {
  return useQuery({ queryKey: ['autofix-coverage'], staleTime: 10 * 60_000, queryFn: () => api<Coverage>('/api/autofix/coverage') })
}

export function PatchView({ patch }: { patch: string }) {
  return (
    <pre className="max-h-96 overflow-auto rounded-field border border-border bg-surface-2 p-2 font-mono text-xs leading-5" aria-label="patch">
      {patch.split('\n').map((l, i) => (
        <div key={i} className={clsx(
          l.startsWith('+++') || l.startsWith('---') ? 'text-muted' : l.startsWith('+') ? 'bg-soft text-primary'
            : l.startsWith('-') ? 'bg-danger-soft text-danger' : l.startsWith('@@') ? 'text-primary' : '')}>{l || ' '}</div>
      ))}
    </pre>
  )
}

function Checklist({ steps }: { steps: AutofixStep[] }) {
  const { t } = useTranslation()
  return (
    <ol className="space-y-1 text-sm" aria-label={t('autofix.checklist')}>
      {steps.map((s, i) => (
        <li key={i} className="flex items-start gap-2">
          <Icon name={s.ok ? 'check' : 'x'} size={15} className={clsx('mt-0.5 shrink-0', s.ok ? 'text-success' : 'text-danger')} />
          <span><b>{t(`autofix.step.${s.name}`, s.name)}</b>{s.detail && <span className="text-muted"> — {s.detail}</span>}</span>
        </li>
      ))}
    </ol>
  )
}

export function AutofixPanel({ runId, finding }: { runId: string; finding: Finding }) {
  const { t } = useTranslation()
  const open = useOpenRecheck()
  const qc = useQueryClient()
  const coverage = useAutofixCoverage()
  const list = useQuery({ queryKey: ['autofixes', runId], queryFn: () => api<Autofix[]>(`/api/runs/${runId}/autofixes`) })
  const latestId = (list.data ?? []).find((a) => a.finding_id === finding.id)?.id
  const detail = useQuery({ queryKey: ['autofix', latestId], enabled: !!latestId, queryFn: () => api<Autofix>(`/api/autofixes/${latestId}`) })
  const [busy, setBusy] = useState<'gen' | 'pr' | 'recheck' | null>(null)
  const af = detail.data
  const kind = finding.autofix ?? 'none'

  const generate = async () => {
    setBusy('gen')
    try {
      await api(`/api/runs/${runId}/findings/${finding.id}/autofix`, { method: 'POST', json: {} })
      await qc.invalidateQueries({ queryKey: ['autofixes', runId] })
    } catch (e) { toast.error(e instanceof ApiError ? e.message : String(e)) } finally { setBusy(null) }
  }
  const createPr = async () => {
    if (!af) return
    setBusy('pr')
    try {
      const r = await api<{ url: string; created: boolean }>(`/api/autofixes/${af.id}/pull-request`, { method: 'POST', json: {} })
      toast.success(r.created ? t('autofix.prCreated') : t('autofix.prUpdated'))
      await qc.invalidateQueries({ queryKey: ['autofix', af.id] })
    } catch (e) { toast.error(e instanceof ApiError ? e.message : String(e)) } finally { setBusy(null) }
  }

  return (
    <div className="mt-3 rounded-card border border-border bg-surface p-4" data-testid="autofix-panel">
      <div className="flex flex-wrap items-center gap-2">
        <Icon name="wrench" size={16} /><b className="text-sm">AI AutoFix</b>
        {kind === 'deterministic' && <Badge tone="primary">{t('autofix.deterministic')}</Badge>}
        {af && <Badge tone={af.status === 'validated' ? 'success' : 'danger'}>{t(`autofix.status.${af.status}`)}</Badge>}
        {coverage.data && <span className="text-xs text-muted">{t('autofix.coverage', { n: coverage.data.available, m: coverage.data.total })}</span>}
        <div className="ml-auto flex gap-2">
          {kind !== 'none' && <Button size="sm" icon="wrench" variant={af ? 'secondary' : 'primary'} loading={busy === 'gen'} onClick={generate}>
            {af ? t('autofix.retry') : t('autofix.run')}</Button>}
        </div>
      </div>
      {kind === 'none' && <p className="mt-2 text-sm text-muted">{t('autofix.none')}</p>}
      {busy === 'gen' && <p className="mt-2 text-sm text-muted">{t('autofix.working')}</p>}
      {af && (
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div className="space-y-3">
            <Checklist steps={af.steps} />
            {af.reason && <p className="text-sm text-danger">{af.reason}</p>}
            {af.kind !== 'deterministic' && af.proposal.explanation && <p className="text-sm">{af.proposal.explanation}</p>}
            {!!af.proposal.requires_config?.length && (
              <div className="rounded-field border border-warning/40 bg-warning/10 p-2 text-sm">
                <b>{t('autofix.requiresConfig')}</b>
                <ul className="mt-1 list-disc pl-5">{af.proposal.requires_config.map((r) => <li key={r.name}><code>{r.name}</code> — {r.description}</li>)}</ul>
              </div>
            )}
            {af.model && <p className="text-xs text-muted">{af.provider} · {af.model}{af.proposal.attempts && af.proposal.attempts > 1 ? ` · ${t('autofix.attempts', { n: af.proposal.attempts })}` : ''}</p>}
          </div>
          <div className="space-y-2">
            {af.patch ? <PatchView patch={af.patch} /> : null}
            {af.status === 'validated' && (
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" icon="download" onClick={() => void downloadFile(`/api/autofixes/${af.id}/patch`, `autofix-${af.finding_id}.patch`)}>
                  {t('autofix.downloadPatch')}</Button>
                <Button size="sm" icon="play" disabled={busy !== null} loading={busy === 'recheck'} onClick={async () => {
                  setBusy('recheck')
                  try {
                    const r = await api<{ run_id: string }>(`/api/autofixes/${af.id}/recheck`, { method: 'POST' })
                    open(r.run_id)
                  } catch (e) { toast.error((e as Error).message) } finally { setBusy(null) }
                }}>{t('pr.recheck')}</Button>
                {af.can_create_pr && <Button size="sm" variant="primary" icon="merge" loading={busy === 'pr'} onClick={createPr}>
                  {af.pr_url ? t('autofix.updatePr') : t('autofix.createPr')}</Button>}
                {af.pr_url && <a className="text-sm text-primary hover:underline" href={af.pr_url} target="_blank" rel="noreferrer noopener">{af.pr_url}</a>}
              </div>
            )}
            {af.status === 'validated' && !af.can_create_pr && af.pr_unavailable_reason && <p className="text-xs text-muted">{af.pr_unavailable_reason}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
