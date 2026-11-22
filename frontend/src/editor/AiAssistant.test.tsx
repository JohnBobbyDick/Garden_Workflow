import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import '../i18n'
import { AiAssistant } from './AiAssistant'

const graph = { schema_version: 1, nodes: [{ id: 'scheduler', type: 'trigger.schedule', config: { cron: '0 12 * * 1' } }], edges: [] }
const proposal = {
  id: 'saved', role: 'assistant', content: 'Изменено расписание', valid: true, status: 'proposed',
  needs_input: [], issues: [], graph, diff: { changed_nodes: ['scheduler'] }, stale: false,
  original_message: 'Запускай по понедельникам', selected_node_id: 'scheduler',
}
const chat = '/api/ai/workflows/workflow/chat'

function mount(staleOnApply = false) {
  let status = 'proposed'
  const sent: unknown[] = []
  const applied = vi.fn()
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (path, req) => {
    const url = String(path)
    if (url === chat && req?.method === 'POST') {
      sent.push(JSON.parse(String(req.body)))
      return Response.json({ ...proposal, id: 'new', content: 'Новая версия' })
    }
    if (url === chat) return Response.json([{ ...proposal, status }])
    if (url === chat + '/saved') return Response.json({ ...proposal, status })
    if (url === chat + '/new') return Response.json({ ...proposal, id: 'new', content: 'Новая версия' })
    if (url.endsWith('/apply') && staleOnApply) {
      return Response.json({ error: { code: 'proposal_stale', message: 'stale' } }, { status: 409 })
    }
    if (url.endsWith('/apply') || url.endsWith('/reject')) {
      status = url.endsWith('/reject') ? 'rejected' : 'applied'
      return Response.json({ graph, status })
    }
    throw new Error('Unknown request')
  })
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AiAssistant workflowId="workflow" dirty={false} selectedNodeId="other" onSaveFirst={async () => true} onApplied={applied} />
  </QueryClientProvider>)
  return { applied, sent }
}

afterEach(() => vi.restoreAllMocks())

it.each([
  ['Применить', 'Принято'], ['Отклонить', 'Отклонено'],
])('reviews a persisted proposal and updates its decision via %s', async (action, status) => {
  const { applied, sent } = mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Посмотреть изменения' }))
  expect(await screen.findByText(/Изменить.*scheduler/)).toBeInTheDocument()
  fireEvent.click(screen.getByText('Параметры нод'))
  expect(screen.getByText(/0 12 \* \* 1/)).toBeVisible()
  expect(screen.getAllByText('Изменено расписание')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: action }))
  expect(await screen.findByText(status)).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Применить' })).toBeNull()
  expect(applied.mock.calls.length).toBe(action === 'Применить' ? 1 : 0)
  expect(sent).toEqual([])
})

it('keeps a stale proposal for review, preserves the draft and only resends with the original target on explicit send', async () => {
  const { applied, sent } = mount(true)
  fireEvent.click(await screen.findByRole('button', { name: 'Посмотреть изменения' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Применить' }))
  const edit = await screen.findByRole('button', { name: 'Подготовить новый запрос' })
  expect(sent).toEqual([])
  expect(applied).not.toHaveBeenCalled()
  const composer = screen.getByRole('textbox')
  fireEvent.change(composer, { target: { value: 'Мой черновик' } })
  fireEvent.click(edit)
  expect(composer).toHaveValue('Запускай по понедельникам')
  fireEvent.click(screen.getByRole('button', { name: 'Отмена' }))
  expect(composer).toHaveValue('Мой черновик')
  expect(sent).toEqual([])
  fireEvent.click(edit)
  fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
  await waitFor(() => expect(sent).toEqual([{ message: 'Запускай по понедельникам', selected_node_id: 'scheduler' }]))
  expect(await screen.findByText('Новая версия')).toBeVisible()
  expect(composer).toHaveValue('Мой черновик')
})

it('includes the current selection on a fresh request and only sends once for a single shortcut', async () => {
  const { sent } = mount()
  const composer = screen.getByRole('textbox')
  expect(screen.getByText(/Выбранная нода.*other/)).toBeVisible()
  fireEvent.change(composer, { target: { value: 'Переименуй её' } })
  fireEvent.keyDown(composer, { key: 'Enter', ctrlKey: true })
  expect(await screen.findByText('Новая версия')).toBeVisible()
  expect(sent).toEqual([{ message: 'Переименуй её', selected_node_id: 'other' }])
})
