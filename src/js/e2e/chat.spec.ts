import { expect, test } from './fixtures'
import { newThread, pickModel, replies, send, setMode } from './studio'

test('a chat reply streams in', async ({ page, mock }) => {
  await newThread(page)
  await pickModel(page, 'Chat', 'Venice: Mock Chat')
  await setMode(page, 'Chat')
  await send(page, 'hello there')
  await expect(replies(page).last()).toContainText('You said: hello there')
  const [call] = await mock.requests('/chat/completions')
  expect(call?.body).toMatchObject({ model: 'mock-chat', stream: true })
})

test('in Auto, the chat model asks for an image and it appears in the reply', async ({ page, mock }) => {
  await newThread(page)
  await pickModel(page, 'Chat', 'Venice: Mock Artist')
  await pickModel(page, 'Image', 'Venice: Mock Image')
  await setMode(page, 'Auto')
  await send(page, 'a lighthouse at dusk')
  const reply = replies(page).last()
  await expect(reply.locator('.media-item.image img')).toBeVisible()
  await expect(reply).toContainText('Here it is.')
  const [generated] = await mock.requests('/image/generate')
  expect(generated?.body).toMatchObject({
    model: 'mock-image',
    prompt: expect.stringContaining('lighthouse'),
  })
})
