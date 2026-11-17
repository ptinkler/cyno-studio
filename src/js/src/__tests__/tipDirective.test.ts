import { mount } from '@vue/test-utils'
import { defineComponent, h, ref, withDirectives } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { vTip } from '../directives/tip'

const bubble = () => document.querySelector<HTMLElement>('#tip-bubble')
const shown = () => (bubble() && !bubble()?.hidden ? bubble()?.textContent : null)

function mountButton(text = ref<string | null>('Rename')) {
  const Button = defineComponent({
    render: () => withDirectives(h('button', { type: 'button' }, 'x'), [[vTip, text.value]]),
  })
  return { w: mount(Button, { attachTo: document.body }), text }
}

describe('v-tip', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('opens on hover and closes on leave', async () => {
    const { w } = mountButton()
    await w.trigger('mouseenter')
    expect(shown()).toBe('Rename')
    await w.trigger('mouseleave')
    expect(shown()).toBeNull()
  })

  it('opens on keyboard focus, describes the element, and closes on Escape', async () => {
    const { w } = mountButton()
    await w.trigger('focus')
    expect(shown()).toBe('Rename')
    expect(w.attributes('aria-describedby')).toBe('tip-bubble')
    await w.trigger('keydown', { key: 'Escape' })
    expect(shown()).toBeNull()
    expect(w.attributes('aria-describedby')).toBeUndefined()
  })

  it('closes when the button is pressed, since that does its own action', async () => {
    const { w } = mountButton()
    await w.trigger('mouseenter')
    await w.trigger('click')
    expect(shown()).toBeNull()
  })

  it('leaves the text as data-tip and follows a changing value', async () => {
    const { w, text } = mountButton()
    expect(w.attributes('data-tip')).toBe('Rename')
    text.value = 'Pin'
    await w.vm.$nextTick()
    expect(w.attributes('data-tip')).toBe('Pin')
  })

  it('shows nothing for an empty value', async () => {
    const { w } = mountButton(ref(null))
    await w.trigger('mouseenter')
    expect(shown()).toBeNull()
    expect(w.attributes('data-tip')).toBeUndefined()
  })

  it('closes when its element goes away', async () => {
    const { w } = mountButton()
    await w.trigger('mouseenter')
    w.unmount()
    expect(shown()).toBeNull()
  })
})
