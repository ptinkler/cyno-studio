import { expect, test } from './fixtures'
import { newThread } from './studio'

test('the Venice pill counts plan credits as dollars', async ({ page, mock }) => {
  await mock.settings({ venice_usd: 0.76, venice_credits: 4.76 })
  await newThread(page)
  await expect(page.locator('.bseg.venice')).toContainText('$5.52')
})
