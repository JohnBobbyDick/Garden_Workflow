import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Catalog, NodeSpec } from '../api/types'
import { Input } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { pick } from '../i18n'
import { useEditor } from './EditorContext'

export const DRAG_MIME = 'application/x-aisw-node'

/* Quick-add chips from the design («Расписание, Secrets, SCA, SAST, Условие, Webhook») + the full searchable catalog. */
const QUICK = ['trigger.schedule', 'scanner.secrets', 'scanner.sca', 'scanner.sast', 'logic.if_else', 'notify.webhook']

function NodeChip({ n, onAdd, lang, full }: { n: NodeSpec; onAdd: (type: string) => void; lang: 'ru' | 'en'; full?: boolean }) {
  return (
    <button
      type="button" draggable data-node-type={n.type} title={pick(n.description, lang)}
      onDragStart={(e) => { e.dataTransfer.setData(DRAG_MIME, n.type); e.dataTransfer.effectAllowed = 'move' }}
      onClick={() => onAdd(n.type)}
      className="flex min-h-8 w-full cursor-grab items-center gap-1.5 rounded-chip bg-soft px-2.5 py-1 text-left text-[13px] font-bold text-primary hover:brightness-95 active:cursor-grabbing"
    >
      <Icon name={n.icon || 'puzzle'} size={14} />
      <span className="min-w-0">
        <span className="block truncate">{pick(n.title, lang)}</span>
        {full && <span className="block truncate font-mono text-[10px] font-normal text-muted">{n.type}</span>}
      </span>
    </button>
  )
}

export function Palette({ categories, onAdd }: { categories: Catalog['categories']; onAdd: (type: string) => void }) {
  const { t } = useTranslation()
  const { catalog, lang } = useEditor()
  const [q, setQ] = useState('')
  const [all, setAll] = useState(false)
  const quick = QUICK.map((ty) => catalog.find((n) => n.type === ty)).filter((n): n is NodeSpec => !!n)
  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return categories.map((c) => ({
      ...c,
      items: catalog.filter((n) => n.category === c.id && (!needle || [n.type, n.title.ru, n.title.en, n.description.ru, n.description.en]
        .some((s) => s.toLowerCase().includes(needle)))),
    })).filter((g) => g.items.length)
  }, [catalog, categories, q])
  const showAll = all || q.trim() !== ''

  return (
    <div aria-label={t('editor.palette')}>
      <h2 className="text-lg font-bold">{t('wf.nodes')}</h2>
      <p className="mb-3 text-[15px] text-muted">{t('wf.addToFlow')}</p>
      <div className="relative mb-3">
        <span className="pointer-events-none absolute left-2.5 top-2.5 text-muted"><Icon name="search" size={15} /></span>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('editor.searchNodes')} className="pl-8" aria-label={t('editor.searchNodes')} />
      </div>
      {!showAll && <div className="space-y-2">{quick.map((n) => <NodeChip key={n.type} n={n} onAdd={onAdd} lang={lang} />)}</div>}
      <button type="button" className="mt-3 flex items-center gap-1 text-[13px] font-bold text-primary hover:underline" aria-expanded={showAll}
        onClick={() => { setAll((a) => !a); setQ('') }}>
        <Icon name="chevron-right" size={13} className={showAll ? 'rotate-90' : ''} />
        {showAll ? t('wf.fewerNodes') : t('wf.allNodes', { n: catalog.length })}
      </button>
      {showAll && (
        <div className="mt-2 max-h-[420px] overflow-y-auto pr-1">
          {groups.map((g) => (
            <div key={g.id} className="mb-3">
              <div className="pb-1 text-[11px] font-bold uppercase tracking-wide text-muted">{pick(g.title, lang)}</div>
              <div className="space-y-1.5">{g.items.map((n) => <NodeChip key={n.type} n={n} onAdd={onAdd} lang={lang} full />)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
