import type { components } from '../api/schema'
import { fetchWithRetry, statusError } from '../api/http'
import { errorMessage } from '../api/json'
import type { BodyFor, EndpointPattern, KnownEndpoint, StreamEventsFor } from '../api/paths'

// The streamed turns: send, retry, edit and reword. Each answers with server-sent events, one `TurnEvent`
// (a type named by the backend's `type` field) per `data:` line. The event models are the backend's
// (`chat/schemas.py`); the route says which events a stream carries.
type Schemas = components['schemas']

export type TurnEvent = StreamEventsFor<'/api/chat/conversations/${string}/messages'>
export type TurnEventOf<Type extends TurnEvent['type']> = Extract<TurnEvent, { type: Type }>

const enc = encodeURIComponent

/** Feed each `data:` event of a server-sent event stream to `onEvent`; resolves when the stream ends. */
export async function readSSE(stream: ReadableStream<Uint8Array>, onEvent: (event: unknown) => void) {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    for (let sep = buffer.indexOf('\n\n'); sep !== -1; sep = buffer.indexOf('\n\n')) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const data = block
        .split('\n')
        .filter(line => line.startsWith('data: '))
        .map(line => line.slice(6))
        .join('\n')
      if (data) onEvent(JSON.parse(data))
    }
  }
}

/**
 * POST a turn and feed each SSE event to `onEvent`. Resolves when the stream ends. Aborting `signal` only
 * stops listening — the server keeps running the turn (use cancelChatMessage to actually stop it).
 */
async function streamTurn<E extends EndpointPattern<'post'>>(
  endpoint: E,
  body: BodyFor<'post', E>,
  onEvent: (event: StreamEventsFor<E>) => void,
  signal?: AbortSignal,
  ..._known: KnownEndpoint<'post', E>
): Promise<void> {
  const init: RequestInit = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
  }
  if (signal) init.signal = signal
  // No retries: a second POST would start a second (billed) turn
  const res = await fetchWithRetry(endpoint, init, 0)
  if (!res.ok) throw new Error(await errorMessage(res, statusError(res).message))
  if (!res.body) throw new Error('The server sent no stream')
  // The route's event models vouch for the shape: this is where a streamed event gets its type
  await readSSE(res.body, event => {
    onEvent(event as StreamEventsFor<E>)
  })
}

type OnEvent = (event: TurnEvent) => void

export const sendChatMessage = (convId: string, body: Schemas['SendMessage'], onEvent: OnEvent, signal?: AbortSignal) =>
  streamTurn(`/api/chat/conversations/${enc(convId)}/messages`, body, onEvent, signal)

export const retryChatMessage = (
  convId: string,
  body: Schemas['RetryMessage'],
  onEvent: OnEvent,
  signal?: AbortSignal,
) => streamTurn(`/api/chat/conversations/${enc(convId)}/retry`, body, onEvent, signal)

export const editChatMessage = (convId: string, body: Schemas['EditMessage'], onEvent: OnEvent, signal?: AbortSignal) =>
  streamTurn(`/api/chat/conversations/${enc(convId)}/edit`, body, onEvent, signal)

// Write a reply's words again, keeping the pictures it already made.
// Body: turn settings + message_id, and `instruction` to edit the words (empty = redo them)
export const rewordChatMessage = (
  convId: string,
  body: Schemas['RewordMessage'],
  onEvent: OnEvent,
  signal?: AbortSignal,
) => streamTurn(`/api/chat/conversations/${enc(convId)}/reword`, body, onEvent, signal)
