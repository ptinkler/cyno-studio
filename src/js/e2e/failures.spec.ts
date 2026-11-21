import { expect, test } from './fixtures'
import { newThread, pickModel, replies, send, setMode } from './studio'

// Each provider failure we have met reaches the user as a clear message, not a hang or a blank card.

const imageFailures = [
  { model: 'Venice: Mock Image (drops)', message: /connection to Venice dropped after \d+s/ },
  { model: 'Venice: Mock Image (filtered)', message: /Blocked by Venice's content filter/ },
  { model: 'Venice: Mock Image (rejected)', message: /Mock: this prompt is rejected/ },
]

for (const { model, message } of imageFailures) {
  test(`image: ${model}`, async ({ page }) => {
    await newThread(page)
    await pickModel(page, 'Image', model)
    await setMode(page, 'Image')
    await send(page, 'a red bicycle')
    await expect(replies(page).last()).toContainText(message)
  })
}

test('a chat stream cut halfway says so', async ({ page }) => {
  await newThread(page)
  await pickModel(page, 'Chat', 'Venice: Mock Chat (drops)')
  await setMode(page, 'Chat')
  await send(page, 'tell me a story')
  await expect(replies(page).last()).toContainText(/connection to Venice dropped/)
})
