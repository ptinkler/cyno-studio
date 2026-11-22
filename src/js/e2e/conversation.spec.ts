import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { newThread, pickModel, replies, send, setMode } from './studio'

// Carrying on a conversation: several turns, editing a prompt, retrying a reply, branching.

const prompts = (page: Page) => page.locator('.msg-user .bubble')

async function startChat(page: Page): Promise<void> {
  await newThread(page)
  await pickModel(page, 'Chat', 'Venice: Mock Chat')
  await setMode(page, 'Chat')
}

async function turn(page: Page, prompt: string, count: number): Promise<void> {
  await send(page, prompt)
  await expect(replies(page)).toHaveCount(count)
  await expect(replies(page).last()).toContainText(`You said: ${prompt}`)
  await expect(page.locator('.compose .sendbtn')).toHaveText('Send')
}

test('turns stay in order, the composer empties after each, and the history survives a reload', async ({ page }) => {
  await startChat(page)
  await turn(page, 'first', 1)
  await expect(page.locator('.compose .ed')).toBeEmpty()
  await turn(page, 'second', 2)
  await turn(page, 'third', 3)
  await expect(prompts(page)).toHaveText(['first', 'second', 'third'])
  await page.reload()
  await expect(prompts(page)).toHaveText(['first', 'second', 'third'])
  await expect(replies(page)).toHaveCount(3)
})

test('the model is sent the earlier turns as context', async ({ page, mock }) => {
  await startChat(page)
  await turn(page, 'remember seven', 1)
  await turn(page, 'what was it', 2)
  const calls = await mock.requests('/chat/completions')
  const last = calls.at(-1)?.body as { messages: { role: string; content: unknown }[] }
  expect(JSON.stringify(last.messages)).toContain('remember seven')
})

test('editing a prompt sends it as a new branch and the original stays reachable', async ({ page }) => {
  await startChat(page)
  await turn(page, 'original wording', 1)
  const bubble = page.locator('.msg-user').first()
  await bubble.hover()
  await bubble.getByRole('button', { name: 'Edit prompt' }).click()
  await page.locator('.edit-box textarea').fill('better wording')
  await page.locator('.edit-box').getByRole('button', { name: 'Send' }).click()
  await expect(prompts(page)).toHaveText(['better wording'])
  await expect(replies(page).last()).toContainText('You said: better wording')
  await expect(page.locator('.branch-nav')).toBeVisible()
  await page.locator('.branch-nav button').first().click()
  await expect(prompts(page)).toHaveText(['original wording'])
})

test('retrying a reply asks the provider again and keeps one reply on screen', async ({ page, mock }) => {
  await startChat(page)
  await turn(page, 'say it again', 1)
  const reply = replies(page).last()
  await reply.hover()
  await reply.getByRole('button', { name: 'Retry reply' }).click()
  await expect.poll(async () => (await mock.requests('/chat/completions')).length).toBe(2)
  await expect(replies(page)).toHaveCount(1)
  await expect(replies(page).last()).toContainText('You said: say it again')
})

test('branching from a reply opens a new thread holding the conversation so far', async ({ page }) => {
  await startChat(page)
  await turn(page, 'before the branch', 1)
  const reply = replies(page).last()
  await reply.hover()
  await reply.getByRole('button', { name: 'Branch from here' }).click()
  await expect(page.locator('.side .nrow')).toHaveCount(2)
  await expect(prompts(page)).toHaveText(['before the branch'])
})
