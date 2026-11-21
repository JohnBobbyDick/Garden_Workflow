import clsx from 'clsx'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { Project } from '../api/types'
import { Icon, type IconName } from '../components/ui/Icon'
import type { FlowNode } from './graphModel'

/* Top bar of the canvas: editable name, where the code comes from, when the check runs, actions. */

export function sourceLabel(src: FlowNode | undefined, project: Project | undefined, t: (k: string) => string): { icon: IconName; text: string } {
  const c = (src?.data.config ?? {}) as Record<string, string | undefined>
  switch (c.mode) {
    case 'git_url': return { icon: 'folder-git', text: (c.git_url ?? '').replace(/^https:\/\//, '') + (c.ref ? ` · ${c.ref}` : '') }
    case 'upload': return { icon: 'upload', text: t('canvas.sourceArchive') }
    case 'path': return { icon: 'folder', text: /organizer-training[\\/]training-project$/.test(c.path ?? '') ? t('wf.modeTraining') : (c.path ?? '').split(/[\\/]/).pop() || t('wf.modePath') }
    default: return { icon: 'folder', text: project ? project.name : t('canvas.sourceNone') }
  }
}

export function InlineName({ value, onSave, readOnly }: { value: string; onSave: (v: string) => void; readOnly?: boolean }) {
  const { t } = useTranslation()
  const [v, setV] = useState(value)
  useEffect(() => setV(value), [value])
  const commit = () => { const n = v.trim(); if (n && n !== value) onSave(n); else setV(value) }
  return (
    <input value={v} readOnly={readOnly} aria-label={t('canvas.name')} onChange={(e) => setV(e.target.value)} onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') { setV(value); (e.target as HTMLInputElement).blur() } }}
      className="h-9 w-[min(320px,28vw)] min-w-[120px] truncate rounded-field border border-transparent bg-transparent px-2 text-[17px] font-bold hover:border-border focus:border-primary focus:bg-surface focus:outline-none" />
  )
}

export function HeaderButton({ icon, children, onClick, active, disabled, title, ariaLabel }: {
  icon: IconName; children?: ReactNode; onClick: () => void; active?: boolean; disabled?: boolean; title?: string; ariaLabel?: string
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={title} aria-label={ariaLabel} aria-pressed={active}
      className={clsx('inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-chip px-2 text-[13px] font-bold transition-colors disabled:opacity-40',
        active ? 'bg-soft text-primary' : 'text-fg hover:bg-soft')}>
      <Icon name={icon} size={15} />{children}
    </button>
  )
}

export type TriggerKind = 'trigger.manual' | 'trigger.schedule' | 'trigger.webhook'

export function TriggerSwitch({ node, readOnly, onChange }: {
  node: FlowNode | undefined; readOnly: boolean; onChange: (type: TriggerKind, config: Record<string, unknown>) => void
}) {
  const { t } = useTranslation()
  if (!node) return null
  const type = node.data.nodeType as TriggerKind
  const daily = String((node.data.config as { daily_at?: string }).daily_at ?? '')
  return (
    <div className="flex max-w-full flex-wrap items-center gap-1">
      <label className="sr-only" htmlFor="trig">{t('wf.trigger')}</label>
      <select id="trig" value={type} disabled={readOnly}
        onChange={(e) => onChange(e.target.value as TriggerKind, e.target.value === 'trigger.schedule' ? { daily_at: daily || '14:00' } : {})}
        className="h-8 cursor-pointer rounded-chip border-0 bg-soft px-2 pr-7 text-[13px] font-bold text-primary">
        <option value="trigger.manual">{t('wf.trManual')}</option>
        <option value="trigger.schedule">{t('wf.trSchedule')}</option>
        <option value="trigger.webhook">{t('wf.trWebhook')}</option>
      </select>
      {type === 'trigger.schedule' && (
        <input type="time" value={daily} readOnly={readOnly} aria-label={t('wf.dailyAt')}
          onChange={(e) => onChange('trigger.schedule', { ...(node.data.config as object), cron: undefined, daily_at: e.target.value })}
          className="h-8 rounded-chip border border-border bg-surface px-2 text-[13px]" />
      )}
    </div>
  )
}

export function OverflowMenu({ items }: { items: { key: string; icon: IconName; label: string; onClick: () => void; danger?: boolean }[] }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])
  return (
    <div ref={ref} className="relative">
      <HeaderButton icon="menu" onClick={() => setOpen((o) => !o)} active={open} ariaLabel={t('canvas.more')} title={t('canvas.more')} />
      {open && (
        <div role="menu" className="card fixed right-2 z-30 w-60 sm:absolute sm:right-0 sm:top-10 py-1 text-sm shadow-pop">
          {items.map((it) => (
            <button key={it.key} role="menuitem" type="button" onClick={() => { setOpen(false); it.onClick() }}
              className={clsx('flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-soft', it.danger && 'text-danger')}>
              <Icon name={it.icon} size={15} />{it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
