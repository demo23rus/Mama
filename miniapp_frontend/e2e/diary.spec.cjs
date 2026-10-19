const { test, expect } = require('@playwright/test')

// Browser/API stays on loopback. All data is synthetic and held only in memory.
test('Дневник малыша: сохранить запись и открыть после перезагрузки', async ({ page }) => {
  const origin = 'http://127.0.0.1:4173'
  const entries = []
  const unexpected = []
  let saves = 0
  let reads = 0

  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const method = request.method()

    // Never download messenger SDKs or send any traffic to external hosts.
    if (method === 'GET' && (
      url.href === 'https://telegram.org/js/telegram-web-app.js' ||
      url.href === 'https://st.max.ru/js/max-web-app.js'
    )) {
      await route.fulfill({ status: 200, contentType: 'application/javascript', body: '/* inert SDK */' })
      return
    }
    if (url.origin !== origin) {
      unexpected.push(`EXTERNAL ${method} ${url.origin}`)
      await route.abort('blockedbyclient')
      return
    }

    if (!url.pathname.startsWith('/api/miniapp/')) {
      await route.continue()
      return
    }

    const path = url.pathname.slice('/api/miniapp'.length)
    const reply = async (payload, status = 200) => {
      await route.fulfill({
        status,
        contentType: 'application/json',
        headers: { 'Cache-Control': 'no-store' },
        body: JSON.stringify(payload),
      })
    }

    if (method === 'GET' && path === '/home') {
      await reply({ name: 'Тест' })
    } else if (method === 'GET' && path === '/profile') {
      await reply({ mode: 'parent' })
    } else if (method === 'GET' && path === '/today') {
      await reply({ registered: false, mode: '' })
    } else if (method === 'GET' && path === '/diary/list') {
      reads += 1
      await reply({ items: entries })
    } else if (method === 'POST' && path === '/diary/add') {
      const body = request.postDataJSON()
      if (!body || typeof body.text !== 'string' || !body.text.startsWith('PLAYWRIGHT TEST:')) {
        unexpected.push('UNEXPECTED_DIARY_CONTENT')
        await reply({ detail: 'Synthetic text required' }, 400)
        return
      }
      entries.push({ text: body.text, created_at: new Date().toISOString() })
      saves += 1
      await reply({ ok: true })
    } else {
      unexpected.push(`UNMOCKED ${method} ${path}`)
      await reply({ detail: 'Isolated test; unexpected request' }, 501)
    }
  })

  const note = 'PLAYWRIGHT TEST: первый зуб малыша. Данные вымышлены.'
  await page.goto('/')
  await expect(page.locator('#homeScreen')).toBeVisible()

  await page.locator('.bottomnav__item[data-route="trackers"]').click()
  await expect(page.locator('#trackersScreen')).toBeVisible()
  await page.locator('#trackersScreen [data-action-card="baby-diary"]').click()
  await expect(page.locator('#diaryTrackerScreen')).toBeVisible()
  await expect(page).toHaveURL(/screen=diary-tracker/)

  await page.locator('#diaryInput').fill(note)
  await page.locator('#diarySaveBtn').click()
  await expect(page.locator('#diarySaveBody')).toContainText('Запись сохранена в дневник')
  await expect(page.locator('#diaryEntries')).toContainText(note)
  expect(saves).toBe(1)

  await page.reload()
  await expect(page.locator('#diaryTrackerScreen')).toBeVisible()
  await expect(page.locator('#diaryEntries')).toContainText(note)
  expect(reads).toBeGreaterThanOrEqual(2)
  expect(entries).toHaveLength(1)
  expect(unexpected).toEqual([])
})
