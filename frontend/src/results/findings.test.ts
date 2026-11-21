import { describe, expect, it } from 'vitest'
import type { Finding } from '../api/types'
import { filterFindings, runVerdict, severityCounts, sortFindings, splitOfficial } from './findings'

const f = (id: string, severity: Finding['severity'], category: Finding['category'], diff?: 'new' | 'existing', path = 'a.kt') =>
  ({ id, severity, category, diff_status: diff, path, line: 1, title: id } as Finding)

const list = [f('1', 'LOW', 'SCA', 'existing', 'z.kt'), f('2', 'CRITICAL', 'SECRET', 'new'), f('3', 'HIGH', 'SAST', 'existing', 'b.kt'),
  f('4', 'HIGH', 'SAST', 'new', 'a.kt'), f('5', 'MEDIUM', 'SCA')]

describe('findings in the results panel', () => {
  it('filters by diff status, severity and category', () => {
    expect(filterFindings(list, { diff: 'new' }).map((x) => x.id)).toEqual(['2', '4'])
    expect(filterFindings(list, { diff: 'existing' }).map((x) => x.id)).toEqual(['1', '3'])
    expect(filterFindings(list, { diff: 'all', severity: 'HIGH' }).map((x) => x.id)).toEqual(['3', '4'])
    expect(filterFindings(list, { diff: 'all', category: 'SCA' }).map((x) => x.id)).toEqual(['1', '5'])
  })
  it('sorts new first, then by severity, then by path', () => {
    expect(sortFindings(list).map((x) => x.id)).toEqual(['2', '4', '3', '5', '1'])
  })
  it('derives a PR verdict only when the run has one', () => {
    expect(runVerdict({ status: 'success', gate: null, verdict: { verdict: 'FAIL' } })).toBe('fail')
    expect(runVerdict({ status: 'success', gate: 'pass', verdict: null })).toBe('pass')
    expect(runVerdict({ status: 'failed', gate: null, verdict: null })).toBe('fail')
    expect(runVerdict({ status: 'success', gate: null, verdict: null })).toBeNull()
    expect(runVerdict({ status: 'running', gate: null, verdict: null })).toBeNull()
  })
})

describe('official findings = what goes into submission.json and the reports', () => {
  it('splits by the export threshold flag and counts severities of the official part only', () => {
    const mk = (id: string, severity: Finding['severity'], official: boolean) => ({ ...f(id, severity, 'SECRET'), official } as Finding)
    const { official, below } = splitOfficial([mk('1', 'HIGH', true), mk('2', 'LOW', false), mk('3', 'HIGH', true), mk('4', 'MEDIUM', false)])
    expect(official.map((x) => x.id)).toEqual(['1', '3'])
    expect(below.map((x) => x.id)).toEqual(['2', '4'])
    expect(severityCounts(official)).toEqual({ HIGH: 2 })
  })
})
