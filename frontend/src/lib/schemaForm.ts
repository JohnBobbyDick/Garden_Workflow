import type { JsonSchema, JsonSchemaProp, Lang } from '../api/types'

export type FieldKind = 'string' | 'number' | 'integer' | 'boolean' | 'enum' | 'multiselect' | 'tags' | 'keyvalue'
  | 'keyvalue-credential' | 'credential' | 'cron' | 'expression' | 'template' | 'textarea' | 'upload' | 'object'

export interface FieldDef {
  key: string
  kind: FieldKind
  label: string
  description?: string
  required: boolean
  options?: string[]
  default?: unknown
  min?: number
  max?: number
  credentialKind?: string
  needsUser: boolean
}

function primaryType(p: JsonSchemaProp): string {
  return Array.isArray(p.type) ? (p.type.find((t) => t !== 'null') ?? 'string') : (p.type ?? 'string')
}

export function fieldKind(p: JsonSchemaProp): FieldKind {
  const widget = p['x-widget'] as string | undefined
  if (p.credential_ref) return 'credential'
  if (widget && ['cron', 'expression', 'template', 'textarea', 'keyvalue', 'keyvalue-credential', 'upload'].includes(widget)) {
    return widget as FieldKind
  }
  const t = primaryType(p)
  if (t === 'array') return p.items?.enum ? 'multiselect' : 'tags'
  if (t === 'object') return 'keyvalue'
  if (p.enum) return 'enum'
  if (t === 'boolean' || t === 'integer' || t === 'number') return t
  return 'string'
}

export function fieldsFromSchema(schema: JsonSchema, lang: Lang): FieldDef[] {
  const required = new Set(schema.required ?? [])
  return Object.entries(schema.properties ?? {}).map(([key, p]) => {
    const kind = fieldKind(p)
    const label = (lang === 'en' ? (p['x-title-en'] as string) : p.title) || p.title || key
    const description = (lang === 'en' ? (p['x-description-en'] as string) : p.description) || undefined
    const options = (kind === 'multiselect' ? p.items?.enum : p.enum)?.map(String)
    return {
      key, kind, label, description, required: required.has(key), options, default: p.default,
      min: p.minimum, max: p.maximum, credentialKind: p['x-credential-kind'] as string | undefined,
      needsUser: !!p['x-required-user-input'] || (!!p.credential_ref && required.has(key)),
    }
  })
}

const UNFILLED_PARAM = /^\{\{param:[^}]+\}\}$/

/** Labels of fields that cannot be guessed (tokens, chat ids, repo paths) and are still empty or an unfilled template parameter. */
export function missingUserInput(schema: JsonSchema, config: Record<string, unknown>, lang: Lang): string[] {
  return fieldsFromSchema(schema, lang)
    .filter((f) => {
      if (!f.needsUser) return false
      const v = config[f.key]
      return v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0)
        || (typeof v === 'string' && UNFILLED_PARAM.test(v))
    })
    .map((f) => f.label)
}

const MSG = {
  ru: { required: 'обязательное поле', min: 'не меньше {n}', max: 'не больше {n}', number: 'нужно число',
    integer: 'нужно целое число', minItems: 'добавьте хотя бы {n}', pattern: 'неверный формат', minLength: 'слишком коротко' },
  en: { required: 'required', min: 'at least {n}', max: 'at most {n}', number: 'must be a number',
    integer: 'must be an integer', minItems: 'add at least {n}', pattern: 'invalid format', minLength: 'too short' },
}

export function validateConfig(schema: JsonSchema, config: Record<string, unknown>, lang: Lang): Record<string, string> {
  const m = MSG[lang]
  const errors: Record<string, string> = {}
  const required = new Set(schema.required ?? [])
  for (const [key, p] of Object.entries(schema.properties ?? {})) {
    const v = config[key]
    const empty = v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0)
    if (empty) {
      if (required.has(key)) errors[key] = m.required
      continue
    }
    const t = primaryType(p)
    if (t === 'integer' || t === 'number') {
      if (typeof v !== 'number' || Number.isNaN(v)) { errors[key] = m.number; continue }
      if (t === 'integer' && !Number.isInteger(v)) { errors[key] = m.integer; continue }
      if (p.minimum !== undefined && v < p.minimum) errors[key] = m.min.replace('{n}', String(p.minimum))
      else if (p.maximum !== undefined && v > p.maximum) errors[key] = m.max.replace('{n}', String(p.maximum))
    }
    if (t === 'array' && Array.isArray(v) && p.minItems !== undefined && v.length < p.minItems) {
      errors[key] = m.minItems.replace('{n}', String(p.minItems))
    }
    if (t === 'string' && typeof v === 'string') {
      if (p.minLength !== undefined && v.length < p.minLength) errors[key] = m.minLength
      else if (p.pattern && !new RegExp(p.pattern).test(v)) errors[key] = m.pattern
    }
  }
  return errors
}

export function defaultsOf(schema: JsonSchema): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, p] of Object.entries(schema.properties ?? {})) if (p.default !== undefined) out[k] = structuredClone(p.default)
  return out
}
