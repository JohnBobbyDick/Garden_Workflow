import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { useUi } from '../store/ui'
import SettingsPage from './SettingsPage'

const cloud = {
  provider: 'nvidia', model: 'nvidia/nemotron-3.5-lightning-30b-a3b', base_url: 'https://integrate.api.nvidia.com/v1',
}
const initial = {
  ...cloud, enabled: true, credential_id: 'key', credential_ids: ['second'], proxy_credential_ids: ['proxy'],
  headers: { 'X-Custom': 'old' }, timeout: 90, json_mode: 'auto', allow_local: false, providers: ['nvidia', 'ollama'],
  proxy_scheme: 'https', proxy_port: '443', max_retries: 4, fallback_models: [], hints: [],
  env_default: { enabled: true, provider: 'nvidia', model: cloud.model },
  ollama_defaults: { base_url: 'http://ollama:11434', model: 'local-model:latest' },
}

function serve(settings = initial) {
  let saved = { ...settings }
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, request) => {
    if (String(url).startsWith('/api/settings/ai')) {
      if (request?.method === 'PUT') saved = { ...saved, ...JSON.parse(String(request.body)) }
      return Response.json(saved)
    }
    if (url === '/api/auth/me') return Response.json({ workspaces: [{ id: 'workspace', role: 'admin' }] })
    if (String(url).startsWith('/api/credentials')) return Response.json([])
    throw new Error('Unknown request')
  })
  return () => saved
}

function mount() {
  useUi.getState().setWorkspace('workspace')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)
}

afterEach(() => vi.restoreAllMocks())

it('saves a local model and clears cloud routing and credentials when switching providers', async () => {
  const saved = serve()
  const view = mount()
  fireEvent.click(await screen.findByRole('radio', { name: 'Ollama' }))
  expect(screen.getByLabelText('Модель')).toHaveValue('local-model:latest')
  expect(screen.getByLabelText(/URL/)).toHaveValue('http://ollama:11434')
  fireEvent.change(screen.getByLabelText('Модель'), { target: { value: 'mine:7b' } })
  fireEvent.change(screen.getByLabelText(/URL/), { target: { value: 'http://localhost:21434' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
  await waitFor(() => expect(saved()).toMatchObject({
    provider: 'ollama', enabled: true, base_url: 'http://localhost:21434', model: 'mine:7b', allow_local: true,
    credential_id: null, credential_ids: [], proxy_credential_ids: [], headers: {}, proxy_scheme: 'auto', proxy_port: null,
  }))
  view.unmount()
  mount()
  expect(await screen.findByRole('radio', { name: 'Ollama' })).toBeChecked()
  expect(screen.getByLabelText('Модель')).toHaveValue('mine:7b')
  fireEvent.click(screen.getByRole('radio', { name: /Nemotron/ }))
  expect(screen.queryByRole('textbox', { name: 'Модель' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
  await waitFor(() => expect(saved()).toMatchObject({ ...cloud, allow_local: false, credential_id: null, fallback_models: [] }))
})

it('distinguishes platform inheritance and activates the selected local provider', async () => {
  const saved = serve({ ...initial, enabled: false })
  mount()
  expect(await screen.findByRole('status')).toHaveTextContent(/Nemotron/)
  fireEvent.click(screen.getByRole('radio', { name: 'Ollama' }))
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
  await waitFor(() => expect(saved()).toMatchObject({ provider: 'ollama', enabled: true }))
})
