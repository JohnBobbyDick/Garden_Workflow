import { create } from 'zustand'
import i18n from '../i18n'
import type { Lang } from '../api/types'

type Theme = 'dark' | 'light'

interface UiState {
  theme: Theme
  lang: Lang
  workspaceId: string | null
  setTheme: (t: Theme) => void
  toggleTheme: () => void
  setLang: (l: Lang) => void
  setWorkspace: (id: string) => void
}

function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t
}

const initialTheme = (localStorage.getItem('aisw.theme') as Theme | null) ?? 'light'
applyTheme(initialTheme)
document.documentElement.lang = (localStorage.getItem('aisw.lang') as Lang | null) ?? 'ru'

export const useUi = create<UiState>((set, get) => ({
  theme: initialTheme,
  lang: (localStorage.getItem('aisw.lang') as Lang | null) ?? 'ru',
  workspaceId: localStorage.getItem('aisw.workspace'),
  setTheme: (theme) => {
    localStorage.setItem('aisw.theme', theme)
    applyTheme(theme)
    set({ theme })
  },
  toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
  setLang: (lang) => {
    localStorage.setItem('aisw.lang', lang)
    document.documentElement.lang = lang
    void i18n.changeLanguage(lang)
    set({ lang })
  },
  setWorkspace: (workspaceId) => {
    localStorage.setItem('aisw.workspace', workspaceId)
    set({ workspaceId })
  },
}))
