import { useCallback, useEffect, useRef, useState } from 'react'

/** Debounced autosave: every change (``revision``) restarts the timer; ``flush`` saves now (before a run).
 *  Returns ``true`` when nothing had to be saved or the save succeeded. */
export function useAutosave(save: () => Promise<boolean>, dirty: boolean, delayMs = 800, revision: unknown = undefined) {
  const timer = useRef<number | null>(null)
  const saveRef = useRef(save)
  const dirtyRef = useRef(dirty)
  const [pending, setPending] = useState(false)
  saveRef.current = save
  dirtyRef.current = dirty

  const cancel = () => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null }
  }

  useEffect(() => {
    if (!dirty) { cancel(); setPending(false); return }
    cancel()
    setPending(true)
    timer.current = window.setTimeout(() => {
      timer.current = null
      void saveRef.current().finally(() => setPending(false))
    }, delayMs)
    return cancel
  }, [dirty, delayMs, revision])

  const flush = useCallback(async () => {
    cancel()
    if (!dirtyRef.current) return true
    try { return await saveRef.current() } finally { setPending(false) }
  }, [])

  return { flush, pending }
}
