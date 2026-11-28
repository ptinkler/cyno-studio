import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import StudioKeys from '../components/studio/StudioKeys.vue'
import * as account from '../composables/useAccount'

vi.mock('../composables/useAccount', async importOriginal => ({
  ...(await importOriginal<typeof account>()),
  fetchUserKeys: vi.fn(),
  saveUserKeys: vi.fn(),
}))

describe('StudioKeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(account.fetchUserKeys).mockResolvedValue({ keys: {} })
  })

  it('says so when keys are saved, so the page can refresh models and balances', async () => {
    vi.mocked(account.saveUserKeys).mockResolvedValue({ keys: { venice: { set: true, hint: '…1234' } } })
    const w = mount(StudioKeys)
    await flushPromises()
    await w.find('input').setValue('sk-test')
    await w.find('.btn-primary').trigger('click')
    await flushPromises()
    expect(w.emitted('saved')).toHaveLength(1)
  })

  it('stays quiet when saving fails', async () => {
    vi.mocked(account.saveUserKeys).mockRejectedValue(new Error('nope'))
    const w = mount(StudioKeys)
    await flushPromises()
    await w.find('.btn-primary').trigger('click')
    await flushPromises()
    expect(w.emitted('saved')).toBeUndefined()
    expect(w.text()).toContain('nope')
  })
})
