import { expect, test } from './fixtures'
import { newThread, pickModel, replies, send, setMode } from './studio'

test('a video renders after a few status checks', async ({ page, mock }) => {
  await newThread(page)
  await pickModel(page, 'Video', 'Venice: Mock Video')
  await setMode(page, 'Video')
  await send(page, 'waves on a beach')
  await expect(replies(page).last().locator('video')).toBeVisible({ timeout: 30_000 })
  expect((await mock.requests('/video/queue')).length).toBe(1)
  expect((await mock.requests('/video/retrieve')).length).toBeGreaterThan(2)
})

test('a failed render shows the provider error', async ({ page }) => {
  await newThread(page)
  await pickModel(page, 'Video', 'Venice: Mock Broken Video')
  await setMode(page, 'Video')
  await send(page, 'waves on a beach')
  await expect(replies(page).last()).toContainText('Mock: render failed', { timeout: 30_000 })
})
