import { Handle, Position, type NodeProps } from '@xyflow/react'
import clsx from 'clsx'
import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import { STATUS_ICON } from '../components/domain'
import { Spinner } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { pick } from '../i18n'
import { fmtDuration } from '../lib/format'
import { missingUserInput } from '../lib/schemaForm'
import { CATEGORY_ACCENT, PORT_COLORS, useEditor } from './EditorContext'
import { specOf, type FlowNode } from './graphModel'

const STATUS_RING: Record<string, string> = {
  running: 'ring-2 ring-info shadow-[0_0_0_6px_rgb(var(--info)/0.15)]', success: 'ring-2 ring-success',
  failed: 'ring-2 ring-danger', skipped: 'opacity-55', cancelled: 'ring-2 ring-warning', pending: '',
}

function NodeCardImpl({ data, selected }: NodeProps<FlowNode>) {
  const { t } = useTranslation()
  const { catalog, lang, runMode } = useEditor()
  const spec = specOf(catalog, data.nodeType)
  const missing = spec && !data.disabled ? missingUserInput(spec.config_schema, data.config, lang) : []
  const accent = CATEGORY_ACCENT[spec?.category ?? ''] ?? '#94a3b8'
  const rows = Math.max(spec?.inputs.length ?? 0, spec?.outputs.length ?? 0, 1)
  const title = spec ? pick(spec.title, lang) : data.nodeType
  return (
    <div
      className={clsx('w-[240px] rounded-xl border bg-surface text-left shadow-card transition-shadow',
        selected ? 'border-primary' : 'border-border', data.disabled && 'opacity-50',
        data.status && STATUS_RING[data.status], data.issues?.length && !data.status && 'border-danger')}
      aria-label={`${title}${data.status ? `: ${t(`status.${data.status}`)}` : ''}`}
    >
      <div className="flex items-center gap-2 rounded-t-xl border-b border-border px-3 py-2" style={{ boxShadow: `inset 3px 0 0 ${accent}` }}>
        <span style={{ color: accent }}><Icon name={spec?.icon || 'puzzle'} size={16} /></span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold">{data.label || title}</div>
          <div className="truncate font-mono text-[10px] text-muted">{data.nodeType}</div>
        </div>
        {data.status === 'running' && <Spinner size={14} className="text-info" />}
        {data.status && data.status !== 'running' && data.status !== 'pending' && (
          <span className={clsx({ 'text-success': data.status === 'success', 'text-danger': data.status === 'failed',
            'text-muted': data.status === 'skipped', 'text-warning': data.status === 'cancelled' })}>
            <Icon name={STATUS_ICON[data.status]} size={15} />
          </span>
        )}
        {!data.status && !runMode && missing.length > 0 && (
          <span className="rounded-full bg-warning/20 px-1.5 text-[10px] font-semibold text-warning"
            title={`${t('editor.needsInput')}: ${missing.join(', ')}`} aria-label={`${t('editor.needsInput')}: ${missing.join(', ')}`}>
            <Icon name="alert" size={12} />
          </span>
        )}
        {!data.status && !!data.issues?.length && (
          <span className="rounded-full bg-danger px-1.5 text-[10px] font-bold text-white" title={data.issues.join('\n')}>{data.issues.length}</span>
        )}
      </div>
      <div className="relative px-3 py-2" style={{ minHeight: rows * 22 + 8 }}>
        {spec?.inputs.map((p, i) => (
          <div key={`in-${p.name}`} className="absolute left-0 flex items-center" style={{ top: 10 + i * 22 }}>
            <Handle type="target" position={Position.Left} id={p.name} style={{ background: PORT_COLORS[p.type], top: 7, left: -6 }}
              title={`${pick(p.title, lang)} · ${p.type}${p.multiple ? ' ×N' : ''}`} />
            <span className="ml-2.5 text-[11px] text-muted">{pick(p.title, lang)}{p.required ? '' : '?'}</span>
          </div>
        ))}
        {spec?.outputs.map((p, i) => (
          <div key={`out-${p.name}`} className="absolute right-0 flex items-center" style={{ top: 10 + i * 22 }}>
            <span className="mr-2.5 text-[11px] text-muted">{pick(p.title, lang)}</span>
            <Handle type="source" position={Position.Right} id={p.name} style={{ background: PORT_COLORS[p.type], top: 7, right: -6 }}
              title={`${pick(p.title, lang)} · ${p.type}`} />
          </div>
        ))}
      </div>
      {(data.summary || data.durationMs !== undefined) && data.status && (
        <div className="flex justify-between gap-2 border-t border-border px-3 py-1 text-[11px] text-muted">
          <span className="truncate">{data.summary}</span>
          {data.durationMs !== undefined && data.durationMs !== null && <span className="tabular-nums">{fmtDuration(data.durationMs, lang)}</span>}
        </div>
      )}
    </div>
  )
}

export const NodeCard = memo(NodeCardImpl)
