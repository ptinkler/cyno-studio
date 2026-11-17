import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import StudioSigninRequests from '../components/studio/StudioSigninRequests.vue'
import * as signins from '../composables/signinRequestsApi'

vi.mock('../composables/signinRequestsApi')

const row = { identity: 'x:42', provider: 'x', email: null, name: '@alice', approved: false, last_seen: null }

describe('StudioSigninRequests', () => {
  beforeEach(() => {
    vi.mocked(signins.fetchSigninRequests).mockResolvedValue({ requests: [row] })
  })

  it('lists a waiting sign-in and approves it', async () => {
    vi.mocked(signins.approveSignin).mockResolvedValue({ requests: [{ ...row, approved: true }] })
    const w = mount(StudioSigninRequests)
    await flushPromises()
    expect(w.text()).toContain('@alice')
    await w.findAll('button')[0]?.trigger('click')
    await flushPromises()
    expect(signins.approveSignin).toHaveBeenCalledWith('x:42')
    expect(w.text()).toContain('Approved')
  })

  it('denies and shows the empty note', async () => {
    vi.mocked(signins.denySignin).mockResolvedValue({ requests: [] })
    const w = mount(StudioSigninRequests)
    await flushPromises()
    await w.findAll('button')[1]?.trigger('click')
    await flushPromises()
    expect(signins.denySignin).toHaveBeenCalledWith('x:42')
    expect(w.text()).toContain('Nobody is waiting')
  })
})
