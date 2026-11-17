import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { fetchMediaPage, importMediaToCharacter, importMediaToChat } from '../composables/mediaApi'

interface Reply {
  ok: boolean
  status: number
  json: () => Promise<unknown>
}

type FetchMock = Mock<(url: string, init: RequestInit) => Promise<Reply>>

function stubFetch(body: unknown): FetchMock {
  const fetchMock: FetchMock = vi.fn()
  fetchMock.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(body) })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastUrl(fetchMock: FetchMock): string {
  const call = fetchMock.mock.calls.at(-1)
  if (!call) throw new Error('fetch was not called')
  return call[0]
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchMediaPage', () => {
  it('leaves off filters that are null, empty or "all"', async () => {
    const fetchMock = stubFetch({ items: [], total: 0, offset: 0 })
    await fetchMediaPage({ offset: 20, limit: 10, kind: 'image', source: 'all', origin: null, q: '' })
    expect(lastUrl(fetchMock)).toBe('/api/media?offset=20&limit=10&kind=image')
  })

  it('asks for the whole library when nothing narrows it', async () => {
    const fetchMock = stubFetch({ items: [], total: 0, offset: 0 })
    await fetchMediaPage()
    expect(lastUrl(fetchMock)).toBe('/api/media?offset=0&limit=0')
  })

  it('returns the items and how many matched before paging', async () => {
    stubFetch({ items: [{ id: 'lib:a.png' }], total: 40, offset: 0 })
    expect(await fetchMediaPage({ limit: 1 })).toEqual({ items: [{ id: 'lib:a.png' }], total: 40 })
  })
})

describe('importing a library item', () => {
  it('into a chat answers with the attachment file', async () => {
    const fetchMock = stubFetch({ file: 'up_1.png' })
    expect(await importMediaToChat('lib:a.png', 'c1')).toEqual({ file: 'up_1.png' })
    const body = fetchMock.mock.calls.at(-1)?.[1].body
    expect(typeof body === 'string' ? (JSON.parse(body) as unknown) : body).toEqual({
      media_id: 'lib:a.png',
      target: 'chat',
      conversation_id: 'c1',
    })
  })

  it('into a character answers with the character', async () => {
    stubFetch({ id: 3, name: 'Ada', images: ['i.png'] })
    expect((await importMediaToCharacter('lib:a.png', 3)).images).toEqual(['i.png'])
  })

  it('refuses an answer of the wrong kind rather than passing it on as the right one', async () => {
    stubFetch({ id: 3, name: 'Ada', images: [] })
    await expect(importMediaToChat('lib:a.png', 'c1')).rejects.toThrow('Unexpected answer')
    stubFetch({ file: 'up_1.png' })
    await expect(importMediaToCharacter('lib:a.png', 3)).rejects.toThrow('Unexpected answer')
  })
})
