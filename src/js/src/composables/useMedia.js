import { reactive, computed } from 'vue'

// The media library (see web/media/): the API wrappers are typed in mediaApi.ts and re-exported here.
export {
  fetchMedia,
  fetchMediaPage,
  uploadMedia,
  deleteMediaMany,
  downloadMediaMany,
  deleteMedia,
  fetchBlockedCounts,
  clearBlocked,
  importMediaToChat,
  importMediaToCharacter,
} from './mediaApi'

/** Where an item came from, for display. */
export function mediaOrigin(item) {
  if (item.origin === 'chat') return item.conversation_title || 'Chat'
  if (item.origin === 'orphan') return item.conversation_title ? `${item.conversation_title} (orphaned)` : 'Orphaned'
  return 'Library'
}

/**
 * Filters over a list of media items (a ref): kind, source, origin and a
 * text search over prompt / name / where it's from.
 */
export function useMediaFilters(items, { kind = 'all', origin = 'all' } = {}) {
  const filters = reactive({ kind, source: 'all', origin, q: '' })
  const filtered = computed(() => {
    const q = filters.q.trim().toLowerCase()
    return items.value.filter(
      i =>
        (filters.kind === 'all' || i.kind === filters.kind) &&
        (filters.source === 'all' || i.source === filters.source) &&
        (filters.origin === 'all' || i.origin === filters.origin) &&
        (!q || [i.prompt, i.name, mediaOrigin(i)].some(s => s?.toLowerCase().includes(q))),
    )
  })
  return { filters, filtered }
}
