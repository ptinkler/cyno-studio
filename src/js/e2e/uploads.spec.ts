import { expect, test } from './fixtures'
import { dropImages, newThread, pickModel, replies, send, setMode } from './studio'

test('two quick drops on a new thread all go with the message', async ({ page, mock }) => {
  // Regression: each drop created its own thread, so the send failed with "Attachment not found"
  await newThread(page)
  await pickModel(page, 'Image', 'Venice: Mock Image')
  await setMode(page, 'Image')
  await dropImages(page, [['red'], ['blue']])
  await expect(page.locator('.compose .note')).toHaveText('')
  await send(page, 'blend these')
  await expect(replies(page).last().locator('.media-item.image img')).toBeVisible()
  await expect(page.getByText('Attachment not found')).toHaveCount(0)
  const [edit] = await mock.requests('/image/multi-edit')
  expect((edit?.body as { images: unknown[] }).images).toHaveLength(2)
})
