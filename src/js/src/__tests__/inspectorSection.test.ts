import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import InspectorSection from '../components/studio/InspectorSection.vue'

const mountSection = () =>
  mount(InspectorSection, { props: { title: 'Models' }, slots: { default: '<p>body</p>' }, attachTo: document.body })

describe('InspectorSection', () => {
  it('folds away on its header and remembers it', async () => {
    const w = mountSection()
    expect(w.find('p').isVisible()).toBe(true)
    await w.find('.ihead').trigger('click')
    expect(w.find('p').isVisible()).toBe(false)
    expect(w.find('.ihead').attributes('aria-expanded')).toBe('false')
    expect(JSON.parse(localStorage.getItem('studio.inspector.collapsed') ?? '[]')).toEqual(['Models'])
    // another copy (e.g. after a reload of the view) starts folded
    expect(mountSection().find('p').isVisible()).toBe(false)
    await w.find('.ihead').trigger('click')
    expect(w.find('p').isVisible()).toBe(true)
  })
})
