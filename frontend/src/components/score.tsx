import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, ApiError } from '../api/client'
import { useWs } from '../api/hooks'
import type { Severity } from '../api/types'
import { useLang } from '../i18n'
import { toast } from '../store/toast'
import { SeverityBadge } from './domain'
import { Badge, Button, Card, EmptyState, Skeleton } from './ui'
import { Icon } from './ui/Icon'

export interface PriorityItem {
  rank: number; finding_id: string; title: string; class: string; category: string; severity: Severity; path: string
  line: number; group?: string | null; artifact?: string | null; version?: string | null; advisory_id?: string | null
  novelty: 'new' | 'existing'; fix_effort: number; fix_effort_source: 'ai' | 'default'; effort_words: string
  priority: number; expected_gain: number; cumulative_gain: number
}
export interface SprintPlan {
  id: string; ai_generated: boolean; provider?: string | null; model?: string | null; created_at: string
  plan: { summary: string; plan: { finding_id: string; action: string; reason: string }[]
    defer: { finding_id: string; reason: string }[]; projected_score: number; priority?: PriorityItem[] }
  validation: { corrected_numbers?: boolean; llm_projected_score?: number; dropped_ids?: string[]; hallucinated_ids?: string[]; error?: string }
}
export interface HistoryPoint { run_id: string; at: string; score: number; delta: number | null; commit?: string | null; verdict?: string | null }
export interface Marker { run_id: string; at: string; kind: 'scanner_set' | 'formula'; value: string }
export interface Trend { enough_data: boolean; slope_per_week: number | null; points: number }
export interface RunScore {
  run_id: string; score: number; delta: number | null; loc: number | null; penalty: number; scale: number
  breakdown: { by_severity: Record<Severity, { count: number; penalty: number }>; by_category: Record<string, number>; counted: number; ignored: number; new: number }
  formula_version: string; scanner_set: string; priority: PriorityItem[]; sprint_plan: SprintPlan | null; note: string
}

export function scoreTone(v: number): string {
  return v >= 80 ? 'text-success' : v >= 50 ? 'text-warning' : 'text-danger'
}

export function Delta({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-xs text-muted">—</span>
  return <span className={clsx('text-sm font-semibold tabular-nums', value > 0 ? 'text-success' : value < 0 ? 'text-danger' : 'text-muted')}>
    {value > 0 ? `▲ +${value}` : value < 0 ? `▼ ${value}` : '±0'}</span>
}

export function TrendLabel({ trend }: { trend: Trend }) {
  const { t } = useTranslation()
  if (!trend.enough_data || trend.slope_per_week === null) return <span className="text-xs text-muted">{t('score.notEnough')}</span>
  const s = trend.slope_per_week
  return <span className={clsx('text-xs', s > 0 ? 'text-success' : s < 0 ? 'text-danger' : 'text-muted')}>
    {s >= 0 ? '📈' : '📉'} {s > 0 ? '+' : ''}{s.toFixed(1)}/{t('score.week')}</span>
}

export function ScoreChart({ points, markers }: { points: HistoryPoint[]; markers: Marker[] }) {
  const { t } = useTranslation()
  const lang = useLang()
  const fmt = (iso: string) => new Date(iso).toLocaleDateString(lang === 'en' ? 'en-GB' : 'ru-RU', { day: '2-digit', month: '2-digit' })
  const data = points.map((p) => ({ ...p, label: `${fmt(p.at)} ${p.commit ? p.commit.slice(0, 7) : ''}`.trim() }))
  if (!data.length) return <EmptyState icon="dashboard" title={t('score.noHistory')} />
  return (
    <div className="h-48" role="img" aria-label={t('score.history')}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false} />
          <XAxis dataKey="label" stroke="rgb(var(--muted))" fontSize={11} tickLine={false} />
          <YAxis domain={[0, 100]} stroke="rgb(var(--muted))" fontSize={11} tickLine={false} />
          <Tooltip contentStyle={{ background: 'rgb(var(--surface))', border: '1px solid rgb(var(--border))', borderRadius: 8 }}
            labelStyle={{ color: 'rgb(var(--fg))' }} />
          {markers.map((m) => {
            const p = data.find((d) => d.run_id === m.run_id)
            return p ? <ReferenceLine key={m.run_id + m.kind} x={p.label} stroke="rgb(var(--warning))" strokeDasharray="4 3"
              label={{ value: t(`score.marker.${m.kind}`), fontSize: 10, fill: 'rgb(var(--warning))', position: 'insideTopLeft' }} /> : null
          })}
          <Line type="monotone" dataKey="score" name="Score" stroke="rgb(var(--primary))" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function where(i: PriorityItem) {
  return i.category === 'SCA' && i.group ? `${i.group}:${i.artifact}:${i.version}${i.advisory_id ? ` · ${i.advisory_id}` : ''}` : `${i.path}:${i.line}`
}

export function PriorityTable({ items, limit }: { items: PriorityItem[]; limit?: number }) {
  const { t } = useTranslation()
  const rows = limit ? items.slice(0, limit) : items
  if (!rows.length) return <EmptyState icon="shield-check" title={t('score.nothingToFix')} />
  return (
    <div className="overflow-x-auto rounded-card border border-border">
      <table className="table-base">
        <thead><tr><th>#</th><th>{t('score.finding')}</th><th>{t('run.severity')}</th><th>{t('score.whyNow')}</th><th className="text-right">{t('score.gain')}</th></tr></thead>
        <tbody>
          {rows.map((i) => (
            <tr key={i.finding_id}>
              <td className="tabular-nums text-muted">{i.rank}</td>
              <td><div className="font-medium">{i.title}</div><div className="font-mono text-xs text-muted">{where(i)}</div></td>
              <td><SeverityBadge severity={i.severity} /></td>
              <td className="whitespace-nowrap text-xs" title={`${t('score.effort')} ${i.fix_effort}/5 · ${i.fix_effort_source === 'ai' ? 'AI' : t('score.default')}`}>
                {i.novelty === 'new' ? <Badge tone="danger">{t('run.diffNew')}</Badge> : <Badge>{t('score.old')}</Badge>}{' '}
                {i.effort_words} <span className="text-muted">· {i.fix_effort}/5{i.fix_effort_source === 'ai' ? ' AI' : ''}</span>
              </td>
              <td className="text-right font-semibold tabular-nums text-success">+{i.expected_gain}
                {i.rank > 1 && <div className="whitespace-nowrap text-[11px] font-normal text-muted">{t('score.cumulative')} +{i.cumulative_gain}</div>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function SprintPlanCard({ runId, plan, priority, onUpdated }: { runId: string; plan: SprintPlan | null; priority: PriorityItem[]; onUpdated: () => void }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const byId = Object.fromEntries([...(plan?.plan.priority ?? []), ...priority].map((p) => [p.finding_id, p]))
  const generate = async () => {
    setBusy(true)
    try { await api(`/api/runs/${runId}/sprint-plan`, { method: 'POST', json: {} }); onUpdated() }
    catch (e) { toast.error(e instanceof ApiError ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <Card title={<span className="flex items-center gap-2"><Icon name="sparkles" size={16} />{t('score.sprintPlan')}</span>}
      actions={<Button size="sm" icon="sparkles" loading={busy} onClick={generate}>{plan ? t('score.regenerate') : t('score.makePlan')}</Button>}>
      {!plan ? <p className="text-sm text-muted">{t('score.planHint')}</p> : (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={plan.ai_generated ? 'primary' : 'warning'}>{plan.ai_generated ? `AI · ${plan.model ?? ''}` : t('score.noAi')}</Badge>
            <span>{t('score.projected')}: <b className={scoreTone(plan.plan.projected_score)}>{plan.plan.projected_score}</b></span>
            {plan.validation.corrected_numbers && <Badge tone="warning" title={`LLM: ${plan.validation.llm_projected_score}`}>{t('score.corrected')}</Badge>}
            {!!plan.validation.hallucinated_ids?.length && <Badge tone="danger">{t('score.removedIds', { n: plan.validation.hallucinated_ids.length })}</Badge>}
          </div>
          <p>{plan.plan.summary}</p>
          <ol className="list-decimal space-y-1 pl-5">
            {plan.plan.plan.map((p) => <li key={p.finding_id}><b>{byId[p.finding_id]?.title ?? p.finding_id}</b> — {p.action}<div className="text-xs text-muted">{p.reason}</div></li>)}
          </ol>
          {!!plan.plan.defer.length && <div className="text-xs text-muted">{t('score.deferred')}: {plan.plan.defer.map((d) => byId[d.finding_id]?.title ?? d.finding_id).join(', ')}</div>}
        </div>
      )}
    </Card>
  )
}

export function ScoreDisclaimer() {
  const { t } = useTranslation()
  return <p className="text-xs text-muted"><Icon name="info" size={13} className="mr-1 inline" />{t('score.disclaimer')}</p>
}

export function RunScoreTab({ runId }: { runId: string }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['run-score', runId], retry: false, queryFn: () => api<RunScore>(`/api/runs/${runId}/score`) })
  if (q.isLoading) return <Skeleton className="h-48" />
  if (!q.data) return <EmptyState icon="dashboard" title={t('score.none')} />
  const s = q.data
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <div className="text-sm text-muted">Security Score</div>
          <div className="flex items-baseline gap-3"><span className={clsx('text-5xl font-bold tabular-nums', scoreTone(s.score))}>{s.score}</span>
            <span className="text-muted">/100</span><Delta value={s.delta} /></div>
          <div className="mt-2 font-mono text-xs text-muted">penalty {s.penalty} · S {s.scale} · LOC {s.loc ?? 0} · v{s.formula_version}</div>
          <div className="mt-1 text-xs text-muted">{s.scanner_set}</div>
        </Card>
        <Card title={t('score.breakdown')} className="lg:col-span-2">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as Severity[]).map((k) => (
              <div key={k} className="rounded-field bg-surface-2 p-2 text-sm"><SeverityBadge severity={k} />
                <div className="mt-1 tabular-nums">{t('score.pcs', { n: s.breakdown.by_severity[k].count })} · <span className="text-danger">−{s.breakdown.by_severity[k].penalty}</span></div></div>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">{t('score.counted', { counted: s.breakdown.counted, ignored: s.breakdown.ignored, fresh: s.breakdown.new })}</p>
        </Card>
      </div>
      <ScoreDisclaimer />
      <Card title={t('score.priority')}><PriorityTable items={s.priority} /></Card>
      <SprintPlanCard runId={runId} plan={s.sprint_plan} priority={s.priority} onUpdated={() => void qc.invalidateQueries({ queryKey: ['run-score', runId] })} />
    </div>
  )
}

export function DashboardScoreCard() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const ws = useWs()
  const q = useQuery({ queryKey: ['dashboard', ws], refetchInterval: 15_000,
    queryFn: () => api<{ score: null | { run_id: string; value: number; delta: number | null; trend: Trend; history: HistoryPoint[]; markers: Marker[]
      top3: PriorityItem[]; sprint_plan: SprintPlan | null } }>(ws ? `/api/dashboard?workspace_id=${ws}` : '/api/dashboard') })
  const sc = q.data?.score
  return (
    <Card title="Security Score" className="mt-4" actions={sc ? <Link className="text-sm text-primary" to={`/runs/${sc.run_id}?tab=score`}>{t('score.details')}</Link> : null}>
      {q.isLoading ? <Skeleton className="h-40" /> : !sc ? <EmptyState icon="dashboard" title={t('score.none')} hint={t('dashboard.noRunsHint')} /> : (
        <div className="grid gap-4 xl:grid-cols-3">
          <div>
            <div className="flex items-baseline gap-3"><span className={clsx('text-5xl font-bold tabular-nums', scoreTone(sc.value))}>{sc.value}</span>
              <span className="text-muted">/100</span><Delta value={sc.delta} /></div>
            <div className="mt-1"><TrendLabel trend={sc.trend} /></div>
            <div className="mt-3"><ScoreDisclaimer /></div>
          </div>
          <div className="xl:col-span-2"><ScoreChart points={sc.history} markers={sc.markers} /></div>
          <div className="xl:col-span-3"><div className="label mb-2">{t('score.top3')}</div><PriorityTable items={sc.top3} /></div>
          <div className="xl:col-span-3"><SprintPlanCard runId={sc.run_id} plan={sc.sprint_plan} priority={sc.top3} onUpdated={() => void qc.invalidateQueries({ queryKey: ['dashboard'] })} /></div>
        </div>
      )}
    </Card>
  )
}
