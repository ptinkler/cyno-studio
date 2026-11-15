/**
 * Reading JSON off a response.
 *
 * `Response.json()` is typed `any`. These helpers are the only places that value is given a
 * type: the callers name a route, and the type comes from the backend's generated schema, so
 * the server's models are what vouches for it.
 */

/** The response body as `T`. `T` must come from the generated schema, never be written by hand. */
export async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T
}

function detailOf(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return undefined
  return typeof body.detail === 'string' && body.detail ? body.detail : undefined
}

/** The `detail` message of an error response, else `fallback`. */
export async function errorMessage(response: Response, fallback: string): Promise<string> {
  const body: unknown = await response.json().catch(() => ({}))
  return detailOf(body) ?? fallback
}
