import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import '../i18n'
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
