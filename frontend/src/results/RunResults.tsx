import clsx from 'clsx'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { downloadFile } from '../api/client'
import { useRunFindings } from '../api/hooks'
import type { Run, Severity } from '../api/types'
import { Chip } from '../components/chip'
import { SeverityBadge, StatusBadge } from '../components/domain'
import { RunScoreTab } from '../components/score'
import { EmptyState, Select, Skeleton, Tabs } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { useLang } from '../i18n'
import { fmtDuration } from '../lib/format'
import { AiReport } from '../pages/RunDetailsPage'
import { FindingDetail } from './FindingDetail'
import { filterFindings, runVerdict, SEVERITY_ORDER, severityCounts, sortFindings, splitOfficial, type DiffFilter } from './findings'

type Tab = 'findings' | 'ai' | 'score' | 'data' | 'journal'

/** Counter that rolls up to its value (findings appear «counted» when a run ends). */
function CountUp({ value }: { value: number }) {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { setShown(value); return }
    const start = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const k = Math.min(1, (now - start) / 600)
      setShown(Math.round(value * (1 - (1 - k) ** 3)))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    const done = window.setTimeout(() => setShown(value), 700)  // rAF does not run in background tabs
    return () => { cancelAnimationFrame(raf); window.clearTimeout(done) }
  }, [value])
  return <span className="tabular-nums">{shown}</span>
}

function FindingsTab({ run }: { run: Run }) {
  const { t } = useTranslation()
  const done = !['queued', 'running'].includes(run.status)
  const q = useRunFindings(run.id, done)
  const sorted = useMemo(() => sortFindings(q.data?.findings ?? []), [q.data])
  // the list shows exactly what submission.json and the reports contain; the rest is a separate, folded block
  const { official: all, below } = useMemo(() => splitOfficial(sorted), [sorted])
  const [showBelow, setShowBelow] = useState(false)
  const hasDiff = all.some((f) => f.diff_status)
  const [diff, setDiff] = useState<DiffFilter>('all')
  const [sev, setSev] = useState<Severity | ''>('')
  const [cat, setCat] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  useEffect(() => { setOpen(null); setDiff(hasDiff ? 'new' : 'all') }, [run.id, hasDiff])
  if (!done) return <p className="text-sm text-muted">{t('results.waiting')}</p>
  if (q.isLoading) return <Skeleton className="h-40" />
  const selected = sorted.find((f) => f.id === open)
  if (selected) return <FindingDetail run={run} finding={selected} onBack={() => setOpen(null)} />
  const list = filterFindings(all, { diff, severity: sev || undefined, category: cat || undefined })
  return (
    <div>
      {hasDiff && (
        <div className="mb-3 flex gap-2" role="tablist" aria-label={t('run.diffFilter')}>
          {(['new', 'existing', 'all'] as const).map((k) => (
            <button key={k} type="button" role="tab" aria-selected={diff === k} onClick={() => setDiff(k)}
              className={clsx('h-8 rounded-chip px-2.5 text-[13px] font-bold', diff === k ? 'bg-primary text-primary-fg' : 'bg-soft text-primary')}>
              {k === 'new' ? t('pr.new') : k === 'existing' ? t('pr.existing') : t('common.all')} · {filterFindings(all, { diff: k }).length}
            </button>
          ))}
        </div>
      )}
      <div className="mb-3 grid grid-cols-2 gap-2">
        <Select aria-label={t('run.allSeverities')} value={sev} onChange={(e) => setSev(e.target.value as Severity | '')} className="h-8 text-[13px]">
          <option value="">{t('run.allSeverities')}</option>
          {SEVERITY_ORDER.map((s) => <option key={s} value={s}>{t(`severity.${s}`)}</option>)}
        </Select>
        <Select aria-label={t('run.allCategories')} value={cat} onChange={(e) => setCat(e.target.value)} className="h-8 text-[13px]">
          <option value="">{t('run.allCategories')}</option>
          {['SECRET', 'SAST', 'SCA'].map((c) => <option key={c} value={c}>{t(`category.${c}`)}</option>)}
        </Select>
      </div>
      {!list.length ? <EmptyState icon="shield-check" title={diff === 'new' ? t('pr.noNew') : t('run.noFindings')} /> : (
        <ul className="space-y-2">
          {list.map((f) => (
            <li key={f.id}>
              <button type="button" onClick={() => setOpen(f.id)}
                className="finding-row w-full rounded-card border border-border bg-surface p-3 text-left transition-colors hover:border-primary/50 hover:bg-surface-2">
                <div className="flex items-center gap-2">
                  <SeverityBadge severity={f.severity} />
                  {f.diff_status === 'new' && <span className="text-[12px] font-bold text-danger">{t('wf.isNew')}</span>}
                  {f.autofix && f.autofix !== 'none' && <span className="ml-auto flex items-center gap-1 text-[12px] font-bold text-primary"><Icon name="wrench" size={12} />AutoFix</span>}
                </div>
                <div className="mt-1.5 text-[14px] font-bold leading-snug">{f.title}</div>
                <div className="truncate font-mono text-[11px] text-muted">{f.path}:{f.line}</div>
              </button>
            </li>
          ))}
        </ul>
      )}
      {below.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          <button type="button" className="flex items-center gap-1 text-[13px] font-bold text-muted hover:text-fg" aria-expanded={showBelow}
            onClick={() => setShowBelow((v) => !v)}>
            <Icon name="chevron-right" size={13} className={showBelow ? 'rotate-90' : ''} />{t('results.belowThreshold', { n: below.length })}
          </button>
          {showBelow && (
            <>
              <p className="mt-1 text-[12px] text-muted">{t('results.belowThresholdHint', { p: q.data?.official_min_confidence ?? 0.6 })}</p>
              <ul className="mt-2 space-y-2">
                {below.map((f) => (
                  <li key={f.id}>
                    <button type="button" onClick={() => setOpen(f.id)}
                      className="w-full rounded-card border border-dashed border-border bg-surface p-3 text-left opacity-75 hover:opacity-100">
                      <div className="flex items-center gap-2"><SeverityBadge severity={f.severity} />
                        <span className="text-[12px] text-warning">{t('run.lowConfidence')}</span></div>
                      <div className="mt-1.5 text-[14px] font-bold leading-snug">{f.title}</div>
                      <div className="truncate font-mono text-[11px] text-muted">{f.path}:{f.line}</div>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function DataTab({ run }: { run: Run }) {
  const { t } = useTranslation()
  const v = (run.verdict ?? {}) as { verdict?: string; new_count?: number; existing_count?: number }
  return (
    <div className="space-y-3">
      {v.verdict && <p className="text-sm">{t('wf.newExisting', { n: v.new_count ?? 0, e: v.existing_count ?? 0, v: v.verdict })}</p>}
      <p className="text-[13px] text-muted">{t('results.dataHint')}</p>
      <ul className="space-y-2">
        {(run.nodes ?? []).map((n) => (
          <li key={n.node_id} className="rounded-field border border-border bg-surface px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[12px] font-bold">{n.node_id}</span>
              <span className="text-[11px] text-muted">{n.node_type}</span>
            </div>
            <div className="mt-0.5 text-[13px]">{n.output_summary?.summary || n.output_summary?.reason || (n.error ?? '—')}</div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function JournalTab({ run }: { run: Run }) {
  const { t } = useTranslation()
  const lang = useLang()
  const notes = run.notifications ?? []
  return (
    <div className="space-y-4">
      <ol className="space-y-1.5 text-sm">
        {(run.nodes ?? []).map((n) => (
          <li key={n.node_id} className="flex gap-2">
            <span aria-hidden="true" className={clsx('w-4 shrink-0 text-center font-bold', n.status === 'success' ? 'text-primary' : n.status === 'failed' ? 'text-danger' : 'text-muted')}>
              {n.status === 'success' ? '✓' : n.status === 'failed' ? '×' : n.status === 'skipped' ? '–' : '…'}
            </span>
            <span className="min-w-0">
              <b>{n.node_id}</b> · {t(`status.${n.status}`)}
              {n.duration_ms !== null && <span className="text-muted"> · {fmtDuration(n.duration_ms, lang)}</span>}
              {n.error && <span className="block text-danger">{n.error}</span>}
            </span>
          </li>
        ))}
      </ol>
      <div>
        <div className="label">{t('wf.notifications')}</div>
        {notes.length ? (
          <ul className="space-y-1 text-sm">{notes.map((n, i) => (
            <li key={i}>{n.channel} · <span className={n.status === 'delivered' ? 'text-primary' : 'text-danger'}>{n.status}</span>{n.detail ? ` · ${n.detail}` : ''}</li>))}</ul>
        ) : <p className="text-[13px] text-muted">{t('wf.noNotifications')}</p>}
      </div>
    </div>
  )
}

export function RunResults({ run, onClose }: { run: Run; onClose?: () => void }) {
  const { t } = useTranslation()
  const lang = useLang()
  const [tab, setTab] = useState<Tab>('findings')
  const done = !['queued', 'running'].includes(run.status)
  const verdict = runVerdict(run)
  const findings = useRunFindings(run.id, done)
  const official = findings.data ? splitOfficial(findings.data.findings).official : null
  const total = official ? official.length : run.summary.total ?? 0
  const bySeverity = official ? severityCounts(official) : run.summary.by_severity ?? {}
  const src = (run.source ?? {}) as { subdir?: string; subdir_detected?: boolean }
  const hasAi = !!run.graph_snapshot?.nodes.some((n) => n.type === 'ai.report')
  const hasScore = run.score !== null
  const tabs = [
    { id: 'findings' as const, label: t('run.findings'), count: total },
    ...(hasAi ? [{ id: 'ai' as const, label: t('run.ai') }] : []),
    ...(hasScore ? [{ id: 'score' as const, label: 'Score' }] : []),
    { id: 'data' as const, label: t('editor.data') },
    { id: 'journal' as const, label: t('wf.journal') },
  ]
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 pb-3 pt-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="text-[12px] text-muted">{t('results.run')} #{run.id.slice(0, 6)} · {new Date(run.created_at).toLocaleString(lang === 'en' ? 'en-GB' : 'ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <StatusBadge status={run.status} />
              {verdict && <Chip tone={verdict === 'fail' ? 'bad' : 'ok'}>{verdict === 'fail' ? t('pr.blocked') : t('pr.unblocked')}</Chip>}
              {run.duration_ms !== null && <span className="text-[12px] text-muted">{fmtDuration(run.duration_ms, lang)}</span>}
            </div>
          </div>
          {onClose && <button type="button" onClick={onClose} aria-label={t('common.close')} className="rounded-chip p-1.5 text-muted hover:bg-soft hover:text-fg"><Icon name="x" size={15} /></button>}
        </div>
        {done && (
          <div className="mt-3 flex items-end gap-4">
            <div><div className="text-[34px] font-bold leading-none"><CountUp value={total} /></div><div className="text-[12px] text-muted">{t('run.findings').toLowerCase()}</div></div>
            {hasScore && <div><div className="text-[34px] font-bold leading-none text-primary"><CountUp value={run.score ?? 0} /></div><div className="text-[12px] text-muted">Security Score</div></div>}
            <div className="ml-auto flex flex-wrap justify-end gap-1">
              {SEVERITY_ORDER.filter((s) => bySeverity[s]).map((s) => (
                <span key={s} className="flex items-center gap-1 text-[12px]"><SeverityBadge severity={s} />{bySeverity[s]}</span>
              ))}
            </div>
          </div>
        )}
        {done && (
          <div className="mt-3 flex flex-wrap gap-1.5 text-[12px]">
            {[['submission.json', 'json'], ['report.md', 'md'], ['report.html', 'html']].map(([name]) => (
              <button key={name} type="button" onClick={() => void downloadFile(`/api/runs/${run.id}/export/${name}`, name)}
                className="inline-flex h-7 items-center gap-1 rounded-chip border border-border bg-surface px-2 font-bold hover:bg-soft">
                <Icon name="download" size={12} />{name}
              </button>
            ))}
            <Link to={`?panel=compare&head=${run.id}`} className="inline-flex h-7 items-center gap-1 rounded-chip border border-border bg-surface px-2 font-bold hover:bg-soft">
              <Icon name="split" size={12} />{t('results.compare')}
            </Link>
            <Link to={`/runs/${run.id}?full=1`} className="inline-flex h-7 items-center gap-1 rounded-chip border border-border bg-surface px-2 font-bold hover:bg-soft">
              <Icon name="external" size={12} />{t('results.fullReport')}
            </Link>
          </div>
        )}
        {src.subdir && (
          <p className="mt-2 text-[12px] text-muted" title={t('results.projectRootHint')}>
            {t('results.projectRoot')}: <span className="font-mono text-fg">{src.subdir}/</span>
            {src.subdir_detected ? ` · ${t('results.projectRootAuto')}` : ''}
          </p>
        )}
        {run.error && <p role="alert" className="mt-3 rounded-field bg-danger-soft px-3 py-2 text-[13px] text-danger">{run.error}</p>}
      </div>
      <div className="px-4 pt-2"><Tabs compact label={t('results.tabs')} value={tab} onChange={setTab} tabs={tabs} /></div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {tab === 'findings' && <FindingsTab run={run} />}
        {tab === 'ai' && <AiReport runId={run.id} findings={findings.data?.findings ?? []} />}
        {tab === 'score' && <RunScoreTab runId={run.id} />}
        {tab === 'data' && <DataTab run={run} />}
        {tab === 'journal' && <JournalTab run={run} />}
      </div>
    </div>
  )
}
