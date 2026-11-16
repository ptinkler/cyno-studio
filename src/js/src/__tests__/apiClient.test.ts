/**
 * Runtime behaviour of the typed client (composables/useApi.ts): what it sends and how it fails.
 * The types are covered by apiTypes.test.ts.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { api } from '../composables/useApi'

interface Reply {
  ok: boolean
  status: number
  json: () => Promise<unknown>
}

type FetchMock = Mock<[string, RequestInit], Promise<Reply>>

function respond(body: unknown, init: { ok?: boolean; status?: number } = {}): Reply {
  return { ok: init.ok ?? true, status: init.status ?? 200, json: () => Promise.resolve(body) }
}

function stubFetch(...responses: Reply[]): FetchMock {
  const fetchMock: FetchMock = vi.fn()
  for (const response of responses) fetchMock.mockResolvedValueOnce(response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastCall(fetchMock: FetchMock): [string, RequestInit] {
  const call = fetchMock.mock.calls.at(-1)
  if (!call) throw new Error('fetch was not called')
  return call
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api.get', () => {
  it('returns the parsed body of the route', async () => {
    const fetchMock = stubFetch(respond({ authenticated: false, user: null }))
    expect(await api.get('/api/auth/status')).toEqual({ authenticated: false, user: null })
    expect(lastCall(fetchMock)[0]).toBe('/api/auth/status')
  })

  it('throws the HTTP status when the response is not ok', async () => {
    stubFetch(respond({}, { ok: false, status: 404 }))
    await expect(api.get('/api/auth/status')).rejects.toThrow('API error: 404')
  })
})

describe('writes', () => {
  it('send the body as JSON', async () => {
    const fetchMock = stubFetch(respond({ keys: {} }))
    await api.put('/api/keys', { keys: { pollo: 'sk' } })
    const [, init] = lastCall(fetchMock)
    expect(init.method).toBe('PUT')
    expect(init.body).toBe(JSON.stringify({ keys: { pollo: 'sk' } }))
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
  })

  it('send nothing for a route that takes no body', async () => {
    const fetchMock = stubFetch(respond({ cancelled: true }))
    await api.post('/api/chat/messages/5/cancel')
    const [, init] = lastCall(fetchMock)
    expect(init.method).toBe('POST')
    expect(init.body).toBeUndefined()
  })

  it('are never retried: a repeated POST could bill twice', async () => {
    const fetchMock = stubFetch(respond({ detail: 'down' }, { ok: false, status: 503 }), respond({}))
    await expect(api.put('/api/keys', { keys: {} })).rejects.toThrow('down')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("fail with the server's detail message", async () => {
    stubFetch(respond({ detail: 'Not allowed' }, { ok: false, status: 403 }))
    await expect(api.delete('/api/characters/3')).rejects.toThrow('Not allowed')
  })
})

describe('api.upload', () => {
  it('posts the file as the multipart field "file", leaving the content type to the browser', async () => {
    const fetchMock = stubFetch(respond({ id: 3 }))
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    await api.upload('/api/characters/3/images', file)
    const [url, init] = lastCall(fetchMock)
    expect(url).toBe('/api/characters/3/images')
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.body as FormData).get('file')).toBeInstanceOf(File)
    expect(init.headers).toBeUndefined()
  })
})
