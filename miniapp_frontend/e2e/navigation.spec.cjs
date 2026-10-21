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


test('Профиль: часовой пояс сохраняется и повторно отображается', async ({ page }) => {
  const api = await useLocalMiniApp(page, { platform: 'telegram' })
  await page.goto('/?screen=profile')
  await expect(page.locator('#profileScreen')).toBeVisible()

  await page.locator('#profileTimezoneBtn').click()
  await expect(page.locator('#timezoneScreen')).toBeVisible()
  await expect(page).toHaveURL(/screen=timezone/)

  await page.locator('#timezoneSelect').selectOption('Asia/Krasnoyarsk')
  await page.locator('#timezoneSaveBtn').click()
  await expect(page.locator('#timezoneBody')).toContainText('Часовой пояс сохранён')
  expect(api.state.timezone).toBe('Asia/Krasnoyarsk')

  await page.locator('[data-back="profile"]').click()
  await expect(page.locator('#profileScreen')).toBeVisible()
  await expect(page.locator('#profileBody')).toContainText('Красноярск')

  expect(api.state.unexpected).toEqual([])
})


test('Профиль: центр уведомлений сохраняет выбранные настройки', async ({ page }) => {
  const api = await useLocalMiniApp(page, { platform: 'telegram' })
  await page.goto('/?screen=profile')
  await page.locator('#profileNotificationsBtn').click()
  await expect(page.locator('#notificationsScreen')).toBeVisible()

  await page.locator('[data-notification-key="vaccine_today"]').check({ force: true })
  await page.locator('[data-notification-key="growth_monthly"]').check({ force: true })
  await page.locator('#notificationsSaveBtn').click()
  await expect(page.locator('#notificationsBody')).toContainText('Настройки уведомлений сохранены')

  expect(api.state.notifications.vaccine_3d).toBe(true)
  expect(api.state.notifications.vaccine_today).toBe(true)
  expect(api.state.notifications.growth_monthly).toBe(true)
  expect(api.state.notifications.weekly_summary).toBe(false)
  expect(api.state.unexpected).toEqual([])
})


test('Сегодня: «Моя неделя» показывает сводку и AI-ориентиры по кнопке', async ({ page }) => {
  const api = await useLocalMiniApp(page, { platform: 'telegram' })
  await page.goto('/?screen=today')
  await expect(page.locator('#todayScreen')).toBeVisible()
  await page.locator('#todayWeekBtn').click()
  await expect(page.locator('#weekScreen')).toBeVisible()
  await expect(page.locator('#weekBody')).toContainText('15.10.2026')
  await expect(page.locator('#weekBody')).toContainText('Активных дней')
  await expect(page.locator('#weekBody')).toContainText('АКДС')

  await page.locator('#weekAdviceBtn').click()
  await expect(page.locator('#weekAdviceBody')).toContainText('PLAYWRIGHT TEST: недельный вывод')
  expect(api.state.unexpected).toEqual([])
})

test('Главная: «Моя неделя» открывает сводку и AI-вывод только по кнопке', async ({ page }) => {
  const api = await useLocalMiniApp(page, { platform: 'telegram' })
  await page.goto('/')
  await page.locator('#weekEntry').click()
  await expect(page.locator('#weekScreen')).toBeVisible()
  await expect(page.locator('#weekBody')).toContainText('15.10.2026 — 21.10.2026')
  await expect(page.locator('#weekBody')).toContainText('Брокколи')

  expect(api.state.calls.filter((call) => call.path === '/week/advice')).toHaveLength(0)
  await page.locator('#weekAdviceBtn').click()
  await expect(page.locator('#weekAdviceBody')).toContainText('PLAYWRIGHT TEST: недельный вывод')
  expect(api.state.calls.filter((call) => call.path === '/week/advice')).toHaveLength(1)
  api.assertSafe()
})


test('Главная: «Актуально для вас» приоритетно показывает ближайшую прививку', async ({ page }) => {
  const future = new Date()
  future.setDate(future.getDate() + 3)
  const dd = String(future.getDate()).padStart(2, '0')
  const mm = String(future.getMonth() + 1).padStart(2, '0')
  const yyyy = future.getFullYear()
  const api = await useLocalMiniApp(page, {
    platform: 'telegram',
    today: {
      registered: true, mode: 'mother', child_age_label: '9 мес.', child_months: 9,
      sleep_count_24h: 0,
      nearest_vaccine: { vaccine: 'АКДС', scheduled_date: dd + '.' + mm + '.' + yyyy },
    },
  })
  await page.goto('/')
  await expect(page.locator('#relevantNow')).toBeVisible()
  await expect(page.locator('#relevantNow')).toContainText('Прививка через 3 дн.')
  await expect(page.locator('#relevantNow')).toContainText('АКДС')
  await page.locator('#relevantNow').click()
  await expect(page.locator('#vaccinesTrackerScreen')).toBeVisible()
  api.assertSafe()
})

test('Главная: «Актуально для вас» поднимает Прикорм 6+ без нового ярлыка', async ({ page }) => {
  const api = await useLocalMiniApp(page, {
    platform: 'telegram',
    today: {
      registered: true, mode: 'mother', child_age_label: '7 мес.', child_months: 7,
      sleep_count_24h: 0,
    },
  })
  await page.goto('/')
  await expect(page.locator('#relevantNow')).toBeVisible()
  await expect(page.locator('#relevantNow')).toContainText('Прикорм 6+')
  expect(await page.locator('.shortcut-grid [data-action-card="complementary-feeding"]').count()).toBe(0)
  api.assertSafe()
})


test('Прикорм 6+: «Что приготовить сегодня?» использует только знакомые продукты', async ({ page }) => {
  const api = await useLocalMiniApp(page, { platform: 'telegram' })
  await page.goto('/?screen=feeding-tracker')
  await page.locator('#cfEntryBtn').click()
  await expect(page.locator('#cfScreen')).toBeVisible()

  await page.locator('[data-cf-nav="ideas"]').click()
  await expect(page.locator('#cfScreen')).toContainText('Что приготовить сегодня?')
  await expect(page.locator('.cf-idea-card').first()).toBeVisible()
  await expect(page.locator('#cfBody')).toContainText('Кабачок')
  await expect(page.locator('#cfBody')).toContainText('Индейка')
  await expect(page.locator('#cfBody')).not.toContainText('Йогурт')
  await expect(page.locator('#cfBody')).toContainText('Продукты с реакцией')
  expect(api.state.unexpected).toEqual([])
})


test('Дневник малыша: сохраняет структурированный момент в хронологию', async ({ page }) => {
  const api = await useLocalMiniApp(page, { platform: 'telegram' })
  await page.goto('/?screen=diary-tracker')
  await page.locator('#diaryMomentsBtn').click()
  await expect(page.locator('#momentsScreen')).toBeVisible()

  await page.locator('[data-moment-kind="first_steps"]').click()
  await page.locator('#momentDate').fill('2026-10-20')
  await page.locator('#momentNote').fill('PLAYWRIGHT TEST: сделал три шага')
  await page.locator('#momentSaveBtn').click()

  await expect(page.locator('#momentsList')).toContainText('Первые шаги')
  await expect(page.locator('#momentsList')).toContainText('20.10.2026')
  await expect(page.locator('#momentsList')).toContainText('PLAYWRIGHT TEST: сделал три шага')
  expect(api.state.moments).toHaveLength(1)
  expect(api.state.unexpected).toEqual([])
})
