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

function serve(settings = initial, role = 'admin') {
  let saved = { ...settings }
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, request) => {
    if (url === '/api/settings/ai/test') return Response.json({ ok: true, model: saved.model, latency_ms: 1 })
    if (String(url).startsWith('/api/settings/ai')) {
      if (request?.method === 'PUT') saved = { ...saved, ...JSON.parse(String(request.body)) }
      return Response.json(saved)
    }
    if (url === '/api/auth/me') return Response.json({ workspaces: [{ id: 'workspace', role }] })
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

it.each(['developer', 'viewer'])('shows the connection controls allowed for %s', async (role) => {
  serve(initial, role)
  mount()
  const test = await screen.findByRole('button', { name: 'Проверить соединение' })
  const diag = screen.getByRole('button', { name: 'Диагностика' })
  expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled()
  if (role === 'viewer') {
    expect(test).toBeDisabled()
    expect(diag).toBeDisabled()
  } else {
    await waitFor(() => expect(test).toBeEnabled())
    fireEvent.click(test)
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/settings/ai/test', expect.anything()))
    expect(vi.mocked(fetch).mock.calls.some(([, req]) => req?.method === 'PUT')).toBe(false)
  }
})

it.each(['ollama', 'nvidia'])('preserves authentication when saving the same %s connection', async (provider) => {
  const saved = serve({ ...initial, provider,
    ...(provider === 'ollama' ? initial.ollama_defaults : cloud) })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Сохранить' }))
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([, req]) => req?.method === 'PUT')).toBe(true))
  expect(saved().headers).toEqual(initial.headers)
  expect(saved().credential_id).toBe(initial.credential_id)
})

it('clears the previous server credentials when changing the Ollama URL', async () => {
  const saved = serve({ ...initial, ...initial.ollama_defaults, provider: 'ollama' })
  mount()
  fireEvent.change(await screen.findByLabelText(/URL/), { target: { value: 'http://localhost:21434' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
  await waitFor(() => expect(saved()).toMatchObject({
    base_url: 'http://localhost:21434', credential_id: null, headers: {},
  }))
})

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
