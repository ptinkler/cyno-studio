import type { Browser, Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { newThread, picker } from './studio'

// What the user sets up follows them to another browser (regression: favourites and presets lived in localStorage).

async function otherBrowser(browser: Browser): Promise<Page> {
  const page = await (await browser.newContext({ baseURL: 'http://127.0.0.1:5057' })).newPage()
  expect((await page.request.post('/api/auth/dev-login')).ok()).toBe(true)
  await newThread(page)
  return page
}

test('a starred model is starred in another browser', async ({ page, browser }) => {
  await page.request.put('/api/chat/settings/model-favourites', { data: { model_favourites: { image: [] } } })
  await newThread(page)
  await picker(page, 'Image').click()
  const row = page.locator('.picker-pop .picker-item', { hasText: 'Mock Image (slow)' })
  await row.locator('.star').click()
  await expect(page.locator('.picker-pop .picker-section').first()).toContainText('Favourites')

  const other = await otherBrowser(browser)
  await picker(other, 'Image').click()
  await expect(other.locator('.picker-pop .picker-item').first()).toContainText('Mock Image (slow)')
})

test('a preset saved from the picker is there in another browser', async ({ page, browser }) => {
  await page.request.put('/api/chat/settings/presets', { data: { presets: [] } })
  await newThread(page)
  await page.getByRole('button', { name: 'Save as preset' }).click()
  await page.getByLabel('New preset name').fill('E2E preset')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Presets' })).toContainText('E2E preset')

  const other = await otherBrowser(browser)
  await other.getByRole('button', { name: 'Presets' }).click()
  await expect(other.getByRole('option', { name: /E2E preset/ })).toBeVisible()
})

test('a folded inspector section stays folded after a reload', async ({ page }) => {
  await newThread(page)
  const head = page.locator('.ihead', { hasText: 'Characters' })
  await head.click()
  await expect(head).toHaveAttribute('aria-expanded', 'false')
  await page.reload()
  await expect(page.locator('.ihead', { hasText: 'Characters' })).toHaveAttribute('aria-expanded', 'false')
})
