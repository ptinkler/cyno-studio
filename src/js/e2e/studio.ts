import type { Locator, Page } from '@playwright/test'
import { expect } from './fixtures'

// Driving the Studio like a user: pick models, switch mode, write and send.

type PickerKind = 'Chat' | 'Image' | 'Video' | 'Audio'
type Mode = 'Auto' | 'Chat' | 'Image' | 'Video' | 'Audio'

export const picker = (page: Page, kind: PickerKind): Locator =>
  page.locator('.side .picker-btn', { has: page.locator('.picker-label', { hasText: new RegExp(`^${kind}`) }) })

/** Choose a model by its display name (e.g. "Venice: Mock Image") in one of the inspector's pickers. */
export async function pickModel(page: Page, kind: PickerKind, name: string): Promise<void> {
  await picker(page, kind).click()
  const pop = page.locator('.picker-pop')
  await pop.locator('.picker-search').fill(name.replace(/^Venice: /, ''))
  await pop.locator('.picker-item', { has: page.getByText(name, { exact: true }) }).click()
  await expect(picker(page, kind)).toContainText(name)
}

export async function setMode(page: Page, mode: Mode): Promise<void> {
  await page.locator('.compose .pillbtn', { hasText: new RegExp(`^${mode}$`) }).click()
}

/** Open a fresh, empty thread. */
export async function newThread(page: Page): Promise<void> {
  await page.goto('/')
  await expect(page.locator('.compose .ed')).toBeVisible()
}

export async function send(page: Page, prompt: string): Promise<void> {
  await page.locator('.compose .ed').fill(prompt)
  await page.locator('.compose .sendbtn').click()
}

/** The assistant's replies in the open thread. */
export const replies = (page: Page): Locator => page.locator('.msg-assistant')

/**
 * Drop images on the composer the way a user drags them in from the desktop: each inner list is one drop, of one
 * different picture per colour. The drops land back to back, in the same moment, like quick successive drags.
 */
export async function dropImages(page: Page, drops: readonly (readonly string[])[]): Promise<void> {
  await page.locator('.compose').evaluate(async (target, groups: readonly (readonly string[])[]) => {
    async function picture(color: string): Promise<File> {
      const canvas = new OffscreenCanvas(16, 16)
      const ctx = canvas.getContext('2d')
      if (ctx) {
        ctx.fillStyle = color
        ctx.fillRect(0, 0, 16, 16)
      }
      return new File([await canvas.convertToBlob({ type: 'image/png' })], `${color}.png`, { type: 'image/png' })
    }
    const transfers = await Promise.all(
      groups.map(async colors => {
        const transfer = new DataTransfer()
        for (const file of await Promise.all(colors.map(picture))) transfer.items.add(file)
        return transfer
      }),
    )
    for (const dataTransfer of transfers) target.dispatchEvent(new DragEvent('drop', { dataTransfer, bubbles: true }))
  }, drops)
}
