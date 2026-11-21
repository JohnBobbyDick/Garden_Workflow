export type RepoInput = { ok: true; url: string } | { ok: false; reason: 'empty' | 'not_https' | 'not_url' }

/** Client-side pre-check of a pasted repository link (the server normalizes and decides). */
export function validateRepoInput(raw: string): RepoInput {
  const url = raw.trim()
  if (!url) return { ok: false, reason: 'empty' }
  if (/^http:\/\//i.test(url)) return { ok: false, reason: 'not_https' }
  let parsed: URL
  try { parsed = new URL(url) } catch { return { ok: false, reason: 'not_url' } }
  if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.pathname.replace(/\/+$/, '').split('/').filter(Boolean).length < 2) {
    return { ok: false, reason: 'not_url' }
  }
  return { ok: true, url }
}
