/* Workspace routing: one screen (/c/:id) with second-level panels in ?panel=…; old page addresses keep working. */

export const PANELS = ['history', 'templates', 'ci', 'overview', 'settings', 'compare'] as const
export type PanelId = (typeof PANELS)[number]

function qs(search: string): URLSearchParams {
  return new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
}

function join(path: string, params: URLSearchParams): string {
  const s = params.toString()
  return s ? `${path}?${s}` : path
}

function panelUrl(panel: PanelId, search: string, extra: Record<string, string> = {}): string {
  const p = new URLSearchParams({ panel, ...extra })
  qs(search).forEach((v, k) => { if (k !== 'panel') p.set(k, v) })
  return join('/', p)
}

/** Old route → new route, or null when the path is already a workspace route. */
export function legacyRedirect(pathname: string, search: string): string | null {
  const path = pathname.replace(/\/+$/, '') || '/'
  const wf = path.match(/^\/workflows\/([^/]+)$/)
  if (wf) return `/c/${wf[1]}`
  if (path === '/workflows') return '/'
  if (path === '/pr') {
    const p = qs(search)
    const run = p.get('run')
    if (!run) return '/'
    p.delete('run')
    return join(`/runs/${run}`, p)
  }
  if (path === '/templates') return panelUrl('templates', search)
  if (path === '/integration') return panelUrl('ci', search)
  if (path === '/settings') return panelUrl('settings', search)
  if (path === '/projects') return panelUrl('settings', search, { tab: 'projects' })
  if (path === '/runs') return panelUrl('history', search)
  if (path === '/runs/compare') return panelUrl('compare', search)
  return null
}

export function panelFromSearch(search: string): PanelId | null {
  const v = qs(search).get('panel')
  return v && (PANELS as readonly string[]).includes(v) ? (v as PanelId) : null
}

/** Same query string with the panel opened (or closed with null, also dropping its sub-tab). */
export function withPanel(search: string, panel: PanelId | null): string {
  const p = qs(search)
  if (p.get('panel') === 'compare' && panel !== 'compare') {
    p.delete('base')
    p.delete('head')
  }
  p.delete('panel')
  p.delete('tab')
  if (panel) p.set('panel', panel)
  const s = p.toString()
  return s ? `?${s}` : ''
}
