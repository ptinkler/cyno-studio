import { expect, test } from './fixtures'
import { dropImages, newThread, pickModel, replies, send, setMode } from './studio'

test('Images sent at 0 keeps pinned images out of a reference video; attachments still go', async ({ page, mock }) => {
  // Regression: reference-to-video models got every pinned image, whatever the slider said
  await newThread(page)
  await pickModel(page, 'Image', 'Venice: Mock Image')
  await pickModel(page, 'Video', 'Venice: Mock Ref Video (refs→video)')
  await setMode(page, 'Image')
  await send(page, 'a castle')
  const card = replies(page).last().locator('.media-item.image')
  await expect(card.locator('img')).toBeVisible()
  await card.hover()
  await card.locator('.pin-btn').click()
  await expect(card.locator('.pin-btn')).toHaveAttribute('aria-pressed', 'true')

  await setMode(page, 'Video')
  await page.locator('.isection', { hasText: 'Images sent' }).locator('input[type=range]').last().fill('0')
  await expect(page.locator('.isection', { hasText: 'Images sent' })).toContainText('None')
  await dropImages(page, [['green']])
  await expect(page.locator('.compose .note')).toHaveText('')
  await send(page, 'the castle at night')
  await expect.poll(async () => (await mock.requests('/video/queue')).length).toBe(1)
  const [queued] = await mock.requests('/video/queue')
  expect((queued?.body as { reference_image_urls?: unknown[] }).reference_image_urls).toHaveLength(1)
})
