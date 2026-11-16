import { describe, it, expect } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import StudioAccount from '../components/studio/StudioAccount.vue'
import { fakeServer } from './fakeServer'

const signedIn = {
  providers: ['google'],
  open_signup: false,
  dev_login: false,
  user: { id: 'u1', email: 'a@x.com', name: 'A', avatar_url: null, provider: 'google', is_admin: false },
}

describe('StudioAccount', () => {
  it('signs out the other devices, not this one', async () => {
    const calls = fakeServer(call => (call.url === '/api/auth/providers' ? signedIn : { ok: true }))
    const w = mount(StudioAccount)
    await flushPromises()
    const button = w.findAll('button').find(b => b.text() === 'Sign out other devices')
    await button?.trigger('click')
    await flushPromises()
    expect(calls.some(c => c.method === 'POST' && c.url === '/api/auth/logout-others')).toBe(true)
    expect(w.emitted('sign-out')).toBeUndefined()
  })

  it('offers nothing to sign out of when nobody is signed in', async () => {
    fakeServer(() => ({ ...signedIn, user: null }))
    const w = mount(StudioAccount)
    await flushPromises()
    expect(w.text()).not.toContain('Sign out other devices')
  })
})
