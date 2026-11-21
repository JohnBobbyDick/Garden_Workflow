import clsx from 'clsx'
import { forwardRef, useEffect, useId, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode,
  type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'
import { createPortal } from 'react-dom'
import { toast } from '../../store/toast'
import { useEmbedded } from '../layout/embedded'
import { Icon, type IconName } from './Icon'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant; size?: 'sm' | 'md'; icon?: IconName; loading?: boolean
}>(function Button({ variant = 'secondary', size = 'md', icon, loading, className, children, disabled, ...rest }, ref) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-chip font-bold transition-colors focus-visible:outline-none',
        'focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-8 px-2.5 text-[13px]' : 'h-[38px] px-4 text-[15px]',
        variant === 'primary' && 'bg-primary text-primary-fg hover:bg-primary/90',
        variant === 'secondary' && 'border border-border bg-surface text-fg hover:bg-soft',
        variant === 'ghost' && 'text-fg hover:bg-soft',
        variant === 'danger' && 'bg-danger text-white hover:bg-danger/90',
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner size={14} /> : icon ? <Icon name={icon} size={15} /> : null}
      {children}
    </button>
  )
})

export function Spinner({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <svg className={clsx('animate-spin', className)} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" fill="none" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  )
}

export function Field({ label, error, hint, children, required, htmlFor }: {
  label: ReactNode; error?: string; hint?: ReactNode; children: ReactNode; required?: boolean; htmlFor?: string
}) {
  return (
    <div className="mb-3">
      <label className="label" htmlFor={htmlFor}>
        {label}
        {required && <span className="ml-0.5 text-danger" aria-hidden="true">*</span>}
      </label>
      {children}
      {error ? <p className="mt-1 text-xs text-danger" role="alert">{error}</p>
        : hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </div>
  )
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  function Input({ className, invalid, ...rest }, ref) {
    return <input ref={ref} aria-invalid={invalid || undefined} className={clsx('input', invalid && 'input-error', className)} {...rest} />
  })

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(
  function Textarea({ className, invalid, ...rest }, ref) {
    return <textarea ref={ref} aria-invalid={invalid || undefined} className={clsx('input min-h-[72px] font-mono text-xs', invalid && 'input-error', className)} {...rest} />
  })

export function Select({ className, invalid, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }) {
  return <select aria-invalid={invalid || undefined} className={clsx('input pr-8', invalid && 'input-error', className)} {...rest}>{children}</select>
}

export function Switch({ checked, onChange, label, id }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; id?: string }) {
  const auto = useId()
  const sid = id ?? auto
  return (
    <label htmlFor={sid} className="flex cursor-pointer items-center gap-2 text-sm">
      <button
        id={sid} type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={clsx('relative h-5 w-9 shrink-0 rounded-full transition-colors', checked ? 'bg-primary' : 'bg-border')}
      >
        <span className={clsx('absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white transition-transform', checked ? 'translate-x-4' : 'translate-x-0.5')} />
      </button>
      <span>{label}</span>
    </label>
  )
}

export function Card({ title, actions, children, className, padded = true }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean
}) {
  return (
    <section className={clsx('card', className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 px-4 pb-1 pt-[17px]">
          <h2 className="text-lg font-bold">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={padded ? 'p-4' : ''}>{children}</div>
    </section>
  )
}

export function Badge({ children, tone = 'neutral', className, title }: {
  children: ReactNode; tone?: 'neutral' | 'success' | 'danger' | 'warning' | 'info' | 'primary'; className?: string; title?: string
}) {
  return (
    <span title={title} className={clsx('inline-flex items-center gap-1 whitespace-nowrap rounded-chip px-2.5 py-1 text-[13px] font-bold leading-5', {
      'bg-surface text-muted border border-border': tone === 'neutral',
      'bg-danger-soft text-danger': tone === 'danger',
      'bg-warning-soft text-warning': tone === 'warning',
      'bg-info/15 text-info': tone === 'info',
      'bg-soft text-primary': tone === 'primary' || tone === 'success',
    }, className)}>{children}</span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse rounded-md bg-surface-2', className)} aria-hidden="true" />
}

export function EmptyState({ icon = 'inbox', title, hint, action }: { icon?: IconName; title: ReactNode; hint?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="rounded-full bg-surface-2 p-3 text-muted"><Icon name={icon} size={22} /></div>
      <p className="font-medium">{title}</p>
      {hint && <p className="max-w-md text-sm text-muted">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation()
  const message = error instanceof Error ? error.message : t('common.unknownError')
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-card bg-danger-soft px-4 py-3 text-sm">
      <span className="flex items-center gap-2 text-danger"><Icon name="alert" size={16} />{message}</span>
      {onRetry && <Button size="sm" onClick={onRetry}>{t('common.retry')}</Button>}
    </div>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange, label, compact }: {
  tabs: { id: T; label: ReactNode; count?: number }[]; value: T; onChange: (v: T) => void; label: string; compact?: boolean
}) {
  return (
    <div role="tablist" aria-label={label} className={clsx('flex gap-1 border-b border-border', compact ? 'flex-wrap' : 'overflow-x-auto overflow-y-hidden')}>
      {tabs.map((tab) => (
        <button
          key={tab.id} role="tab" type="button" aria-selected={value === tab.id} onClick={() => onChange(tab.id)}
          className={clsx('-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 transition-colors', compact ? 'px-2 py-1.5 text-[13px] font-bold' : 'px-3 py-2 text-[15px]',
            value === tab.id ? 'border-primary text-fg' : 'border-transparent text-muted hover:text-fg')}
        >
          {tab.label}
          {tab.count !== undefined && <span className="rounded-full bg-surface-2 px-1.5 text-[11px]">{tab.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function Modal({ open, onClose, title, children, footer, wide }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('input, select, textarea, button')?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); prev?.focus() }
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-fg/40 p-4" onMouseDown={onClose}>
      <div
        ref={ref} role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}
        className={clsx('card max-h-[90vh] w-full overflow-y-auto shadow-pop', wide ? 'max-w-3xl' : 'max-w-lg')}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-4 pb-1 pt-[17px]">
          <h2 className="text-lg font-bold">{title}</h2>
          <button type="button" aria-label="close" className="rounded p-1 text-muted hover:bg-surface-2" onClick={onClose}>
            <Icon name="x" size={16} />
          </button>
        </header>
        <div className="p-4">{children}</div>
        {footer && <footer className="flex flex-wrap justify-end gap-2 border-t border-border px-4 py-3">{footer}</footer>}
      </div>
    </div>,
    document.body,
  )
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const { t } = useTranslation()
  return (
    <Button size="sm" variant="ghost" icon="copy" onClick={() => {
      void navigator.clipboard?.writeText(text).then(() => toast.success(t('common.copied')))
    }}>{label ?? t('common.copy')}</Button>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  const embedded = useEmbedded()
  if (embedded) {
    if (!subtitle && !actions) return null
    return (
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        {subtitle ? <p className="text-sm text-muted">{subtitle}</p> : <span />}
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    )
  }
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[34px] font-bold leading-tight lg:text-display">{title}</h1>
        {subtitle && <p className="mt-1 text-[15px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function DiffView({ before, after, path }: { before: string; after: string; path?: string }) {
  return (
    <div className="overflow-x-auto rounded-field border border-border bg-surface-2 font-mono text-xs">
      {path && <div className="border-b border-border px-3 py-1.5 text-muted">{path}</div>}
      <pre className="p-2 leading-5">
        {before.split('\n').map((l, i) => <div key={`b${i}`} className="bg-danger/10 text-danger"><span aria-hidden="true">- </span>{l}</div>)}
        {after.split('\n').map((l, i) => <div key={`a${i}`} className="bg-success/10 text-success"><span aria-hidden="true">+ </span>{l}</div>)}
      </pre>
    </div>
  )
}
