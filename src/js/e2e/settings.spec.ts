import { expect, test } from './fixtures'

// Settings that belong to this browser (theme, text size) and the account actions.

const html = 'html'

test('the theme choice is applied at once and remembered after a reload', async ({ page }) => {
  await page.goto('/settings')
  const theme = page.getByRole('group', { name: 'Theme' })
  await theme.getByRole('button', { name: 'Dark' }).click()
  await expect(page.locator(html)).toHaveAttribute('data-theme', 'dark')
  await page.reload()
  await expect(page.locator(html)).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('group', { name: 'Theme' }).getByRole('button', { name: 'Light' }).click()
  await expect(page.locator(html)).toHaveAttribute('data-theme', 'light')
  await page.reload()
  await expect(page.locator(html)).toHaveAttribute('data-theme', 'light')
})

test('the text size changes the page and is remembered after a reload', async ({ page }) => {
  await page.goto('/settings')
  const size = () => page.locator(html).evaluate(el => getComputedStyle(el).fontSize)
  const before = await size()
  await page.getByRole('group', { name: 'Text size' }).getByRole('button', { name: 'Large' }).click()
  await expect.poll(size).not.toBe(before)
  const large = await size()
  await page.reload()
  expect(await size()).toBe(large)
  await page.getByRole('group', { name: 'Text size' }).getByRole('button', { name: 'Comfortable' }).click()
  await expect.poll(size).toBe(before)
})

test('a saved provider key shows as set after a reload, and clearing it removes it', async ({ page }) => {
  await page.goto('/settings')
  const keys = page.locator('.scard', { hasText: 'Provider keys' })
  const clears = keys.getByRole('button', { name: 'Clear' })
  await expect(clears).toHaveCount(1) // Venice, set by the fixture
  await keys.getByPlaceholder('Paste key').nth(1).fill('sk-or-mock-key')
  await keys.getByRole('button', { name: 'Save keys' }).click()
  await expect(keys.getByText('Saved')).toBeVisible()
  await page.reload()
  await expect(clears).toHaveCount(2)

  await clears.last().click()
  await keys.getByRole('button', { name: 'Save keys' }).click()
  await expect(keys.getByText('Saved')).toBeVisible()
  await page.reload()
  await expect(clears).toHaveCount(1)
})

test('signing out asks to sign in again', async ({ page }) => {
  await page.goto('/settings')
  await page.locator('.scard', { hasText: 'Account' }).getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Sign in' })).toBeVisible()
})
