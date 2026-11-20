import type { Lang } from '../api/types'

const RANGES: [number, number][] = [[0, 59], [0, 23], [1, 31], [1, 12], [0, 7]]

function validPart(part: string, [lo, hi]: [number, number]): boolean {
  return part.split(',').every((item) => {
    const [base, step] = item.split('/')
    if (step !== undefined && !(/^\d+$/.test(step) && Number(step) > 0)) return false
    if (base === '*') return true
    const [a, b] = base.split('-')
    const ok = (v: string) => /^\d+$/.test(v) && Number(v) >= lo && Number(v) <= hi
    return b === undefined ? ok(a) : ok(a) && ok(b) && Number(a) <= Number(b)
  })
}

export function isValidCron(expr: string): boolean {
  const parts = expr.trim().split(/\s+/)
  return parts.length === 5 && parts.every((p, i) => validPart(p, RANGES[i]))
}

const DAYS = {
  ru: ['воскресенье', 'понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье'],
  en: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
}
const EVERY_DAY_PREFIX = { ru: ['Каждое', 'Каждый', 'Каждый', 'Каждую', 'Каждый', 'Каждую', 'Каждую', 'Каждое'] }

const pad = (n: string) => n.padStart(2, '0')

export function describeCron(expr: string, lang: Lang): string {
  if (!isValidCron(expr)) return lang === 'ru' ? 'Некорректное cron-выражение' : 'Invalid cron expression'
  const [m, h, dom, mon, dow] = expr.trim().split(/\s+/)
  const num = (s: string) => /^\d+$/.test(s)
  const time = num(m) && num(h) ? `${pad(h)}:${pad(m)}` : null
  if (m.startsWith('*/') && h === '*' && dom === '*' && mon === '*' && dow === '*') {
    return lang === 'ru' ? `Каждые ${m.slice(2)} мин` : `Every ${m.slice(2)} min`
  }
  if (num(m) && h === '*' && dom === '*' && mon === '*' && dow === '*') {
    return m === '0' ? (lang === 'ru' ? 'Каждый час' : 'Every hour')
      : (lang === 'ru' ? `Каждый час в :${pad(m)}` : `Every hour at :${pad(m)}`)
  }
  if (time && dom === '*' && mon === '*') {
    if (dow === '*') return lang === 'ru' ? `Каждый день в ${time}` : `Every day at ${time}`
    if (dow === '1-5') return lang === 'ru' ? `По будням в ${time}` : `On weekdays at ${time}`
    if (dow === '0,6' || dow === '6,0') return lang === 'ru' ? `По выходным в ${time}` : `On weekends at ${time}`
    if (num(dow)) {
      const d = Number(dow)
      return lang === 'ru' ? `${EVERY_DAY_PREFIX.ru[d]} ${DAYS.ru[d]} в ${time}` : `Every ${DAYS.en[d]} at ${time}`
    }
  }
  if (time && num(dom) && mon === '*' && dow === '*') {
    return lang === 'ru' ? `Ежемесячно ${dom}-го числа в ${time}` : `Monthly on day ${dom} at ${time}`
  }
  return lang === 'ru' ? `По расписанию cron «${expr}»` : `On cron schedule "${expr}"`
}

export const CRON_PRESETS: { cron: string; ru: string; en: string }[] = [
  { cron: '0 14 * * *', ru: 'Каждый день в 14:00', en: 'Every day at 14:00' },
  { cron: '0 9 * * 1-5', ru: 'По будням в 09:00', en: 'Weekdays at 09:00' },
  { cron: '0 * * * *', ru: 'Каждый час', en: 'Every hour' },
  { cron: '*/30 * * * *', ru: 'Каждые 30 минут', en: 'Every 30 minutes' },
  { cron: '0 8 * * 1', ru: 'По понедельникам в 08:00', en: 'Mondays at 08:00' },
]
