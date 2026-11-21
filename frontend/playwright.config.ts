import { defineConfig } from '@playwright/test'
import { existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const backend = resolve(import.meta.dirname, '../backend')
const py = existsSync(join(backend, '.venv/Scripts/python.exe')) ? join(backend, '.venv/Scripts/python.exe') : join(backend, '.venv/bin/python')
const data = mkdtempSync(join(tmpdir(), 'aisw-e2e-'))
const dbUrl = `sqlite:///${data.replace(/\\/g, '/')}/e2e.db`
const API_PORT = 8011
const UI_PORT = 5181
const apiUrl = `http://127.0.0.1:${API_PORT}`
const uiUrl = `http://127.0.0.1:${UI_PORT}`

export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: uiUrl,
    channel: process.env.PW_CHANNEL ?? (process.platform === 'win32' ? 'msedge' : undefined),
    viewport: { width: 1920, height: 1080 },
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${py}" -m alembic upgrade head && "${py}" -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: backend,
      url: `${apiUrl}/api/healthz`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { APP_DATABASE_URL: dbUrl, APP_DATA_DIR: data, APP_INPROCESS_WORKER: 'true', APP_ENV: 'dev',
        APP_PUBLIC_URL: uiUrl, APP_CORS_ORIGINS: uiUrl, APP_WORKER_POLL_SECONDS: '0.3', LLM_ENABLED: 'false' },
    },
    {
      command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${UI_PORT} --strictPort`,
      url: uiUrl,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { VITE_API_PROXY: apiUrl },
    },
  ],
})
