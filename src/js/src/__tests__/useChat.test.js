import { describe, it, expect, vi, afterEach } from 'vitest'
import { readSSE, chatMediaUrl, sendChatMessage } from '../composables/useChat'

function streamOf(chunks) {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c))
      controller.close()
    },
  })
}

describe('readSSE', () => {
  it('parses events split across arbitrary chunk boundaries', async () => {
    const events = []
    await readSSE(
      streamOf([
        'data: {"type":"st',
        'art"}\n\ndata: {"type":"delta","text":"hi"}\n',
        '\n: keep-alive\n\ndata: {"type":"done"}\n\n',
      ]),
      e => events.push(e),
    )
    expect(events).toEqual([{ type: 'start' }, { type: 'delta', text: 'hi' }, { type: 'done' }])
  })

  it('ignores comment-only blocks', async () => {
    const events = []
    await readSSE(streamOf([': keep-alive\n\n']), e => events.push(e))
    expect(events).toEqual([])
  })
})

describe('chatMediaUrl', () => {
  it('encodes path segments', () => {
    expect(chatMediaUrl('abc', 'img 1.png')).toBe('/api/chat/media/abc/img%201.png')
  })
})

describe('sendChatMessage', () => {
  afterEach(() => vi.unstubAllGlobals())

  const body = { content: 'hi' }

  it('posts the turn as JSON and feeds each event to the callback', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      body: streamOf(['data: {"type":"delta","text":"a"}\n\n', 'data: {"type":"done","message":null}\n\n']),
    }))
    vi.stubGlobal('fetch', fetchMock)
    const events = []
    await sendChatMessage('c 1', body, e => events.push(e))
    expect(events).toEqual([
      { type: 'delta', text: 'a' },
      { type: 'done', message: null },
    ])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/chat/conversations/c%201/messages')
    expect(init.method).toBe('POST')
    expect(init.headers.Accept).toBe('text/event-stream')
    expect(JSON.parse(init.body)).toEqual(body)
  })

  it('does not retry a failed turn: a second POST would start a second billed turn', async () => {
    const fetchMock = vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ detail: 'No key' }) }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(sendChatMessage('c1', body, () => {})).rejects.toThrow('No key')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('passes the abort signal on', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, body: streamOf([]) }))
    vi.stubGlobal('fetch', fetchMock)
    const ctl = new AbortController()
    await sendChatMessage('c1', body, () => {}, ctl.signal)
    expect(fetchMock.mock.calls[0][1].signal).toBe(ctl.signal)
  })
})
