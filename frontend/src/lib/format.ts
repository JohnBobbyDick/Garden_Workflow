import type { Lang } from '../api/types'

const locale = (lang: Lang) => (lang === 'en' ? 'en-GB' : 'ru-RU')

export function fmtDate(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat(locale(lang), { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso))
}

export function fmtNumber(n: number | null | undefined, lang: Lang): string {
  if (n === null || n === undefined) return '—'
  return new Intl.NumberFormat(locale(lang)).format(n)
}

export function fmtDuration(ms: number | null | undefined, lang: Lang): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return lang === 'ru' ? `${ms} мс` : `${ms} ms`
  const s = ms / 1000
  if (s < 60) return lang === 'ru' ? `${s.toFixed(1)} с` : `${s.toFixed(1)} s`
  const m = Math.floor(s / 60)
  return lang === 'ru' ? `${m} мин ${Math.round(s % 60)} с` : `${m} min ${Math.round(s % 60)} s`
}

export function fmtRelative(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return '—'
  const diff = (new Date(iso).getTime() - Date.now()) / 1000
  const rtf = new Intl.RelativeTimeFormat(locale(lang), { numeric: 'auto' })
  const abs = Math.abs(diff)
  if (abs < 60) return rtf.format(Math.round(diff), 'second')
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  return rtf.format(Math.round(diff / 86400), 'day')
}

export const SEVERITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const
