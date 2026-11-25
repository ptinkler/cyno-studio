import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StudioFeed from '../components/studio/StudioFeed.vue'
import type { UiMessage } from '../composables/studioTypes'

const msg = (id: number) => ({ id, role: 'user', content: 'hi', media: [], status: 'done' }) as unknown as UiMessage

function feed() {
  const w = mount(StudioFeed, {
    props: { messages: [msg(1)], active: 'c1' },
    global: { stubs: { ChatMessage: true }, directives: { tip: {} } },
  })
  const el = w.find('.feed').element
  const set = (top: number) => {
    Object.defineProperty(el, 'scrollHeight', { value: 5000, configurable: true })
    Object.defineProperty(el, 'clientHeight', { value: 800, configurable: true })
    el.scrollTop = top
  }
  return { w, set }
}

describe('StudioFeed jump buttons', () => {
  it('shows none at an end of a short scroll, Latest when scrolled up, Start when far from it', async () => {
    const { w, set } = feed()
    set(4200) // at the bottom
    await w.find('.feed').trigger('scroll')
    expect(w.find('.jump').exists()).toBe(true) // far from start
    expect(w.find('.latest').exists()).toBe(false)
    set(100) // near the top
    await w.find('.feed').trigger('scroll')
    expect(w.find('.up').exists()).toBe(false)
    expect(w.find('.latest').exists()).toBe(true)
    set(2000)
    await w.find('.feed').trigger('scroll')
    expect(w.find('.up').exists()).toBe(true)
    expect(w.find('.latest').exists()).toBe(true)
  })
})
