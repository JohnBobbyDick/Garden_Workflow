import clsx from 'clsx'
import { useTranslation } from 'react-i18next'
import type { NodeStatus, RunStatus, Severity } from '../api/types'
import { useToasts } from '../store/toast'
import { Spinner } from './ui'
import { Icon } from './ui/Icon'

const SEV_CLASS: Record<Severity, string> = {
  CRITICAL: 'bg-danger-soft text-danger',
  HIGH: 'bg-danger-soft text-danger',
  MEDIUM: 'bg-warning-soft text-warning',
  LOW: 'bg-soft text-primary',
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation()
  return (
    <span className={clsx('inline-flex rounded-chip px-2.5 py-1 text-[13px] font-bold leading-5', SEV_CLASS[severity])}>
      {t(`severity.${severity}`)}
    </span>
  )
}

const STATUS_TONE: Record<string, string> = {
  queued: 'text-muted bg-surface border border-border', pending: 'text-muted bg-surface border border-border',
  running: 'text-primary bg-soft', success: 'text-primary bg-soft', failed: 'text-danger bg-danger-soft',
  cancelled: 'text-warning bg-warning-soft', skipped: 'text-muted bg-surface border border-dashed border-border',
}

export const STATUS_ICON: Record<string, string> = {
  queued: 'clock', pending: 'clock', success: 'check', failed: 'x', cancelled: 'stop', skipped: 'chevron-right',
}

export function StatusBadge({ status }: { status: RunStatus | NodeStatus }) {
  const { t } = useTranslation()
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-chip px-2.5 py-1 text-[13px] font-bold leading-5', STATUS_TONE[status])}>
      {status === 'running' ? <Spinner size={12} /> : <Icon name={STATUS_ICON[status] ?? 'info'} size={12} />}
      {t(`status.${status}`)}
    </span>
  )
}

export function GateBadge({ gate }: { gate: 'pass' | 'fail' | null | undefined }) {
  if (!gate) return null
  return (
    <span className={clsx('rounded-chip px-2.5 py-1 text-[13px] font-bold leading-5 uppercase', gate === 'pass' ? 'bg-soft text-primary' : 'bg-danger-soft text-danger')}>
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
          className={clsx('pointer-events-auto flex items-start gap-2 rounded-field border px-3 py-2.5 text-sm shadow-pop',
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
