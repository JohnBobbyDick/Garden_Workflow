import clsx from 'clsx'
import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Icon } from '../components/ui/Icon'

/* Second-level panel sliding over the canvas from the right: the canvas and the open check stay where they are.
   Esc / backdrop close it; focus moves into the panel and returns to where it was. */
export function Drawer({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    window.setTimeout(() => ref.current?.querySelector<HTMLElement>('button, a, input, select, textarea')?.focus(), 30)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose() }
      if (e.key === 'Tab' && ref.current) {
        const items = [...ref.current.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
          .filter((el) => !el.hasAttribute('disabled'))
        if (!items.length) return
        const first = items[0]
        const last = items[items.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => { window.removeEventListener('keydown', onKey, true); prev?.focus() }
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-40 flex justify-end" role="presentation">
      <div className="drawer-backdrop absolute inset-0 bg-fg/25" onMouseDown={onClose} aria-hidden="true" />
      <div ref={ref} role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}
        className={clsx('drawer-panel relative flex h-full flex-col border-l border-border bg-bg shadow-pop',
          wide ? 'w-[min(1180px,92vw)]' : 'w-[min(920px,80vw)]')}>
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-5">
          <h2 className="text-lg font-bold">{title}</h2>
          <button type="button" onClick={onClose} aria-label={t('common.close')} className="rounded-chip p-2 text-muted hover:bg-soft hover:text-fg">
            <Icon name="x" size={18} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
