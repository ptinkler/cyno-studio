import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { newThread, pickModel, send, setMode, replies } from './studio'

// Generated pictures end up where the user looks for them: the thread, the Media library and a gallery.

async function makeImage(page: Page, prompt: string): Promise<void> {
  await newThread(page)
  await pickModel(page, 'Image', 'Venice: Mock Image')
  await setMode(page, 'Image')
  await send(page, prompt)
  await expect(replies(page).last().locator('.media-item.image img')).toBeVisible()
}

test('a generated image is in the Media library, and its filters narrow it down', async ({ page }) => {
  await makeImage(page, 'a red barn')
  await page.locator('.side').getByText('Media', { exact: true }).click()
  const tiles = page.locator('.media-grid .tile')
  await expect(tiles).toHaveCount(1)
  await expect(page.locator('.mhead .gcount')).toHaveText('1 item')

  const bar = page.locator('.mbar')
  await bar.getByLabel('Type').selectOption('video')
  await expect(tiles).toHaveCount(0)
  await bar.getByLabel('Type').selectOption('all')
  await bar.getByLabel('Source').selectOption('upload')
  await expect(tiles).toHaveCount(0)
  await bar.getByLabel('Source').selectOption('generated')
  await expect(tiles).toHaveCount(1)

  // The search runs on Enter
  await bar.getByPlaceholder('Search prompts…').fill('zeppelin')
  await bar.getByPlaceholder('Search prompts…').press('Enter')
  await expect(tiles).toHaveCount(0)
  await bar.getByPlaceholder('Search prompts…').fill('barn')
  await bar.getByPlaceholder('Search prompts…').press('Enter')
  await expect(tiles).toHaveCount(1)
})

test('a tile opens the full image, and its thumbnail loads', async ({ page }) => {
  await makeImage(page, 'a quiet harbour')
  await page.goto('/media')
  const thumb = page.locator('.media-grid .tile img')
  await expect(thumb).toBeVisible()
  await expect.poll(() => thumb.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)
  await expect(page.locator('.media-grid .tile')).toHaveAttribute('href', /\/api\/chat\/media\/.+\.png$/)
})

test('a gallery thread collects what is generated in it, and keeps it after a reload', async ({ page }) => {
  await page.goto('/?new=gallery')
  await pickModel(page, 'Image', 'Venice: Mock Image')
  await expect(page.getByText('No generations in this thread yet.')).toBeVisible()
  await send(page, 'a gallery picture')
  await expect(page.locator('.gens .cell.done, .gens .cell').first()).toBeVisible()
  await page.reload()
  await expect(page.getByText('No generations in this thread yet.')).toHaveCount(0)
})
