import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { CustomNode } from '../api/types'
import { Button, Input } from '../components/ui'

interface Props {
  onSave: (node: Omit<CustomNode, 'id'>) => void
  onCancel: () => void
  saving: boolean
}

export function CustomNodeForm({ onSave, onCancel, saving }: Props) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [rows, setRows] = useState([{ id: 0, output: '', path: '' }])
  const nextId = useRef(1)
  const keys = rows.map((r) => r.output.trim())
  const reserved = keys.some((k) => ['findings', 'constructor', 'prototype'].includes(k))
  const invalid = new Set(keys.filter(Boolean)).size !== keys.filter(Boolean).length ||
    keys.some((k) => k !== '' && !/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(k))
  const update = (id: number, field: 'output' | 'path', v: string) =>
    setRows((old) => old.map((r) => r.id === id ? { ...r, [field]: v } : r))
  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault()
      if (name.trim() && !invalid && !reserved && !saving) {
        onSave({ name: name.trim(), fields: Object.fromEntries(rows.map((r) => [r.output.trim(), r.path.trim()])) })
      }
    }}>
      <h2 className="text-lg font-bold">{t('customNodes.create')}</h2>
      <p className="text-sm text-muted">{t('customNodes.hint')}</p>
      <label className="block text-sm font-semibold">{t('common.name')}
        <Input autoFocus required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <p className="text-xs text-muted">{t('customNodes.example')}</p>
      {rows.map((row) => (
        <fieldset key={row.id} className="space-y-2 rounded-chip border border-border p-2.5">
          <label className="block text-xs font-semibold">{t('customNodes.path')}
            <Input placeholder="counts.HIGH" required maxLength={512} pattern="=.+|[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*"
              value={row.path} onChange={(e) => update(row.id, 'path', e.target.value)} />
          </label>
          <label className="block text-xs font-semibold">{t('customNodes.output')}
            <Input placeholder="high" required maxLength={64} value={row.output} onChange={(e) => update(row.id, 'output', e.target.value)} />
          </label>
          {rows.length > 1 && <Button size="sm" type="button" icon="trash" onClick={() => setRows(rows.filter((r) => r.id !== row.id))}>
            {t('common.remove')}
          </Button>}
        </fieldset>
      ))}
      {rows.length < 24 && <Button type="button" size="sm" icon="plus"
        onClick={() => setRows([...rows, { id: nextId.current++, output: '', path: '' }])}>{t('customNodes.add')}</Button>}
      {(invalid || reserved) && <p role="alert" className="text-xs text-danger">{t(reserved ? 'customNodes.reserved' : 'customNodes.invalid')}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={saving} disabled={invalid || reserved || !name.trim()} variant="primary">{t('customNodes.save')}</Button>
        <Button type="button" disabled={saving} onClick={onCancel}>{t('common.cancel')}</Button>
      </div>
    </form>
  )
}
