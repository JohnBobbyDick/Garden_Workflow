import { useAuth } from '../store/auth'

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message)
  }
}

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

let refreshing: Promise<boolean> | null = null

async function refreshTokens(): Promise<boolean> {
  const { refreshToken, setTokens, clear } = useAuth.getState()
  if (!refreshToken) return false
  refreshing ??= (async () => {
    try {
      const r = await fetch(`${BASE}/api/auth/refresh`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: refreshToken }),
      })
      if (!r.ok) {
        clear()
        return false
      }
      const body = await r.json()
      setTokens(body.access_token, body.refresh_token, body.user)
      return true
    } catch {
      return false
    } finally {
      refreshing = null
    }
  })()
  return refreshing
}

export function authHeaders(): Record<string, string> {
  const token = useAuth.getState().accessToken
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function parseError(r: Response): Promise<ApiError> {
  try {
    const body = await r.json()
    const e = body?.error
    if (e) return new ApiError(r.status, e.code, e.message, e.details)
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(r.status, 'http_error', `HTTP ${r.status}`)
}

export async function apiFetch(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers)
  for (const [k, v] of Object.entries(authHeaders())) headers.set(k, v)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const r = await fetch(`${BASE}${path}`, { ...init, headers })
  if (r.status === 401 && retry && useAuth.getState().refreshToken && !path.startsWith('/api/auth/')) {
    if (await refreshTokens()) return apiFetch(path, init, false)
  }
  if (!r.ok) throw await parseError(r)
  return r
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init
  const r = await apiFetch(path, json !== undefined ? { ...rest, body: JSON.stringify(json) } : rest)
  if (r.status === 204) return undefined as T
  const ct = r.headers.get('content-type') ?? ''
  return (ct.includes('application/json') ? await r.json() : await r.text()) as T
}

export function withWs(path: string, workspaceId: string | null): string {
  if (!workspaceId) return path
  return `${path}${path.includes('?') ? '&' : '?'}workspace_id=${encodeURIComponent(workspaceId)}`
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const r = await apiFetch(path)
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
