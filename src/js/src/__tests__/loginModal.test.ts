import { afterEach, describe, it, expect } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import LoginModal from '../components/LoginModal.vue'
import { useAuth } from '../composables/useAuth'
import { fakeServer } from './fakeServer'

const providers = { providers: ['x'], open_signup: false, dev_login: false, user: null }

afterEach(() => {
  history.replaceState(null, '', '/')
})

async function openAt(url: string) {
  history.replaceState(null, '', url)
  fakeServer(() => providers)
  useAuth().promptLogin()
  const w = mount(LoginModal, { attachTo: document.body })
  await flushPromises()
  return w
}

describe('LoginModal after a refused sign-in', () => {
  it('tells an email-less user the id to give the admin, and clears the address', async () => {
    const w = await openAt('/?auth=denied&id=x%3A42')
    expect(document.body.textContent).toContain('x:42')
    expect(document.body.textContent).toContain('ALLOWED_OAUTH_IDS')
    expect(location.search).toBe('')
    w.unmount()
  })

  it('asks an email user to give the admin their email', async () => {
    const w = await openAt('/?auth=denied')
    expect(document.body.textContent).toContain('add your email')
    w.unmount()
  })

  it('says nothing for an ordinary visit', async () => {
    const w = await openAt('/')
    expect(document.body.textContent).not.toContain('allowed in')
    w.unmount()
  })
})
