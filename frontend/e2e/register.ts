import { expect, type Page } from '@playwright/test'
import { createHash, randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

export async function register(page: Page, prefix: string) {
  const email = `${prefix}-${randomUUID()}@example.org`
  await page.goto('/register')
  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Пароль').fill('E2e-Strong-Passw0rd')
  await page.getByRole('button', { name: 'Получить код' }).click()
  const field = page.getByLabel('Код из письма')
  await expect(field).toBeVisible()
  const mailbox = join(process.env.AISW_E2E_INBOX!, createHash('sha256').update(email).digest('hex'))
  const body = await readFile(mailbox, 'utf8')
  const code = body.match(/\b[0-9]{6}\b/)?.[0]
  if (!code) throw new Error('Registration email is missing its confirmation code')
  await field.fill(code)
  await page.getByRole('button', { name: 'Создать аккаунт' }).click()
  await expect(page).not.toHaveURL(/\/register$/)
}
