import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import clsx from 'clsx'
import { Fragment, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError, downloadFile } from '../api/client'
import { useAiReport, useCatalog, useInvalidate, useRun, useRunFindings } from '../api/hooks'
import type { AIReportResponse, Finding, Run } from '../api/types'
import { GateBadge, SeverityBadge, StatusBadge } from '../components/domain'
import { Page } from '../components/layout/AppShell'
import { AutofixPanel } from '../components/autofix'
import { RunScoreTab } from '../components/score'
import { Badge, Button, Card, CopyButton, DiffView, EmptyState, ErrorState, Input, PageHeader, Select, Skeleton, Tabs } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { EditorContext } from '../editor/EditorContext'
import { graphToFlow } from '../editor/graphModel'
import { NodeCard } from '../editor/NodeCard'
import { useRunEvents } from '../editor/useRunEvents'
import { useLang } from '../i18n'
import { fmtDate, fmtDuration, SEVERITIES } from '../lib/format'
import { toast } from '../store/toast'

const nodeTypes = { aisw: NodeCard }
type Tab = 'graph' | 'findings' | 'score' | 'ai' | 'logs' | 'artifacts'

function where(f: Finding) {
  return f.category === 'SCA' ? `${f.group}:${f.artifact}:${f.version}` : `${f.path}:${f.line}${f.end_line && f.end_line !== f.line ? `–${f.end_line}` : ''}`
}

function RunGraph({ run, live }: { run: Run; live: ReturnType<typeof useRunEvents> }) {
  const catalog = useCatalog()
  const lang = useLang()
  const flow = useMemo(() => graphToFlow(run.graph_snapshot ?? { schema_version: 1, nodes: [], edges: [] }), [run.graph_snapshot])
  const status = Object.fromEntries((run.nodes ?? []).map((n) => [n.node_id, n]))
  const nodes = flow.nodes.map((n) => {
    const ln = live.nodes[n.id]
    return { ...n, draggable: false, data: { ...n.data, status: ln?.status ?? status[n.id]?.status ?? 'pending',
      durationMs: ln?.durationMs ?? status[n.id]?.duration_ms, summary: ln?.summary ?? status[n.id]?.output_summary?.summary } }
  })
  const edges = flow.edges.map((e) => {
    const d = live.edges[e.id]
    const tgt = live.nodes[e.target]?.status ?? status[e.target]?.status
    return { ...e, type: 'smoothstep', label: d ? (d.count ?? '✓') : undefined,
      className: d && live.status === 'running' ? 'edge-active' : tgt === 'skipped' ? 'edge-skipped' : '' }
  })
  return (
    <EditorContext.Provider value={{ catalog: catalog.data?.nodes ?? [], lang, runMode: true }}>
      <div className="h-[520px] overflow-hidden rounded-card border border-border">
        <ReactFlowProvider>
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView nodesConnectable={false} nodesDraggable={false} elementsSelectable={false}>
            <Background variant={BackgroundVariant.Dots} gap={16} size={1.2} color="rgb(var(--border))" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </ReactFlowProvider>
      </div>
    </EditorContext.Provider>
  )
}

function VerdictBadge({ verdict }: { verdict: Record<string, unknown> | null }) {
  const { t } = useTranslation()
  const v = verdict?.verdict as string | undefined
  if (v !== 'PASS' && v !== 'FAIL') return null
  const reason = verdict?.would_fail_reason as string | undefined
  return <Badge tone={v === 'PASS' ? 'success' : 'danger'} title={`${t('run.verdictNew')}: ${verdict?.new_count ?? 0} · ${t('run.diffExisting')}: ${verdict?.existing_count ?? 0}${reason ? ` · ${reason}` : ''}`}>
    diff: {v}</Badge>
}

function FindingsTable({ findings, runId }: { findings: Finding[]; runId: string }) {
  const { t } = useTranslation()
  const [cat, setCat] = useState('')
  const [sev, setSev] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<'severity' | 'path'>('severity')
  const [open, setOpen] = useState<string | null>(null)
  const hasDiff = findings.some((f) => f.diff_status)
  const [diff, setDiff] = useState<'all' | 'new' | 'existing'>('all')
  const rank = (s: string) => SEVERITIES.indexOf(s as never)
  const counts = { new: findings.filter((f) => f.diff_status === 'new').length, existing: findings.filter((f) => f.diff_status === 'existing').length }
  const list = findings.filter((f) => (diff === 'all' || f.diff_status === diff) && (!cat || f.category === cat) && (!sev || f.severity === sev)
    && (!q || `${f.title} ${f.class} ${f.path} ${f.advisory_id ?? ''}`.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => (sort === 'severity' ? rank(a.severity) - rank(b.severity) || a.path.localeCompare(b.path) : a.path.localeCompare(b.path) || a.line - b.line))
  return (
    <>
      {hasDiff && (
        <div className="mb-3"><Tabs label={t('run.diffFilter')} value={diff} onChange={setDiff} tabs={[
          { id: 'new', label: `${t('run.diffNew')} (${counts.new})` }, { id: 'existing', label: `${t('run.diffExisting')} (${counts.existing})` },
          { id: 'all', label: `${t('common.all')} (${findings.length})` }]} /></div>
      )}
      <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-4">
        <Select aria-label={t('run.allCategories')} value={cat} onChange={(e) => setCat(e.target.value)}>
          <option value="">{t('run.allCategories')}</option>
          {['SECRET', 'SAST', 'SCA'].map((c) => <option key={c} value={c}>{t(`category.${c}`)}</option>)}
        </Select>
        <Select aria-label={t('run.allSeverities')} value={sev} onChange={(e) => setSev(e.target.value)}>
          <option value="">{t('run.allSeverities')}</option>
          {SEVERITIES.map((s) => <option key={s} value={s}>{t(`severity.${s}`)}</option>)}
        </Select>
        <Select aria-label="sort" value={sort} onChange={(e) => setSort(e.target.value as 'severity' | 'path')}>
          <option value="severity">{t('run.sortSeverity')}</option><option value="path">{t('run.sortPath')}</option>
        </Select>
        <Input placeholder={t('common.search')} aria-label={t('common.search')} value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {!list.length ? <EmptyState icon="shield-check" title={t('run.noFindings')} /> : (
        <div className="overflow-x-auto rounded-card border border-border">
          <table className="table-base">
            <thead><tr><th>{t('run.severity')}</th><th>{t('run.category')}</th><th>{t('run.class')}</th><th>{t('run.location')}</th><th>{t('run.confidence')}</th></tr></thead>
            <tbody>
              {list.map((f) => (
                <Fragment key={f.id}>
                  <tr className={clsx('cursor-pointer', !f.official && 'opacity-70')} onClick={() => setOpen(open === f.id ? null : f.id)}
                    aria-expanded={open === f.id} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setOpen(open === f.id ? null : f.id)}>
                    <td><SeverityBadge severity={f.severity} /></td>
                    <td><Badge>{f.category}</Badge></td>
                    <td><div className="font-medium">{f.title}</div><div className="font-mono text-xs text-muted">{f.class}{f.diff_status === 'new' && <Badge tone="danger" className="ml-1">{t('run.diffNew')}</Badge>}</div></td>
                    <td className="font-mono text-xs">{where(f)}{f.advisory_id && <div className="text-muted">{f.advisory_id}</div>}</td>
                    <td className="tabular-nums">{Math.round(f.confidence * 100)}%{!f.official && <div className="text-[11px] text-warning">{t('run.lowConfidence')}</div>}</td>
                  </tr>
                  {open === f.id && (
                    <tr><td colSpan={5} className="bg-surface-2/50">
                      <div className="grid gap-3 p-2 md:grid-cols-2">
                        <div>
                          <p className="mb-2 text-sm">{f.description}</p>
                          <p className="text-xs text-muted"><b>{t('run.why')}:</b> {f.severity_reason}</p>
                          {f.cwe && <p className="text-xs text-muted">{f.cwe}</p>}
                          {f.alternate_locations?.length ? <p className="mt-1 text-xs text-muted">{f.alternate_locations.map((l) => `${l.path}:${l.line}`).join(', ')}</p> : null}
                          {f.fixed_versions?.length ? <p className="mt-1 text-xs"><b>{t('run.fixedIn')}:</b> {f.fixed_versions.join(', ')}</p> : null}
                          {f.diff_status === 'new' && (f.diff_hunk || f.introduced_in_commit) && (
                            <p className="mt-1 font-mono text-xs text-muted">{f.diff_hunk}{f.introduced_in_commit && <> · {t('run.commit')} {f.introduced_in_commit.slice(0, 7)}</>}{f.author && <> · {f.author}</>}</p>
                          )}
                          <p className="mt-2 text-sm"><b>{t('run.recommendation')}:</b> {f.remediation}</p>
                        </div>
                        {f.snippet && <div><div className="label">{t('run.snippet')}</div><pre className="overflow-x-auto rounded-field border border-border bg-surface p-2 font-mono text-xs">{f.snippet}</pre></div>}
                      </div>
                      <AutofixPanel runId={runId} finding={f} />
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

export function TrustIndicator({ ai }: { ai: AIReportResponse }) {
  const { t } = useTranslation()
  if (!ai.ai_generated) {
    return <div className="rounded-field border border-warning/40 bg-warning/10 p-3 text-sm text-warning"><Icon name="info" size={15} className="mr-1 inline" />{t('run.deterministic')}{ai.error ? ` — ${ai.error}` : ''}</div>
  }
  const m = ai.validation.metrics as Record<string, number & string[]>
  const total = Number(m.total_items ?? 0)
  const valid = Number(m.valid_items ?? 0)
  const pct = total ? Math.round((valid / total) * 100) : 100
  const tone = ai.validation.flags.hallucinated_ids || pct < 80 ? 'warning' : 'success'
  return (
    <div className={clsx('rounded-field border p-3 text-sm', tone === 'success' ? 'border-success/40 bg-success/10' : 'border-warning/40 bg-warning/10')}>
      <div className="mb-1 flex items-center gap-2 font-semibold">
        <Icon name="shield-check" size={16} />{t('run.trust')}: {pct}%
        <span className="font-normal text-muted">· {t('run.model')}: {ai.provider}/{ai.model}</span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <span>{t('run.accepted', { a: valid, b: total })}</span>
        <span>{t('run.dropped', { n: Number(m.dropped ?? 0) })}</span>
        <span>{t('run.fixesKept', { n: Number(m.fixes_kept ?? 0) })}</span>
        {ai.validation.flags.hallucinated_ids && <span className="text-warning">{t('run.hallucinated', { ids: (m.hallucinated_ids as unknown as string[]).join(', ') })}</span>}
      </div>
    </div>
  )
}

export function AiReport({ runId, findings }: { runId: string; findings: Finding[] }) {
  const { t } = useTranslation()
  const ai = useAiReport(runId)
  if (ai.isLoading) return <Skeleton className="h-40" />
  if (ai.error instanceof ApiError && ai.error.status === 404) return <EmptyState icon="sparkles" title={t('run.noAi')} />
  if (ai.error) return <ErrorState error={ai.error} onRetry={() => ai.refetch()} />
  const r = ai.data!
  const byId = Object.fromEntries(findings.map((f) => [f.id, f]))
  return (
    <div className="space-y-4">
      <TrustIndicator ai={r} />
      <Card title={t('run.summary')}><p className="text-sm leading-relaxed">{r.report.summary}</p></Card>
      {r.report.priority_order.length > 0 && (
        <Card title={t('run.priority')}>
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {r.report.priority_order.filter((id) => byId[id]).slice(0, 15).map((id) => (
              <li key={id}><SeverityBadge severity={byId[id].severity} /> {byId[id].title} <span className="font-mono text-xs text-muted">{where(byId[id])}</span></li>
            ))}
          </ol>
        </Card>
      )}
      {r.report.findings.filter((i) => byId[i.finding_id]).map((i) => {
        const f = byId[i.finding_id]
        return (
          <Card key={i.finding_id} title={<span className="flex items-center gap-2"><SeverityBadge severity={f.severity} />{f.title}
            <span className="font-mono text-xs font-normal text-muted">{where(f)}</span>{i.source === 'deterministic' && <Badge>{t('run.noAiBadge')}</Badge>}</span>}>
            <p className="text-sm">{i.explanation}</p>
            <p className="mt-2 text-sm"><b>{t('run.impact')}:</b> {i.impact}</p>
            <div className="mt-2 text-sm"><b>{t('run.steps')}:</b><ul className="mt-1 list-disc pl-5">{i.remediation_steps.map((s, k) => <li key={k}>{s}</li>)}</ul></div>
            {i.safe_version && <p className="mt-2 text-sm"><b>{t('run.safeVersion')}:</b> <code>{i.safe_version}</code></p>}
            {i.fix && <div className="mt-3"><div className="mb-1 flex justify-end"><CopyButton text={i.fix.after} label={t('run.copyFix')} /></div>
              <DiffView before={i.fix.before} after={i.fix.after} path={`${i.fix.path}:${i.fix.start_line}-${i.fix.end_line}`} /></div>}
          </Card>
        )
      })}
      {r.report.global_recommendations.length > 0 && <Card title={t('run.global')}><ul className="list-disc pl-5 text-sm">{r.report.global_recommendations.map((g, k) => <li key={k}>{g}</li>)}</ul></Card>}
      <Card title={t('run.checks')}>
        <ul className="space-y-1 text-xs">
          {r.validation.checks.map((c, k) => (
            <li key={k} className="flex gap-2"><Badge tone={c.status === 'ok' ? 'success' : c.status === 'failed' ? 'danger' : 'warning'}>{c.status}</Badge>
              <span className="font-mono">{c.check}</span><span className="text-muted">{c.details}</span></li>
          ))}
        </ul>
      </Card>
    </div>
  )
}

export default function RunDetailsPage() {
  const { t } = useTranslation()
  const lang = useLang()
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) ?? 'findings'
  const run = useRun(id, true)
  const done = !!run.data && ['success', 'failed', 'cancelled'].includes(run.data.status)
  const findings = useRunFindings(id, done)
  const live = useRunEvents(id ?? null)
  const invalidate = useInvalidate()
  if (run.error) return <Page><ErrorState error={run.error} onRetry={() => run.refetch()} /></Page>
  if (!run.data) return <Page><Skeleton className="h-10 w-1/3" /><Skeleton className="mt-4 h-64" /></Page>
  const r = run.data
  const logs = Object.entries(live.nodes).flatMap(([nid, n]) => n.logs.map((l) => ({ ...l, node: nid }))).sort((a, b) => a.at.localeCompare(b.at))
  const cancel = async () => {
    try { await api(`/api/runs/${r.id}/cancel`, { method: 'POST' }); await invalidate('run') } catch (e) { toast.error((e as Error).message) }
  }
  return (
    <Page wide>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-x-3 gap-y-2">{t('run.title')}: {r.workflow_name ?? r.id.slice(0, 8)} <StatusBadge status={r.status} /> <GateBadge gate={r.gate} /><VerdictBadge verdict={r.verdict} /></span>}
        subtitle={`${t(`trigger.${r.trigger_type}`, r.trigger_type)} · ${fmtDate(r.created_at, lang)} · ${t('common.duration')}: ${fmtDuration(r.duration_ms, lang)}`}
        actions={<>
          {!done && <Button icon="stop" variant="danger" onClick={cancel}>{t('runs.cancel')}</Button>}
          {r.workflow_id && <Link to={`/workflows/${r.workflow_id}`} className="text-sm text-primary hover:underline">{t('runs.workflow')}</Link>}
          <Button icon="download" disabled={!done} onClick={() => downloadFile(`/api/runs/${r.id}/export/submission.json`, 'submission.json')}>{t('run.exportJson')}</Button>
          <Button icon="download" disabled={!done} onClick={() => downloadFile(`/api/runs/${r.id}/export/report.md`, 'report.md')}>{t('run.exportMd')}</Button>
          <Button icon="download" disabled={!done} onClick={() => downloadFile(`/api/runs/${r.id}/export/report.html`, 'report.html')}>{t('run.exportHtml')}</Button>
        </>}
      />
      {r.error && <div className="mb-4"><ErrorState error={new Error(r.error)} /></div>}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <div className="card p-3"><div className="text-xs text-muted">{t('common.total')}</div><div className="text-xl font-semibold">{r.summary.total ?? '—'}</div></div>
        {SEVERITIES.map((s) => <div key={s} className="card p-3"><SeverityBadge severity={s} /><div className="mt-1 text-xl font-semibold tabular-nums">{r.summary.by_severity?.[s] ?? 0}</div></div>)}
      </div>
      <Tabs label={t('run.title')} value={tab} onChange={(v) => setParams({ tab: v })} tabs={[
        { id: 'findings', label: t('run.findings'), count: findings.data?.findings.length },
        ...(r.score !== null && r.score !== undefined ? [{ id: 'score' as Tab, label: `Score ${r.score}` }] : []),
        { id: 'graph', label: t('run.graph') }, { id: 'ai', label: t('run.ai') },
        { id: 'logs', label: t('run.logs'), count: logs.length }, { id: 'artifacts', label: t('run.artifacts') },
      ]} />
      <div className="mt-4">
        {tab === 'graph' && <RunGraph run={r} live={live} />}
        {tab === 'findings' && (findings.isLoading || !done ? <Skeleton className="h-48" /> : <FindingsTable runId={r.id} findings={findings.data?.findings ?? []} />)}
        {tab === 'score' && (done ? <RunScoreTab runId={r.id} /> : <Skeleton className="h-48" />)}
        {tab === 'ai' && (done ? <AiReport runId={r.id} findings={findings.data?.findings ?? []} /> : <Skeleton className="h-48" />)}
        {tab === 'logs' && (logs.length ? (
          <div className="card max-h-[560px] overflow-auto p-3 font-mono text-xs">
            {logs.map((l, i) => <div key={i} className={clsx(l.level === 'warning' && 'text-warning')}><span className="text-muted">{new Date(l.at).toLocaleTimeString()} [{l.node}]</span> {l.message}</div>)}
          </div>) : <EmptyState icon="history" title={t('editor.noLogs')} />)}
        {tab === 'artifacts' && (
          <div className="grid gap-4 md:grid-cols-2">
            <Card title={t('run.artifacts')}>
              {(r.artifacts ?? []).length ? <ul className="space-y-2">{r.artifacts!.map((a) => (
                <li key={a.name} className="flex items-center justify-between gap-2 text-sm"><span className="font-mono">{a.name}</span>
                  <Button size="sm" icon="download" onClick={() => downloadFile(a.url, a.name)}>{t('common.download')}</Button></li>))}</ul>
                : <p className="text-sm text-muted">—</p>}
            </Card>
            <Card title={t('run.notifications')}>
              {(r.notifications ?? []).length ? <ul className="space-y-2 text-sm">{r.notifications!.map((n, i) => (
                <li key={i} className="flex items-center gap-2"><Badge tone={n.status === 'delivered' ? 'success' : 'danger'}>{n.status}</Badge>{n.channel}<span className="text-muted">{n.detail}</span></li>))}</ul>
                : <p className="text-sm text-muted">—</p>}
            </Card>
          </div>
        )}
      </div>
    </Page>
  )
}
