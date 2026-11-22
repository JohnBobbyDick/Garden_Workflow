import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, downloadFile } from '../api/client'
import type { Finding, Run } from '../api/types'
import type { Autofix } from '../components/autofix'
import { Chip } from '../components/chip'
import { SeverityBadge } from '../components/domain'
import { Button } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { toast } from '../store/toast'
import { useOpenRecheck } from './FixedProjectActions'

function PatchLines({ patch }: { patch: string }) {
  const lines = patch.split('\n').filter((l) => !l.startsWith('diff ') && !l.startsWith('index '))
  return (
    <pre className="max-h-72 overflow-auto rounded-field bg-surface-2 px-3 py-2 font-mono text-[12px] leading-5" aria-label="patch">
      {lines.map((l, i) => (
        <div key={i} className={clsx(l.startsWith('+++') || l.startsWith('---') || l.startsWith('@@') ? 'text-muted'
          : l.startsWith('+') ? 'text-primary' : l.startsWith('-') ? 'text-danger' : '')}>{l || ' '}</div>
      ))}
    </pre>
  )
}

/** One finding: where / why / what to do, then AI AutoFix → validation → PR or .patch → re-check with the patch. */
export function FindingDetail({ run, finding, onBack }: { run: Run; finding: Finding; onBack: () => void }) {
  const { t } = useTranslation()
  const openRecheck = useOpenRecheck()
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['autofixes', run.id], queryFn: () => api<Autofix[]>(`/api/runs/${run.id}/autofixes`) })
  const latestId = (list.data ?? []).find((a) => a.finding_id === finding.id)?.id
  const detail = useQuery({ queryKey: ['autofix', latestId], enabled: !!latestId, queryFn: () => api<Autofix>(`/api/autofixes/${latestId}`) })
  const [busy, setBusy] = useState<'gen' | 'pr' | 'recheck' | null>(null)
  const [steps, setSteps] = useState(false)
  useEffect(() => { setSteps(false) }, [finding.id])
  const af = latestId ? detail.data : undefined
  const kind = finding.autofix ?? 'none'

  const act = async (what: 'gen' | 'pr' | 'recheck') => {
    setBusy(what)
    try {
      if (what === 'gen') {
        await api(`/api/runs/${run.id}/findings/${finding.id}/autofix`, { method: 'POST', json: {} })
        await qc.invalidateQueries({ queryKey: ['autofixes', run.id] })
      } else if (what === 'pr' && af) {
        const r = await api<{ url: string; created: boolean }>(`/api/autofixes/${af.id}/pull-request`, { method: 'POST', json: {} })
        toast.success(r.created ? t('autofix.prCreated') : t('autofix.prUpdated'))
        await qc.invalidateQueries({ queryKey: ['autofix', af.id] })
      } else if (what === 'recheck' && af) {
        const r = await api<{ run_id: string }>(`/api/autofixes/${af.id}/recheck`, { method: 'POST', json: {} })
        openRecheck(r.run_id)
      }
    } catch (e) { toast.error(e instanceof ApiError ? e.message : String(e)) } finally { setBusy(null) }
  }

  return (
    <div className="space-y-4">
      <button type="button" onClick={onBack} className="flex items-center gap-1 text-[13px] font-bold text-primary hover:underline">
        <Icon name="chevron-right" size={13} className="rotate-180" />{t('results.backToList')}
      </button>
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          {finding.diff_status && <Chip tone={finding.diff_status === 'new' ? 'bad' : 'plain'}>{finding.diff_status === 'new' ? t('wf.isNew') : t('wf.isExisting')}</Chip>}
          <span className="text-[12px] text-muted">{t(`category.${finding.category}`)}</span>
        </div>
        <h3 className="mt-2 text-lg font-bold leading-snug">{finding.title}</h3>
        <p className="font-mono text-[12px] text-muted">{finding.path}:{finding.line}{finding.advisory_id ? ` · ${finding.advisory_id}` : ''}</p>
      </div>
      <p className="text-sm">{finding.description}</p>
      <p className="text-[13px] text-muted"><b>{t('run.why')}:</b> {finding.severity_reason}</p>
      {finding.remediation && <p className="text-sm"><b>{t('run.recommendation')}:</b> {finding.remediation}</p>}
      {finding.snippet && <pre className="overflow-x-auto rounded-field border border-border bg-surface-2 p-2 font-mono text-[12px]" aria-label={t('run.snippet')}>{finding.snippet}</pre>}

      {run.status === 'success' && <section className="rounded-card border border-border bg-surface p-4" aria-label="AI AutoFix">
        <div className="mb-2 flex items-center gap-2 font-bold"><Icon name="wrench" size={16} />AI AutoFix</div>
        {kind === 'none' ? <p className="text-sm text-muted">{t('autofix.none')}</p> : (
          <>
            {af?.kind !== 'deterministic' && af?.proposal.explanation && <p className="mb-2 text-sm">{af.proposal.explanation}</p>}
            {af?.patch && <PatchLines patch={af.patch} />}
            {!af && (
              <>
                <Button variant="primary" icon="wrench" loading={busy === 'gen'} onClick={() => act('gen')}>{t('pr.checkPatch')}</Button>
                <p className="mt-2 text-[13px] text-muted">{busy === 'gen' ? t('autofix.working') : t('pr.patchHint')}</p>
              </>
            )}
            {af && (
              <div className="mt-3 space-y-3">
                <p className={clsx('text-sm font-bold', af.status === 'validated' ? 'text-primary' : 'text-danger')} role="status">
                  {af.status === 'validated' ? t('pr.patchOk') : `${t('pr.patchRejected')}${af.reason ? `: ${af.reason}` : ''}`}
                </p>
                <button type="button" className="flex items-center gap-1 text-[13px] text-muted hover:text-fg" aria-expanded={steps} onClick={() => setSteps((s) => !s)}>
                  <Icon name="chevron-right" size={13} className={clsx('transition-transform', steps && 'rotate-90')} />{t('autofix.checklist')}
                </button>
                {steps && (
                  <ol className="space-y-1 text-sm">
                    {af.steps.map((s, i) => (
                      <li key={i} className="flex gap-2"><span className={s.ok ? 'text-primary' : 'text-danger'} aria-hidden="true">{s.ok ? '✓' : '×'}</span>
                        <span><b>{t(`autofix.step.${s.name}`, s.name)}</b>{s.detail && <span className="text-muted"> — {s.detail}</span>}</span></li>
                    ))}
                  </ol>
                )}
                {!!af.proposal.requires_config?.length && (
                  <div className="rounded-field bg-warning-soft p-2 text-sm">
                    <b>{t('autofix.requiresConfig')}</b>
                    <ul className="mt-1 list-disc pl-5">{af.proposal.requires_config.map((r) => <li key={r.name}><code>{r.name}</code> — {r.description}</li>)}</ul>
                  </div>
                )}
                {af.status === 'rejected' && <Button icon="wrench" loading={busy === 'gen'} onClick={() => act('gen')}>{t('autofix.retry')}</Button>}
                {af.status === 'validated' && (
                  <div className="flex flex-wrap gap-2">
                    {af.can_create_pr && <Button variant={af.pr_url ? 'secondary' : 'primary'} icon="merge" loading={busy === 'pr'} onClick={() => act('pr')}>
                      {af.pr_url ? t('autofix.updatePr') : t('autofix.createPr')}</Button>}
                    <Button icon="download" onClick={() => void downloadFile(`/api/autofixes/${af.id}/patch`, `autofix-${af.finding_id}.patch`)}>{t('autofix.downloadPatch')}</Button>
                    <Button variant={af.can_create_pr && !af.pr_url ? 'secondary' : 'primary'} icon="play" loading={busy === 'recheck'}
                      disabled={busy !== null} onClick={() => act('recheck')}>{t('pr.recheck')}</Button>
                  </div>
                )}
                {af.pr_url && <p className="text-sm">{t('pr.prCreated')} · <a className="font-bold text-primary hover:underline" href={af.pr_url} target="_blank" rel="noreferrer noopener">{af.pr_url}</a></p>}
                {af.status === 'validated' && !af.can_create_pr && af.pr_unavailable_reason && <p className="text-[13px] text-muted">{af.pr_unavailable_reason}</p>}

              </div>
            )}
          </>
        )}
      </section>}
    </div>
  )
}
