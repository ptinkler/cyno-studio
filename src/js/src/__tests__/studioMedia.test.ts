import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import StudioMedia from '../components/studio/StudioMedia.vue'
import { confirmDialog } from '../composables/useDialog'
import * as media from '../composables/useMedia'
import { libraryEntry } from './models'

vi.mock('../composables/useMedia', async importOriginal => ({
  ...(await importOriginal<typeof media>()),
  fetchMediaPage: vi.fn(),
  deleteMediaMany: vi.fn(),
  downloadMediaMany: vi.fn(),
}))
vi.mock('../composables/useDialog', () => ({ confirmDialog: vi.fn() }))

const ITEMS = ['a', 'b', 'c', 'd'].map(n => libraryEntry({ id: `lib:${n}.png`, name: `${n}.png` }))

async function mountMedia() {
  vi.mocked(media.fetchMediaPage).mockResolvedValue({ items: ITEMS, total: ITEMS.length })
  const w = mount(StudioMedia)
  await flushPromises()
  return w
}

describe('StudioMedia selecting', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('offers Select all from the start, and shows the bar with the count', async () => {
    const w = await mountMedia()
    expect(w.find('.bulkbar').exists()).toBe(false)
    const selectAll = w.findAll('button').find(b => b.text() === 'Select all')
    await selectAll?.trigger('click')
    expect(w.find('.bulkbar').text()).toContain('4 selected')
  })

  it('shift-click selects the range from the last tick', async () => {
    const w = await mountMedia()
    await w.findAll('.check')[0]?.trigger('click')
    await w.findAll('.check')[2]?.trigger('click', { shiftKey: true })
    expect(w.find('.bulkbar').text()).toContain('3 selected')
  })

  it('deletes the picked items after asking, then reloads', async () => {
    vi.mocked(confirmDialog).mockResolvedValue({ checked: false })
    const w = await mountMedia()
    await w.findAll('.check')[1]?.trigger('click')
    await w.findAll('.check')[3]?.trigger('click')
    await w
      .findAll('.bulkbar button')
      .find(b => b.text() === 'Delete')
      ?.trigger('click')
    await flushPromises()
    expect(media.deleteMediaMany).toHaveBeenCalledWith(['lib:b.png', 'lib:d.png'])
    expect(w.find('.bulkbar').exists()).toBe(false)
  })
})
