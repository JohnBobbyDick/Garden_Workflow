import clsx from 'clsx'
import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useMe, useWorkflows } from '../api/hooks'
import type { RunStatus } from '../api/types'
import { ThemeLangToggles } from '../components/layout/AppShell'
import { EmbeddedContext } from '../components/layout/embedded'
import { Spinner } from '../components/ui'
import { Icon, type IconName } from '../components/ui/Icon'
import { useAuth } from '../store/auth'
import { useUi } from '../store/ui'
import { useWorkspaceUi } from '../store/workspace'
import { useCompactWorkspace } from './useCompactWorkspace'
import { Drawer } from './Drawer'
import { NewCheckDialog } from './NewCheckDialog'
import { legacyRedirect, panelFromSearch, withPanel, type PanelId } from './routes'

const RunsPage = lazy(() => import('../pages/RunsPage'))
const ComparePage = lazy(() => import('../pages/ComparePage'))
const TemplatesPage = lazy(() => import('../pages/TemplatesPage'))
const IntegrationPage = lazy(() => import('../pages/IntegrationPage'))
const DashboardPage = lazy(() => import('../pages/DashboardPage'))
const SettingsPage = lazy(() => import('../pages/SettingsPage'))

const PANEL_ITEMS: { id: PanelId; icon: IconName }[] = [
  { id: 'history', icon: 'history' }, { id: 'templates', icon: 'template' }, { id: 'ci', icon: 'ci' },
  { id: 'overview', icon: 'dashboard' }, { id: 'settings', icon: 'settings' },
]

const DOT: Record<RunStatus, string> = {
  success: 'bg-primary', failed: 'bg-danger', running: 'bg-edge animate-pulse', queued: 'bg-muted', cancelled: 'bg-warning',
}

function PanelBody({ panel }: { panel: PanelId }): ReactNode {
  switch (panel) {
    case 'history': return <RunsPage />
    case 'compare': return <ComparePage />
    case 'templates': return <TemplatesPage />
    case 'ci': return <IntegrationPage />
    case 'overview': return <DashboardPage />
    case 'settings': return <SettingsPage />
  }
}

function Rail() {
  const { t } = useTranslation()
  const nav = useNavigate()
  const loc = useLocation()
  const wfs = useWorkflows()
  const me = useMe()
  const { workspaceId, setWorkspace } = useUi()
  const { railCollapsed: desktopCollapsed, toggleRail: toggleDesktopRail } = useWorkspaceUi()
  const compact = useCompactWorkspace()
  const [mobileExpanded, setMobileExpanded] = useState(false)
  const railCollapsed = compact ? !mobileExpanded : desktopCollapsed
  const toggleRail = () => compact ? setMobileExpanded(!mobileExpanded) : toggleDesktopRail()
  useEffect(() => setMobileExpanded(false), [loc.key])
  const { refreshToken, clear } = useAuth()
  const [account, setAccount] = useState(false)
  const panel = panelFromSearch(loc.search)
  const openPanel = (p: PanelId) => nav({ search: withPanel(loc.search, panel === p ? null : p) })
  const logout = async () => {
    try { if (refreshToken) await api('/api/auth/logout', { method: 'POST', json: { refresh_token: refreshToken } }) } finally { clear(); nav('/login') }
  }
  const item = 'flex h-9 w-full items-center gap-2.5 rounded-chip px-2.5 text-[14px] transition-colors'
  return (
    <div className="relative shrink-0 max-lg:w-16">
      {compact && mobileExpanded && <button type="button" aria-label={t('ws.collapseRail')} onClick={toggleRail}
        className="fixed inset-0 z-20 bg-fg/25" />}
    <aside className={clsx('relative z-20 flex h-full shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-200',
      railCollapsed ? 'w-16' : 'w-[248px]')} aria-label={t('ws.navigation')}>
      <div className={clsx("flex h-14 shrink-0 items-center gap-2 px-3", railCollapsed && "justify-center")}>
        {!railCollapsed && <img src="/garden-security.png" alt="" width={32} height={32} className="shrink-0" />}
        {!railCollapsed && <span className="truncate text-[16px] font-bold">Garden Security</span>}
        <button type="button" onClick={toggleRail} className={clsx('rounded-chip p-1.5 text-muted hover:bg-soft hover:text-fg', !railCollapsed && 'ml-auto')}
          aria-label={railCollapsed ? t('ws.expandRail') : t('ws.collapseRail')} title={railCollapsed ? t('ws.expandRail') : t('ws.collapseRail')}>
          <Icon name="chevron-right" size={15} className={railCollapsed ? '' : 'rotate-180'} />
        </button>
      </div>
      <div className="px-2">
        <button type="button" onClick={() => nav({ search: '?new=1' })} className={clsx(item, 'bg-primary font-bold text-primary-fg hover:bg-primary/90', railCollapsed && 'justify-center px-0')}
          title={t('ws.newCheck')} aria-label={t('ws.newCheck')}>
          <Icon name="plus" size={16} />{!railCollapsed && t('ws.newCheck')}
        </button>
      </div>
      {!railCollapsed && <div className="px-4 pb-1 pt-4 text-[11px] font-bold uppercase tracking-wide text-muted">{t('ws.checks')}</div>}
      <nav className={clsx('min-h-0 flex-1 overflow-y-auto px-2', railCollapsed && 'pt-3')} aria-label={t('ws.checks')}>
        {wfs.isLoading ? <div className="p-3"><Spinner size={16} /></div> : (wfs.data ?? []).map((w) => (
          <NavLink key={w.id} to={`/c/${w.id}`} title={w.name}
            className={({ isActive }) => clsx(item, railCollapsed && 'justify-center px-0', isActive ? 'bg-soft font-bold text-primary' : 'text-fg hover:bg-surface-2')}>
            <span className={clsx('h-2 w-2 shrink-0 rounded-full', w.last_run ? DOT[w.last_run.status] : 'border border-muted')}
              aria-label={w.last_run ? t(`status.${w.last_run.status}`) : t('ws.neverRun')} />
            {railCollapsed ? <span className="sr-only">{w.name}</span> : <span className="truncate">{w.name}</span>}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-border px-2 py-2">
        {PANEL_ITEMS.map((p) => (
          <button key={p.id} type="button" onClick={() => openPanel(p.id)} aria-pressed={panel === p.id} title={t(`ws.panel.${p.id}`)}
            className={clsx(item, railCollapsed && 'justify-center px-0', panel === p.id ? 'bg-soft font-bold text-primary' : 'text-muted hover:bg-surface-2 hover:text-fg')}>
            <Icon name={p.icon} size={16} />{!railCollapsed && t(`ws.panel.${p.id}`)}
          </button>
        ))}
      </div>
      <div className={clsx('relative flex items-center gap-1 border-t border-border p-2', railCollapsed && 'flex-col')}>
        <button type="button" onClick={() => setAccount((o) => !o)} aria-expanded={account} aria-haspopup="menu"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-soft text-[13px] font-bold text-primary"
          title={me.data?.user.email} aria-label={me.data?.user.email}>
          {(me.data?.user.display_name || me.data?.user.email || '?').slice(0, 1).toUpperCase()}
        </button>
        {!railCollapsed && <span className="min-w-0 flex-1 truncate text-[12px] text-muted">{me.data?.workspaces.find((w) => w.id === workspaceId)?.name}</span>}
        <ThemeLangToggles stacked={railCollapsed} />
        {account && (
          <div role="menu" className="card absolute bottom-12 left-2 z-50 w-72 p-3 shadow-pop">
            <div className="mb-2 truncate text-sm text-muted">{me.data?.user.email}</div>
            <label className="label" htmlFor="ws-select">{t('common.workspace')}</label>
            <select id="ws-select" className="input mb-3" value={workspaceId ?? ''}
              onChange={(e) => { setWorkspace(e.target.value); setAccount(false); nav('/') }}>
              {(me.data?.workspaces ?? []).map((w) => <option key={w.id} value={w.id}>{w.name} · {t(`settings.roles.${w.role}`)}</option>)}
            </select>
            <button type="button" role="menuitem" onClick={logout} className="flex w-full items-center gap-2 rounded-chip px-2 py-2 text-left text-sm hover:bg-soft">
              <Icon name="logout" size={15} />{t('nav.logout')}
            </button>
          </div>
        )}
      </div>
    </aside>
    </div>
  )
}

export function WorkspaceLayout() {
  const { t } = useTranslation()
  const token = useAuth((s) => s.accessToken)
  const { setUser } = useAuth()
  const me = useMe(!!token)
  const { workspaceId, setWorkspace, lang } = useUi()
  const loc = useLocation()
  const nav = useNavigate()
  const panel = panelFromSearch(loc.search)
  const params = new URLSearchParams(loc.search)

  useEffect(() => {
    if (!me.data) return
    setUser(me.data.user)
    const ids = me.data.workspaces.map((w) => w.id)
    if (!workspaceId || !ids.includes(workspaceId)) setWorkspace(ids[0])
  }, [me.data, workspaceId, setWorkspace, setUser])

  useEffect(() => {
    // the backend renders AI reports and notifications in the user's language
    if (me.data && me.data.user.locale !== lang) void api('/api/auth/me', { method: 'PATCH', json: { locale: lang } })
  }, [lang, me.data])

  if (!token) return <Navigate to="/login" replace />
  const legacy = legacyRedirect(loc.pathname, loc.search)
  if (legacy) return <Navigate to={legacy} replace />
  if (me.isLoading || !workspaceId) return <div className="flex h-full items-center justify-center"><Spinner size={28} /></div>

  return (
    <div className="flex h-full">
      <a href="#canvas" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-fg">
        {t('nav.skip')}
      </a>
      <Rail />
      <main id="canvas" className="relative min-w-0 flex-1">
        <Outlet />
      </main>
      {(params.get('new') === '1' || (params.get('source') === '1' && loc.pathname.startsWith('/c/'))) && (
        <NewCheckDialog mode={params.get('new') === '1' ? 'create' : 'change-source'} templateId={params.get('template')}
          onClose={() => {
            const p = new URLSearchParams(loc.search)
            for (const k of ['new', 'source', 'template']) p.delete(k)
            nav({ search: p.toString() ? `?${p}` : '' })
          }} />
      )}
      <Drawer open={!!panel} onClose={() => nav({ search: withPanel(loc.search, null) })} title={panel ? t(`ws.panel.${panel}`) : ''}
        wide={panel === 'overview' || panel === 'compare'}>
        <Suspense fallback={<div className="flex h-40 items-center justify-center"><Spinner size={22} /></div>}>
          {panel && <EmbeddedContext.Provider value><PanelBody panel={panel} /></EmbeddedContext.Provider>}
        </Suspense>
      </Drawer>
    </div>
  )
}
