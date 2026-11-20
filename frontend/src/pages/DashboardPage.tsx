import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useProjects, useRuns, useWorkflows } from '../api/hooks'
import type { Run, Severity } from '../api/types'
import { SeverityBadge, StatusBadge } from '../components/domain'
import { Page } from '../components/layout/AppShell'
import { Button, Card, EmptyState, ErrorState, PageHeader, Skeleton } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { useLang } from '../i18n'
import { fmtNumber, fmtRelative, SEVERITIES } from '../lib/format'

const SEV_COLOR: Record<Severity, string> = {
  CRITICAL: 'rgb(var(--sev-critical))', HIGH: 'rgb(var(--sev-high))', MEDIUM: 'rgb(var(--sev-medium))', LOW: 'rgb(var(--sev-low))',
}

function Stat({ icon, label, value, loading, children }: { icon: string; label: string; value: string; loading: boolean; children?: React.ReactNode }) {
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 text-sm text-muted"><Icon name={icon} size={16} />{label}</div>
      {loading ? <Skeleton className="mt-2 h-8 w-20" /> : <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>}
      {children}
    </div>
  )
}

function latestPerWorkflow(runs: Run[]): Run[] {
  const seen = new Set<string>()
  return runs.filter((r) => r.status === 'success' && r.workflow_id && !seen.has(r.workflow_id) && seen.add(r.workflow_id))
}

export default function DashboardPage() {
  const { t } = useTranslation()
  const lang = useLang()
  const navigate = useNavigate()
  const projects = useProjects()
  const workflows = useWorkflows()
  const runs = useRuns({ limit: 200 }, 15_000)
  const weekAgo = Date.now() - 7 * 86400_000

  const sev = useMemo(() => {
    const acc: Record<Severity, number> = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 }
    for (const r of latestPerWorkflow(runs.data ?? [])) {
      for (const s of SEVERITIES) acc[s] += r.summary.by_severity?.[s] ?? 0
    }
    return acc
  }, [runs.data])

  const chart = useMemo(() => (runs.data ?? []).filter((r) => r.status === 'success').slice(0, 20).reverse().map((r) => ({
    name: new Date(r.created_at).toLocaleDateString(lang === 'en' ? 'en-GB' : 'ru-RU', { day: '2-digit', month: '2-digit' }),
    ...Object.fromEntries(SEVERITIES.map((s) => [s, r.summary.by_severity?.[s] ?? 0])),
  })), [runs.data, lang])

  const loading = runs.isLoading || workflows.isLoading || projects.isLoading
  return (
    <Page wide>
      <PageHeader title={t('dashboard.title')} actions={<>
        <Button icon="plus" variant="primary" onClick={() => navigate('/workflows?new=1')}>{t('dashboard.newWorkflow')}</Button>
        <Button icon="folder" onClick={() => navigate('/projects?new=1')}>{t('dashboard.newProject')}</Button>
      </>} />
      {runs.error && <ErrorState error={runs.error} onRetry={() => runs.refetch()} />}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat icon="folder" label={t('dashboard.projects')} value={fmtNumber(projects.data?.length, lang)} loading={loading} />
        <Stat icon="workflow" label={t('dashboard.workflows')} value={fmtNumber(workflows.data?.length, lang)} loading={loading} />
        <Stat icon="history" label={t('dashboard.runs7d')} loading={loading}
          value={fmtNumber((runs.data ?? []).filter((r) => new Date(r.created_at).getTime() >= weekAgo).length, lang)} />
        <Stat icon="shield-check" label={t('dashboard.vulns')} loading={loading} value={fmtNumber(Object.values(sev).reduce((a, b) => a + b, 0), lang)}>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {SEVERITIES.map((s) => <span key={s} className="flex items-center gap-1 text-xs"><SeverityBadge severity={s} />{sev[s]}</span>)}
          </div>
        </Stat>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title={t('dashboard.chart')} className="xl:col-span-2">
          {chart.length === 0 ? <EmptyState icon="dashboard" title={t('dashboard.noRuns')} hint={t('dashboard.noRunsHint')} /> : (
            <div className="h-72" role="img" aria-label={t('dashboard.chart')}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false} />
                  <XAxis dataKey="name" stroke="rgb(var(--muted))" fontSize={12} tickLine={false} />
                  <YAxis allowDecimals={false} stroke="rgb(var(--muted))" fontSize={12} tickLine={false} />
                  <Tooltip contentStyle={{ background: 'rgb(var(--surface))', border: '1px solid rgb(var(--border))', borderRadius: 8 }}
                    labelStyle={{ color: 'rgb(var(--fg))' }} cursor={{ fill: 'rgb(var(--surface-2))' }} />
                  <Legend itemSorter={(i) => SEVERITIES.indexOf(i.value as Severity)} formatter={(v: string) => t(`severity.${v}`)} />
                  {SEVERITIES.map((s) => <Bar key={s} dataKey={s} stackId="a" fill={SEV_COLOR[s]} name={s} maxBarSize={36} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card title={t('dashboard.quick')}>
          <div className="flex flex-col gap-2">
            <Button icon="plus" onClick={() => navigate('/workflows?new=1')}>{t('dashboard.newWorkflow')}</Button>
            <Button icon="folder" onClick={() => navigate('/projects?new=1')}>{t('dashboard.newProject')}</Button>
            <Button icon="history" onClick={() => navigate('/runs')}>{t('dashboard.openRuns')}</Button>
            <Button icon="settings" onClick={() => navigate('/settings')}>{t('nav.settings')}</Button>
          </div>
        </Card>
      </div>
      <Card title={t('dashboard.recent')} className="mt-4" padded={false}>
        {loading ? <div className="space-y-2 p-4">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-8" />)}</div>
          : (runs.data ?? []).length === 0 ? <EmptyState icon="history" title={t('dashboard.noRuns')} hint={t('dashboard.noRunsHint')} />
            : (
              <div className="overflow-x-auto">
                <table className="table-base">
                  <thead><tr><th>{t('runs.workflow')}</th><th>{t('common.status')}</th><th>{t('runs.findings')}</th><th>{t('runs.trigger')}</th><th>{t('runs.started')}</th></tr></thead>
                  <tbody>
                    {(runs.data ?? []).slice(0, 8).map((r) => (
                      <tr key={r.id}>
                        <td><Link className="font-medium text-primary hover:underline" to={`/runs/${r.id}`}>{r.workflow_name ?? '—'}</Link></td>
                        <td><StatusBadge status={r.status} /></td>
                        <td className="tabular-nums">{r.summary.total ?? '—'}</td>
                        <td>{t(`trigger.${r.trigger_type}`, r.trigger_type)}</td>
                        <td className="text-muted">{fmtRelative(r.created_at, lang)}</td>
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
