import { describe, it, expect } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import BaseDialog from '../components/BaseDialog.vue'

describe('BaseDialog', () => {
  it('Esc closes only the dialog on top (a picker opened from inside another)', () => {
    const outer = mount(BaseDialog, { props: { open: true, title: 'Space' }, attachTo: document.body })
    const inner = mount(BaseDialog, { props: { open: true, title: 'Characters' }, attachTo: document.body })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(inner.emitted('close')).toHaveLength(1)
    expect(outer.emitted('close')).toBeUndefined()
    inner.unmount()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(outer.emitted('close')).toHaveLength(1)
    outer.unmount()
  })

  it('moves focus into the dialog, keeps Tab inside it, and gives focus back on close', async () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    const w = mount(BaseDialog, {
      props: { open: false, title: 'Rename' },
      slots: { default: '<input id="name" />' },
      attachTo: document.body,
    })
    await w.setProps({ open: true })
    await flushPromises()
    expect(document.activeElement?.id).toBe('name')
    // Tab from the last control (the field) wraps to the first (the ✕), not out to the page
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(document.querySelector('.dialog .x'))
    await w.setProps({ open: false })
    expect(document.activeElement).toBe(opener)
    w.unmount()
    opener.remove()
  })
})
