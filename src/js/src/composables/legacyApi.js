// The untyped API helpers, kept only for endpoints whose backend response still has no model
// (the route returns a loose dict, so there is nothing to generate a type from). Every call site
// of these is migration debt: give the route a response model, regenerate the types (`make gen-api`)
// and move the caller to `api` in useApi.ts. Delete this file when the last caller is gone.
import { fetchWithRetry } from '../api/http'
import { errorMessage } from '../api/json'

export async function apiGet(endpoint) {
  const response = await fetchWithRetry(endpoint)
  if (!response.ok) throw new Error(`API error: ${response.status}`)
  return response.json()
}

// JSON (or FormData) request with the error's `detail` as the message
async function apiSend(method, endpoint, data) {
  const isForm = data instanceof FormData
  const options = { method }
  if (data !== undefined) {
    options.body = isForm ? data : JSON.stringify(data)
    if (!isForm) options.headers = { 'Content-Type': 'application/json' }
  }
  // No retries on writes: POST/PUT/PATCH/DELETE aren't idempotent, and a 5xx or
  // network hiccup on a generation submit would otherwise silently re-fire it —
  // billing (and showing) several images when one failed. GET retries below.
  const response = await fetchWithRetry(endpoint, options, 0)
  if (!response.ok) throw new Error(await errorMessage(response, `API error: ${response.status}`))
  return response.json()
}

export const apiPost = (endpoint, data = {}) => apiSend('POST', endpoint, data)
export const apiPut = (endpoint, data = {}) => apiSend('PUT', endpoint, data)
export const apiPatch = (endpoint, data = {}) => apiSend('PATCH', endpoint, data)
export const apiDelete = endpoint => apiSend('DELETE', endpoint)

/** POST a file as multipart form data (field "file"). */
export function apiUpload(endpoint, file) {
  const form = new FormData()
  form.append('file', file)
  return apiSend('POST', endpoint, form)
}
