import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Navigate, Outlet, useNavigate } from 'react-router-dom'
import { useMe } from '../../api/hooks'
import { api } from '../../api/client'
import { useAuth } from '../../store/auth'
import { useUi } from '../../store/ui'
import { Spinner } from '../ui'
import { Icon } from '../ui/Icon'

export const NAV = [
  { to: '/', key: 'dashboard', icon: 'dashboard' },
  { to: '/projects', key: 'projects', icon: 'folder' },
  { to: '/workflows', key: 'workflows', icon: 'workflow' },
  { to: '/runs', key: 'runs', icon: 'history' },
  { to: '/templates', key: 'templates', icon: 'template' },
  { to: '/integration', key: 'integration', icon: 'ci' },
  { to: '/settings', key: 'settings', icon: 'settings' },
] as const

export function ThemeLangToggles() {
  const { t } = useTranslation()
  const { theme, toggleTheme, lang, setLang } = useUi()
  return (
    <div className="flex items-center gap-1">
      <button
        type="button" onClick={toggleTheme} className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-fg"
        aria-label={`${t('common.theme')}: ${theme === 'dark' ? t('common.dark') : t('common.light')}`}
        title={`${t('common.theme')}: ${theme === 'dark' ? t('common.dark') : t('common.light')}`}
      >
        <Icon name={theme === 'dark' ? 'moon' : 'sun'} size={17} />
      </button>
      <button
        type="button" onClick={() => setLang(lang === 'ru' ? 'en' : 'ru')}
        className="flex items-center gap-1 rounded-lg px-2 py-2 text-xs font-semibold text-muted hover:bg-surface-2 hover:text-fg"
        aria-label={`${t('common.language')}: ${lang.toUpperCase()}`}
      >
        <Icon name="lang" size={16} />{lang.toUpperCase()}
      </button>
    </div>
  )
}

export function AppShell() {
  const { t } = useTranslation()
  const token = useAuth((s) => s.accessToken)
  const { refreshToken, clear, setUser } = useAuth()
  const me = useMe(!!token)
  const { workspaceId, setWorkspace, lang } = useUi()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)

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
  if (me.isLoading || !workspaceId) {
    return <div className="flex h-full items-center justify-center"><Spinner size={28} /></div>
  }

  const logout = async () => {
    try {
      if (refreshToken) await api('/api/auth/logout', { method: 'POST', json: { refresh_token: refreshToken } })
    } finally {
      clear()
      navigate('/login')
    }
  }

  const ws = me.data?.workspaces ?? []
  return (
    <div className="flex h-full">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-fg">
        {t('nav.skip')}
      </a>
      <aside className={clsx('fixed inset-y-0 left-0 z-40 w-60 shrink-0 border-r border-border bg-surface transition-transform md:static md:translate-x-0',
        mobileOpen ? 'translate-x-0' : '-translate-x-full')}>
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <span className="font-semibold leading-tight">AI Security<br /><span className="text-xs font-normal text-muted">Workflow</span></span>
        </div>
        <nav className="flex flex-col gap-0.5 p-2" aria-label="main">
          {NAV.map((n) => (
            <NavLink
              key={n.to} to={n.to} end={n.to === '/'} onClick={() => setMobileOpen(false)}
              className={({ isActive }) => clsx('flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
                isActive ? 'bg-primary/15 font-medium text-primary' : 'text-muted hover:bg-surface-2 hover:text-fg')}
            >
              <Icon name={n.icon} size={17} />{t(`nav.${n.key}`)}
            </NavLink>
          ))}
        </nav>
      </aside>
      {mobileOpen && <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setMobileOpen(false)} />}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
          <button className="rounded p-1.5 text-muted hover:bg-surface-2 md:hidden" aria-label="menu" onClick={() => setMobileOpen(true)}>
            <Icon name="menu" size={18} />
          </button>
          <label className="sr-only" htmlFor="ws-select">{t('common.workspace')}</label>
          <select
            id="ws-select" className="input h-9 w-auto max-w-[360px] py-1" value={workspaceId}
            onChange={(e) => setWorkspace(e.target.value)}
          >
            {ws.map((w) => <option key={w.id} value={w.id}>{w.name} · {t(`settings.roles.${w.role}`)}</option>)}
          </select>
          <div className="flex-1" />
          <ThemeLangToggles />
          <span className="hidden text-sm text-muted sm:inline">{me.data?.user.email}</span>
          <button type="button" onClick={logout} className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-fg" aria-label={t('nav.logout')} title={t('nav.logout')}>
            <Icon name="logout" size={17} />
          </button>
        </header>
        <main id="main" className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export function Page({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return <div className={clsx('mx-auto w-full p-4 md:p-6', wide ? 'max-w-[1600px]' : 'max-w-6xl')}>{children}</div>
}
