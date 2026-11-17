import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import InfoTip from '../components/InfoTip.vue'

const span = (w: ReturnType<typeof mountTip>) => w.find('.infotip')
const tip = () => document.body.querySelector('[role="tooltip"]')

function mountTip(props: { focusable?: boolean; toggle?: boolean } = {}) {
  return mount(InfoTip, {
    props: { text: 'What this means', ...props },
    slots: { default: '<b>chip</b>' },
    attachTo: document.body,
  })
}

describe('InfoTip', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('shows on hover and hides on leave', async () => {
    const w = mountTip()
    await span(w).trigger('mouseenter')
    expect(tip()?.textContent).toBe('What this means')
    await span(w).trigger('mouseleave')
    expect(tip()).toBeNull()
  })

  it('shows on keyboard focus and closes on Escape', async () => {
    const w = mountTip()
    await span(w).trigger('focusin')
    expect(tip()).not.toBeNull()
    expect(span(w).attributes('aria-describedby')).toBe(tip()?.id)
    await span(w).trigger('keydown', { key: 'Escape' })
    expect(tip()).toBeNull()
  })

  it('toggles on tap, which is how touch reaches it', async () => {
    const w = mountTip()
    await span(w).trigger('click')
    expect(tip()).not.toBeNull()
    await span(w).trigger('click')
    expect(tip()).toBeNull()
  })

  it('does not toggle on tap when the child does something on tap, and stays out of the tab order', async () => {
    const w = mountTip({ focusable: false, toggle: false })
    expect(span(w).attributes('tabindex')).toBeUndefined()
    await span(w).trigger('click')
    expect(tip()).toBeNull()
  })

  it('is in the tab order by default', () => {
    expect(span(mountTip()).attributes('tabindex')).toBe('0')
  })
})
