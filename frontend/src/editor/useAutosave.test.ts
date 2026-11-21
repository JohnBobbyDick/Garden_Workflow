import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAutosave } from './useAutosave'

describe('useAutosave: debounced save, flushed before a run', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('saves once after the delay when dirty', async () => {
    const save = vi.fn(async () => true)
    const { rerender } = renderHook(({ dirty, rev }) => useAutosave(save, dirty, 800, rev), { initialProps: { dirty: true, rev: 1 } })
    rerender({ dirty: true, rev: 2 })
    rerender({ dirty: true, rev: 3 })
    await act(async () => { vi.advanceTimersByTime(799) })
    expect(save).not.toHaveBeenCalled()
    await act(async () => { vi.advanceTimersByTime(1) })
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('does nothing when clean', async () => {
    const save = vi.fn(async () => true)
    renderHook(() => useAutosave(save, false, 800, 1))
    await act(async () => { vi.advanceTimersByTime(2000) })
    expect(save).not.toHaveBeenCalled()
  })

  it('flush saves immediately and cancels the pending timer', async () => {
    const save = vi.fn(async () => true)
    const { result } = renderHook(() => useAutosave(save, true, 800, 1))
    let ok = false
    await act(async () => { ok = await result.current.flush() })
    expect(ok).toBe(true)
    await act(async () => { vi.advanceTimersByTime(2000) })
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('flush on a clean graph does not save', async () => {
    const save = vi.fn(async () => true)
    const { result } = renderHook(() => useAutosave(save, false, 800, 1))
    await act(async () => { expect(await result.current.flush()).toBe(true) })
    expect(save).not.toHaveBeenCalled()
  })
})
