import { useCallback, useEffect, useRef, useState } from 'react'

/** Debounced autosave: every change (``revision``) restarts the timer; ``flush`` saves now (before a run).
 *  Returns ``true`` when nothing had to be saved or the save succeeded. */
export function useAutosave(save: () => Promise<boolean>, dirty: boolean, delayMs = 800, revision: unknown = undefined) {
  const timer = useRef<number | null>(null)
  const saveRef = useRef(save)
  const dirtyRef = useRef(dirty)
  const revisionRef = useRef(revision)
  const inFlight = useRef<Promise<boolean> | null>(null)
  const [pending, setPending] = useState(false)
  saveRef.current = save
  dirtyRef.current = dirty
  revisionRef.current = revision

  const cancel = () => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null }
  }

  const flush = useCallback(() => {
    cancel()
    if (inFlight.current) return inFlight.current
    if (!dirtyRef.current) return Promise.resolve(true)
    setPending(true)
    const saveLatest = async () => {
      while (dirtyRef.current) {
        const writing = revisionRef.current
        if (!(await saveRef.current())) return false
        if (writing === revisionRef.current) break
        cancel()
      }
      return true
    }
    inFlight.current = saveLatest().finally(() => {
      inFlight.current = null
      setPending(false)
    })
    return inFlight.current
  }, [])

  useEffect(() => {
    if (!dirty) { cancel(); setPending(false); return }
    setPending(true)
    timer.current = window.setTimeout(() => { void flush() }, delayMs)
    return cancel
  }, [dirty, delayMs, revision, flush])

  return { flush, pending }
}
