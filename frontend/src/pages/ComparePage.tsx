import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Run, Severity } from '../api/types'
import { SeverityBadge, StatusBadge } from '../components/domain'
import { Page } from '../components/layout/AppShell'
import { Card, EmptyState, ErrorState, PageHeader, Skeleton } from '../components/ui'
import { useLang } from '../i18n'
import { fmtDate } from '../lib/format'

interface Brief { id: string; category: string; class: string; severity: Severity; title: string; path: string; line: number;
  group?: string; artifact?: string; version?: string; advisory_id?: string }
interface CompareResult { base: Run; head: Run; new: Brief[]; fixed: Brief[]; unchanged: Brief[];
  severity_changed: { finding: Brief; from: Severity; to: Severity }[]; by_category: Record<string, Record<string, number>> }

function List({ items, tone }: { items: Brief[]; tone: string }) {
  const { t } = useTranslation()
  if (!items.length) return <p className="text-sm text-muted">{t('common.none')}</p>
  return (
    <ul className="space-y-1.5 text-sm">
      {items.map((f) => (
        <li key={f.id} className={`flex flex-wrap items-center gap-2 border-l-2 pl-2 ${tone}`}>
          <SeverityBadge severity={f.severity} /><span className="font-medium">{f.title}</span>
          <span className="font-mono text-xs text-muted">{f.category === 'SCA' ? `${f.group}:${f.artifact}:${f.version} ${f.advisory_id}` : `${f.path}:${f.line}`}</span>
        </li>
      ))}
    </ul>
  )
}

export default function ComparePage() {
  const { t } = useTranslation()
  const lang = useLang()
  const [p] = useSearchParams()
  const base = p.get('base')
  const head = p.get('head')
  const q = useQuery({ queryKey: ['compare', base, head], enabled: !!base && !!head,
    queryFn: () => api<CompareResult>(`/api/runs/compare?base=${base}&head=${head}`) })
  if (!base || !head) return <Page><EmptyState title={t('runs.compareHint')} /></Page>
  return (
    <Page wide>
      <PageHeader title={t('run.compareTitle')} />
      {q.error && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {q.isLoading || !q.data ? <Skeleton className="h-64" /> : (
        <>
          <div className="mb-4 grid gap-3 md:grid-cols-2">
            {(['base', 'head'] as const).map((k) => (
              <div key={k} className="card p-3 text-sm">
                <div className="text-xs uppercase text-muted">{t(`run.${k}`)}</div>
                <Link className="font-medium text-primary hover:underline" to={`/runs/${q.data[k].id}`}>{q.data[k].workflow_name}</Link>
                <div className="mt-1 flex items-center gap-2 text-muted"><StatusBadge status={q.data[k].status} />{fmtDate(q.data[k].created_at, lang)} · {q.data[k].summary.total ?? 0}</div>
              </div>
            ))}
          </div>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            {[['newTotal', q.data.new.length, 'text-danger'], ['fixedTotal', q.data.fixed.length, 'text-success'],
              ['unchanged', q.data.unchanged.length, 'text-muted'], ['severityChanged', q.data.severity_changed.length, 'text-warning']].map(([k, n, c]) => (
              <div key={k as string} className="card p-3"><div className="text-xs text-muted">{t(`run.${k}`)}</div><div className={`text-2xl font-semibold ${c}`}>{n as number}</div></div>
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={t('run.fixedTotal')}><List items={q.data.fixed} tone="border-success" /></Card>
            <Card title={t('run.newTotal')}><List items={q.data.new} tone="border-danger" /></Card>
            <Card title={t('run.severityChanged')}>
              {q.data.severity_changed.length ? <ul className="space-y-1 text-sm">{q.data.severity_changed.map((c) => (
                <li key={c.finding.id}>{c.finding.title}: <SeverityBadge severity={c.from} /> → <SeverityBadge severity={c.to} /></li>))}</ul>
                : <p className="text-sm text-muted">{t('common.none')}</p>}
            </Card>
            <Card title={t('run.categories')}>
              <table className="table-base"><thead><tr><th /><th>{t('run.newTotal')}</th><th>{t('run.fixedTotal')}</th><th>{t('run.unchanged')}</th></tr></thead>
                <tbody>{Object.entries(q.data.by_category).map(([c, v]) => (
                  <tr key={c}><td>{t(`category.${c}`)}</td><td>{v.new}</td><td>{v.fixed}</td><td>{v.unchanged}</td></tr>))}</tbody></table>
            </Card>
          </div>
        </>
      )}
    </Page>
  )
}
