import { fetchWithRetry, statusError } from '../api/http'
import { errorMessage, readJson } from '../api/json'
import type { BodyFor, EndpointPattern, FormEndpoint, KnownEndpoint, ResponseFor, SendArgs } from '../api/paths'

// Endpoints whose backend response has no model yet; see legacyApi.js.
export { apiDelete, apiGet, apiPatch, apiPost, apiPut, apiUpload } from './legacyApi'

const JSON_HEADERS = { 'Content-Type': 'application/json' }
const REVOKE_AFTER_MS = 10_000

/** `endpoint` is checked against the backend's routes; the body and the result are that route's types. */
async function get<E extends EndpointPattern<'get'>>(
  endpoint: E,
  ..._known: KnownEndpoint<'get', E>
): Promise<ResponseFor<'get', E>> {
  const response = await fetchWithRetry(endpoint)
  if (!response.ok) throw statusError(response)
  return readJson<ResponseFor<'get', E>>(response)
}

// JSON request with the error's `detail` as the message. No retries on writes: POST/PUT/PATCH/DELETE
// aren't idempotent, and a 5xx or network hiccup on a generation submit would otherwise silently
// re-fire it, billing (and showing) several images when one failed. GETs retry.
async function send<M extends 'post' | 'put' | 'patch' | 'delete', E extends string>(
  method: M,
  endpoint: E,
  body: unknown,
): Promise<ResponseFor<M, E>> {
  const init: RequestInit = { method: method.toUpperCase() }
  if (body instanceof FormData) {
    init.body = body // the browser sets the multipart boundary itself
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = JSON_HEADERS
  }
  const response = await fetchWithRetry(endpoint, init, 0)
  if (!response.ok) throw new Error(await errorMessage(response, statusError(response).message))
  return readJson<ResponseFor<M, E>>(response)
}

/** The typed client: every call names a route the backend serves, and its types come from the generated schema. */
export const api = {
  get,
  post: <E extends EndpointPattern<'post'>>(endpoint: E, ...args: SendArgs<'post', E>) =>
    send('post', endpoint, args[0]),
  put: <E extends EndpointPattern<'put'>>(endpoint: E, ...args: SendArgs<'put', E>) => send('put', endpoint, args[0]),
  patch: <E extends EndpointPattern<'patch'>>(endpoint: E, ...args: SendArgs<'patch', E>) =>
    send('patch', endpoint, args[0]),
  /** POST a multipart form to a route that takes one. */
  postForm: <E extends EndpointPattern<'post'>>(endpoint: E, form: FormData, ..._known: FormEndpoint<E>) =>
    send('post', endpoint, form),
  /** POST one file as the form field "file". */
  upload: <E extends EndpointPattern<'post'>>(endpoint: E, file: Blob, ..._known: FormEndpoint<E>) => {
    const form = new FormData()
    form.append('file', file)
    return send('post', endpoint, form)
  },
  delete: <E extends EndpointPattern<'delete'>>(endpoint: E, ..._known: KnownEndpoint<'delete', E>) =>
    send('delete', endpoint, undefined),
}

/** POST JSON, get a file back; saves it under `filename` through a temporary link. */
export async function apiDownload<E extends EndpointPattern<'post'>>(
  endpoint: E,
  data: BodyFor<'post', E>,
  filename: string,
  ..._known: KnownEndpoint<'post', E>
): Promise<void> {
  const response = await fetchWithRetry(
    endpoint,
    { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(data) },
    0,
  )
  if (!response.ok) throw statusError(response, 'Download failed')
  const url = URL.createObjectURL(await response.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  a.click()
  setTimeout(() => {
    URL.revokeObjectURL(url)
  }, REVOKE_AFTER_MS)
}
