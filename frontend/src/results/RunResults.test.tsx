import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import type { Run } from '../api/types'
import '../i18n'
import { RunResults } from './RunResults'

it.each([false, true])('refreshes an open AI tab at completion (early report: %s)', async (early) => {
  let summary = 'Промежуточный отчёт'
  const requests = vi.spyOn(globalThis, 'fetch').mockImplementation(async (path) => {
    if (String(path).endsWith('/auth/me')) return Response.json({ workspaces: [] })
    if (String(path).endsWith('/ai-report')) return Response.json({
      report: { summary, findings: [], priority_order: [], global_recommendations: [] },
      validation: { checks: [], metrics: {}, flags: {} },
    })
    return Response.json({ findings: [] })
  })
  try {
    const client = new QueryClient()
    const view = (status: Run['status'], reportReady = false) => <MemoryRouter><QueryClientProvider client={client}>
      <RunResults run={{ id: 'one', status, summary: {}, score: null, created_at: '2026-01-01',
        nodes: reportReady ? [{ node_type: 'ai.report', status: 'success' }] : [],
        graph_snapshot: { nodes: [{ type: 'ai.report' }] } } as Run} />
    </QueryClientProvider></MemoryRouter>
    const { rerender } = render(view('running'))
    fireEvent.click(screen.getByRole('tab', { name: /AI/i }))
    expect(requests.mock.calls.some(([path]) => String(path).endsWith('/ai-report'))).toBe(false)
    if (early) {
      rerender(view('running', true))
      expect(await screen.findByText(summary)).toBeVisible()
    }
    summary = 'Отчёт готов'
    rerender(view('success', true))
    expect(await screen.findByText('Отчёт готов')).toBeVisible()
  } finally { requests.mockRestore() }
})

it('rechecks usable fixes even if another finding fails during batch generation', async () => {
  const paths: string[] = []
  const findings = ['dependency', 'manual-review'].map((id) => ({
    id, title: id, path: id, line: 1, severity: 'HIGH', category: 'SCA', autofix: id === 'dependency' ? 'deterministic' : 'llm',
  }))
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input)
    paths.push(path)
    if (path.endsWith('/auth/me')) return Response.json({ workspaces: [{ id: 'ws', role: 'developer' }] })
    if (path.endsWith('/findings')) return Response.json({ findings })
    if (path.endsWith('/autofixes')) return Response.json([{ id: 'validated', finding_id: 'dependency', status: 'validated' }])
    if (path.endsWith('/autofix')) return Response.json({ error: { code: 'provider_unavailable', message: 'Unavailable' } }, { status: 502 })
    if (path.endsWith('/recheck')) return Response.json({ run_id: 'corrected', applied: ['validated'], skipped: [] })
    throw new Error(path)
  })
  try {
    render(<MemoryRouter initialEntries={['/c/w?run=original']}><QueryClientProvider client={new QueryClient()}>
      <RunResults run={{ id: 'original', workspace_id: 'ws', workflow_id: 'w', status: 'success', summary: {}, score: null, created_at: '2026-01-01' } as Run} />
      <LocationSearch />
    </QueryClientProvider></MemoryRouter>)
    await screen.findByText('dependency')
    fireEvent.click(screen.getByRole('button', { name: 'Действия с запуском' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Исправить все' }))
    expect(await screen.findByText('?run=corrected')).toBeVisible()
    expect(paths.filter((p) => p.endsWith('/recheck'))).toHaveLength(1)
  } finally { fetcher.mockRestore() }
})

function LocationSearch() {
  return <output>{useLocation().search}</output>
}

it('opens the full report when a Safari mouse press clears focus before the click', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) =>
    Response.json(String(input).endsWith('/auth/me') ? { workspaces: [] } : { findings: [] }))
  try {
    render(<MemoryRouter initialEntries={['/c/w?run=original']}><QueryClientProvider client={new QueryClient()}>
      <RunResults run={{ id: 'original', workflow_id: 'w', status: 'success', summary: {}, score: null, created_at: '2026-01-01' } as Run} />
      <LocationSearch />
    </QueryClientProvider></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: 'Действия с запуском' }))
    const report = screen.getByRole('menuitem', { name: 'Полный отчёт' })
    fireEvent.mouseDown(report)
    // Safari clears the previous item's focus without focusing the button under the pointer.
    act(() => (document.activeElement as HTMLElement).blur())
    fireEvent.mouseUp(report)
    fireEvent.click(report)
    expect(await screen.findByText('?full=1')).toBeVisible()
  } finally { fetcher.mockRestore() }
})
