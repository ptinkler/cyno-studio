/**
 * A stand-in for the network: every request the app makes is recorded and answered by one function, so a
 * test can say what the server returns and then check what was sent.
 */
export interface Call {
  method: string
  url: string
  /** The JSON body that was sent, or null when there was none. */
  body: unknown
}

const urlOf = (input: unknown): string => {
  if (typeof input === 'string') return input
  return input instanceof URL ? input.href : ''
}

/** Answer every fetch with `answer(call)` as JSON (status 200); returns the list the calls are recorded in. */
export function fakeServer(answer: (call: Call) => unknown): Call[] {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown, init?: { method?: string; body?: unknown }) => {
      const call: Call = {
        method: init?.method ?? 'GET',
        url: urlOf(input),
        body: typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : null,
      }
      calls.push(call)
      const reply = answer(call)
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: () => Promise.resolve(reply),
        text: () => Promise.resolve(JSON.stringify(reply)),
      })
    }),
  )
  return calls
}
