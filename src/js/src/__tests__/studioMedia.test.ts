import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import StudioMedia from '../components/studio/StudioMedia.vue'
import { confirmDialog } from '../composables/useDialog'
import * as media from '../composables/useMedia'
import { showToastKey } from '../injection'
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
    expect(w.find('.selbar').exists()).toBe(false)
    const selectAll = w.findAll('button').find(b => b.text() === 'Select all')
    await selectAll?.trigger('click')
    expect(w.find('.selbar').text()).toContain('4 selected')
  })

  it('shift-click selects the range from the last tick', async () => {
    const w = await mountMedia()
    await w.findAll('.check')[0]?.trigger('click')
    await w.findAll('.check')[2]?.trigger('click', { shiftKey: true })
    expect(w.find('.selbar').text()).toContain('3 selected')
  })

  it('deletes the picked items after asking, then reloads', async () => {
    vi.mocked(confirmDialog).mockResolvedValue({ checked: false })
    vi.mocked(media.deleteMediaMany).mockResolvedValue({ deleted: ['lib:b.png', 'lib:d.png'], failed: [], kept: 0 })
    const w = await mountMedia()
    await w.findAll('.check')[1]?.trigger('click')
    await w.findAll('.check')[3]?.trigger('click')
    await w.find('.selbar button[aria-label="Delete"]').trigger('click')
    await flushPromises()
    expect(media.deleteMediaMany).toHaveBeenCalledWith(['lib:b.png', 'lib:d.png'])
    expect(w.find('.selbar').exists()).toBe(false)
  })

  it("says so when a deleted picture's file stayed because another card uses it as a reference", async () => {
    vi.mocked(confirmDialog).mockResolvedValue({ checked: false })
    vi.mocked(media.deleteMediaMany).mockResolvedValue({ deleted: ['lib:b.png'], failed: [], kept: 1 })
    const toast = vi.fn()
    const w = mount(StudioMedia, { global: { provide: { [showToastKey as symbol]: toast } } })
    vi.mocked(media.fetchMediaPage).mockResolvedValue({ items: ITEMS, total: ITEMS.length })
    await flushPromises()
    await w.findAll('.check')[1]?.trigger('click')
    await w.find('.selbar button[aria-label="Delete"]').trigger('click')
    await flushPromises()
    expect(toast).toHaveBeenCalledWith(expect.stringContaining('1 file was kept'))
  })

  it('filters from the dropdowns, asking the server again', async () => {
    const w = await mountMedia()
    await w.findAll('select')[0]?.setValue('video')
    await w.findAll('select')[2]?.setValue('orphan')
    const last = vi.mocked(media.fetchMediaPage).mock.calls.at(-1)?.[0]
    expect(last).toMatchObject({ kind: 'video', origin: 'orphan' })
  })
})
