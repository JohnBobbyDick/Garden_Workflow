import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const TRAINING = resolve(import.meta.dirname, '../../fixtures/organizer-training/training-project')
const SCREENS = resolve(import.meta.dirname, '../../docs/screens')

async function drop(page: Page, type: string, x: number, y: number) {
  const canvas = page.locator('.react-flow__pane')
  await page.locator(`[data-node-type="${type}"]`).dragTo(canvas, { targetPosition: { x, y } })
}

async function connect(page: Page, from: string, out: string, to: string, inp: string) {
  const src = page.locator(`.react-flow__node[data-id="${from}"] .react-flow__handle.source[data-handleid="${out}"]`)
  const dst = page.locator(`.react-flow__node[data-id="${to}"] .react-flow__handle.target[data-handleid="${inp}"]`)
  const a = (await src.boundingBox())!
  const b = (await dst.boundingBox())!
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 })
  await page.waitForTimeout(80)
  await page.mouse.up()
}

async function runFromEditor(page: Page) {
  await page.getByRole('button', { name: 'Запустить' }).click()
  await expect(page.getByText('Выполняется').or(page.getByText('Успешно')).first()).toBeVisible()
  await expect(page.locator('header, div').getByText('Успешно', { exact: true }).first()).toBeVisible({ timeout: 90_000 })
}

test('register → build workflow by drag-and-drop → run → live statuses → findings/AI → compare → screenshots', async ({ page }) => {
  const email = `e2e-${Date.now()}@example.org`
  await page.goto('/register')
  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Пароль').fill('E2e-Strong-Passw0rd')
  await page.getByRole('button', { name: 'Создать аккаунт' }).click()
  await expect(page.getByRole('heading', { name: 'Обзор' })).toBeVisible()

  await page.getByRole('link', { name: 'Сценарии' }).click()
  await page.getByRole('button', { name: 'Новый сценарий' }).first().click()
  await page.getByLabel('Название').fill('E2E аудит')
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await expect(page.locator('.react-flow__node[data-id="manual_1"]')).toBeVisible()

  // build the graph by dragging blocks from the palette
  for (let i = 0; i < 3; i++) await page.locator('.react-flow__controls-zoomout').click()
  await drop(page, 'source.repo', 120, 150)
  await drop(page, 'scanner.secrets', 420, 80)
  await drop(page, 'scanner.sca', 420, 230)
  await drop(page, 'scanner.sast', 420, 380)
  await drop(page, 'logic.merge', 720, 150)
  await drop(page, 'ai.report', 720, 380)
  await drop(page, 'output.report_export', 720, 650)

  await connect(page, 'manual_1', 'out', 'repo_1', 'in')
  for (const s of ['secrets_1', 'sca_1', 'sast_1']) {
    await connect(page, 'repo_1', 'out', s, 'in')
    await connect(page, s, 'out', 'merge_1', 'in')
  }
  await connect(page, 'merge_1', 'out', 'report_1', 'in')
  await connect(page, 'merge_1', 'out', 'report_export_1', 'in')
  await connect(page, 'report_1', 'out', 'report_export_1', 'ai')
  // invalid connection is rejected with a message (types repo → findings input)
  await connect(page, 'repo_1', 'out', 'report_export_1', 'in')
  await expect(page.getByText(/Этот вход принимает только одну связь|Несовместимые типы портов/)).toBeVisible()
  await expect(page.locator('.react-flow__edge')).toHaveCount(10)
  await page.getByRole('button', { name: 'Авто-раскладка' }).click()

  // configure the source node from the generated form
  await page.locator('.react-flow__node[data-id="repo_1"]').click()
  await page.getByLabel('Источник').selectOption('path')
  await page.getByLabel('Путь (внутри APP_SCAN_ROOTS)').fill(TRAINING)
  await page.getByRole('button', { name: 'Проверить граф' }).click()
  await expect(page.getByText('Граф корректен')).toBeVisible()

  // undo/redo keeps working
  await page.locator('.react-flow__pane').click({ position: { x: 20, y: 20 } })
  await page.keyboard.press('Control+z')
  await page.keyboard.press('Control+y')

  const editorUrl = page.url()
  await runFromEditor(page)
  await expect(page.locator('.react-flow__node[data-id="sast_1"]')).toContainText(/находок|найдено/)

  await page.getByRole('link', { name: 'Открыть детали запуска' }).click()
  await expect(page.getByRole('tab', { name: /Находки/ })).toContainText('15')
  await expect(page.getByText('Внедрение SQL').first()).toBeVisible()
  await page.getByRole('tab', { name: 'AI-отчёт' }).click()
  await expect(page.getByText(/Отчёт сформирован без AI/).first()).toBeVisible()
  const runUrl = page.url()

  // second run + comparison
  await page.goto(editorUrl)
  await runFromEditor(page)
  await page.getByRole('link', { name: 'Запуски' }).click()
  const boxes = page.getByRole('checkbox')
  await boxes.nth(0).check()
  await boxes.nth(1).check()
  await page.getByRole('button', { name: 'Сравнить выбранные' }).click()
  await expect(page.getByRole('heading', { name: 'Сравнение запусков' })).toBeVisible()
  await expect(page.getByText('Без изменений').first()).toBeVisible()

  // screenshots: dark/light × RU/EN
  mkdirSync(SCREENS, { recursive: true })
  for (const theme of ['dark', 'light'] as const) {
    for (const lang of ['ru', 'en'] as const) {
      await page.evaluate(([t, l]) => { localStorage.setItem('aisw.theme', t); localStorage.setItem('aisw.lang', l) }, [theme, lang])
      await page.goto('/')
      await page.waitForTimeout(1200)
      await page.screenshot({ path: `${SCREENS}/dashboard-${theme}-${lang}.png` })
      await page.goto(runUrl)
      await page.waitForTimeout(1200)
      await page.screenshot({ path: `${SCREENS}/run-${theme}-${lang}.png` })
      await page.goto('/workflows')
      await page.getByRole('link', { name: 'E2E аудит' }).click()
      await page.waitForTimeout(1500)
      await page.screenshot({ path: `${SCREENS}/editor-${theme}-${lang}.png` })
    }
  }
})

test('template library: use a built-in template → run → publish own → find it → rate', async ({ page }) => {
  await page.goto('/register')
  await page.getByLabel('E-mail').fill(`tpl-${Date.now()}@example.org`)
  await page.getByLabel('Пароль').fill('E2e-Strong-Passw0rd')
  await page.getByRole('button', { name: 'Создать аккаунт' }).click()
  await page.getByRole('link', { name: 'Шаблоны' }).click()
  await page.getByLabel('Поиск').fill('SCA')
  await page.getByRole('button', { name: /SCA зависимостей/ }).click()
  await page.getByLabel(/src\.path/).fill(TRAINING)
  await page.getByLabel('Название нового сценария').fill('Из шаблона')
  await page.getByRole('button', { name: 'Использовать' }).click()
  await expect(page.getByRole('heading', { name: 'Из шаблона' })).toBeVisible()
  await runFromEditor(page)
  await page.getByRole('button', { name: 'К редактированию' }).click()
  await page.getByRole('button', { name: 'Опубликовать как шаблон' }).click()
  await page.getByLabel('Название', { exact: false }).first().fill('Мой SCA-шаблон')
  await page.getByRole('dialog').getByRole('button', { name: 'Опубликовать как шаблон' }).click()
  await expect(page.getByText('Шаблон опубликован')).toBeVisible()
  await page.getByRole('link', { name: 'Шаблоны' }).click()
  await page.getByLabel('scope').selectOption('mine')
  await page.getByRole('button', { name: /Мой SCA-шаблон/ }).click()
  await page.getByRole('button', { name: 'Ваша оценка 5' }).click()
  await page.getByLabel('Оставить отзыв').fill('Работает')
  await page.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.getByRole('dialog').getByText('Работает')).toBeVisible()
})
