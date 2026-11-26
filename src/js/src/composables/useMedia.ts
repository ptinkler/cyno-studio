import { reactive, computed } from 'vue'
import type { Ref } from 'vue'
import type { LibraryEntry } from './mediaApi'

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

const hasTitle = (title: string | null | undefined): title is string =>
  title !== null && title !== undefined && title !== ''

/** Where an item came from, for display. */
export function mediaOrigin(item: Pick<LibraryEntry, 'origin' | 'conversation_title'>): string {
  const title = item.conversation_title
  if (item.origin === 'chat') return hasTitle(title) ? title : 'Chat'
  if (item.origin === 'orphan') return hasTitle(title) ? `${title} (orphaned)` : 'Orphaned'
  return 'Library'
}

/** The media filters' state: kind, source and origin ('all' = any), and the search text. */
export interface MediaFilterState {
  kind: string
  source: string
  origin: string
  q: string
}

/**
 * Filters over a list of media items (a ref): kind, source, origin and a
 * text search over prompt / name / where it's from.
 */
export function useMediaFilters(
  items: Ref<readonly LibraryEntry[]>,
  { kind = 'all', origin = 'all' }: { kind?: string; origin?: string } = {},
) {
  const filters = reactive<MediaFilterState>({ kind, source: 'all', origin, q: '' })
  const filtered = computed(() => {
    const q = filters.q.trim().toLowerCase()
    const wanted = (setting: string, actual: string | null): boolean => setting === 'all' || setting === actual
    return items.value.filter(
      i =>
        wanted(filters.kind, i.kind) &&
        wanted(filters.source, i.source) &&
        wanted(filters.origin, i.origin) &&
        (!q || [i.prompt, i.name, mediaOrigin(i)].some(s => s?.toLowerCase().includes(q))),
    )
  })
  return { filters, filtered }
}
