/**
 * Type-level tests for the typed API client (api/paths.ts, composables/useApi.ts).
 *
 * `npm run typecheck` is what runs these: a failing assertion is a compile error. The calls sit
 * in functions that are never invoked, so nothing touches the network.
 */
import { describe, expectTypeOf, it } from 'vitest'
import type { components } from '../api/schema'
import type {
  BodyFor,
  EndpointPattern,
  FormEndpoint,
  KnownEndpoint,
  ResponseFor,
  RouteFor,
  SendArgs,
} from '../api/paths'
import { api } from '../composables/useApi'
import type { TurnEvent, TurnEventOf } from '../composables/chatStreamApi'

type Schemas = components['schemas']

describe('route matching', () => {
  it('finds a literal route', () => {
    expectTypeOf<RouteFor<'get', '/api/auth/status'>>().toEqualTypeOf<'/api/auth/status'>()
  })

  it('ignores the query string', () => {
    expectTypeOf<RouteFor<'get', '/api/auth/status?x=1'>>().toEqualTypeOf<'/api/auth/status'>()
    expectTypeOf<RouteFor<'get', `/api/auth/status?${string}`>>().toEqualTypeOf<'/api/auth/status'>()
  })

  it('maps a template string onto the {param} route', () => {
    expectTypeOf<
      RouteFor<'get', `/api/chat/conversations/${string}`>
    >().toEqualTypeOf<'/api/chat/conversations/{conv_id}'>()
  })

  it('keeps a wide segment off the literal routes beside a {param} route', () => {
    expectTypeOf<RouteFor<'get', `/api/media/${string}`>>().not.toEqualTypeOf<'/api/media/blocked'>()
  })

  it('does not let a parameter swallow a slash', () => {
    expectTypeOf<RouteFor<'get', `/api/chat/conversations/${string}/nothing/here`>>().toBeNever()
  })

  it('knows which method a route has', () => {
    expectTypeOf<RouteFor<'post', '/api/auth/status'>>().toBeNever()
    expectTypeOf<RouteFor<'put', '/api/keys'>>().toEqualTypeOf<'/api/keys'>()
  })

  it('rejects an endpoint the backend does not serve', () => {
    expectTypeOf<KnownEndpoint<'get', '/api/nope'>>().toEqualTypeOf<[endpointIsNotABackendRoute: never]>()
    expectTypeOf<KnownEndpoint<'get', '/api/auth/status'>>().toEqualTypeOf<[]>()
  })
})

describe('request and response types', () => {
  it('comes from the backend models', () => {
    expectTypeOf<ResponseFor<'get', '/api/auth/status'>>().toEqualTypeOf<Schemas['AuthStatus']>()
    expectTypeOf<ResponseFor<'get', '/api/keys'>>().toEqualTypeOf<Schemas['KeysStatus']>()
    expectTypeOf<BodyFor<'put', '/api/keys'>>().toEqualTypeOf<Schemas['KeysUpdate']>()
  })

  it('has no nullable or optional fields the backend does not declare', () => {
    expectTypeOf<Schemas['SessionUser']>().toEqualTypeOf<{ email: string; name: string | null; is_admin: boolean }>()
    expectTypeOf<Schemas['KeyStatus']>().toEqualTypeOf<{ hint: string; set: boolean }>()
  })
})

describe('the client', () => {
  it('returns the route response', () => {
    const status = () => api.get('/api/auth/status')
    expectTypeOf(status).returns.resolves.toEqualTypeOf<Schemas['AuthStatus']>()
    const keys = () => api.put('/api/keys', { keys: { pollo: 'sk' } })
    expectTypeOf(keys).returns.resolves.toEqualTypeOf<Schemas['KeysStatus']>()
  })

  it('takes a template string endpoint', () => {
    const id = 'abc'
    const open = () => api.get(`/api/chat/conversations/${id}`)
    expectTypeOf(open).returns.resolves.toEqualTypeOf<ResponseFor<'get', '/api/chat/conversations/{conv_id}'>>()
  })

  it('takes a template whose id is only known to be a string', () => {
    const id = (value: number): string => String(value)
    const update = (n: number) => api.put(`/api/chat/instructions/${id(n)}`, { name: 'n', content: 'c' })
    expectTypeOf(update).returns.resolves.toEqualTypeOf<Schemas['Instruction']>()
    const remove = (n: number) => api.delete(`/api/chat/spaces/${id(n)}`)
    expectTypeOf(remove).returns.resolves.toEqualTypeOf<Schemas['Deleted']>()
  })

  it('refuses an endpoint the backend does not serve', () => {
    // Not a route of any shape: the endpoint constraint rejects it
    expectTypeOf<'/api/nope'>().not.toMatchTypeOf<EndpointPattern<'get'>>()
    // Shaped like a route but with a slash inside a {param} segment: the trailing check demands an argument no caller can give
    expectTypeOf<KnownEndpoint<'get', `/api/chat/conversations/${string}/x/y`>>().toEqualTypeOf<
      [endpointIsNotABackendRoute: never]
    >()
    // A route with no PUT is refused for PUT
    expectTypeOf<'/api/auth/status'>().not.toMatchTypeOf<EndpointPattern<'put'>>()
  })

  it('takes the backend model as the request body', () => {
    expectTypeOf(api.put<'/api/keys'>)
      .parameter(1)
      .toEqualTypeOf<Schemas['KeysUpdate']>()
    expectTypeOf<{ keys: { pollo: number } }>().not.toMatchTypeOf<Schemas['KeysUpdate']>()
  })
})

describe('streamed turns', () => {
  it('carry the backend event union, told apart by `type`', () => {
    expectTypeOf<TurnEvent['type']>().toEqualTypeOf<
      'start' | 'delta' | 'media' | 'characters' | 'instructions' | 'title' | 'error' | 'done'
    >()
    expectTypeOf<TurnEventOf<'delta'>>().toEqualTypeOf<Schemas['DeltaEvent']>()
    expectTypeOf<TurnEventOf<'media'>['item']>().toEqualTypeOf<Schemas['MediaCard']>()
    expectTypeOf<TurnEventOf<'done'>['message']>().toEqualTypeOf<Schemas['ShownMessage'] | null>()
  })

  it('narrow on `type`', () => {
    const text = (event: TurnEvent): string | undefined => (event.type === 'delta' ? event.text : undefined)
    expectTypeOf(text).returns.toEqualTypeOf<string | undefined>()
  })
})

describe('writes without a JSON body, and multipart uploads', () => {
  it('a bodyless route takes no body argument', () => {
    expectTypeOf<SendArgs<'post', '/api/chat/messages/5/cancel'>>().toEqualTypeOf<[]>()
    expectTypeOf<SendArgs<'put', '/api/keys'>>().toEqualTypeOf<[body: Schemas['KeysUpdate']]>()
  })

  it('only a route that declares a multipart form takes an upload', () => {
    expectTypeOf<FormEndpoint<'/api/characters/3/images'>>().toEqualTypeOf<[]>()
    expectTypeOf<FormEndpoint<'/api/keys'>>().toEqualTypeOf<[endpointTakesNoForm: never]>()
  })
})
