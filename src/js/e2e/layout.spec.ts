import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { newThread, pickModel, replies, send, setMode } from './studio'

// The Studio fits the window: the side panels give way on a narrow one and nothing runs off the page.

const noSidewaysScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)

test.describe('a phone-sized window', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('the panels start as rails and the composer has room', async ({ page }) => {
    await newThread(page)
    await expect(page.locator('.side.collapsed')).toHaveCount(2)
    const box = await page.locator('.compose').boundingBox()
    expect(box?.width).toBeGreaterThan(250)
    expect(await noSidewaysScroll(page)).toBe(true)
  })

  test('a chat works, with the inspector opened over it to pick the model and closed again', async ({ page }) => {
    await newThread(page)
    await page.locator('.side.right .rail').click()
    await pickModel(page, 'Chat', 'Venice: Mock Chat')
    await page.getByRole('button', { name: 'Collapse inspector' }).click()
    await expect(page.locator('.side.right')).toHaveClass(/collapsed/)
    await setMode(page, 'Chat')
    await send(page, 'hello from a small screen')
    await expect(replies(page).last()).toContainText('You said: hello from a small screen')
    const box = await replies(page).last().boundingBox()
    expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(390)
    expect(await noSidewaysScroll(page)).toBe(true)
  })

  test('the sidebar opens over the chat and closes again', async ({ page }) => {
    await newThread(page)
    await page.locator('.side:not(.right) .rail').click()
    const left = page.locator('.side:not(.right)')
    await expect(left).not.toHaveClass(/collapsed/)
    expect((await left.locator('.panel').boundingBox())?.width).toBeGreaterThan(250)
    expect(await noSidewaysScroll(page)).toBe(true)
    await left.getByRole('button', { name: 'Collapse sidebar' }).click()
    await expect(left).toHaveClass(/collapsed/)
  })

  test('the inspector opens over the chat from the right edge', async ({ page }) => {
    await newThread(page)
    await page.locator('.side.right .rail').click()
    const panel = page.locator('.side.right .panel')
    await expect(panel).toBeVisible()
    const box = await panel.boundingBox()
    expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(390)
    expect(await noSidewaysScroll(page)).toBe(true)
  })
})

test('the thread filters fit the sidebar on a small laptop', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 700 })
  await newThread(page)
  const side = await page.locator('.side:not(.right)').boundingBox()
  const filter = page.locator('.side:not(.right) .nfilter')
  const sideRight = (side?.x ?? 0) + (side?.width ?? 0)
  for (const pill of await filter.locator('.pillbtn').all()) {
    const box = await pill.boundingBox()
    expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(sideRight)
  }
})

test('a window narrowed after loading folds the panels away', async ({ page }) => {
  await newThread(page)
  await expect(page.locator('.side.collapsed')).toHaveCount(0)
  await page.setViewportSize({ width: 600, height: 800 })
  await expect(page.locator('.side.collapsed')).toHaveCount(2)
  await page.setViewportSize({ width: 1200, height: 800 })
  await page.locator('.side:not(.right) .rail').click() // the user's own choice is not undone by widening again
  await expect(page.locator('.side:not(.right)')).not.toHaveClass(/collapsed/)
})
