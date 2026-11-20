import { createContext, useContext } from 'react'
import type { Lang, NodeSpec } from '../api/types'

export interface EditorCtx {
  catalog: NodeSpec[]
  lang: Lang
  runMode: boolean
}

export const EditorContext = createContext<EditorCtx>({ catalog: [], lang: 'ru', runMode: false })

export const useEditor = () => useContext(EditorContext)

export const PORT_COLORS: Record<string, string> = {
  trigger: '#a78bfa', repo: '#22d3ee', findings: '#f59e0b', report: '#34d399', json: '#60a5fa', text: '#f472b6',
  bool: '#facc15', any: '#94a3b8',
}

export const CATEGORY_ACCENT: Record<string, string> = {
  trigger: '#a78bfa', source: '#22d3ee', scanner: '#f59e0b', logic: '#60a5fa', analysis: '#2dd4bf', ai: '#c084fc',
  output: '#34d399', notify: '#f472b6',
}
