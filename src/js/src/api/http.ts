/** The fetch layer under the API clients: session cookie, sign-in prompt on 401, retries on 5xx. */
import { useAuth } from '../composables/useAuth'

const BASE_URL = ''

const RETRY_CONFIG = {
  maxRetries: 3,
  initialDelay: 500,
  maxDelay: 2000,
}

const HTTP_UNAUTHORIZED = 401
const HTTP_SERVER_ERROR = 500

export const API_KEY_REQUIRED = 'API key required'

/** The error for a response that isn't ok, worded as `what` failed with its HTTP status. */
export function statusError(response: Response, what = 'API error'): Error {
  return new Error(`${what}: ${String(response.status)}`)
}

type Attempt = { response: Response } | { error: Error }

/** One request: the response when it's final (success, a client error, or the last try), else the error to retry on. */
async function fetchOnce(url: string, opts: RequestInit, isLast: boolean): Promise<Attempt> {
  const response = await fetch(url, opts)
  if (response.status === HTTP_UNAUTHORIZED) {
    useAuth().promptLogin()
    throw new Error(API_KEY_REQUIRED)
  }
  if (response.ok || response.status < HTTP_SERVER_ERROR || isLast) return { response }
  return { error: statusError(response) }
}

/** `fetchOnce`, with a network failure turned into an error to retry on (a missing login is not retried). */
async function tryFetch(url: string, opts: RequestInit, isLast: boolean): Promise<Attempt> {
  try {
    return await fetchOnce(url, opts, isLast)
  } catch (thrown) {
    const error = asError(thrown)
    if (error.message === API_KEY_REQUIRED) throw error
    return { error }
  }
}

function asError(thrown: unknown): Error {
  return thrown instanceof Error ? thrown : new Error(String(thrown))
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/** Fetch `endpoint`, retrying network failures and 5xx up to `retries` more times (GETs only; writes pass 0). */
export async function fetchWithRetry(
  endpoint: string,
  options: RequestInit = {},
  retries: number = RETRY_CONFIG.maxRetries,
): Promise<Response> {
  const opts: RequestInit = { credentials: 'same-origin', ...options }
  let lastError: Error | undefined
  let delay = RETRY_CONFIG.initialDelay

  for (let attempt = 0; attempt <= retries; attempt++) {
    const result = await tryFetch(`${BASE_URL}${endpoint}`, opts, attempt === retries)
    if ('response' in result) return result.response
    lastError = result.error

    if (attempt < retries) {
      await sleep(delay)
      delay = Math.min(delay * 2, RETRY_CONFIG.maxDelay)
    }
  }

  throw lastError ?? new Error('Request failed')
}
