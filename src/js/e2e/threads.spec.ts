import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { newThread, pickModel, replies, send, setMode } from './studio'

// The sidebar's thread list: what a user does to find, name, pin and remove conversations.

const sidebar = (page: Page) => page.locator('.side')
const row = (page: Page, title: string) => sidebar(page).locator('.nrow', { hasText: title })

async function chat(page: Page, prompt: string): Promise<void> {
  await newThread(page)
  await pickModel(page, 'Chat', 'Venice: Mock Chat')
  await setMode(page, 'Chat')
  await send(page, prompt)
  await expect(replies(page).last()).toContainText(`You said: ${prompt}`)
}

test('a thread is listed under its first message and reopens from its link after a reload', async ({ page }) => {
  await chat(page, 'remember the lighthouse')
  await expect(row(page, 'remember the lighthouse')).toBeVisible()
  await expect(page).toHaveURL(/\/[0-9a-f]{32}/)
  await page.reload()
  await expect(replies(page).last()).toContainText('You said: remember the lighthouse')
  await expect(row(page, 'remember the lighthouse')).toHaveClass(/active/)
})

test('renaming a thread keeps the new name after a reload', async ({ page }) => {
  await chat(page, 'first topic')
  await row(page, 'first topic').hover()
  await row(page, 'first topic').getByRole('button', { name: 'Rename' }).click()
  await sidebar(page).locator('.nrename').fill('Renamed topic')
  await sidebar(page).getByRole('button', { name: 'Confirm rename' }).click()
  await expect(row(page, 'Renamed topic')).toBeVisible()
  await page.reload()
  await expect(row(page, 'Renamed topic')).toBeVisible()
  await expect(row(page, 'first topic')).toHaveCount(0)
})

test('cancelling a rename leaves the name alone', async ({ page }) => {
  await chat(page, 'keep this name')
  await row(page, 'keep this name').hover()
  await row(page, 'keep this name').getByRole('button', { name: 'Rename' }).click()
  await sidebar(page).locator('.nrename').fill('Something else')
  await sidebar(page).getByRole('button', { name: 'Cancel rename' }).click()
  await expect(row(page, 'keep this name')).toBeVisible()
})

test('deleting a thread asks first, then removes it and returns to a blank chat', async ({ page }) => {
  await chat(page, 'doomed thread')
  await row(page, 'doomed thread').hover()
  await row(page, 'doomed thread').getByRole('button', { name: 'Delete chat' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(row(page, 'doomed thread')).toBeVisible()

  await row(page, 'doomed thread').hover()
  await row(page, 'doomed thread').getByRole('button', { name: 'Delete chat' }).click()
  await page.getByRole('dialog').locator('.btn-danger').click()
  await expect(row(page, 'doomed thread')).toHaveCount(0)
  await page.reload()
  await expect(row(page, 'doomed thread')).toHaveCount(0)
})

test('pinning moves a thread to the pinned section and it stays there after a reload', async ({ page }) => {
  await chat(page, 'pin me')
  await row(page, 'pin me').hover()
  await row(page, 'pin me').getByRole('button', { name: 'Pin chat' }).click()
  await expect(sidebar(page).getByText('Pinned', { exact: true })).toBeVisible()
  await page.reload()
  await expect(sidebar(page).getByText('Pinned', { exact: true })).toBeVisible()
  await row(page, 'pin me').hover()
  await expect(row(page, 'pin me').getByRole('button', { name: 'Unpin chat' })).toBeVisible()
})

test('searching narrows the list to matching threads', async ({ page }) => {
  await chat(page, 'apples and pears')
  await chat(page, 'bananas only')
  await sidebar(page).getByPlaceholder('Search threads…').fill('banana')
  await expect(row(page, 'bananas only')).toBeVisible()
  await expect(row(page, 'apples and pears')).toHaveCount(0)
  await sidebar(page).getByPlaceholder('Search threads…').fill('')
  await expect(row(page, 'apples and pears')).toBeVisible()
})

test('New chat opens an empty composer without touching the old thread', async ({ page }) => {
  await chat(page, 'an older thread')
  await sidebar(page).locator('.newbtn', { hasText: 'New chat' }).click()
  await expect(page.locator('.compose .ed')).toBeEmpty()
  await expect(replies(page)).toHaveCount(0)
  await expect(row(page, 'an older thread')).toBeVisible()
})
