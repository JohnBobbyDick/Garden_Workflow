import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { useRuns, useWorkflows, type RunFilters } from '../api/hooks'
import { GateBadge, SeverityBadge, StatusBadge } from '../components/domain'
import { Page } from '../components/layout/AppShell'
import { Button, Card, EmptyState, ErrorState, Input, PageHeader, Select, Skeleton } from '../components/ui'
import { useLang } from '../i18n'
import { fmtDate, fmtDuration, SEVERITIES } from '../lib/format'

export default function RunsPage() {
  const { t } = useTranslation()
  const lang = useLang()
  const navigate = useNavigate()
  const [f, setF] = useState<RunFilters>({ limit: 100 })
  const runs = useRuns(f, 5000)
  const workflows = useWorkflows()
  const [picked, setPicked] = useState<string[]>([])
  const set = (k: keyof RunFilters, v: string) => setF((x) => ({ ...x, [k]: v || undefined }))
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id]))

  return (
    <Page wide>
      <PageHeader title={t('runs.title')} subtitle={t('runs.compareHint')} actions={
        <Button icon="split" variant="primary" disabled={picked.length !== 2}
          onClick={() => {
            const sorted = [...picked].sort((a, b) => {
              const ra = runs.data?.find((r) => r.id === a)?.created_at ?? ''
              const rb = runs.data?.find((r) => r.id === b)?.created_at ?? ''
              return ra.localeCompare(rb)
            })
            navigate(`/runs/compare?base=${sorted[0]}&head=${sorted[1]}`)
          }}>{t('runs.compare')}</Button>} />
      <Card className="mb-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Select aria-label={t('runs.workflow')} value={f.workflow_id ?? ''} onChange={(e) => set('workflow_id', e.target.value)}>
            <option value="">{t('runs.anyWorkflow')}</option>
            {(workflows.data ?? []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </Select>
          <Select aria-label={t('common.status')} value={f.status ?? ''} onChange={(e) => set('status', e.target.value)}>
            <option value="">{t('runs.anyStatus')}</option>
            {['queued', 'running', 'success', 'failed', 'cancelled'].map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
          </Select>
          <Select aria-label={t('runs.trigger')} value={f.trigger_type ?? ''} onChange={(e) => set('trigger_type', e.target.value)}>
            <option value="">{t('runs.anyTrigger')}</option>
            {['manual', 'schedule', 'ci', 'webhook'].map((s) => <option key={s} value={s}>{t(`trigger.${s}`)}</option>)}
          </Select>
          <Input type="date" aria-label={`${t('runs.period')} ${t('runs.from')}`} value={f.since?.slice(0, 10) ?? ''}
            onChange={(e) => set('since', e.target.value ? `${e.target.value}T00:00:00Z` : '')} />
          <Input type="date" aria-label={`${t('runs.period')} ${t('runs.to')}`} value={f.until?.slice(0, 10) ?? ''}
            onChange={(e) => set('until', e.target.value ? `${e.target.value}T23:59:59Z` : '')} />
        </div>
      </Card>
      {runs.error && <ErrorState error={runs.error} onRetry={() => runs.refetch()} />}
      <Card padded={false}>
        {runs.isLoading ? <div className="space-y-2 p-4">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-9" />)}</div>
          : !runs.data?.length ? <EmptyState icon="history" title={t('runs.empty')} />
            : (
              <div className="overflow-x-auto">
                <table className="table-base">
                  <thead>
                    <tr>
                      <th className="w-10"><span className="sr-only">{t('runs.compare')}</span></th>
                      <th>{t('runs.workflow')}</th><th>{t('common.status')}</th><th>{t('runs.findings')}</th><th>{t('runs.gate')}</th>
                      <th>{t('runs.trigger')}</th><th>{t('runs.started')}</th><th>{t('common.duration')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.data.map((r) => (
                      <tr key={r.id}>
                        <td><input type="checkbox" aria-label={`${t('runs.compare')} ${r.id}`} checked={picked.includes(r.id)} onChange={() => toggle(r.id)} /></td>
                        <td><Link className="font-medium text-primary hover:underline" to={`/runs/${r.id}`}>{r.workflow_name ?? r.id.slice(0, 8)}</Link></td>
                        <td><StatusBadge status={r.status} /></td>
                        <td>
                          <div className="flex flex-wrap items-center gap-1">
                            <span className="mr-1 tabular-nums">{r.summary.total ?? '—'}</span>
                            {SEVERITIES.filter((s) => r.summary.by_severity?.[s]).map((s) => (
                              <span key={s} className="flex items-center gap-0.5 text-xs"><SeverityBadge severity={s} />{r.summary.by_severity?.[s]}</span>
                            ))}
                          </div>
                        </td>
                        <td><GateBadge gate={r.gate} /></td>
                        <td>{t(`trigger.${r.trigger_type}`, r.trigger_type)}</td>
                        <td className="text-muted">{fmtDate(r.created_at, lang)}</td>
                        <td className="tabular-nums text-muted">{fmtDuration(r.duration_ms, lang)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
      </Card>
    </Page>
  )
}
