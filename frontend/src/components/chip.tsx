import clsx from 'clsx'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Run } from '../api/types'

/* Compact status chip (h32, r9, 13 bold) — the one shape used for verdicts, severities and links in the workspace. */
export function Chip({ children, tone = 'ok', onClick, to, title }: {
  children: ReactNode; tone?: 'ok' | 'bad' | 'warn' | 'plain'; onClick?: () => void; to?: string; title?: string
}) {
  const cls = clsx('inline-flex h-8 shrink-0 items-center gap-1 whitespace-nowrap rounded-chip px-2.5 text-[13px] font-bold leading-5', {
    'bg-soft text-primary': tone === 'ok', 'bg-danger-soft text-danger': tone === 'bad',
    'bg-warning-soft text-warning': tone === 'warn', 'border border-border bg-surface text-fg': tone === 'plain',
  }, (onClick || to) && 'hover:brightness-95')
  if (to) return <Link to={to} className={cls} title={title}>{children}</Link>
  if (onClick) return <button type="button" className={cls} onClick={onClick} title={title}>{children}</button>
  return <span className={cls} title={title}>{children}</span>
}

export const runLabel = (r: Pick<Run, 'id' | 'created_at'>, lang: 'ru' | 'en') =>
  `#${r.id.slice(0, 6)} · ${new Date(r.created_at).toLocaleString(lang === 'en' ? 'en-GB' : 'ru-RU',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}`
