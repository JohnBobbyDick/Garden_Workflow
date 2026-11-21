import { Handle, NodeToolbar, Position, type NodeProps } from '@xyflow/react'
import clsx from 'clsx'
import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import { Spinner } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { pick } from '../i18n'
import { fmtDuration } from '../lib/format'
import { missingUserInput } from '../lib/schemaForm'
import { PORT_COLORS, useEditor } from './EditorContext'
import { specOf, type FlowNode } from './graphModel'
import { nodeVisualState } from './runAnimation'

/* Garden Security node card (Figma «Нода»): white card r15, 32px soft icon chip, title 16 bold, subtitle 13 muted,
   status glyph top-right (✓ primary · × danger · ! attention). Typed ports: inputs on top, outputs at the bottom (vertical flow);
   a selected node of a shown run expands inline with its result (frame «Diff Scanner раскрыт»). */

const GLYPH: Record<string, { ch: string; cls: string }> = {
  success: { ch: '✓', cls: 'text-primary' }, failed: { ch: '×', cls: 'text-danger' },
  skipped: { ch: '–', cls: 'text-muted' }, cancelled: { ch: '!', cls: 'text-warning' },
}

function NodeCardImpl({ id, data, selected }: NodeProps<FlowNode>) {
  const { t } = useTranslation()
  const { catalog, lang, runMode, onQuickAdd } = useEditor()
  const spec = specOf(catalog, data.nodeType)
  const missing = spec && !data.disabled ? missingUserInput(spec.config_schema, data.config, lang) : []
  const specTitle = spec ? pick(spec.title, lang) : data.nodeType
  const title = data.label || specTitle
  const subtitle = data.label && data.label !== specTitle ? specTitle : (spec ? pick(spec.description, lang) : data.nodeType)
  const glyph = data.status ? GLYPH[data.status] : undefined
  const expanded = selected && runMode && data.status && data.status !== 'pending'
  const visual = nodeVisualState(data.status, runMode)
  return (
    <div
      className={clsx('node-card w-[240px] rounded-card border bg-surface text-left', `node-${visual}`,
        data.finaleDelay !== undefined && 'node-finale',
        selected ? 'border-primary ring-2 ring-primary/25' : 'border-border', data.disabled && 'opacity-50',
        data.issues?.length && !data.status && 'border-danger')}
      style={data.finaleDelay !== undefined ? { ['--finale-delay' as string]: `${data.finaleDelay}ms` } : undefined}
      aria-label={`${title}${data.status ? `: ${t(`status.${data.status}`)}` : ''}`}
    >
      {!!spec?.inputs.length && (
        <div className="flex justify-around border-b border-border/70 px-2 pb-0.5 pt-1">
          {spec.inputs.map((p, i) => (
            <span key={`in-${p.name}`} className="truncate text-[11px] text-muted">
              {pick(p.title, lang)}{p.required ? '' : '?'}
              <Handle type="target" position={Position.Top} id={p.name}
                style={{ background: PORT_COLORS[p.type], left: `${((i + 0.5) / spec.inputs.length) * 100}%`, top: -6 }}
                title={`${pick(p.title, lang)} · ${p.type}${p.multiple ? ' ×N' : ''}`} />
            </span>
          ))}
        </div>
      )}
      <div className="flex items-start gap-2.5 px-2.5 pb-2 pt-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-chip bg-soft text-primary">
          <Icon name={spec?.icon || 'puzzle'} size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-base font-bold leading-5">{title}</div>
          <div className="truncate text-[13px] leading-[18px] text-muted" title={subtitle}>{subtitle}</div>
        </div>
        {data.status === 'running' && <Spinner size={14} className="mt-0.5 text-primary" />}
        {glyph && <span className={clsx('text-[15px] font-bold leading-4', glyph.cls)} aria-hidden="true">{glyph.ch}</span>}
        {missing.length > 0 && (
          <span className="font-bold leading-4 text-primary" title={`${t('editor.needsInput')}: ${missing.join(', ')}`}
            aria-label={`${t('editor.needsInput')}: ${missing.join(', ')}`}>!</span>
        )}
        {!data.status && !!data.issues?.length && (
          <span className="rounded-full bg-danger px-1.5 text-[10px] font-bold text-white" title={data.issues.join('\n')}>{data.issues.length}</span>
        )}
      </div>
      {!!spec?.outputs.length && (
        <div className="flex justify-around border-t border-border/70 px-2 pb-1 pt-0.5">
          {spec.outputs.map((p, i) => (
            <span key={`out-${p.name}`} className="truncate text-[11px] text-muted">
              {pick(p.title, lang)}
              <Handle type="source" position={Position.Bottom} id={p.name}
                style={{ background: PORT_COLORS[p.type], left: `${((i + 0.5) / spec.outputs.length) * 100}%`, bottom: -6, top: 'auto' }}
                title={`${pick(p.title, lang)} · ${p.type}`} />
            </span>
          ))}
        </div>
      )}
      {data.status && data.status !== 'pending' && (data.summary || data.durationMs !== undefined) && !expanded && (
        <div className="flex justify-between gap-2 border-t border-border/70 px-2.5 py-1 text-[11px] text-muted">
          <span className="truncate">{data.summary}</span>
          {data.durationMs !== undefined && data.durationMs !== null && <span className="tabular-nums">{fmtDuration(data.durationMs, lang)}</span>}
        </div>
      )}
      {selected && onQuickAdd && !!spec?.outputs.length && (
        <NodeToolbar position={Position.Bottom} offset={6}>
          <button type="button" onClick={() => onQuickAdd(id)} title={t('canvas.addAfter')} aria-label={t('canvas.addAfter')}
            className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-fg shadow-pop hover:scale-110 transition-transform">
            <Icon name="plus" size={15} />
          </button>
        </NodeToolbar>
      )}
      {expanded && (
        <div className="space-y-1 border-t border-border/70 px-2.5 py-2 text-[13px]">
          <div className="font-bold">{t(`status.${data.status}`)}{data.durationMs !== undefined && data.durationMs !== null ? ` · ${fmtDuration(data.durationMs, lang)}` : ''}</div>
          {data.error && <div className="whitespace-pre-wrap break-words text-danger">{data.error}</div>}
          {data.summary && <div className="whitespace-pre-wrap break-words">{data.summary}</div>}
          {data.reason && <div className="text-muted">{data.reason}</div>}
        </div>
      )}
    </div>
  )
}

export const NodeCard = memo(NodeCardImpl)
