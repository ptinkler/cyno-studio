import { defineConfig, devices } from '@playwright/test'

// End-to-end tests: the real app (built frontend + Python API on a fresh data folder) against the mock providers
// (tests/mock_providers), driven in headless Chromium. `npm run e2e` (build first: `npm run build`).
const APP = 'http://127.0.0.1:5057'

export default defineConfig({
  testDir: 'e2e',
  // The mock providers and the app are started once for the run, and stopped after (see e2e/servers.ts)
  globalSetup: './e2e/servers.ts',
  // One app, one database, one mock: tests run one at a time and reset the mock between them
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 1 : 0,
  snapshotPathTemplate: '{testDir}/visual/__screenshots__/{testFileName}/{arg}{ext}',
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.002 } },
  reporter: process.env['CI'] ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: APP,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: 'visual/**',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      // Screenshot comparisons: the browser runs in Docker (scripts/visual-browser.sh) so every machine renders alike
      name: 'visual',
      testMatch: 'visual/**/*.spec.ts',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        connectOptions: { wsEndpoint: 'ws://127.0.0.1:3100/' },
      },
    },
  ],
})
