import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { Catalog } from '../api/types'
import { Icon } from '../components/ui/Icon'
import { Palette } from './Palette'

/* Floating node palette over the canvas: «+» in the header, Tab, or «+» under a node. Nodes can be clicked (added in
   view / under the source node and connected) or dragged onto the canvas. */
export function QuickAdd({ open, onClose, categories, onAdd, fromLabel }: {
  open: boolean; onClose: () => void; categories: Catalog['categories']; onAdd: (type: string) => void; fromLabel?: string
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    window.setTimeout(() => ref.current?.querySelector<HTMLInputElement>('input')?.focus(), 20)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div ref={ref} role="dialog" aria-label={t('canvas.addNode')}
      className="quickadd absolute left-3 top-3 z-20 flex max-h-[calc(100%-24px)] w-[300px] flex-col rounded-card border border-border bg-surface p-4 shadow-pop">
      <div className="mb-1 flex items-start justify-between gap-2">
        {fromLabel ? <p className="text-[13px] text-muted">{t('canvas.addAfterNode', { name: fromLabel })}</p> : <span />}
        <button type="button" onClick={onClose} aria-label={t('common.close')} className="-mr-1 -mt-1 rounded-chip p-1.5 text-muted hover:bg-soft hover:text-fg">
          <Icon name="x" size={15} />
        </button>
      </div>
      <div className="min-h-0 overflow-y-auto pr-1">
        <Palette categories={categories} onAdd={onAdd} />
      </div>
    </div>
  )
}
