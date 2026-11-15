/**
 * Types that turn the generated OpenAPI `paths` into a typed client.
 *
 * `api.get('/api/chat/conversations/' + id)` and `api.get(`/api/chat/conversations/${id}`)` both
 * resolve to the `/api/chat/conversations/{conv_id}` operation, so the request body and the
 * response come from the backend's models. A path the backend doesn't serve is a compile error.
 */
import type { paths } from './schema'

export type Method = 'get' | 'post' | 'put' | 'patch' | 'delete'

/** Every route that has an operation for method `M`. */
export type PathsWith<M extends Method> = {
  [P in keyof paths]: [NonNullable<paths[P][M]>] extends [never] ? never : P
}[keyof paths]

type Operation<P extends keyof paths, M extends Method> = NonNullable<paths[P][M]>

// --- Matching a concrete endpoint string against the route templates ---------------------------

type WithoutQuery<E extends string> = E extends `${infer Path}?${string}` ? Path : E

// A `{param}` segment matches any single, non-empty segment; a literal one must match exactly.
// A wide (`${string}`) segment never matches a literal one, so `/api/media/${id}` is the
// `{media_id}` route and not `/api/media/blocked`.
type SegmentMatches<E extends string, P extends string> = P extends `{${string}}`
  ? E extends '' | `${string}/${string}`
    ? false
    : true
  : E extends P
    ? true
    : false

type Matches<E extends string, P extends string> = P extends `${infer PH}/${infer PT}`
  ? E extends `${infer EH}/${infer ET}`
    ? SegmentMatches<EH, PH> extends true
      ? Matches<ET, PT>
      : false
    : false
  : SegmentMatches<E, P>

/** The route(s) of method `M` that endpoint string `E` (query string allowed) refers to. */
export type RouteFor<M extends Method, E extends string> =
  WithoutQuery<E> extends infer S extends string
    ? S extends PathsWith<M>
      ? S
      : { [P in PathsWith<M>]: Matches<S, P> extends true ? P : never }[PathsWith<M>]
    : never

/**
 * The extra arguments a call needs: none when some route of method `M` matches `E`, else one that can
 * never be supplied, so an unknown endpoint fails to compile. It is a trailing parameter rather than a
 * constraint on `E` because wrapping `E` itself stops TypeScript inferring `/a/${id}` as a template.
 */
export type KnownEndpoint<M extends Method, E extends string> = [RouteFor<M, E>] extends [never]
  ? [endpointIsNotABackendRoute: never]
  : []

/** A route template as a string pattern: `/a/{id}/b` becomes `/a/${string}/b`, with an optional query string. */
type Pattern<P extends string> = P extends `${infer Head}{${string}}${infer Tail}`
  ? `${Head}${string}${Pattern<Tail>}`
  : P

/**
 * Every endpoint string shape a method accepts. It is the constraint on a client call's endpoint:
 * a constraint made of template literals is what makes TypeScript keep `/a/${id}` as a template
 * type instead of widening it to `string`. `KnownEndpoint` then does the strict per-segment check.
 */
export type EndpointPattern<M extends Method> = {
  [P in PathsWith<M>]: Pattern<P> | `${Pattern<P>}?${string}`
}[PathsWith<M>]

// --- What a route takes and returns -------------------------------------------------------------

type JsonBodyOf<O> = O extends { requestBody: { content: { 'application/json': infer B } } } ? B : never

type JsonResponseOf<O> = O extends { responses: infer R }
  ? R extends { 200: { content: { 'application/json': infer J } } }
    ? J
    : R extends { 201: { content: { 'application/json': infer J } } }
      ? J
      : never
  : never

/** The JSON request body of route `P` for method `M` (`never` when it takes none). */
export type RequestBody<P extends keyof paths, M extends Method> = JsonBodyOf<Operation<P, M>>

/** The JSON a route answers with (`never` for streams, files and redirects). */
export type ResponseOf<P extends keyof paths, M extends Method> = JsonResponseOf<Operation<P, M>>

/** The JSON a request to `E` answers with. */
export type ResponseFor<M extends Method, E extends string> = ResponseOf<RouteFor<M, E>, M>

/** The JSON body to send to `E`. */
export type BodyFor<M extends Method, E extends string> = RequestBody<RouteFor<M, E>, M>
