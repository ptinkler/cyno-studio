import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

// The things a user keeps between chats: characters, instruction snippets, spaces and presets.

const dialog = (page: Page) => page.getByRole('dialog')

test('a character can be created, edited and deleted', async ({ page }) => {
  await page.goto('/characters')
  await page.getByRole('button', { name: 'New character' }).click()
  await dialog(page).getByLabel('Name').fill('Linh')
  await dialog(page).getByLabel('Description').fill('Tall, silver braid, green coat')
  await dialog(page).getByRole('button', { name: 'Create' }).click()
  const card = page.locator('.gcard', { hasText: 'Linh' })
  await expect(card).toContainText('Tall, silver braid')

  await page.reload()
  await page.locator('.gcard', { hasText: 'Linh' }).click()
  await dialog(page).getByLabel('Description').fill('Short copper hair')
  await dialog(page).getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.locator('.gcard', { hasText: 'Linh' })).toContainText('Short copper hair')

  await page.locator('.gcard', { hasText: 'Linh' }).click()
  await dialog(page).getByRole('button', { name: 'Delete' }).click()
  await page
    .getByRole('dialog', { name: /^Delete/ })
    .getByRole('button', { name: 'Delete' })
    .click()
  await expect(page.locator('.gcard', { hasText: 'Linh' })).toHaveCount(0)
})

test('an instruction snippet can be created, found by search and deleted', async ({ page }) => {
  await page.goto('/instructions')
  await page.getByRole('button', { name: 'Snippet' }).click()
  await dialog(page).getByLabel('Name', { exact: true }).fill('Pirate voice')
  await dialog(page).getByLabel('Instructions').fill('Answer like a pirate.')
  await dialog(page).getByRole('button', { name: 'Create' }).click()
  const card = page.locator('.gcard', { hasText: 'Pirate voice' })
  await expect(card).toContainText('Answer like a pirate.')

  await page.getByPlaceholder('Search instructions').fill('no such thing')
  await expect(card).toHaveCount(0)
  await page.getByPlaceholder('Search instructions').fill('pirate')
  await expect(card).toBeVisible()

  await card.click()
  await dialog(page).getByRole('button', { name: 'Delete' }).click()
  await page
    .getByRole('dialog', { name: /^Delete/ })
    .getByRole('button', { name: 'Delete' })
    .click()
  await expect(card).toHaveCount(0)
})

test('a space can be created and shows in the sidebar after a reload', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'New space' }).click()
  await dialog(page).getByLabel('Name').fill('Fantasy novel')
  await dialog(page)
    .getByRole('button', { name: /Create|Save/ })
    .click()
  await expect(page.locator('.side').getByText('Fantasy novel')).toBeVisible()
  await page.reload()
  await expect(page.locator('.side').getByText('Fantasy novel')).toBeVisible()
})

test('a preset made on the Presets page can be picked in a chat', async ({ page }) => {
  await page.goto('/presets')
  await page.getByRole('button', { name: 'New preset' }).click()
  await dialog(page).getByLabel('Name').fill('Page preset')
  await dialog(page)
    .getByRole('button', { name: /Create|Save/ })
    .click()
  await expect(page.locator('.gcard, .card', { hasText: 'Page preset' }).first()).toBeVisible()
  await page.goto('/')
  await page.getByRole('button', { name: 'Presets' }).click()
  await expect(page.getByRole('option', { name: /Page preset/ })).toBeVisible()
})
