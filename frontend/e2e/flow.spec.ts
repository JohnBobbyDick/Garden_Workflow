import { register } from './register'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const SCREENS = process.env.AISW_SCREEN_DIR ?? resolve(import.meta.dirname, '../../docs/screens')

async function newCheckDialog(page: Page) {
  const dlg = page.getByRole('dialog', { name: 'Новая проверка' })
  // a fresh account gets the window automatically; otherwise open it from the left column
  const auto = await dlg.waitFor({ timeout: 8000 }).then(() => true, () => false)
  if (!auto) await page.getByRole('button', { name: 'Новая проверка' }).first().click()
  await expect(dlg).toBeVisible()
  return dlg
}

async function moveNode(page: Page, node: Locator) {
  await node.hover()
  const before = await node.evaluate(el => (el as HTMLElement).style.transform)
  const box = (await node.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 64, box.y + box.height / 2 + 32, { steps: 10 })
  await page.mouse.up()
  await expect.poll(() => node.evaluate(el => (el as HTMLElement).style.transform)).not.toBe(before)
}

async function waitRunEnd(page: Page) {
  await expect(page.locator('.run-banner')).toContainText(/Успешно|Ошибка/, { timeout: 90_000 })
}

async function drop(page: Page, type: string, x: number, y: number) {
  await page.getByLabel('Найти блок…').fill(type)
  await page.locator(`[role=dialog] [data-node-type="${type}"]`).dragTo(page.locator('.react-flow__pane'), { targetPosition: { x, y } })
}

async function connect(page: Page, from: string, out: string, to: string, inp: string) {
  const src = page.locator(`.react-flow__node[data-id="${from}"] .react-flow__handle.source[data-handleid="${out}"]`)
  const dst = page.locator(`.react-flow__node[data-id="${to}"] .react-flow__handle.target[data-handleid="${inp}"]`)
  // Quick-add pans the canvas. Wait for both handles to settle before reading their coordinates.
  await dst.hover({ trial: true })
  await src.hover({ trial: true })
  const a = (await src.boundingBox())!
  const b = (await dst.boundingBox())!
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 })
  await page.waitForTimeout(80)
  await page.mouse.up()
}

test('jury path: first visit → «Новая проверка» → учебный проект → запуск → итоги → AutoFix → перепроверка → старые ссылки', async ({ page }) => {
  await register(page, 'e2e')
  // no checks yet: the new-check window opens by itself
  const dlg = await newCheckDialog(page)
  await dlg.getByRole('tab', { name: 'Учебный проект' }).click()
  await dlg.getByRole('button', { name: 'Создать и запустить' }).click()
  await expect(page).toHaveURL(/\/c\/[0-9a-f]{32}\?run=[0-9a-f]{32}/)
  await waitRunEnd(page)
  await expect(page.locator('.run-banner')).toContainText('Успешно')
  await expect(page.locator('.node-success').first()).toBeVisible()
  await expect(page.locator('.react-flow__edge.edge-done').first()).toBeAttached()

  const node = page.locator('.react-flow__node[data-id="src"]')
  await node.click()
  await expect(page.getByRole('button', { name: 'Раскладка', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'AI', exact: true })).toBeVisible()
  for (const name of ['Логи', 'Данные', 'Настройки']) await page.getByRole('tab', { name, exact: name !== 'Логи' }).click()
  const saved = page.waitForResponse(r => r.request().method() === 'PUT' && /\/api\/workflows\/[^/]+$/.test(r.url()))
  await moveNode(page, node)
  expect((await saved).ok()).toBeTruthy()
  const after = await node.evaluate(el => (el as HTMLElement).style.transform)
  await page.reload()
  await expect(node).toBeVisible()
  await expect.poll(() => node.evaluate(el => (el as HTMLElement).style.transform)).toBe(after)

  const results = page.getByRole('complementary', { name: 'Панель свойств и результатов' })
  await expect(results.getByRole('tab', { name: /Находки/ })).toContainText('15')
  await results.getByRole('button', { name: /Уязвимая зависимость org\.apache\.commons:commons-text/ }).click()
  await results.getByRole('button', { name: 'Проверить патч' }).click()
  await expect(results.getByText('Патч проверен и готов к применению.')).toBeVisible({ timeout: 60_000 })
  await expect(results.getByRole('button', { name: 'Создать PR' })).toHaveCount(0)  // organizers' repo is read-only
  await results.getByRole('button', { name: 'Применить патч и перепроверить' }).click()
  await expect(results.getByRole('tab', { name: /Находки/ })).toContainText('14', { timeout: 90_000 })
  await expect(results.getByRole('button', { name: /Уязвимая зависимость org\.apache\.commons:commons-text/ })).toHaveCount(0)
  const correctedUrl = page.url()
  const correctedId = new URL(correctedUrl).searchParams.get('run')!
  await page.getByRole('button', { name: 'Ещё', exact: true }).click()
  await page.getByRole('menuitem', { name: 'CI/CD' }).click()
  const ci = page.getByRole('dialog', { name: 'CI/CD' })
  await expect(ci).toContainText(/runs-on|stages/)
  await ci.getByRole('button', { name: 'Закрыть' }).click()
  await expect(page).toHaveURL(correctedUrl, { timeout: 5000 })

  const actions = results.getByRole('button', { name: 'Действия с запуском' })
  const menu = results.getByRole('menu', { name: 'Действия с запуском' })
  for (const name of ['report.md', 'submission.json', 'report.html']) {
    await actions.click()
    const pending = page.waitForEvent('download')
    await menu.getByRole('menuitem', { name, exact: true }).click()
    const file = await pending
    expect(file.suggestedFilename()).toBe(name)
    const contents = await readFile((await file.path())!, 'utf8')
    if (name === 'submission.json') expect(JSON.parse(contents).findings).toHaveLength(14)
    else {
      expect(contents).toMatch(name === 'report.md' ? /^# Отчёт/ : /^<!DOCTYPE html>/)
      expect(contents).toContain('build.gradle.kts')
    }
  }
  await actions.click()
  await menu.getByRole('menuitem', { name: 'Сравнить' }).click()
  const compare = page.getByRole('dialog', { name: 'Сравнение запусков' })
  await expect(compare.getByText(/commons-text/).first()).toBeVisible()
  await compare.getByRole('button', { name: 'Закрыть' }).click()
  await expect(page).toHaveURL(correctedUrl)
  await actions.click()
  await menu.getByRole('menuitem', { name: 'Полный отчёт' }).click()
  await expect(page).toHaveURL(new RegExp('/runs/' + correctedId + '\\?full=1'))
  await expect(page.getByRole('tab', { name: /Находки/ })).toBeVisible()
  await page.goBack()
  await actions.click()
  await menu.getByRole('menuitem', { name: 'Исправить все' }).click()
  await expect(results.getByRole('tab', { name: /Находки/ })).toContainText('10', { timeout: 90_000 })
  const download = page.waitForEvent('download')
  await results.getByRole('button', { name: 'Действия с запуском' }).click()
  await menu.getByRole('menuitem', { name: /Скачать исправленный проект/ }).click()
  expect((await download).suggestedFilename()).toMatch(/^fixed-.*\.zip$/)

  // links from notifications / CI / report.html and the old editor address keep working
  const [, wf, run] = page.url().match(/\/c\/([0-9a-f]{32})\?run=([0-9a-f]{32})/)!
  await page.goto(`/runs/${run}?full=1&tab=graph`)
  await moveNode(page, page.locator('.react-flow__node[data-id="src"]'))
  await page.goto(`/runs/${run}`)
  await expect(page).toHaveURL(new RegExp(`/c/${wf}\\?run=${run}`))
  await page.goto(`/workflows/${wf}`)
  await expect(page).toHaveURL(new RegExp(`/c/${wf}$`))
})

test('constructor: blank graph → nodes by drag, «+» under a node and Tab → links → run with live statuses', async ({ page }) => {
  await register(page, 'canvas')
  const dlg = await newCheckDialog(page)
  await dlg.getByRole('tab', { name: 'Учебный проект' }).click()
  await dlg.getByRole('button', { name: /Пустой граф/ }).click()
  await dlg.getByRole('button', { name: 'Создать и открыть' }).click()
  await expect(page.locator('.react-flow__node[data-id="src"]')).toBeVisible()

  // quick-add palette: drag three scanners and a merge onto the canvas (right of the floating palette)
  await page.locator('.react-flow__node[data-id="src"]').click()
  await page.getByRole('button', { name: 'Ноды', exact: true }).click()
  const pane = (await page.locator('.react-flow__pane').boundingBox())!
  const src = (await page.locator('.react-flow__node[data-id="src"]').boundingBox())!
  const cx = src.x - pane.x + src.width / 2
  const y = src.y - pane.y + src.height + 80
  await drop(page, 'scanner.secrets', Math.max(380, cx - 280), y)
  await drop(page, 'scanner.sca', Math.max(380, cx) + 280, y)
  await drop(page, 'scanner.sast', Math.max(380, cx) + 560, y)
  await page.keyboard.press('Escape')
  for (const s of ['secrets_1', 'sca_1', 'sast_1']) await connect(page, 'src', 'out', s, 'in')
  await expect(page.locator('.react-flow__edge')).toHaveCount(4)

  // «+» under a selected node: the new node is placed below and connected automatically
  await page.locator('.react-flow__node[data-id="secrets_1"]').click()
  await page.getByRole('button', { name: 'Добавить ноду после этой' }).click()
  await page.getByLabel('Найти блок…').fill('output.report_export')
  await page.locator('[role=dialog] [data-node-type="output.report_export"]').click()
  await expect(page.locator('.react-flow__node[data-id="report_export_1"]')).toBeVisible()
  await expect(page.locator('.react-flow__edge')).toHaveCount(5)

  // Tab toggles the palette
  await page.locator('.react-flow__pane').click({ position: { x: 20, y: 20 } })
  await page.keyboard.press('Tab')
  await expect(page.getByRole('dialog', { name: 'Добавить ноду' })).toBeVisible()
  await page.keyboard.press('Escape')

  // invalid connection is refused with a reason
  await connect(page, 'src', 'out', 'report_export_1', 'in')
  await expect(page.getByText(/Этот вход принимает только одну связь|Несовместимые типы портов/)).toBeVisible()

  // undo / redo
  await page.keyboard.press('Control+z')
  await page.keyboard.press('Control+y')

  await page.getByRole('button', { name: 'Запустить' }).click()
  await waitRunEnd(page)
  await expect(page.locator('.react-flow__node[data-id="secrets_1"]')).toContainText(/находок|найдено/)
  await expect(page.locator('.react-flow__edge-textwrapper').first()).toBeAttached()
})

test('templates and CI/CD in panels: publish → find → rate → use for your repo; CI YAML', async ({ page }) => {
  await register(page, 'tpl')
  const dlg = await newCheckDialog(page)
  await dlg.getByRole('tab', { name: 'Учебный проект' }).click()
  await dlg.getByRole('button', { name: /Только секреты/ }).click()
  await dlg.getByRole('button', { name: 'Создать и открыть' }).click()
  await expect(page.locator('.react-flow__node').first()).toBeVisible()

  await page.getByRole('button', { name: 'Ещё' }).click()
  await page.getByRole('menuitem', { name: 'Опубликовать как шаблон' }).click()
  await page.getByRole('dialog').getByLabel('Название', { exact: false }).first().fill('Мой шаблон секретов')
  await page.getByRole('dialog').getByRole('button', { name: 'Опубликовать как шаблон' }).click()
  await expect(page.getByText('Шаблон опубликован')).toBeVisible()

  await page.getByRole('button', { name: 'Шаблоны' }).click()
  const panel = page.getByRole('dialog', { name: 'Шаблоны' })
  await panel.getByLabel('scope').selectOption('mine')
  await panel.getByRole('button', { name: /Мой шаблон секретов/ }).click()
  await moveNode(page, page.locator('[role=dialog] .react-flow__node').first())
  await page.getByRole('button', { name: 'Ваша оценка 5' }).click()
  await page.getByLabel('Оставить отзыв').fill('Работает')
  await page.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.getByText('Работает')).toBeVisible()
  await page.getByRole('button', { name: 'Использовать для своего репозитория' }).click()
  const nc = page.getByRole('dialog', { name: 'Новая проверка' })
  await expect(nc).toBeVisible()
  await expect(nc.getByRole('button', { name: /Мой шаблон секретов/ })).toBeVisible()
  await nc.getByRole('button', { name: 'Закрыть' }).or(nc.getByLabel('close')).first().click()

  await page.getByRole('button', { name: 'CI/CD' }).click()
  await expect(page.getByRole('dialog', { name: 'CI/CD' })).toContainText(/runs-on|stages|aisw/)
})

test('editor menu validates, exports, reimports the same file and deletes a disposable workflow', async ({ page }, testInfo) => {
  await register(page, 'menu')
  const dlg = await newCheckDialog(page)
  await dlg.getByRole('tab', { name: 'Учебный проект' }).click()
  await dlg.getByRole('button', { name: 'Создать и открыть' }).click()
  const node = page.locator('.react-flow__node[data-id="src"]')
  await expect(node).toBeVisible()
  const more = page.getByRole('button', { name: 'Ещё', exact: true })
  async function choose(name: string) {
    await more.click()
    await page.getByRole('menuitem', { name, exact: true }).click()
  }
  await choose('Проверить граф')
  await expect(page.getByText('Граф корректен', { exact: true })).toBeVisible()
  const pending = page.waitForEvent('download')
  await choose('Экспорт JSON')
  const file = await pending
  const contents = JSON.parse(await readFile((await file.path())!, 'utf8'))
  const src = contents.graph.nodes.find((n: { id: string }) => n.id === 'src')
  src.label = 'Источник из файла'
  const filename = testInfo.outputPath('workflow.json')
  await writeFile(filename, JSON.stringify(contents))
  for (let attempt = 0; attempt < 2; attempt++) {
    const picker = page.waitForEvent('filechooser')
    await choose('Импорт JSON')
    await (await picker).setFiles(filename)
    await expect(node).toContainText(src.label, { timeout: 5000 })
    if (attempt === 0) {
      await page.keyboard.press('Control+z')
      await expect(node).not.toContainText(src.label)
    }
  }
  const url = page.url()
  page.once('dialog', dialog => dialog.dismiss())
  await choose('Удалить проверку')
  await expect(page).toHaveURL(url)
  const deletion = page.waitForResponse(r => r.request().method() === 'DELETE' && r.url().endsWith(new URL(url).pathname.split('/').pop()!))
  page.once('dialog', dialog => dialog.accept())
  await choose('Удалить проверку')
  expect((await deletion).ok()).toBe(true)
  await expect(page).not.toHaveURL(url)
})

test('own repository link: https only, confirmation required, attested repo becomes the source', async ({ page }) => {
  await register(page, 'link')
  const dlg = await newCheckDialog(page)
  await dlg.getByLabel('Ссылка на репозиторий (https)').fill('http://github.com/x/y')
  await expect(dlg.getByRole('alert')).toContainText('https')
  await dlg.getByLabel('Ссылка на репозиторий (https)').fill('https://github.com/TBagirov/training/tree/main/training-project')
  const open = dlg.getByRole('button', { name: 'Создать и открыть' })
  await expect(open).toBeDisabled()
  await dlg.getByRole('checkbox').check()
  await expect(open).toBeEnabled()
  await open.click()
  const resolved = await Promise.race([
    page.waitForURL(/\/c\/[0-9a-f]{32}/, { timeout: 20_000 }).then(() => true),
    dlg.getByRole('alert').waitFor({ timeout: 20_000 }).then(() => false),
  ])
  test.skip(!resolved && /разрешить имя/.test(await dlg.getByRole('alert').innerText()), 'no DNS in this environment')
  await expect(page.getByRole('button', { name: /github\.com\/tbagirov\/training/ })).toBeVisible()
})

test('settings → AI: proxy secret and connection diagnostics table; screenshots', async ({ page }) => {
  await register(page, 'ai')
  const dlg = await newCheckDialog(page)
  await dlg.getByRole('tab', { name: 'Учебный проект' }).click()
  await dlg.getByRole('button', { name: 'Создать и запустить' }).click()
  await waitRunEnd(page)
  const runUrl = page.url()

  await page.getByRole('button', { name: 'Настройки' }).click()
  const panel = page.getByRole('dialog', { name: 'Настройки' })
  await panel.getByRole('radio', { name: /Nemotron/ }).click()
  await panel.getByText('Ключи, прокси и повторные попытки', { exact: true }).click()
  await panel.getByLabel('Название прокси').fill('dead-proxy')
  await panel.getByLabel('Прокси', { exact: true }).fill('127.0.0.1:9:user:secret-pass')
  await panel.getByRole('button', { name: 'Добавить прокси' }).click()
  await expect(panel.getByRole('checkbox', { name: /dead-proxy/ })).toBeChecked()
  await expect(panel).not.toContainText('secret-pass')
  await panel.getByRole('radio', { name: 'Ollama' }).click()
  await panel.getByLabel('Base URL').fill('http://127.0.0.1:9')
  await panel.getByLabel('Модель', { exact: true }).fill('local-test')
  await panel.getByRole('button', { name: 'Диагностика' }).click()
  const table = panel.getByRole('table', { name: 'Диагностика' })
  await expect(table).toBeVisible({ timeout: 60_000 })
  await expect(table).toContainText('напрямую')
  await expect(table).toContainText('FAIL')
  await expect(table).not.toContainText('secret-pass')
  await page.keyboard.press('Escape')

  mkdirSync(SCREENS, { recursive: true })
  for (const theme of ['light', 'dark'] as const) {
    for (const lang of ['ru', 'en'] as const) {
      await page.evaluate(([th, l]) => { localStorage.setItem('aisw.theme', th); localStorage.setItem('aisw.lang', l) }, [theme, lang])
      await page.goto(runUrl)
      await expect(page.locator('.node-success').first()).toBeVisible({ timeout: 20_000 })
      await page.waitForTimeout(1200)
      await page.screenshot({ path: `${SCREENS}/workspace-${theme}-${lang}.png` })
    }
  }
  await page.evaluate(() => { localStorage.setItem('aisw.theme', 'light'); localStorage.setItem('aisw.lang', 'ru') })
  await page.goto(`${runUrl.split('?')[0]}?new=1`)
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${SCREENS}/new-check-light-ru.png` })
  await page.goto(`/runs/${runUrl.split('run=')[1]}?full=1`)
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${SCREENS}/run-report-light-ru.png` })
})

test('workspace nodes: author a rule, reuse it after reload, run it on grouped findings', async ({ page }) => {
  await register(page, 'custom')
  const dlg = await newCheckDialog(page)
  await dlg.getByRole('tab', { name: 'Учебный проект' }).click()
  await dlg.getByRole('button', { name: /Пустой граф/ }).click()
  await dlg.getByRole('button', { name: 'Создать и открыть' }).click()
  await page.locator('.react-flow__node[data-id="src"]').click()
  await page.getByRole('button', { name: 'Ноды', exact: true }).click()
  const palette = page.getByRole('dialog', { name: 'Добавить ноду' })
  await palette.getByRole('button', { name: 'Создать ноду' }).click()
  await palette.getByLabel('Название').fill('Нужно ревью')
  await palette.getByLabel('Поле результата').fill('review')
  await palette.getByLabel('Путь или условие').fill('=total > 0')
  await palette.getByRole('button', { name: 'Сохранить ноду' }).click()
  await expect(palette.getByRole('button', { name: 'Нужно ревью' })).toBeVisible()
  await page.reload()
  for (const [source, type] of [['src', 'scanner.secrets'], ['secrets_1', 'analysis.top_findings'],
    ['top_findings_1', 'analysis.group_findings'], ['group_findings_1', 'Нужно ревью']]) {
    await page.locator(`.react-flow__node[data-id="${source}"]`).click()
    await page.getByRole('button', { name: 'Добавить ноду после этой' }).click()
    await palette.getByLabel('Найти блок…').fill(type)
    if (type === 'Нужно ревью') await palette.getByRole('button', { name: type }).click()
    else await palette.locator(`[data-node-type="${type}"]`).click()
  }
  await expect(page.locator('.react-flow__node[data-id="map_fields_1"]')).toContainText('Нужно ревью')
  await page.getByRole('button', { name: 'Запустить' }).click()
  await waitRunEnd(page)
  await expect(page.locator('.run-banner')).toContainText('Успешно')
  await page.locator('.react-flow__node[data-id="map_fields_1"]').click()
  await page.getByRole('tab', { name: 'Данные' }).click()
  await expect(page.getByText(/"review":\s*true/).first()).toBeVisible()
})

test('review catalog: find review nodes and export a sampled scan to CSV', async ({ page }) => {
  await register(page, 'review')
  const dlg = await newCheckDialog(page)
  await dlg.getByRole('tab', { name: 'Учебный проект' }).click()
  await dlg.getByRole('button', { name: /Пустой граф/ }).click()
  await dlg.getByRole('button', { name: 'Создать и открыть' }).click()
  await page.locator('.react-flow__node[data-id="src"]').click()
  await page.getByRole('button', { name: 'Ноды', exact: true }).click()
  const palette = page.getByRole('dialog', { name: 'Добавить ноду' })
  const search = palette.getByLabel('Найти блок…')
  for (const type of ['logic.path_filter', 'logic.finding_delta', 'logic.check_fields', 'logic.join_json',
    'logic.render_text', 'analysis.audit_sample', 'analysis.file_hotspots', 'analysis.dependency_fixes',
    'analysis.severity_budget', 'analysis.ai_coverage', 'output.findings_csv']) {
    await search.fill(type)
    await expect(palette.locator(`[data-node-type="${type}"]`)).toBeVisible()
  }
  await page.keyboard.press('Escape')
  for (const [source, type] of [['src', 'scanner.secrets'], ['secrets_1', 'analysis.audit_sample'],
    ['audit_sample_1', 'output.findings_csv']]) {
    await page.locator(`.react-flow__node[data-id="${source}"]`).click()
    await page.getByRole('button', { name: 'Добавить ноду после этой' }).click()
    await search.fill(type)
    await palette.locator(`[data-node-type="${type}"]`).click()
  }
  await page.getByRole('button', { name: 'Запустить' }).click()
  await waitRunEnd(page)
  await expect(page.locator('.run-banner')).toContainText('Успешно')
  await page.getByRole('button', { name: 'Действия с запуском' }).click()
  await page.getByRole('menuitem', { name: 'Полный отчёт' }).click()
  await page.getByRole('tab', { name: 'Артефакты и экспорт' }).click()
  const row = page.getByRole('listitem').filter({ hasText: /findings-.*\.csv/ })
  await expect(row).toBeVisible()
  const download = page.waitForEvent('download')
  await row.getByRole('button', { name: 'Скачать' }).click()
  expect((await download).suggestedFilename()).toMatch(/^findings-.*\.csv$/)
})
