'use strict'
const { test, expect } = require('@playwright/test')
const { useLocalMiniApp } = require('./helpers/local-api.cjs')

test('основные разделы: Главная, Помощник, Трекеры, История и Профиль', async ({ page }) => {
  const api = await useLocalMiniApp(page)
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/')
  await expect(page.locator('#homeScreen')).toBeVisible()
  await expect(page.locator('#heroGreeting')).toHaveText('Привет, Автотест!')

  const screens = [
    ['assistant', '#assistantScreen'],
    ['trackers', '#trackersScreen'],
    ['history', '#historyScreen'],
    ['profile', '#profileScreen'],
    ['home', '#homeScreen'],
  ]
  for (const [route, selector] of screens) {
    await page.locator('.bottomnav__item[data-route="' + route + '"]').click()
    await expect(page.locator(selector)).toBeVisible()
    await expect(page).toHaveURL(new RegExp('screen=' + route))
  }

  await page.locator('.bottomnav__item[data-route="profile"]').click()
  await expect(page.locator('#profileBody')).toContainText('Все функции бесплатно')
  await expect(page.locator('#profileBody')).toContainText('Автотест')
  await expect(page.locator('#profileBody')).toContainText('9 мес.')

  // Browsing must not create records, payments or messages.
  expect(api.state.calls.filter((call) => call.method !== 'GET')).toEqual([])
  expect(pageErrors).toEqual([])
  api.assertSafe()
})

test('прямая ссылка во внутренний экран восстанавливается после обновления', async ({ page }) => {
  const api = await useLocalMiniApp(page)
  await page.goto('/?screen=trackers')
  await expect(page.locator('#trackersScreen')).toBeVisible()
  await page.locator('[data-action-card="baby-diary"]').click()
  await expect(page.locator('#diaryTrackerScreen')).toBeVisible()
  await expect(page).toHaveURL(/screen=diary-tracker/)
  await page.reload()
  await expect(page.locator('#diaryTrackerScreen')).toBeVisible()
  api.assertSafe()
})
