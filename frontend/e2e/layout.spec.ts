import { register } from './register'
import { expect, test } from '@playwright/test'

test('workspace actions, node palette and results fit a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await register(page, 'layout')
  const dialog = page.getByRole('dialog', { name: 'Новая проверка' })
  await dialog.getByRole('tab', { name: 'Учебный проект' }).click()
  for (const action of await dialog.locator('footer button').all()) {
    expect.soft(await action.evaluate(el => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(1)
  }
  await dialog.getByRole('button', { name: 'Создать и открыть' }).click()
  await expect(page.locator('.react-flow__node').first()).toBeAttached()
  const canvas = page.locator('.canvas-area')
  for (const width of [390, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await expect.poll(() => canvas.evaluate(el => el.clientWidth)).toBeGreaterThan(280)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('.react-flow__node[data-id="src"]').click()
  await page.getByRole('button', { name: 'Ноды', exact: true }).click()
  const palette = page.getByRole('dialog', { name: 'Добавить ноду' })
  await expect(palette.getByLabel('Найти блок…')).toBeInViewport()
  await expect(palette.getByRole('button', { name: 'Закрыть' })).toBeInViewport()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Запустить' }).click()
  const results = page.getByRole('complementary', { name: 'Панель свойств и результатов' })
  await expect(results.getByRole('tab', { name: /Находки/ })).toContainText('15')
  const box = (await results.boundingBox())!
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(390)
})
