import { describe, expect, it } from 'vitest'
import { describeCron, isValidCron } from './cron'

describe('cron', () => {
  it('describes common schedules in RU and EN', () => {
    expect(describeCron('0 14 * * *', 'ru')).toBe('Каждый день в 14:00')
    expect(describeCron('30 9 * * 1-5', 'ru')).toBe('По будням в 09:30')
    expect(describeCron('0 14 * * *', 'en')).toBe('Every day at 14:00')
    expect(describeCron('*/15 * * * *', 'ru')).toBe('Каждые 15 мин')
    expect(describeCron('0 * * * *', 'en')).toBe('Every hour')
    expect(describeCron('0 8 * * 1', 'ru')).toBe('Каждый понедельник в 08:00')
    expect(describeCron('0 3 1 * *', 'en')).toBe('Monthly on day 1 at 03:00')
  })
  it('validates fields', () => {
    expect(isValidCron('0 14 * * *')).toBe(true)
    expect(isValidCron('61 * * * *')).toBe(false)
    expect(isValidCron('* * *')).toBe(false)
    expect(isValidCron('*/5 0-6 1,15 * 1-5')).toBe(true)
  })
})
