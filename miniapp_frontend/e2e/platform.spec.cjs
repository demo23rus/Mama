'use strict'
const { test, expect } = require('@playwright/test')
const { useLocalMiniApp } = require('./helpers/local-api.cjs')

for (const platform of ['telegram', 'max']) {
  test(platform + ': синтетический SDK и корректные заголовки Mini App', async ({ page }) => {
    const api = await useLocalMiniApp(page, { platform })
    await page.goto('/?screen=profile')
    await expect(page.locator('#profileScreen')).toBeVisible()
    await expect(page.locator('#profileBody')).toContainText(platform === 'telegram' ? 'Telegram' : 'MAX')

    const profileCall = api.state.calls.find((c) => c.method === 'GET' && c.path === '/profile')
    expect(profileCall).toBeDefined()
    expect(profileCall.headers['x-miniapp-platform']).toBe(platform)
    expect(profileCall.headers['x-init-data']).toBe('SYNTHETIC_TEST_INIT_DATA_NOT_SIGNED')
    expect(api.state.calls.filter((c) => c.method !== 'GET')).toEqual([])
    api.assertSafe()
  })
}

test('без авторизации: ошибка 401 не выдаёт профиль и не отправляет данные', async ({ page }) => {
  const api = await useLocalMiniApp(page, { httpErrors: { 'GET /profile': 401 } })
  await page.goto('/?screen=profile')
  await expect(page.locator('#profileBody')).toContainText('Нужен вход через Telegram')
  await expect(page.locator('#profileBody')).not.toContainText('Автотест')
  expect(api.state.calls.filter((c) => c.method !== 'GET')).toEqual([])
  api.assertSafe()
})

test('ошибка сервера: профиль показывает повторную попытку без побочных запросов', async ({ page }) => {
  const api = await useLocalMiniApp(page, { httpErrors: { 'GET /profile': 500 } })
  await page.goto('/?screen=profile')
  await expect(page.locator('#profileBody')).toContainText('Не получилось загрузить')
  await expect(page.locator('#profileRetryBtn')).toBeVisible()
  await page.locator('#profileRetryBtn').click()
  await expect(page.locator('#profileBody')).toContainText('Не получилось загрузить')
  const attempts = api.state.calls.filter((c) => c.method === 'GET' && c.path === '/profile')
  expect(attempts.length).toBeGreaterThanOrEqual(2)
  api.assertSafe()
})

for (const platform of ['telegram', 'max']) {
  test(platform + ': нативная кнопка Назад открывает предыдущий раздел', async ({ page }) => {
    const api = await useLocalMiniApp(page, { platform })
    await page.goto('/?screen=trackers')
    await expect(page.locator('#trackersScreen')).toBeVisible()
    await page.locator('[data-action-card="baby-diary"]').click()
    await expect(page.locator('#diaryTrackerScreen')).toBeVisible()

    const before = await page.evaluate(() => ({
      ready: window.__mamaMockBridge.ready,
      expand: window.__mamaMockBridge.expand,
      shown: window.__mamaMockBridge.show,
      hasBackCallback: typeof window.__mamaMockBridge.backCallback === 'function',
    }))
    expect(before.ready).toBeGreaterThanOrEqual(1)
    expect(before.expand).toBeGreaterThanOrEqual(1)
    expect(before.shown).toBeGreaterThanOrEqual(1)
    expect(before.hasBackCallback).toBe(true)

    await page.evaluate(() => window.__mamaMockBridge.backCallback())
    await expect(page.locator('#trackersScreen')).toBeVisible()
    const hideCount = await page.evaluate(() => window.__mamaMockBridge.hide)
    expect(hideCount).toBeGreaterThanOrEqual(2)
    api.assertSafe()
  })
}
