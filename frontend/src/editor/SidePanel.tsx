import clsx from 'clsx'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { NodeSpec, ValidationIssue } from '../api/types'
import { StatusBadge } from '../components/domain'
import { Input, Tabs } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { pick } from '../i18n'
import { fmtDuration } from '../lib/format'
import { PORT_COLORS, useEditor } from './EditorContext'
import type { FlowNode } from './graphModel'
import { SchemaForm } from './SchemaForm'
import type { NodeLive, PortPreview } from './useRunEvents'

function PortList({ spec }: { spec: NodeSpec }) {
  const { t } = useTranslation()
  const { lang } = useEditor()
  const row = (p: NodeSpec['inputs'][number], dir: string) => (
    <li key={`${dir}${p.name}`} className="flex items-center gap-2 text-xs">
      <span className="h-2.5 w-2.5 rounded-full" style={{ background: PORT_COLORS[p.type] }} />
      <span className="font-mono">{p.name}</span><span className="text-muted">{p.type}{p.multiple ? ' ×N' : ''}{p.required ? '' : ` (${t('common.optional')})`}</span>
      <span className="text-muted">— {pick(p.title, lang)}</span>
    </li>
  )
  return (
    <div className="mt-4 grid grid-cols-1 gap-3 border-t border-border pt-3">
      {spec.inputs.length > 0 && <div><div className="label">{t('editor.inputs')}</div><ul className="space-y-1">{spec.inputs.map((p) => row(p, 'i'))}</ul></div>}
      {spec.outputs.length > 0 && <div><div className="label">{t('editor.outputs')}</div><ul className="space-y-1">{spec.outputs.map((p) => row(p, 'o'))}</ul></div>}
    </div>
  )
}

export function ConfigPanel({ node, spec, issues, onChange, readOnly }: {
  node: FlowNode; spec: NodeSpec | undefined; issues: ValidationIssue[]
  onChange: (patch: Partial<FlowNode['data']>) => void; readOnly?: boolean
}) {
  const { t } = useTranslation()
  const { lang } = useEditor()
  const serverErrors = Object.fromEntries(issues.filter((i) => i.field).map((i) => [i.field!, i.message]))
  const general = issues.filter((i) => !i.field || !(spec?.config_schema.properties ?? {})[i.field])
  return (
    <div className="p-4">
      <div className="mb-1 text-xs font-mono text-muted">{node.data.nodeType} · {node.id}</div>
      <h2 className="text-base font-semibold">{spec ? pick(spec.title, lang) : node.data.nodeType}</h2>
      {spec && <p className="mt-1 text-sm text-muted">{pick(spec.description, lang)}</p>}
      {general.length > 0 && (
        <ul className="mt-3 space-y-1 rounded-field border border-danger/40 bg-danger/10 p-2 text-xs text-danger" role="alert">
          {general.map((i, k) => <li key={k} className="flex gap-1.5"><Icon name="alert" size={13} />{i.message}</li>)}
        </ul>
      )}
      <div className="mt-4">
        <label className="label" htmlFor="node-label">{t('editor.label')}</label>
        <Input id="node-label" value={node.data.label} readOnly={readOnly} placeholder={spec ? pick(spec.title, lang) : ''}
          onChange={(e) => onChange({ label: e.target.value })} />
      </div>
      <div className="mt-3">
        {spec && <SchemaForm schema={spec.config_schema} value={node.data.config} lang={lang} serverErrors={serverErrors} readOnly={readOnly}
          onChange={(config) => onChange({ config })} />}
      </div>
      {spec && <PortList spec={spec} />}
    </div>
  )
}

function Preview({ p, name }: { p: PortPreview; name: string }) {
  return (
    <div className="mb-2 rounded-field border border-border">
      <div className="flex items-center justify-between border-b border-border px-2 py-1 text-xs">
        <span className="font-mono">{name} · {p.type}</span>
        <span className="text-muted">{p.count !== null && p.count !== undefined ? `${p.count} · ` : ''}{p.summary}</span>
      </div>
      <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-all p-2 font-mono text-[11px] text-muted">{p.preview}</pre>
    </div>
  )
}

export function RunNodePanel({ node, live, children }: { node: FlowNode; live: NodeLive | undefined; children: ReactNode }) {
  const { t } = useTranslation()
  const { lang } = useEditor()
  const [tab, setTab] = useState<'settings' | 'logs' | 'data'>('settings')
  return (
    <div className="flex h-full flex-col">
      {tab !== 'settings' && <div className="p-4 pb-2">
        <div className="mb-1 font-mono text-xs text-muted">{node.data.nodeType} · {node.id}</div>
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold">{node.data.label || node.id}</h2>
          {live && <StatusBadge status={live.status} />}
          {live?.durationMs !== undefined && live?.durationMs !== null && <span className="text-xs text-muted">{fmtDuration(live.durationMs, lang)}</span>}
        </div>
        {live?.error && <p role="alert" className="mt-2 rounded-field bg-danger/10 p-2 text-xs text-danger">{live.error}</p>}
        {live?.reason && <p className="mt-2 text-xs text-muted">{live.reason}</p>}
      </div>}
      <div className="px-4 pt-2"><Tabs label={node.data.label || node.id} value={tab} onChange={setTab} tabs={[
        { id: 'settings', label: t('nav.settings') }, { id: 'logs', label: t('editor.logs'), count: live?.logs.length ?? 0 }, { id: 'data', label: t('editor.data') }]} /></div>
      <div className={clsx("flex-1 overflow-y-auto", tab !== 'settings' && "p-4")}>
        {tab === 'settings' ? children : tab === 'logs' ? (live?.logs.length ? (
          <ul className="space-y-1 font-mono text-[11px]">
            {live.logs.map((l, i) => (
              <li key={i} className={clsx(l.level === 'warning' && 'text-warning', l.level === 'error' && 'text-danger')}>
                <span className="text-muted">{new Date(l.at).toLocaleTimeString()} </span>{l.message}
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-muted">{t('editor.noLogs')}</p>) : (
          <>
            {live?.inputs && <><div className="label">{t('editor.inputs')}</div>{Object.entries(live.inputs).map(([k, v]) =>
              (Array.isArray(v) ? v : [v]).map((p, i) => <Preview key={`${k}${i}`} p={p} name={k} />))}</>}
            {live?.outputs && <><div className="label mt-3">{t('editor.outputs')}</div>{Object.entries(live.outputs).map(([k, p]) => <Preview key={k} p={p} name={k} />)}</>}
            {!live?.inputs && !live?.outputs && <p className="text-sm text-muted">—</p>}
          </>
        )}
      </div>
    </div>
  )
}
