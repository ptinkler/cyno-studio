import { test as base, expect } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

// What every end-to-end test gets: a signed-in page with a Venice key (pointed at the mock), and the mock's
// control API, reset before the test.

export const MOCK = 'http://127.0.0.1:5056'

/** One request the app sent to a mock provider. */
export interface MockRequest {
  provider: string
  method: string
  path: string
  body: unknown
  params: Record<string, string>
}

export class Mock {
  constructor(private readonly http: APIRequestContext) {}

  async reset(): Promise<void> {
    await this.http.post(`${MOCK}/__mock/reset`)
  }

  /** Turn behaviour knobs (see tests/mock_providers/state.py `Settings`). */
  async settings(changes: Record<string, number>): Promise<void> {
    expect((await this.http.post(`${MOCK}/__mock/settings`, { data: changes })).ok()).toBe(true)
  }

  /** What the app sent, oldest first; only requests whose path ends with `path` when given. */
  async requests(path?: string): Promise<MockRequest[]> {
    const reply = await this.http.get(`${MOCK}/__mock/requests`, { params: path ? { path } : {} })
    return ((await reply.json()) as { requests: MockRequest[] }).requests
  }
}

/** The database lives as long as the app: each test starts with no threads, spaces, characters, snippets, presets or favourites. */
async function clearUserContent(page: Page): Promise<void> {
  const list = async <T>(path: string): Promise<T> => (await (await page.request.get(path)).json()) as T
  const remove = async (path: string, ids: { id: string | number }[]): Promise<void> => {
    for (const { id } of ids) await page.request.delete(`${path}/${String(id)}`)
  }
  await remove(
    '/api/chat/conversations',
    (await list<{ conversations: { id: string }[] }>('/api/chat/conversations')).conversations,
  )
  await remove('/api/chat/spaces', (await list<{ spaces: { id: string }[] }>('/api/chat/spaces')).spaces)
  await remove(
    '/api/characters',
    (await list<{ characters: { id: string }[] }>('/api/characters?include_adhoc=true')).characters,
  )
  const instructions = await list<{ instructions: { id: string }[]; groups: { id: string }[] }>(
    '/api/chat/instructions',
  )
  await remove('/api/chat/instructions', instructions.instructions)
  await remove('/api/chat/instruction-groups', instructions.groups)
  await page.request.put('/api/chat/settings/presets', { data: { presets: [] } })
  await page.request.put('/api/chat/settings/model-favourites', { data: { model_favourites: {} } })
}

export const test = base.extend<{ mock: Mock }>({
  // Automatic: every test starts from a reset mock, whether or not it reads the mock itself
  mock: [
    async ({ playwright }, use) => {
      const http = await playwright.request.newContext()
      const mock = new Mock(http)
      await mock.reset()
      await use(mock)
      await http.dispose()
    },
    { auto: true },
  ],
  page: async ({ page }, use) => {
    expect((await page.request.post('/api/auth/dev-login')).ok()).toBe(true)
    expect((await page.request.put('/api/keys', { data: { keys: { venice: 'mock-key' } } })).ok()).toBe(true)
    await clearUserContent(page)
    await use(page)
  },
})

export { expect }
