'use strict'

// Isolated in-memory server used ONLY by localhost Playwright tests.
// No calls to Telegram, MAX, production Mama, user data, or payment APIs.
const { expect } = require('@playwright/test')

const ORIGIN = 'http://127.0.0.1:4173'
const SDK_SCRIPTS = new Set([
  'https://telegram.org/js/telegram-web-app.js',
  'https://st.max.ru/js/max-web-app.js',
])

async function useLocalMiniApp(page, opts = {}) {
  const state = {
    diary: [],
    history: [],
    growth: [],
    timezone: 'Europe/Moscow',
    timezoneConfigured: false,
    notifications: { vaccine_3d: true, vaccine_today: false, growth_monthly: false, weekly_summary: false },
    unexpected: [],
    calls: [],
  }

  if (opts.platform === 'telegram' || opts.platform === 'max') {
    await page.addInitScript((platform) => {
      const bridge = { ready: 0, expand: 0, show: 0, hide: 0, backCallback: null }
      window.__mamaMockBridge = bridge
      const sdk = {
        initData: 'SYNTHETIC_TEST_INIT_DATA_NOT_SIGNED',
        ready() { bridge.ready += 1 },
        expand() { bridge.expand += 1 },
        BackButton: {
          show() { bridge.show += 1 },
          hide() { bridge.hide += 1 },
          onClick(callback) { bridge.backCallback = callback },
        },
        openLink() {},
      }
      if (platform === 'telegram') window.Telegram = { WebApp: sdk }
      else window.WebApp = sdk
    }, opts.platform)
  }

  await page.route('**/*', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const method = req.method()

    // The two SDK scripts are not downloaded in the test.
    if (method === 'GET' && SDK_SCRIPTS.has(url.href)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: '/* local test-only empty SDK */',
      })
      return
    }
    if (url.origin !== ORIGIN) {
      state.unexpected.push('EXTERNAL ' + method + ' ' + url.origin)
      await route.abort('blockedbyclient')
      return
    }
    if (!url.pathname.startsWith('/api/miniapp/')) {
      await route.continue()
      return
    }

    const path = url.pathname.slice('/api/miniapp'.length)
    const key = method + ' ' + path
    const call = { method, path, headers: req.headers() }
    state.calls.push(call)
    const reply = (body, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      headers: { 'Cache-Control': 'no-store' },
      body: JSON.stringify(body),
    })

    // Negative 401/500 scenarios are a controlled test response.
    if (opts.httpErrors && Object.hasOwn(opts.httpErrors, key)) {
      await reply({ detail: 'Synthetic test error' }, opts.httpErrors[key])
      return
    }
    if (key === 'GET /home') {
      await reply({ name: 'Автотест' })
    } else if (key === 'GET /profile') {
      await reply({
        registered: true,
        name: 'Автотест',
        mode: 'mother',
        child_months: 9,
        timezone: state.timezone,
        timezone_configured: state.timezoneConfigured,
      })
    } else if (key === 'POST /profile/timezone') {
      const body = req.postDataJSON()
      call.body = body
      if (!['Europe/Moscow','Asia/Krasnoyarsk','Asia/Yekaterinburg'].includes(body.timezone)) {
        await reply({ detail: 'invalid_timezone' }, 400)
        return
      }
      state.timezone = body.timezone
      state.timezoneConfigured = true
      await reply({ ok: true, timezone: state.timezone })
    } else if (key === 'GET /notifications') {
      await reply({ settings: state.notifications, timezone: state.timezone, timezone_configured: state.timezoneConfigured })
    } else if (key === 'POST /notifications') {
      const body = req.postDataJSON()
      call.body = body
      for (const key of ['vaccine_3d','vaccine_today','growth_monthly','weekly_summary']) {
        if (typeof body[key] !== 'boolean') {
          await reply({ detail: 'invalid_notification_settings' }, 400)
          return
        }
      }
      state.notifications = { ...body }
      await reply({ ok: true, settings: state.notifications })
    } else if (key === 'GET /today') {
      await reply({ registered: true, mode: 'mother', child_age_label: '9 мес.', sleep_count_24h: 0 })
    } else if (key === 'GET /week') {
      await reply({
        registered: true, mode: 'mother', child_age_label: '9 мес.',
        period_start: '15.10.2026', period_end: '21.10.2026',
        activity_days: 4, sleep_count: 7, feeding_count: 6, symptoms_count: 1,
        diary_count: 2, new_foods_count: 2, last_food: 'Брокколи',
        last_growth: { height: 72, weight: 9.1 },
        last_diary: { entry: 'PLAYWRIGHT TEST: хорошая неделя' },
        nearest_vaccine: { vaccine: 'АКДС', scheduled_date: '25.10.2026' },
      })
    } else if (key === 'GET /week/advice') {
      await reply({ ok: true, answer: 'PLAYWRIGHT TEST: недельный вывод' })
    } else if (key === 'GET /history/recent') {
      await reply({ items: state.history })
    } else if (key === 'GET /diary/list') {
      await reply({ items: state.diary })
    } else if (key === 'POST /diary/add') {
      const body = req.postDataJSON()
      if (typeof body.text !== 'string' || !body.text.startsWith('PLAYWRIGHT TEST:')) {
        state.unexpected.push('NON_SYNTHETIC_DIARY_WRITE')
        await reply({ detail: 'Synthetic text only' }, 400)
        return
      }
      state.diary.unshift({ text: body.text, created_at: new Date().toISOString() })
      state.history.unshift({ type: 'diary', label: 'Дневник', detail: body.text, created_at: new Date().toISOString() })
      call.body = body
      await reply({ ok: true })
    } else if (key === 'POST /sleep/log') {
      const body = req.postDataJSON()
      call.body = body
      if (body.action !== 'start' && body.action !== 'end') {
        state.unexpected.push('INVALID_SLEEP_ACTION')
        await reply({ detail: 'Bad action' }, 400)
        return
      }
      state.history.unshift({
        type: 'sleep',
        label: 'Сон',
        detail: body.action === 'start' ? 'уснул' : 'проснулся',
        created_at: new Date().toISOString(),
      })
      await reply({ ok: true })
    } else if (key === 'POST /feeding/log') {
      const body = req.postDataJSON()
      call.body = body
      if (!['left', 'right', 'bottle'].includes(body.side) || !Number.isInteger(body.duration) || body.duration <= 0) {
        state.unexpected.push('INVALID_FEEDING_DATA')
        await reply({ detail: 'Bad feeding payload' }, 400)
        return
      }
      state.history.unshift({
        type: 'feeding',
        label: 'Питание',
        detail: body.side + ': ' + body.duration + ' мин',
        created_at: new Date().toISOString(),
      })
      await reply({ ok: true })
    } else if (key === 'POST /symptoms/log') {
      const body = req.postDataJSON()
      call.body = body
      if (!String(body.symptom || '').startsWith('PLAYWRIGHT TEST:')) {
        state.unexpected.push('NON_SYNTHETIC_SYMPTOM_WRITE')
        await reply({ detail: 'Synthetic text only' }, 400)
        return
      }
      state.history.unshift({
        type: 'symptoms',
        label: 'Самочувствие',
        detail: body.symptom,
        created_at: new Date().toISOString(),
      })
      await reply({ ok: true })
    } else if (key === 'GET /growth/list') {
      await reply({ items: state.growth })
    } else if (key === 'POST /growth/log') {
      const body = req.postDataJSON()
      call.body = body
      if (typeof body.height !== 'number' || typeof body.weight !== 'number') {
        state.unexpected.push('INVALID_GROWTH_DATA')
        await reply({ detail: 'Numeric values required' }, 400)
        return
      }
      state.growth.unshift({ height: body.height, weight: body.weight, created_at: new Date().toISOString() })
      await reply({ ok: true })
    } else if (key === 'GET /vaccines/list') {
      await reply({ items: [] })
    } else {
      state.unexpected.push('UNMOCKED ' + key)
      await reply({ detail: 'Not part of the isolated test contract' }, 501)
    }
  })

  return {
    state,
    assertSafe() {
      expect(state.unexpected).toEqual([])
      // Only explicit synthetic tracker writes are permitted in tests.
      const allowed = new Set(['/diary/add', '/sleep/log', '/feeding/log', '/symptoms/log', '/growth/log', '/profile/timezone', '/notifications'])
      expect(state.calls.filter((call) => call.method !== 'GET' && !allowed.has(call.path))).toEqual([])
    },
  }
}

module.exports = { useLocalMiniApp }
