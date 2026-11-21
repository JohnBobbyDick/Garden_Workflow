import { describe, expect, it } from 'vitest'
import { finaleOrder, nodeVisualState } from './runAnimation'

describe('node look during a run', () => {
  it.each([
    [undefined, false, 'idle'],
    [undefined, true, 'waiting'],
    ['pending', true, 'waiting'],
    ['running', true, 'running'],
    ['success', true, 'success'],
    ['failed', true, 'failed'],
    ['skipped', true, 'skipped'],
    ['cancelled', true, 'failed'],
    ['success', false, 'success'],
  ] as const)('%s (run active: %s) → %s', (status, active, expected) => {
    expect(nodeVisualState(status, active)).toBe(expected)
  })
})

describe('final wave over successful nodes', () => {
  it('goes in start order and skips the rest', () => {
    expect(finaleOrder([
      { id: 'c', status: 'success', startedAt: '2026-11-21T10:00:03Z' },
      { id: 'a', status: 'success', startedAt: '2026-11-21T10:00:01Z' },
      { id: 'x', status: 'failed', startedAt: '2026-11-21T10:00:02Z' },
      { id: 's', status: 'skipped', startedAt: null },
      { id: 'b', status: 'success', startedAt: '2026-11-21T10:00:02Z' },
    ])).toEqual(['a', 'b', 'c'])
  })
  it('keeps nodes without a start time last, stable', () => {
    expect(finaleOrder([{ id: 'n', status: 'success', startedAt: null }, { id: 'm', status: 'success', startedAt: '2026-11-21T10:00:00Z' }]))
      .toEqual(['m', 'n'])
  })
})
