import type { RunEvent } from './types'
import { apiFetch } from './client'

/** Fetch-based SSE reader: sends the Authorization header (EventSource cannot) and resumes via Last-Event-ID. */
export function subscribeRunEvents(runId: string, onEvent: (e: RunEvent) => void, onEnd?: () => void): () => void {
  const ctrl = new AbortController()
  let lastId = 0
  let stopped = false

  async function connect(attempt: number): Promise<void> {
    try {
      const r = await apiFetch(`/api/runs/${runId}/events`, {
        signal: ctrl.signal, headers: lastId ? { 'Last-Event-ID': String(lastId) } : {},
      })
      const reader = r.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let idx
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const chunk = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          const dataLine = chunk.split('\n').find((l) => l.startsWith('data: '))
          const idLine = chunk.split('\n').find((l) => l.startsWith('id: '))
          if (idLine) lastId = Number(idLine.slice(4))
          if (dataLine) onEvent(JSON.parse(dataLine.slice(6)) as RunEvent)
        }
      }
      if (!stopped) onEnd?.()
    } catch (err) {
      if (stopped || (err as Error).name === 'AbortError') return
      if (attempt < 5) {
        await new Promise((res) => setTimeout(res, 500 * 2 ** attempt))
        return connect(attempt + 1)
      }
      onEnd?.()
    }
  }

  void connect(0)
  return () => {
    stopped = true
    ctrl.abort()
  }
}
