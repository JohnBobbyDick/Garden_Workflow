import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import '../i18n'
import * as client from '../api/client'
import { SchemaForm } from './SchemaForm'

const schema = {
  type: 'object',
  properties: {
    host: { type: 'string', title: 'Сервер', 'x-title-en': 'Host' },
    port: { type: 'integer', title: 'Порт', minimum: 1, maximum: 65535 },
    security: { type: 'string', title: 'Шифрование', enum: ['starttls', 'tls'] },
    cron: { type: 'string', title: 'Расписание', 'x-widget': 'cron' },
    expr: { type: 'string', title: 'Условие', 'x-widget': 'expression' },
  },
  required: ['host'],
}

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, queryFn: async () => [] } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

describe('SchemaForm', () => {
  it('renders a widget per schema property and shows validation', () => {
    const onChange = vi.fn()
    wrap(<SchemaForm schema={schema} value={{ port: 70000 }} onChange={onChange} lang="ru" />)
    expect(screen.getByLabelText(/Сервер/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Шифрование/).tagName).toBe('SELECT')
    expect(screen.getByText('не больше 65535')).toBeInTheDocument()
    expect(screen.getByText('обязательное поле')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/Сервер/), { target: { value: 'smtp.local' } })
    expect(onChange).toHaveBeenLastCalledWith({ port: 70000, host: 'smtp.local' })
  })

  it('describes cron and inserts expression variables', () => {
    const onChange = vi.fn()
    wrap(<SchemaForm schema={schema} value={{ host: 'h', cron: '0 14 * * *', expr: '' }} onChange={onChange} lang="ru" />)
    expect(screen.getByText('Каждый день в 14:00', { selector: 'p' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'severity.max' }))
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ expr: 'severity.max ' }))
  })

  it('uses English labels when lang=en', () => {
    wrap(<SchemaForm schema={schema} value={{}} onChange={() => {}} lang="en" />)
    expect(screen.getByLabelText(/Host/)).toBeInTheDocument()
  })
})

const telegramSchema = {
  type: 'object',
  properties: { chat_id: { type: 'string', title: 'Получатель', 'x-widget': 'telegram-chat' } },
}

function RecipientEditor() {
  const [value, setValue] = useState<Record<string, unknown>>({ bot_token: 'credential-id', chat_id: '@oldname' })
  return <SchemaForm schema={telegramSchema} value={value} onChange={setValue} lang="ru" />
}

it('preserves a manual numeric recipient when an earlier lookup completes', async () => {
  let finish!: (value: unknown) => void
  const api = vi.spyOn(client, 'api').mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  try {
    wrap(<RecipientEditor />)
    const field = screen.getByLabelText('Получатель')
    fireEvent.click(screen.getByRole('button', { name: 'Найти Chat ID' }))
    fireEvent.change(field, { target: { value: '-100777' } })
    await act(async () => finish({ chat_id: '42' }))
    expect(field).toHaveValue('-100777')
    expect(screen.getByRole('button', { name: 'Найти Chat ID' })).toBeDisabled()
    expect(api).toHaveBeenCalledTimes(1)
  } finally { api.mockRestore() }
})

it('shows an actionable lookup error next to the unchanged recipient', async () => {
  const api = vi.spyOn(client, 'api').mockRejectedValueOnce(new client.ApiError(409, 'telegram_updates_busy', 'upstream text'))
  try {
    wrap(<RecipientEditor />)
    fireEvent.click(screen.getByRole('button', { name: 'Найти Chat ID' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/webhook.*ID/i)
    expect(screen.getByLabelText('Получатель')).toHaveValue('@oldname')
  } finally { api.mockRestore() }
})
