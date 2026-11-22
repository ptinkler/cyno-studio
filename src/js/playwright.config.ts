import { defineConfig, devices } from '@playwright/test'

// End-to-end tests: the real app (built frontend + Python API on a fresh data folder) against the mock providers
// (tests/mock_providers), driven in headless Chromium. `npm run e2e` (build first: `npm run build`).
const MOCK = 'http://127.0.0.1:5056'
const APP = 'http://127.0.0.1:5057'
const repoRoot = '../..'
const python = (module: string, args = ''): string =>
  `uv run --project ${repoRoot} env PYTHONPATH=src/py:. python -m ${module} ${args}`.trim()

export default defineConfig({
  testDir: 'e2e',
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
  webServer: [
    {
      command: python('tests.mock_providers', '--port 5056'),
      cwd: repoRoot,
      url: `${MOCK}/__mock/settings`,
      reuseExistingServer: !process.env['CI'], // locally, servers you started yourself are used as they are
    },
    {
      command: python('scripts.e2e_app', `--port 5057 --mock ${MOCK}`),
      cwd: repoRoot,
      url: `${APP}/api/auth/status`,
      reuseExistingServer: !process.env['CI'],
      timeout: 60_000,
    },
  ],
})
