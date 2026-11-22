import type { Page } from '@playwright/test'
import { expect, test } from '../fixtures'
import { newThread, pickModel, replies, send, setMode } from '../studio'

// Screenshot comparisons of the Studio's main screens, in both themes. They catch what the behaviour tests cannot:
// a layout that moved, a colour that went, text that no longer fits. Baselines live in __screenshots__ and come from
// the Docker browser (`make e2e-visual`); after a change that is meant, `make e2e-visual-update` and look at the images.

const THEMES = ['light', 'dark'] as const
const SHOT = { stylePath: 'e2e/visual/visual.css' }

async function theme(page: Page, choice: (typeof THEMES)[number]): Promise<void> {
  await page.addInitScript(value => {
    localStorage.setItem('studio.theme', value)
  }, choice)
}

/** Fonts in, images decoded and the inspector settled: what a still picture needs. */
async function settled(page: Page): Promise<void> {
  await page.evaluate(() => document.fonts.ready)
  await expect
    .poll(() => page.evaluate(() => [...document.images].every(img => img.complete && img.naturalWidth > 0)))
    .toBe(true)
}

async function chatReply(page: Page): Promise<void> {
  await newThread(page)
  await pickModel(page, 'Chat', 'Venice: Mock Chat')
  await setMode(page, 'Chat')
  await send(page, 'Describe a lighthouse at dusk.')
  await expect(replies(page).last()).toContainText('You said: Describe a lighthouse at dusk.')
  await expect(page.locator('.compose .sendbtn')).toHaveText('Send')
}

async function imageReply(page: Page, prompt: string): Promise<void> {
  await newThread(page)
  await pickModel(page, 'Image', 'Venice: Mock Image')
  await setMode(page, 'Image')
  await send(page, prompt)
  await expect(replies(page).last().locator('.media-item.image img')).toBeVisible()
  await expect(page.locator('.compose .sendbtn')).toHaveText('Send')
}

// Nothing about an account or a key may reach a committed picture, even the throwaway e2e ones: they are covered
const PRIVATE = ['.who', '.krow', '.kset']

async function shoot(page: Page, name: string): Promise<void> {
  await settled(page)
  const mask = PRIVATE.map(selector => page.locator(selector))
  await expect(page).toHaveScreenshot(`${name}.png`, { ...SHOT, mask, maskColor: '#888888' })
}

for (const choice of THEMES) {
  test.describe(choice, () => {
    test.beforeEach(async ({ page }) => {
      await theme(page, choice)
    })

    test('home, empty', async ({ page }) => {
      await newThread(page)
      await shoot(page, `home-${choice}`)
    })

    test('a chat thread', async ({ page }) => {
      await chatReply(page)
      await shoot(page, `chat-${choice}`)
    })

    test('an image reply', async ({ page }) => {
      await imageReply(page, 'a red barn')
      await shoot(page, `image-reply-${choice}`)
    })

    test('the model picker open', async ({ page }) => {
      await newThread(page)
      await page.locator('.side .picker-btn', { hasText: 'Image' }).click()
      await expect(page.locator('.picker-pop')).toBeVisible()
      await shoot(page, `picker-${choice}`)
    })

    test('a gallery thread with a picture', async ({ page }) => {
      await page.goto('/?new=gallery')
      await pickModel(page, 'Image', 'Venice: Mock Image')
      await send(page, 'a gallery picture')
      await expect(page.locator('.gens .cell').first()).toBeVisible()
      await shoot(page, `gallery-${choice}`)
    })

    test('the media library', async ({ page }) => {
      await imageReply(page, 'a quiet harbour')
      await page.goto('/media')
      await expect(page.locator('.media-grid .tile')).toHaveCount(1)
      await shoot(page, `media-${choice}`)
    })

    test('settings', async ({ page }) => {
      await page.goto('/settings')
      await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
      await shoot(page, `settings-${choice}`)
    })

    test('tools and library', async ({ page }) => {
      await page.goto('/tools')
      await expect(page.getByRole('heading', { level: 1, name: 'Tools & library' })).toBeVisible()
      await shoot(page, `tools-${choice}`)
    })

    test('characters, instructions and presets pages', async ({ page }) => {
      for (const [path, heading] of [
        ['/characters', 'Characters'],
        ['/instructions', 'Instructions'],
        ['/presets', 'Presets'],
      ] as const) {
        await page.goto(path)
        await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
        await shoot(page, `${heading.toLowerCase()}-${choice}`)
      }
    })

    test('the delete confirmation', async ({ page }) => {
      await chatReply(page)
      const row = page.locator('.side .nrow', { hasText: 'Describe a lighthouse' })
      await row.hover()
      await row.getByRole('button', { name: 'Delete chat' }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await shoot(page, `delete-dialog-${choice}`)
    })
  })
}

test.describe('a small laptop', () => {
  test.use({ viewport: { width: 1024, height: 700 } })

  test('home', async ({ page }) => {
    await newThread(page)
    await shoot(page, 'small-home')
  })

  test('a chat thread', async ({ page }) => {
    await chatReply(page)
    await shoot(page, 'small-chat')
  })
})
