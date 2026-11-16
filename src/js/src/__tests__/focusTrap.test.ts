import { describe, expect, it } from 'vitest'
import { defineComponent, h, ref, toRef } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { useFocusTrap } from '../composables/useFocusTrap'

const Dialog = defineComponent({
  props: { open: { type: Boolean, default: true }, withField: Boolean },
  setup(props) {
    const card = ref<HTMLElement | null>(null)
    useFocusTrap(card, toRef(props, 'open'))
    return () =>
      h('div', { ref: card }, [
        h('button', { id: 'a' }, 'A'),
        props.withField ? h('input', { id: 'field', autofocus: true }) : null,
        h('button', { id: 'z' }, 'Z'),
      ])
  },
})

const press = (key: string, shiftKey = false) =>
  document.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true }))

describe('useFocusTrap', () => {
  it('moves focus into the dialog when it opens', async () => {
    const w = mount(Dialog, { attachTo: document.body })
    await flushPromises()
    expect(document.activeElement?.id).toBe('a')
    w.unmount()
  })

  it("doesn't take focus from a field inside that already has it", async () => {
    const w = mount(Dialog, { props: { withField: true }, attachTo: document.body })
    document.getElementById('field')?.focus()
    await flushPromises()
    expect(document.activeElement?.id).toBe('field')
    w.unmount()
  })

  it('wraps Tab from the last control to the first, and Shift+Tab the other way', async () => {
    const w = mount(Dialog, { attachTo: document.body })
    await flushPromises()
    document.getElementById('z')?.focus()
    press('Tab')
    expect(document.activeElement?.id).toBe('a')
    press('Tab', true)
    expect(document.activeElement?.id).toBe('z')
    w.unmount()
  })

  it('pulls focus back if it has wandered out to the page', async () => {
    const outside = document.createElement('button')
    document.body.append(outside)
    const w = mount(Dialog, { attachTo: document.body })
    await flushPromises()
    outside.focus()
    press('Tab')
    expect(document.activeElement?.id).toBe('a')
    w.unmount()
    outside.remove()
  })

  it('gives focus back to what opened it when it closes', async () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    const w = mount(Dialog, { attachTo: document.body })
    await flushPromises()
    expect(document.activeElement).not.toBe(opener)
    w.unmount()
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })
})
