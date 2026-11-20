import clsx from 'clsx'
import { useTranslation } from 'react-i18next'
import type { NodeStatus, RunStatus, Severity } from '../api/types'
import { useToasts } from '../store/toast'
import { Spinner } from './ui'
import { Icon } from './ui/Icon'

const SEV_CLASS: Record<Severity, string> = {
  CRITICAL: 'bg-sev-critical text-white',
  HIGH: 'bg-sev-high text-white',
  MEDIUM: 'bg-sev-medium text-black',
  LOW: 'bg-sev-low text-white',
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation()
  return (
    <span className={clsx('inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide', SEV_CLASS[severity])}>
      {t(`severity.${severity}`)}
    </span>
  )
}

const STATUS_TONE: Record<string, string> = {
  queued: 'text-muted bg-surface-2 border border-border', pending: 'text-muted bg-surface-2 border border-border',
  running: 'text-info bg-info/15', success: 'text-success bg-success/15', failed: 'text-danger bg-danger/15',
  cancelled: 'text-warning bg-warning/15', skipped: 'text-muted bg-surface-2 border border-dashed border-border',
}

export const STATUS_ICON: Record<string, string> = {
  queued: 'clock', pending: 'clock', success: 'check', failed: 'x', cancelled: 'stop', skipped: 'chevron-right',
}

export function StatusBadge({ status }: { status: RunStatus | NodeStatus }) {
  const { t } = useTranslation()
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', STATUS_TONE[status])}>
      {status === 'running' ? <Spinner size={12} /> : <Icon name={STATUS_ICON[status] ?? 'info'} size={12} />}
      {t(`status.${status}`)}
    </span>
  )
}

export function GateBadge({ gate }: { gate: 'pass' | 'fail' | null | undefined }) {
  if (!gate) return null
  return (
    <span className={clsx('rounded-md px-2 py-0.5 text-xs font-bold uppercase', gate === 'pass' ? 'bg-success/15 text-success' : 'bg-danger/15 text-danger')}>
      {gate}
    </span>
  )
}

export function Toaster() {
  const { toasts, dismiss } = useToasts()
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div
          key={t.id} role={t.kind === 'error' ? 'alert' : 'status'}
          className={clsx('pointer-events-auto flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm shadow-card',
            'bg-surface', t.kind === 'error' ? 'border-danger/50' : t.kind === 'success' ? 'border-success/50' : 'border-border')}
        >
          <Icon name={t.kind === 'error' ? 'alert' : t.kind === 'success' ? 'check' : 'info'} size={16}
            className={t.kind === 'error' ? 'text-danger' : t.kind === 'success' ? 'text-success' : 'text-info'} />
          <span className="flex-1">{t.message}</span>
          {t.action && <button className="font-medium text-primary" onClick={t.action.onClick}>{t.action.label}</button>}
          <button aria-label="close" className="text-muted hover:text-fg" onClick={() => dismiss(t.id)}><Icon name="x" size={14} /></button>
        </div>
      ))}
    </div>
  )
}
