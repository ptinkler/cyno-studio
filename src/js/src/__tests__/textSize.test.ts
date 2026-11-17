import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import StudioSettings from '../components/studio/StudioSettings.vue'
import { fakeServer } from './fakeServer'

afterEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-text')
  vi.resetModules()
})

async function fresh() {
  vi.resetModules()
  return import('../composables/useTextSize')
}

describe('text size', () => {
  it('starts comfortable and puts that on <html>', async () => {
    await fresh()
    expect(document.documentElement.getAttribute('data-text')).toBe('comfortable')
  })

  it('remembers the choice for next time', async () => {
    const { useTextSize } = await fresh()
    useTextSize().setTextSize('large')
    await flushPromises()
    expect(document.documentElement.getAttribute('data-text')).toBe('large')
    expect(localStorage.getItem('studio.textSize')).toBe('large')
    await fresh()
    expect(document.documentElement.getAttribute('data-text')).toBe('large')
  })

  it("ignores a stored value it doesn't know", async () => {
    localStorage.setItem('studio.textSize', 'gigantic')
    await fresh()
    expect(document.documentElement.getAttribute('data-text')).toBe('comfortable')
  })

  it('is chosen in Settings, which shows the one in use', async () => {
    fakeServer(() => ({ providers: [], open_signup: false, dev_login: false, user: null }))
    await fresh()
    const w = mount(StudioSettings, {
      global: { stubs: { StudioTitleModel: true, StudioKeys: true, StudioUploads: true } },
    })
    await flushPromises()
    const group = w.find('[aria-label="Text size"]')
    const buttons = group.findAll('button')
    expect(buttons.map(b => b.text())).toEqual(['Compact', 'Comfortable', 'Large'])
    expect(buttons[1]?.classes()).toContain('on')
    await buttons[0]?.trigger('click')
    expect(document.documentElement.getAttribute('data-text')).toBe('compact')
    expect(group.findAll('button')[0]?.classes()).toContain('on')
  })
})
