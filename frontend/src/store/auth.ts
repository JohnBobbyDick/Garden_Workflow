import { create } from 'zustand'
import type { User } from '../api/types'

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: User | null
  setTokens: (access: string, refresh: string, user?: User) => void
  setUser: (u: User) => void
  clear: () => void
}

const KEY = 'aisw.auth'

function load(): Pick<AuthState, 'accessToken' | 'refreshToken' | 'user'> {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) return JSON.parse(raw)
  } catch {
    /* corrupted storage → signed out */
  }
  return { accessToken: null, refreshToken: null, user: null }
}

export const useAuth = create<AuthState>((set, get) => ({
  ...load(),
  setTokens: (accessToken, refreshToken, user) => {
    const next = { accessToken, refreshToken, user: user ?? get().user }
    localStorage.setItem(KEY, JSON.stringify(next))
    set(next)
  },
  setUser: (user) => {
    const next = { accessToken: get().accessToken, refreshToken: get().refreshToken, user }
    localStorage.setItem(KEY, JSON.stringify(next))
    set({ user })
  },
  clear: () => {
    localStorage.removeItem(KEY)
    set({ accessToken: null, refreshToken: null, user: null })
  },
}))
