import { describe, expect, it } from 'vitest'
import { fieldsFromSchema, validateConfig } from './schemaForm'

const schema = {
  type: 'object',
  properties: {
    host: { type: 'string', title: 'Сервер', 'x-title-en': 'Host', minLength: 1 },
    port: { type: 'integer', title: 'Порт', 'x-title-en': 'Port', minimum: 1, maximum: 65535, default: 587 },
    security: { type: 'string', title: 'Шифрование', enum: ['starttls', 'tls', 'none'] },
    tls: { type: 'boolean', title: 'TLS' },
    to: { type: 'array', title: 'Кому', items: { type: 'string' }, minItems: 1 },
    rules: { type: 'array', title: 'Правила', items: { type: 'string', enum: ['a', 'b'] } },
    password: { type: 'string', title: 'Пароль', credential_ref: true, 'x-widget': 'credential', 'x-credential-kind': 'smtp' },
    cron: { type: 'string', title: 'Cron', 'x-widget': 'cron' },
    headers: { type: 'object', title: 'Заголовки', 'x-widget': 'keyvalue' },
  },
  required: ['host', 'to'],
}

describe('schema form', () => {
  it('maps JSON Schema to widgets with localized labels', () => {
    const f = Object.fromEntries(fieldsFromSchema(schema, 'en').map((x) => [x.key, x]))
    expect(f.host).toMatchObject({ kind: 'string', label: 'Host', required: true })
    expect(f.port).toMatchObject({ kind: 'integer', min: 1, max: 65535, default: 587 })
    expect(f.security.kind).toBe('enum')
    expect(f.tls.kind).toBe('boolean')
    expect(f.to.kind).toBe('tags')
    expect(f.rules.kind).toBe('multiselect')
    expect(f.password).toMatchObject({ kind: 'credential', credentialKind: 'smtp' })
    expect(f.cron.kind).toBe('cron')
    expect(f.headers.kind).toBe('keyvalue')
    expect(fieldsFromSchema(schema, 'ru')[0].label).toBe('Сервер')
  })
  it('validates required, ranges and types', () => {
    const errs = validateConfig(schema, { port: 70000, to: [] }, 'ru')
    expect(Object.keys(errs).sort()).toEqual(['host', 'port', 'to'])
    expect(validateConfig(schema, { host: 'smtp', to: ['a@b.c'], port: 25 }, 'ru')).toEqual({})
  })
})
