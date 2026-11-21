import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, withWs } from '../api/client'
import { useMe, useRuns, useWs } from '../api/hooks'
import type { Severity } from '../api/types'
import { Page } from '../components/layout/AppShell'
import { useEmbedded } from '../components/layout/embedded'
import { Delta, ScoreDisclaimer, SprintPlanCard, TrendLabel, type HistoryPoint, type PriorityItem, type SprintPlan, type Trend } from '../components/score'
import { Button, EmptyState, ErrorState, Skeleton } from '../components/ui'
import { useLang } from '../i18n'
import { fmtNumber, SEVERITIES } from '../lib/format'

interface RecentRun { id: string; workflow_name: string | null; created_at: string; status: string; score: number | null
  gate: 'pass' | 'fail' | null; verdict: string | null; commit: string | null; pr_number: string | number | null; total: number | null }
interface Dashboard {
  projects: number; workflows: number; runs: number; findings_by_severity: Record<Severity, number>
  period: '7d' | '30d'; checks: number; open_findings: number; blocking_findings: number; validated_patches: number
  findings_by_category: Record<string, number>; last_run_id: string | null; recent_runs: RecentRun[]
  score: null | { run_id: string; value: number; delta: number | null; trend: Trend; history: HistoryPoint[]; top3: PriorityItem[]; sprint_plan: SprintPlan | null }
}

const SEV_BAR: Record<Severity, string> = { CRITICAL: 'bg-sev-critical', HIGH: 'bg-sev-high', MEDIUM: 'bg-sev-medium', LOW: 'bg-sev-low' }
const SEV_COLOR: Record<Severity, string> = {
  CRITICAL: 'rgb(var(--sev-critical))', HIGH: 'rgb(var(--sev-high))', MEDIUM: 'rgb(var(--sev-medium))', LOW: 'rgb(var(--sev-low))',
}

function Panel({ title, children, className, action }: { title: React.ReactNode; children: React.ReactNode; className?: string; action?: React.ReactNode }) {
  return (
    <section className={clsx('card p-[17px]', className)}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <h2 className="text-lg font-bold">{title}</h2>{action}
      </div>
      {children}
    </section>
  )
}

function Chip({ children, tone = 'ok', to }: { children: React.ReactNode; tone?: 'ok' | 'bad'; to?: string }) {
  const cls = clsx('inline-flex h-8 shrink-0 items-center rounded-chip px-2.5 text-[13px] font-bold', tone === 'ok' ? 'bg-soft text-primary' : 'bg-danger-soft text-danger')
  return to ? <Link to={to} className={cls}>{children}</Link> : <span className={cls}>{children}</span>
}

function StatCard({ title, value, hint, loading }: { title: string; value: number | undefined; hint: string; loading: boolean }) {
  const lang = useLang()
  return (
    <div className="card h-[124px] px-[17px] pt-[15px]">
      <h2 className="text-lg font-bold">{title}</h2>
      {loading ? <Skeleton className="mt-2 h-9 w-16" /> : <div className="mt-1 text-num font-bold tabular-nums">{fmtNumber(value, lang)}</div>}
      <p className="mt-1 text-[13px] text-muted">{hint}</p>
    </div>
  )
}

function ScoreLine({ points }: { points: HistoryPoint[] }) {
  const lang = useLang()
  const fmt = (iso: string) => new Date(iso).toLocaleDateString(lang === 'en' ? 'en-GB' : 'ru-RU', { day: 'numeric', month: 'short' })
  if (points.length < 2) return <div className="h-[140px]" />
  return (
    <div>
      <div className="h-[110px]" role="img" aria-label="Security Score">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points.map((p) => ({ ...p, label: fmt(p.at) }))} margin={{ top: 6, right: 2, bottom: 6, left: 2 }}>
            <CartesianGrid horizontal vertical={false} stroke="rgb(var(--grid))" strokeDasharray="0" />
            <YAxis hide domain={['dataMin - 10', 'dataMax + 10']} />
            <XAxis hide dataKey="label" />
            <Tooltip contentStyle={{ background: 'rgb(var(--surface))', border: '1px solid rgb(var(--border))', borderRadius: 9 }} />
            <Line type="linear" dataKey="score" stroke="rgb(var(--primary))" strokeWidth={3} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-4 flex justify-between text-[13px] text-muted"><span>{fmt(points[0].at)}</span><span>{fmt(points[points.length - 1].at)}</span></div>
    </div>
  )
}

export default function DashboardPage() {
  const { t } = useTranslation()
  const lang = useLang()
  const ws = useWs()
  const me = useMe()
  const qc = useQueryClient()
  const embedded = useEmbedded()
  const navigate = useNavigate()
  const [period, setPeriod] = useState<'7d' | '30d'>('7d')
  const q = useQuery({ queryKey: ['dashboard', ws, period], refetchInterval: 15_000,
    queryFn: () => api<Dashboard>(withWs(`/api/dashboard?period=${period}`, ws)) })
  const runs = useRuns({ limit: 50 }, 15_000)
  const d = q.data
  const loading = q.isLoading
  const days = period === '7d' ? 7 : 30
  const wsName = me.data?.workspaces.find((w) => w.id === ws)?.name ?? ''
  const sev = d?.findings_by_severity
  const sevTotal = sev ? SEVERITIES.reduce((a, s) => a + (sev[s] ?? 0), 0) : 0
  const chart = useMemo(() => (runs.data ?? []).filter((r) => r.status === 'success').slice(0, 20).reverse().map((r) => ({
    name: new Date(r.created_at).toLocaleDateString(lang === 'en' ? 'en-GB' : 'ru-RU', { day: '2-digit', month: '2-digit' }),
    ...Object.fromEntries(SEVERITIES.map((s) => [s, r.summary.by_severity?.[s] ?? 0])),
  })), [runs.data, lang])

  return (
    <Page>
      {!embedded && <p className="text-[13px] font-bold text-muted">{wsName} / {t('dashboard.breadcrumb')}</p>}
      <div className={embedded ? 'flex flex-wrap items-center justify-between gap-4' : 'mt-2 flex flex-wrap items-end justify-between gap-4'}>
        <div>
          {!embedded && <h1 className="text-display">{t('dashboard.title')}</h1>}
          <p className="mt-1 text-[15px] text-muted">{t('dashboard.subtitle', { ws: wsName })}</p>
        </div>
        <label className="sr-only" htmlFor="dash-period">{t('runs.period')}</label>
        <select id="dash-period" value={period} onChange={(e) => setPeriod(e.target.value as '7d' | '30d')}
          className="mb-4 h-8 w-[184px] cursor-pointer rounded-chip border-0 bg-soft px-2.5 text-[13px] font-bold text-primary">
          <option value="7d">{t('dashboard.period7')}</option>
          <option value="30d">{t('dashboard.period30')}</option>
        </select>
      </div>
      {q.error && <div className="mt-4"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>}

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard title={t('dashboard.checks')} value={d?.checks} hint={t('dashboard.checksHint', { n: days })} loading={loading} />
        <StatCard title={t('dashboard.open')} value={d?.open_findings} hint={t('dashboard.lastCheck')} loading={loading} />
        <StatCard title={t('dashboard.blocking')} value={d?.blocking_findings} hint={t('dashboard.lastCheck')} loading={loading} />
        <StatCard title={t('dashboard.patches')} value={d?.validated_patches} hint={t('dashboard.patchesHint')} loading={loading} />
      </div>

      <div className="mt-[18px] grid grid-cols-1 gap-[18px] xl:grid-cols-[minmax(0,790fr)_minmax(0,528fr)]">
        <section className="rounded-card border border-border bg-score-bg px-5 pb-4 pt-[17px]">
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-[19px] font-bold">Security Score</h2>
            {d?.score && <Chip to={`/runs/${d.score.run_id}?tab=score`}>{t('dashboard.lastRun')}</Chip>}
          </div>
          {loading ? <Skeleton className="mt-4 h-40" /> : !d?.score ? <p className="mt-6 text-sm text-muted">{t('dashboard.noScore')}</p> : (
            <>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-score font-bold tabular-nums text-primary">{d.score.value}</span>
                <span className="text-[21px] text-muted">/ 100</span>
                <span className="ml-3"><Delta value={d.score.delta} /></span>
                <span className="ml-2"><TrendLabel trend={d.score.trend} /></span>
              </div>
              <ScoreLine points={d.score.history} />
              <div className="mt-2"><ScoreDisclaimer /></div>
            </>
          )}
        </section>
        <div className="flex flex-col gap-4">
          <Panel title={t('dashboard.priority')}>
            {!d?.score?.top3.length ? <p className="text-sm text-muted">—</p> : (
              <ul className="space-y-2.5">
                {d.score.top3.map((p) => (
                  <li key={p.finding_id} className="flex items-center justify-between gap-3">
                    <Link to={`/runs/${d.score!.run_id}?tab=findings`} className="truncate text-[15px] font-bold hover:text-primary" title={p.title}>{p.title}</Link>
                    <Chip>≈ +{p.expected_gain}</Chip>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          {d?.score ? <SprintPlanCard runId={d.score.run_id} plan={d.score.sprint_plan} priority={d.score.top3}
            onUpdated={() => void qc.invalidateQueries({ queryKey: ['dashboard'] })} /> : null}
        </div>
      </div>

      <div className="mt-[18px] grid grid-cols-1 gap-[18px] lg:grid-cols-2">
        <Panel title={t('dashboard.byType')}>
          <ul className="space-y-1">
            {(['SCA', 'SAST', 'SECRET'] as const).map((c) => (
              <li key={c} className="flex items-center justify-between"><span className="text-sm text-muted">{t(`dashboard.type${c}`)}</span>
                <Chip>{d?.findings_by_category?.[c] ?? 0}</Chip></li>
            ))}
          </ul>
        </Panel>
        <Panel title={t('dashboard.levels')}>
          {!sevTotal ? <p className="text-sm text-muted">—</p> : (
            <>
              <div className="mt-6 flex h-4 gap-[5px]" role="img" aria-label={SEVERITIES.map((s) => `${s} ${sev![s]}`).join(', ')}>
                {SEVERITIES.map((s) => sev![s] ? <div key={s} className={clsx('rounded-[4px]', SEV_BAR[s])} style={{ flexGrow: sev![s] }} /> : null)}
              </div>
              <div className="mt-5 grid grid-cols-4 text-sm text-muted">
                {SEVERITIES.map((s) => <span key={s}>{s.charAt(0) + s.slice(1).toLowerCase()} {sev![s]}</span>)}
              </div>
            </>
          )}
        </Panel>
      </div>

      <Panel title={t('dashboard.history')} className="mt-[18px]">
        {!d?.recent_runs.length ? <EmptyState icon="history" title={t('dashboard.noRuns')} hint={t('dashboard.noRunsHint')} /> : (
          <ul className="space-y-3">
            {d.recent_runs.slice(0, 6).map((r) => {
              const failed = r.status !== 'success' || r.verdict === 'FAIL' || r.gate === 'fail'
              const date = new Date(r.created_at).toLocaleDateString(lang === 'en' ? 'en-GB' : 'ru-RU', { day: 'numeric', month: 'short' })
              return (
                <li key={r.id} className="flex items-center justify-between gap-3">
                  <Link to={`/runs/${r.id}`} className="truncate text-[15px] font-bold hover:text-primary">
                    {[r.pr_number ? `PR #${r.pr_number}` : r.workflow_name, date, r.commit].filter(Boolean).join(' · ')}
                  </Link>
                  <Chip tone={failed ? 'bad' : 'ok'} to={`/runs/${r.id}`}>
                    {r.status !== 'success' ? t(`status.${r.status}`) : r.verdict || r.gate ? (failed ? 'FAIL' : 'PASS') : t('status.success')}{r.score !== null ? ` · ${r.score}` : ''}
                  </Chip>
                </li>
              )
            })}
          </ul>
        )}
      </Panel>

      <div className="mt-[18px] grid grid-cols-1 gap-[18px] xl:grid-cols-3">
        <Panel title={t('dashboard.chart')} className="xl:col-span-2">
          {chart.length === 0 ? <EmptyState icon="dashboard" title={t('dashboard.noRuns')} /> : (
            <div className="h-64" role="img" aria-label={t('dashboard.chart')}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                  <CartesianGrid strokeDasharray="0" stroke="rgb(var(--grid))" vertical={false} />
                  <XAxis dataKey="name" stroke="rgb(var(--muted))" fontSize={12} tickLine={false} />
                  <YAxis allowDecimals={false} stroke="rgb(var(--muted))" fontSize={12} tickLine={false} />
                  <Tooltip contentStyle={{ background: 'rgb(var(--surface))', border: '1px solid rgb(var(--border))', borderRadius: 9 }} cursor={{ fill: 'rgb(var(--soft))' }} />
                  {SEVERITIES.map((s) => <Bar key={s} dataKey={s} stackId="a" fill={SEV_COLOR[s]} name={t(`severity.${s}`)} maxBarSize={36} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>
        <Panel title={t('dashboard.overview')}>
          <dl className="mb-4 space-y-1 text-sm">
            {([['projects', d?.projects], ['workflows', d?.workflows], ['runs', d?.runs]] as const).map(([k, v]) => (
              <div key={k} className="flex justify-between"><dt className="text-muted">{t(`nav.${k}`)}</dt><dd className="font-bold tabular-nums">{fmtNumber(v, lang)}</dd></div>
            ))}
          </dl>
          <div className="flex flex-col gap-2">
            <Button icon="plus" variant="primary" onClick={() => navigate('/workflows?new=1')}>{t('dashboard.newWorkflow')}</Button>
            <Button icon="folder" onClick={() => navigate('/projects?new=1')}>{t('dashboard.newProject')}</Button>
            <Button icon="history" onClick={() => navigate('/runs')}>{t('dashboard.openRuns')}</Button>
          </div>
        </Panel>
      </div>
    </Page>
  )
}
