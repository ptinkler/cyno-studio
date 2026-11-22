import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// Every page of the Studio opens, from a deep link and from a reload, without a script error or a failed request.

const PAGES = [
  ['/settings', 'Settings'],
  ['/tools', 'Tools & library'],
  ['/media', 'Media library'],
  ['/usage', 'Credit usage'],
  ['/characters', 'Characters'],
  ['/instructions', 'Instructions'],
  ['/presets', 'Presets'],
  ['/requests', 'Request log'],
] as const

/** Collect what a user would never see but a developer must: script errors and failed API calls. */
function watchForTrouble(page: Page): string[] {
  const trouble: string[] = []
  page.on('pageerror', error => trouble.push(`script error: ${error.message}`))
  // A failed request also logs "Failed to load resource": the response check below names it, so skip that echo
  page.on('console', message => {
    if (message.type() === 'error' && !message.text().startsWith('Failed to load resource'))
      trouble.push(`console: ${message.text()}`)
  })
  page.on('response', response => {
    const { pathname } = new URL(response.url())
    // Pollo and OpenRouter have no key in these tests, so their balances say so with a 503
    if (pathname.endsWith('-balance') && response.status() === 503) return
    if (pathname.startsWith('/api/') && response.status() >= 400)
      trouble.push(`${String(response.status())} ${response.request().method()} ${pathname}`)
  })
  return trouble
}

for (const [path, heading] of PAGES) {
  test(`${path} opens from a link and after a reload`, async ({ page }) => {
    const trouble = watchForTrouble(page)
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    expect(trouble).toEqual([])
  })
}

test('the sidebar links reach Media, Tools and Settings, and Back returns to the chat', async ({ page }) => {
  await page.goto('/')
  for (const [label, heading] of [
    ['Media', 'Media library'],
    ['Tools & library', 'Tools & library'],
    ['Settings', 'Settings'],
  ] as const) {
    await page.locator('.side').getByText(label, { exact: true }).click()
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
  }
  await page.getByRole('button', { name: 'Back' }).click()
  await expect(page.locator('.compose .ed')).toBeVisible()
})

test('an unknown address lands on the Studio home', async ({ page }) => {
  await page.goto('/no/such/place/at/all')
  await expect(page).toHaveURL(/\/$/)
  await expect(page.locator('.compose .ed')).toBeVisible()
})
