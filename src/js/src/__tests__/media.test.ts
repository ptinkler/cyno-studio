import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import MediaPicker from '../components/media/MediaPicker.vue'
import { useMediaFilters, mediaOrigin } from '../composables/useMedia'
import type { LibraryEntry } from '../composables/mediaApi'
import { all, one } from './dom'
import { fakeServer } from './fakeServer'
import { stubIntersectionObserver } from './intersection'
import { libraryEntry } from './models'

const ITEMS = [
  libraryEntry({ id: 'lib:a.png', name: 'a.png', url: '/a', created_at: '2026-10-07' }),
  libraryEntry({
    id: 'chat:c:g.png',
    source: 'generated',
    origin: 'chat',
    name: 'g.png',
    url: '/g',
    conversation_title: 'Fox chat',
    prompt: 'fox in snow',
  }),
]

describe('useMediaFilters', () => {
  it('filters by kind, source, origin and search', () => {
    const { filters, filtered } = useMediaFilters(ref(ITEMS))
    expect(filtered.value).toHaveLength(2)
    filters.kind = 'image'
    expect(filtered.value.map(i => i.id)).toEqual(['lib:a.png', 'chat:c:g.png'])
    filters.source = 'generated'
    expect(filtered.value.map(i => i.id)).toEqual(['chat:c:g.png'])
    filters.kind = 'all'
    filters.source = 'all'
    filters.q = 'fox chat' // matches where it's from
    expect(filtered.value.map(i => i.id)).toEqual(['chat:c:g.png'])
  })

  it('names where an item is from', () => {
    expect(ITEMS.map(mediaOrigin)).toEqual(['Library', 'Fox chat'])
    expect(mediaOrigin({ origin: 'orphan', conversation_title: 'Old chat' })).toBe('Old chat (orphaned)')
    expect(mediaOrigin({ origin: 'orphan' })).toBe('Orphaned')
  })
})

// The picker pages and filters server-side now, so the stub has to answer the
// way /api/media does: apply the query, then slice.
function stubLibrary(rows = ITEMS) {
  const library = [...rows]
  fakeServer(({ url }) => {
    if (url.endsWith('/api/media/upload')) {
      // As the server does: it joins the library, so the next list request has it
      const item = libraryEntry({ id: 'lib:new.png', name: 'new.png', url: '/n' })
      library.unshift(item)
      return item
    }
    const p = new URL(url, 'http://t').searchParams
    const q = (p.get('q') ?? '').toLowerCase()
    const matches = (i: LibraryEntry): boolean =>
      (!p.get('kind') || i.kind === p.get('kind')) &&
      (!p.get('source') || i.source === p.get('source')) &&
      (!p.get('origin') || i.origin === p.get('origin')) &&
      (!q || [i.prompt, i.name, i.conversation_title].some(v => v?.toLowerCase().includes(q)))
    const hits = library.filter(matches)
    const offset = Number(p.get('offset') ?? 0)
    const limit = Number(p.get('limit') ?? 0)
    const items = limit ? hits.slice(offset, offset + limit) : hits.slice(offset)
    return { items, total: hits.length, offset }
  })
}

describe('MediaPicker', () => {
  beforeEach(() => {
    stubLibrary()
  })

  async function open(props: Record<string, unknown> = {}) {
    const w = mount(MediaPicker, { props: { open: false, ...props }, attachTo: document.body })
    await w.setProps({ open: true })
    await flushPromises()
    return w
  }

  it('offers only images and emits the picked ones', async () => {
    const withVideo = [...ITEMS, libraryEntry({ id: 'lib:v.mp4', kind: 'video', name: 'v.mp4', url: '/v' })]
    stubLibrary(withVideo)
    const w = await open()
    const tiles = all('.tile')
    expect(tiles).toHaveLength(2) // asked the server for images only, so the video isn't offered
    tiles[0]?.click()
    tiles[1]?.click()
    await flushPromises()
    one('.actions .btn-primary').click()
    expect(w.emitted('pick')?.[0]).toEqual([
      [expect.objectContaining({ id: 'lib:a.png' }), expect.objectContaining({ id: 'chat:c:g.png' })],
    ])
    expect(w.emitted('close')).toBeTruthy()
    w.unmount()
  })

  it('shows the given kinds and enforces per-kind caps', async () => {
    const withVideo = [...ITEMS, libraryEntry({ id: 'lib:v.mp4', kind: 'video', name: 'v.mp4', url: '/v' })]
    stubLibrary(withVideo)
    const w = await open({ kinds: ['image', 'video'], limits: { image: 1, video: 1 } })
    expect(all('.tile')).toHaveLength(3) // both images + the video are offered
    const tiles = all('.tile')
    tiles[0]?.click() // image 1
    tiles[1]?.click() // image 2 — over the image cap of 1, ignored
    await flushPromises()
    expect(all('.tile.selected')).toHaveLength(1)
    w.unmount()
  })

  it('opens on the source it was given (uploads only)', async () => {
    const w = await open({ source: 'upload' })
    // ITEMS has one upload (lib:a.png) and one generated (chat:c:g.png)
    expect(all('.tile')).toHaveLength(1)
    expect(one(HTMLSelectElement, 'select[aria-label="Source"]').value).toBe('upload')
    w.unmount()
  })

  it('single mode swaps the selection', async () => {
    const w = await open({ multiple: false })
    const tiles = all('.tile')
    tiles[0]?.click()
    tiles[1]?.click()
    await flushPromises()
    expect(all('.tile.selected')).toHaveLength(1)
    w.unmount()
  })

  it('uploads go to the library and come back selected', async () => {
    const w = await open()
    const input = one(HTMLInputElement, 'input[type=file]')
    Object.defineProperty(input, 'files', { value: [new File(['x'], 'n.png', { type: 'image/png' })] })
    input.dispatchEvent(new Event('change'))
    await flushPromises()
    expect(all('.tile.selected')).toHaveLength(1)
    expect(all('.tile')).toHaveLength(3)
    w.unmount()
  })

  it('opens on the origin it was given, widening it for an upload', async () => {
    const w = await open({ origin: 'chat' })
    expect(one(HTMLSelectElement, 'select[aria-label="Where from"]').value).toBe('chat')
    expect(all('.tile')).toHaveLength(1)
    const input = one(HTMLInputElement, 'input[type=file]')
    Object.defineProperty(input, 'files', { value: [new File(['x'], 'n.png', { type: 'image/png' })] })
    input.dispatchEvent(new Event('change'))
    await flushPromises()
    expect(all('.tile')).toHaveLength(3)
    w.unmount()
  })
})

describe('MediaGrid lazy rendering', () => {
  it('renders a batch of thumbnail tiles, then more as the end scrolls into view', async () => {
    const { default: MediaGrid } = await import('../components/media/MediaGrid.vue')
    const observer = stubIntersectionObserver()
    const items = Array.from({ length: 130 }, (_, n) =>
      libraryEntry({ id: `lib:${String(n)}.png`, url: `/full/${String(n)}`, thumb_url: `/thumb/${String(n)}` }),
    )
    const w = mount(MediaGrid, { props: { items, pageSize: 50 } })
    await flushPromises()
    expect(w.findAll('.tile')).toHaveLength(50)
    // Tiles use the small thumbnail and load lazily — never the full file
    const img = w.find('.tile img')
    expect(img.attributes('src')).toBe('/thumb/0')
    expect(img.attributes('loading')).toBe('lazy')
    observer.reveal()
    await flushPromises()
    expect(w.findAll('.tile')).toHaveLength(100)
    observer.reveal()
    await flushPromises()
    expect(w.findAll('.tile')).toHaveLength(130)
    expect(w.find('.sentinel').exists()).toBe(false)
    // New filter results start from the first page again
    await w.setProps({ items: items.slice(0, 80) })
    expect(w.findAll('.tile')).toHaveLength(50)
    observer.restore()
    w.unmount()
  })

  it('asks the caller for more once every loaded tile is shown (server paging)', async () => {
    const { default: MediaGrid } = await import('../components/media/MediaGrid.vue')
    const observer = stubIntersectionObserver()
    // A full server page already loaded, with more rows waiting on the server
    const pages = Array.from({ length: 80 }, (_, i) => libraryEntry({ id: `lib:${String(i)}.png` }))
    const w = mount(MediaGrid, { props: { items: pages.slice(0, 50), pageSize: 50, hasMore: true } })
    await flushPromises()
    expect(w.findAll('.tile')).toHaveLength(50)
    observer.reveal() // reaching the end of the loaded page asks for the next
    await flushPromises()
    expect(w.emitted('more')).toHaveLength(1)
    // The parent appends the next page to the end — the window isn't reset to the top
    await w.setProps({ items: pages, hasMore: false })
    observer.reveal()
    await flushPromises()
    expect(w.findAll('.tile')).toHaveLength(80)
    expect(w.find('.sentinel').exists()).toBe(false) // nothing more to load
    observer.restore()
    w.unmount()
  })
})

describe('MediaGrid thumbnails', () => {
  it('defaults to batches of 20, retries a failed thumbnail once, then shows a placeholder', async () => {
    vi.useFakeTimers()
    const { default: MediaGrid } = await import('../components/media/MediaGrid.vue')
    const observer = stubIntersectionObserver()
    const items = Array.from({ length: 30 }, (_, n) =>
      libraryEntry({ id: `lib:${String(n)}.png`, thumb_url: `/thumb/${String(n)}` }),
    )
    const w = mount(MediaGrid, { props: { items } })
    await flushPromises()
    expect(w.findAll('.tile')).toHaveLength(20)
    const img = w.find('.tile img')
    await img.trigger('error')
    vi.advanceTimersByTime(2000)
    expect(img.element.getAttribute('src')).toBe('/thumb/0?retry=1')
    await img.trigger('error')
    expect(w.findAll('.tile')[0]?.find('.no-thumb').exists()).toBe(true)
    observer.restore()
    vi.useRealTimers()
    w.unmount()
  })
})
