import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Catalog } from '../api/types'
import { Input } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { pick } from '../i18n'
import { CATEGORY_ACCENT, useEditor } from './EditorContext'

export const DRAG_MIME = 'application/x-aisw-node'

export function Palette({ categories, onAdd }: { categories: Catalog['categories']; onAdd: (type: string) => void }) {
  const { t } = useTranslation()
  const { catalog, lang } = useEditor()
  const [q, setQ] = useState('')
  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return categories.map((c) => ({
      ...c,
      items: catalog.filter((n) => n.category === c.id && (!needle || [n.type, n.title.ru, n.title.en, n.description.ru, n.description.en]
        .some((s) => s.toLowerCase().includes(needle)))),
    })).filter((g) => g.items.length)
  }, [catalog, categories, q])

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-surface" aria-label={t('editor.palette')}>
      <div className="border-b border-border p-3">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{t('editor.palette')}</h2>
        <div className="relative">
          <span className="pointer-events-none absolute left-2.5 top-2.5 text-muted"><Icon name="search" size={15} /></span>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('editor.searchNodes')} className="pl-8" aria-label={t('editor.searchNodes')} />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {groups.map((g) => (
          <div key={g.id} className="mb-3">
            <div className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{pick(g.title, lang)}</div>
            {g.items.map((n) => (
              <button
                key={n.type} type="button" draggable
                onDragStart={(e) => { e.dataTransfer.setData(DRAG_MIME, n.type); e.dataTransfer.effectAllowed = 'move' }}
                onClick={() => onAdd(n.type)} data-node-type={n.type}
                title={pick(n.description, lang)}
                className="mb-1 flex w-full cursor-grab items-start gap-2 rounded-lg border border-transparent px-2 py-1.5 text-left hover:border-border hover:bg-surface-2 active:cursor-grabbing"
              >
                <span className="mt-0.5" style={{ color: CATEGORY_ACCENT[n.category] }}><Icon name={n.icon || 'puzzle'} size={15} /></span>
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-medium">{pick(n.title, lang)}</span>
                  <span className="block truncate font-mono text-[10px] text-muted">{n.type}</span>
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </aside>
  )
}
