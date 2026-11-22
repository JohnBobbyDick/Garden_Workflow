import { expect, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'

export async function register(page: Page, prefix: string) {
  const email = `${prefix}-${randomUUID()}@example.org`
  await page.goto('/register')
  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Пароль').fill('E2e-Strong-Passw0rd')
  await page.getByRole('button', { name: 'Создать аккаунт' }).click()
  await expect(page).not.toHaveURL(/\/register$/)
}
