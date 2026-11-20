import { describe, expect, it } from 'vitest'
import en from './en'
import ru from './ru'

type Dict = { [k: string]: string | Dict }

function entries(obj: Dict, prefix = ''): [string, string][] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === 'object' ? entries(v, `${prefix}${k}.`) : [[`${prefix}${k}`, v] as [string, string]])
}

describe('i18n', () => {
  it('RU and EN have the same keys', () => {
    expect(entries(en).map(([k]) => k).sort()).toEqual(entries(ru).map(([k]) => k).sort())
  })
  it('has no empty strings in either language', () => {
    const empty = [...entries(ru), ...entries(en)].filter(([, v]) => v.trim() === '').map(([k]) => k)
    expect(empty).toEqual([])
  })
  it('placeholders match between languages', () => {
    const ph = (s: string) => (s.match(/\{\{\w+\}\}/g) ?? []).sort().join(',')
    const enMap = Object.fromEntries(entries(en))
    const bad = entries(ru).filter(([k, v]) => ph(v) !== ph(enMap[k] ?? '')).map(([k]) => k)
    expect(bad).toEqual([])
  })
})
