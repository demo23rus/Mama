const { defineConfig, devices } = require('@playwright/test')

// Synthetic local-only Mini App test: browser and API fixtures on 127.0.0.1.
// Does not contact Telegram/MAX APIs, Mama production, users or payment services.
module.exports = defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.cjs',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    serviceWorkers: 'block',
  },
  projects: [
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'], browserName: 'chromium' } },
  ],
  webServer: {
    command: 'python3 -m http.server 4173 --bind 127.0.0.1 --directory .',
    cwd: __dirname,
    url: 'http://127.0.0.1:4173/index.html',
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
