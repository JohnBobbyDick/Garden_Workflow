import { create } from 'zustand'

export type ToastKind = 'success' | 'error' | 'info'

export interface Toast {
  id: number
  kind: ToastKind
  message: string
  action?: { label: string; onClick: () => void }
}

interface ToastState {
  toasts: Toast[]
  push: (kind: ToastKind, message: string, action?: Toast['action']) => void
  dismiss: (id: number) => void
}

let seq = 0

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push: (kind, message, action) => {
    const id = ++seq
    set({ toasts: [...get().toasts, { id, kind, message, action }].slice(-4) })
    window.setTimeout(() => get().dismiss(id), kind === 'error' ? 8000 : 4000)
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}))

export const toast = {
  success: (m: string) => useToasts.getState().push('success', m),
  error: (m: string, action?: Toast['action']) => useToasts.getState().push('error', m, action),
  info: (m: string) => useToasts.getState().push('info', m),
}
