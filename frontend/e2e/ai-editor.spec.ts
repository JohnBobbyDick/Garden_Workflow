import { expect, test } from '@playwright/test'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { register } from './register'

test('selected node → proposal → reopen history on a narrow screen → apply once', async ({ page }) => {
  let modelRequests = 0
  let selectedInPrompt = false
  const label = 'Обновлённый источник'
  const server = createServer(async (req, res) => {
    if (req.method !== 'POST' || req.url !== '/api/chat') { res.writeHead(404).end(); return }
    modelRequests++
    let body = ''
    req.setEncoding('utf8')
    for await (const chunk of req) body += chunk
    const messages = JSON.parse(body).messages as { role: string; content: string }[]
    selectedInPrompt = messages.some(m => m.role === 'user' && /"selected_node_id"\s*:\s*"src"/.test(m.content))
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify({ model: 'editor-test', done: true, message: { role: 'assistant', content: JSON.stringify({
      explanation: 'Меняю название источника', operations: [{ op: 'update_node', node_id: 'src', label }],
    }) } }))
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  try {
    await register(page, 'editor-chat')
    const token = await page.evaluate(() => JSON.parse(localStorage.getItem('aisw.auth')!).accessToken)
    const headers = { Authorization: `Bearer ${token}` }
    const me = await page.request.get('/api/auth/me', { headers })
    const ws = (await me.json()).workspaces[0].id
    const configured = await page.request.put('/api/settings/ai', { headers, data: {
      workspace_id: ws, enabled: true, provider: 'ollama', model: 'editor-test', allow_local: true,
      base_url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    } })
    expect(configured.ok()).toBe(true)
    const dlg = page.getByRole('dialog', { name: 'Новая проверка' })
    await dlg.getByRole('tab', { name: 'Учебный проект' }).click()
    await dlg.getByRole('button', { name: /Пустой граф/ }).click()
    await dlg.getByRole('button', { name: 'Создать и открыть' }).click()
    const node = page.locator('.react-flow__node[data-id="src"]')
    await node.click()
    const ai = page.getByRole('button', { name: 'AI', exact: true })
    await ai.click()
    await page.getByRole('textbox', { name: /Например/ }).fill('Переименуй эту ноду')
    await page.getByRole('button', { name: 'Отправить' }).click()
    const apply = page.getByRole('button', { name: 'Применить', exact: true })
    await expect(apply).toBeVisible()
    await expect(node).not.toContainText(label)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()
    await expect(node).toBeAttached()
    await expect(ai).toBeVisible({ timeout: 5000 })
    await ai.click()
    await page.getByRole('button', { name: 'Посмотреть изменения' }).click()
    await apply.click()
    await expect(node).toContainText(label)
    await page.reload()
    await expect(node).toContainText(label)
    expect(modelRequests).toBe(1)
    expect(selectedInPrompt).toBe(true)
  } finally {
    server.closeAllConnections()
    await new Promise<void>((resolve, reject) => server.close(err => err ? reject(err) : resolve()))
  }
})
