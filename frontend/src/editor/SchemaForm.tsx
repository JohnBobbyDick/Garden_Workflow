import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, apiFetch } from '../api/client'
import { useCredentials, useWs } from '../api/hooks'
import type { JsonSchema, Lang } from '../api/types'
import { Badge, Button, Input, Select, Switch, Textarea } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { CRON_PRESETS, describeCron, isValidCron } from '../lib/cron'
import { fieldsFromSchema, validateConfig, type FieldDef } from '../lib/schemaForm'
import { toast } from '../store/toast'

export const EXPRESSION_VARS = ['findings.count', 'severity.max', 'severity.critical', 'severity.high', 'category',
  'new_findings.count', 'verdict', 'gate', 'score.value', 'score.delta']
export const EXPRESSION_OPS = ['>=', '==', '!=', '>', '<', 'and', 'or', 'not', 'HIGH', 'CRITICAL']
export const TEMPLATE_VARS = ['findings.count', 'severity.critical', 'severity.high', 'new_findings.count', 'verdict',
  'score.value', 'score.delta', 'run.url', 'ai.summary', 'project.name', 'workflow.name']

interface Props {
  schema: JsonSchema
  value: Record<string, unknown>
  onChange: (v: Record<string, unknown>) => void
  lang: Lang
  serverErrors?: Record<string, string>
  readOnly?: boolean
}

function Chips({ items, onPick, label }: { items: string[]; onPick: (s: string) => void; label: string }) {
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1" aria-label={label}>
      <span className="text-[11px] text-muted">{label}:</span>
      {items.map((v) => (
        <button key={v} type="button" onClick={() => onPick(v)}
          className="rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] hover:border-primary">{v}</button>
      ))}
    </div>
  )
}

function InsertableText({ value, onChange, kind, id, invalid, readOnly }: {
  value: string; onChange: (v: string) => void; kind: 'expression' | 'template'; id: string; invalid?: boolean; readOnly?: boolean
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLTextAreaElement>(null)
  const insert = (token: string) => {
    const el = ref.current
    const text = kind === 'template' ? `{{${token}}}` : token
    const pos = el?.selectionStart ?? value.length
    const pre = value.slice(0, pos)
    const sep = kind === 'expression' && pre && !pre.endsWith(' ') ? ' ' : ''
    const next = pre + sep + text + (kind === 'expression' ? ' ' : '') + value.slice(el?.selectionEnd ?? pos)
    onChange(next)
    requestAnimationFrame(() => el?.focus())
  }
  return (
    <>
      <Textarea ref={ref} id={id} value={value} onChange={(e) => onChange(e.target.value)} invalid={invalid} readOnly={readOnly}
        rows={kind === 'expression' ? 2 : 4} spellCheck={false} />
      {!readOnly && (kind === 'expression'
        ? <><Chips items={EXPRESSION_VARS} onPick={insert} label={t('editor.expressionVars')} /><Chips items={EXPRESSION_OPS} onPick={insert} label={t('editor.operators')} /></>
        : <Chips items={TEMPLATE_VARS} onPick={insert} label={t('editor.templateVars')} />)}
    </>
  )
}

function CronField({ value, onChange, lang, id, readOnly }: { value: string; onChange: (v: string) => void; lang: Lang; id: string; readOnly?: boolean }) {
  const { t } = useTranslation()
  const valid = !value || isValidCron(value)
  return (
    <>
      <div className="flex gap-2">
        <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder="0 14 * * *" className="font-mono" invalid={!valid} readOnly={readOnly} />
        <Select aria-label={t('editor.cronPresets')} value="" disabled={readOnly} className="w-40" onChange={(e) => e.target.value && onChange(e.target.value)}>
          <option value="">{t('editor.cronPresets')}</option>
          {CRON_PRESETS.map((p) => <option key={p.cron} value={p.cron}>{lang === 'en' ? p.en : p.ru}</option>)}
        </Select>
      </div>
      {value && <p className={valid ? 'mt-1 text-xs text-success' : 'mt-1 text-xs text-danger'}>{describeCron(value, lang)}</p>}
    </>
  )
}

function TagsField({ value, onChange, id, options, readOnly }: { value: string[]; onChange: (v: string[]) => void; id: string; options?: string[]; readOnly?: boolean }) {
  const [draft, setDraft] = useState('')
  if (options) {
    return (
      <div className="flex flex-wrap gap-1.5" id={id} role="group">
        {options.map((o) => {
          const on = value.includes(o)
          return (
            <button key={o} type="button" aria-pressed={on} disabled={readOnly}
              onClick={() => onChange(on ? value.filter((v) => v !== o) : [...value, o])}
              className={on ? 'rounded-full border border-primary bg-primary/15 px-2 py-0.5 text-xs text-primary'
                : 'rounded-full border border-border px-2 py-0.5 text-xs text-muted hover:text-fg'}>{o}</button>
          )
        })}
      </div>
    )
  }
  const add = () => {
    const v = draft.trim()
    if (v && !value.includes(v)) onChange([...value, v])
    setDraft('')
  }
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap gap-1">
        {value.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs">
            {v}{!readOnly && <button type="button" aria-label={`remove ${v}`} onClick={() => onChange(value.filter((x) => x !== v))}><Icon name="x" size={11} /></button>}
          </span>
        ))}
      </div>
      {!readOnly && <Input id={id} value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={add}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add() } }} placeholder="Enter ↵" />}
    </div>
  )
}

function CredentialSelect({ value, onChange, kind, id, readOnly }: { value: string; onChange: (v: string) => void; kind?: string; id: string; readOnly?: boolean }) {
  const { t } = useTranslation()
  const creds = useCredentials()
  const list = [...(creds.data ?? [])].sort((a, b) => Number(b.kind === kind) - Number(a.kind === kind))
  return (
    <>
      <Select id={id} value={value} disabled={readOnly} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t('editor.credentialNone')}</option>
        {list.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.kind} · {c.display}</option>)}
      </Select>
      {!creds.isLoading && list.length === 0 && (
        <p className="mt-1 text-xs text-muted"><Link className="text-primary hover:underline" to="/settings?tab=credentials">{t('editor.credentialMissing')}</Link></p>
      )}
    </>
  )
}

function KeyValue({ value, onChange, credential, readOnly }: { value: Record<string, string>; onChange: (v: Record<string, string>) => void; credential?: boolean; readOnly?: boolean }) {
  const { t } = useTranslation()
  const rows = Object.entries(value)
  const set = (i: number, k: string, v: string) => {
    const next = rows.map((r, j) => (j === i ? [k, v] : r))
    onChange(Object.fromEntries(next))
  }
  return (
    <div className="space-y-1.5">
      {rows.map(([k, v], i) => (
        <div key={i} className="flex gap-1.5">
          <Input aria-label={t('common.key')} value={k} readOnly={readOnly} onChange={(e) => set(i, e.target.value, v)} className="w-2/5" />
          {credential ? <div className="flex-1"><CredentialSelect id={`kv-${i}`} value={v} readOnly={readOnly} onChange={(nv) => set(i, k, nv)} /></div>
            : <Input aria-label={t('common.value')} value={v} readOnly={readOnly} onChange={(e) => set(i, k, e.target.value)} />}
          {!readOnly && <Button size="sm" variant="ghost" icon="trash" aria-label={t('common.remove')} onClick={() => onChange(Object.fromEntries(rows.filter((_, j) => j !== i)))} />}
        </div>
      ))}
      {!readOnly && <Button size="sm" icon="plus" onClick={() => onChange({ ...value, [`key${rows.length + 1}`]: '' })}>{t('editor.addItem')}</Button>}
    </div>
  )
}

export function UploadField({ value, onChange, id, readOnly }: { value: string; onChange: (v: string) => void; id: string; readOnly?: boolean }) {
  const ws = useWs()
  const [busy, setBusy] = useState(false)
  const upload = async (file: File) => {
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      if (ws) fd.append('workspace_id', ws)
      const r = await apiFetch('/api/uploads', { method: 'POST', body: fd })
      onChange((await r.json()).id)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex items-center gap-2">
      <Input id={id} value={value} readOnly className="font-mono text-xs" />
      {!readOnly && <label className="inline-flex h-9 cursor-pointer items-center rounded-field border border-border bg-surface-2 px-3 text-sm">
        {busy ? '…' : <Icon name="upload" size={15} />}
        <input type="file" className="sr-only" accept=".zip,.tar,.tgz,.gz" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      </label>}
    </div>
  )
}

function Widget({ f, value, set, lang, id, invalid, readOnly }: {
  f: FieldDef; value: unknown; set: (v: unknown) => void; lang: Lang; id: string; invalid: boolean; readOnly?: boolean
}) {
  const str = (value ?? '') as string
  switch (f.kind) {
    case 'boolean': return <Switch id={id} checked={!!value} onChange={(v) => !readOnly && set(v)} label={f.label} />
    case 'integer': case 'number':
      return <Input id={id} type="number" readOnly={readOnly} invalid={invalid} min={f.min} max={f.max} value={value === undefined || value === null ? '' : String(value)}
        onChange={(e) => set(e.target.value === '' ? undefined : f.kind === 'integer' ? parseInt(e.target.value, 10) : parseFloat(e.target.value))} />
    case 'enum':
      return <Select id={id} disabled={readOnly} invalid={invalid} value={str} onChange={(e) => set(e.target.value)}>
        {!f.required && !f.options?.includes('') && <option value="">—</option>}
        {f.options?.map((o) => <option key={o} value={o}>{o || '—'}</option>)}
      </Select>
    case 'multiselect': return <TagsField id={id} readOnly={readOnly} value={(value as string[]) ?? []} onChange={set} options={f.options} />
    case 'tags': return <TagsField id={id} readOnly={readOnly} value={(value as string[]) ?? []} onChange={set} />
    case 'keyvalue': case 'object': return <KeyValue readOnly={readOnly} value={(value as Record<string, string>) ?? {}} onChange={set} />
    case 'keyvalue-credential': return <KeyValue credential readOnly={readOnly} value={(value as Record<string, string>) ?? {}} onChange={set} />
    case 'credential': return <CredentialSelect id={id} readOnly={readOnly} value={str} onChange={(v) => set(v || undefined)} kind={f.credentialKind} />
    case 'cron': return <CronField id={id} readOnly={readOnly} value={str} onChange={set} lang={lang} />
    case 'expression': return <InsertableText id={id} readOnly={readOnly} kind="expression" value={str} onChange={set} invalid={invalid} />
    case 'template': return <InsertableText id={id} readOnly={readOnly} kind="template" value={str} onChange={set} invalid={invalid} />
    case 'textarea': return <Textarea id={id} readOnly={readOnly} value={str} onChange={(e) => set(e.target.value)} invalid={invalid} />
    case 'upload': return <UploadField id={id} readOnly={readOnly} value={str} onChange={set} />
    default: return <Input id={id} readOnly={readOnly} value={str} onChange={(e) => set(e.target.value || undefined)} invalid={invalid} />
  }
}

function TelegramLookup({ token, username, onFound }: { token: string; username: string; onFound: (id: string) => void }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const request = useRef<AbortController | null>(null)
  const apply = useRef(onFound)
  apply.current = onFound
  useEffect(() => () => request.current?.abort(), [])
  const lookup = async () => {
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    try {
      const chat = await api<{ chat_id: string }>(`/api/credentials/${token}/telegram-chat`, {
        method: 'POST', json: { username }, signal: controller.signal,
      })
      if (!controller.signal.aborted) apply.current(chat.chat_id)
    } catch (e) {
      if (!controller.signal.aborted) toast.error((e as Error).message)
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  return <Button type="button" size="sm" className="mt-2" loading={busy}
    disabled={!token || !/^@?[A-Za-z][A-Za-z0-9_]{0,31}$/.test(username)} onClick={lookup}>
    {t('editor.findTelegramChat')}
  </Button>
}

export function SchemaForm({ schema, value, onChange, lang, serverErrors = {}, readOnly }: Props) {
  const { t } = useTranslation()
  const base = useId()
  const fields = useMemo(() => fieldsFromSchema(schema, lang), [schema, lang])
  const clientErrors = useMemo(() => validateConfig(schema, value, lang), [schema, value, lang])
  if (!fields.length) return <p className="text-sm text-muted">{t('editor.noParams')}</p>
  return (
    <div>
      {fields.map((f) => {
        const id = `${base}-${f.key}`
        const err = clientErrors[f.key] ?? serverErrors[f.key]
        const v = value[f.key] ?? f.default
        return (
          <div key={f.key} className="mb-3">
            {f.kind !== 'boolean' && (
              <label htmlFor={id} className="label flex items-center gap-1.5">
                {f.label}{f.required && <span className="text-danger" aria-hidden="true">*</span>}
                {f.needsUser && (value[f.key] === undefined || value[f.key] === '') && <Badge tone="warning">{t('editor.needsInput')}</Badge>}
              </label>
            )}
            <Widget f={f} value={v} lang={lang} id={id} invalid={!!err} readOnly={readOnly}
              set={(nv) => onChange({ ...value, [f.key]: nv })} />
            {!readOnly && schema.properties?.[f.key]?.['x-widget'] === 'telegram-chat' &&
              <TelegramLookup key={JSON.stringify([value.bot_token, v])} token={String(value.bot_token ?? '')}
                username={String(v ?? '').trim()} onFound={id => onChange({ ...value, [f.key]: id })} />}
            {err ? <p className="mt-1 text-xs text-danger" role="alert">{err}</p>
              : f.description ? <p className="mt-1 text-xs text-muted">{f.description}</p> : null}
          </div>
        )
      })}
    </div>
  )
}
