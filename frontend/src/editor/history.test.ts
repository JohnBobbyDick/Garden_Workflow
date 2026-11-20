import { describe, expect, it } from 'vitest'
import { History } from './history'

describe('undo/redo history', () => {
  it('undoes and redoes snapshots in order', () => {
    const h = new History<number>(10)
    h.push(1)
    h.push(2)
    h.push(3)
    expect(h.undo(4)).toBe(3)
    expect(h.undo(3)).toBe(2)
    expect(h.redo(2)).toBe(3)
    expect(h.canRedo).toBe(true)
  })
  it('a new change clears the redo stack', () => {
    const h = new History<string>(10)
    h.push('a')
    h.undo('b')
    h.push('c')
    expect(h.canRedo).toBe(false)
  })
  it('respects the limit', () => {
    const h = new History<number>(2)
    h.push(1)
    h.push(2)
    h.push(3)
    expect(h.undo(9)).toBe(3)
    expect(h.undo(3)).toBe(2)
    expect(h.undo(2)).toBeUndefined()
  })
})
