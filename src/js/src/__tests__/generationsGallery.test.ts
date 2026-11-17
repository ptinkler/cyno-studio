import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import GenerationGrid from '../components/studio/GenerationGrid.vue'
import GenerationModal from '../components/studio/GenerationModal.vue'
import type { GenerationItem } from '../composables/studioTypes'
import { generationItem } from './models'

const ITEMS: GenerationItem[] = [
  generationItem({
    id: 'd1',
    kind: 'image',
    status: 'done',
    url: '/u1',
    preview: '/p1',
    file: 'a.png',
    favourite: true,
    prompt: 'cat',
  }),
  generationItem({
    id: 'd2',
    kind: 'video',
    status: 'done',
    url: '/u2',
    file: 'b.mp4',
    favourite: false,
    prompt: 'dog',
  }),
  generationItem({ id: 'p1', kind: 'image', status: 'pending', file: null, prompt: 'making…' }),
  generationItem({ id: 'e1', kind: 'video', status: 'error', file: null, moderated: true, prompt: 'nope' }),
]

describe('GenerationGrid', () => {
  it('renders done, pending and error tiles (the live queue)', () => {
    const w = mount(GenerationGrid, { props: { items: ITEMS } })
    expect(w.findAll('.cell')).toHaveLength(4)
    expect(w.find('.pending .spinner').exists()).toBe(true)
    expect(w.find('.errored').text()).toContain('Blocked')
    expect(w.find('.ginprog').text()).toContain('1 generating')
  })

  it('emits open only for finished tiles, and favourite on the star', async () => {
    const w = mount(GenerationGrid, { props: { items: ITEMS } })
    await w.find('.cell.done .thumb').trigger('click')
    expect(w.emitted('open')).toBeTruthy()
    await w.find('.cell.done .fav').trigger('click')
    expect(w.emitted('favourite')).toBeTruthy()
  })

  it('opens the modal from a failed tile but not from a pending one', async () => {
    const w = mount(GenerationGrid, { props: { items: ITEMS } })
    expect(w.find('.cell.pending button').exists()).toBe(false) // pending is a dead div
    await w.find('.cell.error .thumb').trigger('click')
    expect(w.emitted('open')?.[0]).toEqual([expect.objectContaining({ id: 'e1' })])
  })

  it('filters by kind and by favourites-only', async () => {
    const w = mount(GenerationGrid, { props: { items: ITEMS } })
    const seg = w.findAll('.seg button')
    await seg[1]?.trigger('click') // Images
    expect(w.findAll('.cell')).toHaveLength(2) // d1 + p1
    await seg[0]?.trigger('click') // All
    await w.find('.gfav').trigger('click') // favourites only
    expect(w.findAll('.cell')).toHaveLength(1) // only d1 is favourite
    expect(w.find('.cell img').attributes('src')).toBe('/p1')
  })

  it('hides the favourites filter when favFilter is false', () => {
    const w = mount(GenerationGrid, { props: { items: ITEMS, favFilter: false } })
    expect(w.find('.gfav').exists()).toBe(false)
  })
})

describe('GenerationModal teleport', () => {
  // The modal lives inside .studio in StudioView; teleporting to body (not
  // .studio) is what makes it open on first use. Regression guard for f0e306d.
  it('opens when nested inside a .studio root and item is set', async () => {
    const item = ref<GenerationItem | null>(null)
    const Parent = defineComponent({
      setup: () => () =>
        h('div', { class: 'studio' }, [h('div', 'x'), h(GenerationModal, { item: item.value, theme: 'dark' })]),
    })
    const w = mount(Parent, { attachTo: document.body })
    item.value = generationItem({ id: 'a', url: '/u', file: 'a.png', prompt: 'hi' })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    const back = document.body.querySelector('.gm-back')
    expect(back).toBeTruthy()
    expect(back?.classList.contains('studio')).toBe(true)
    w.unmount()
  })

  it('shows the failure reason and a Retry action for an errored item', () => {
    const studio = document.createElement('div')
    studio.className = 'studio'
    document.body.appendChild(studio)
    const item = generationItem({ id: 'e', status: 'error', file: null, error: 'model exploded', prompt: 'x' })
    const w = mount(GenerationModal, { props: { item, canManage: true }, attachTo: document.body })
    expect(document.body.querySelector('.gm-err-msg')?.textContent).toContain('model exploded')
    expect(document.body.querySelector('.gm-media img')).toBeFalsy() // no broken image
    const actions = [...document.body.querySelectorAll('.gm-actions .gm-btn')].map(b => b.textContent.trim())
    expect(actions.some(t => t.includes('Retry'))).toBe(true)
    expect(actions.some(t => t.includes('Download'))).toBe(false) // nothing to download
    w.unmount()
    studio.remove()
  })
})

describe('GenerationGrid selecting', () => {
  const selectable = () => mount(GenerationGrid, { props: { items: ITEMS, selectable: true } })

  it('offers Select only when the page can delete', () => {
    expect(mount(GenerationGrid, { props: { items: ITEMS } }).text()).not.toContain('Select')
    expect(selectable().text()).toContain('Select')
  })

  it('picks finished tiles instead of opening them, then emits the picked ones', async () => {
    const w = selectable()
    await w
      .findAll('button')
      .find(b => b.text() === 'Select')
      ?.trigger('click')
    await w.findAll('.cell.done .thumb')[0]?.trigger('click')
    expect(w.emitted('open')).toBeUndefined()
    expect(w.text()).toContain('1 selected')
    await w
      .findAll('button')
      .find(b => b.text() === 'Delete')
      ?.trigger('click')
    expect(w.emitted('deleteMany')?.[0]).toEqual([[expect.objectContaining({ id: 'd1' })]])
    expect(w.text()).not.toContain('selected') // back to normal
  })

  it('All picks only the tiles that have a file', async () => {
    const w = selectable()
    await w
      .findAll('button')
      .find(b => b.text() === 'Select')
      ?.trigger('click')
    await w
      .findAll('.pillbtn')
      .find(b => b.text() === 'All')
      ?.trigger('click')
    expect(w.text()).toContain('2 selected') // the pending and failed tiles have nothing to delete
  })
})
