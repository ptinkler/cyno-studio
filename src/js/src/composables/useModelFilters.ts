import { reactive } from 'vue'
import type { ModelKind } from './chatModelsApi'
import { PROVIDER_IDS } from './modelTags'
import type { Provider } from './modelTags'
import { asRecord, asStrings, readStored, writeStored } from '../utils/storage'

// Per-kind model-picker filters: which providers and capability tags the list
// is narrowed to. Multi-select; an empty list means "all". A per-browser
// convenience (like favourites / uncensored-only), so localStorage is enough
// and it's shared across every picker of the same kind.
const KEY = 'models.filters'

interface KindFilters {
  providers: Provider[]
  tags: string[]
}

type Filters = Record<ModelKind, KindFilters>

const isProvider = (id: string): id is Provider => (PROVIDER_IDS as readonly string[]).includes(id)

function loadKind(stored: unknown): KindFilters {
  const one = asRecord(stored)
  return { providers: asStrings(one['providers']).filter(isProvider), tags: asStrings(one['tags']) }
}

function load(): Filters {
  const stored = asRecord(readStored(KEY))
  return {
    text: loadKind(stored['text']),
    image: loadKind(stored['image']),
    video: loadKind(stored['video']),
    audio: loadKind(stored['audio']),
  }
}

const filters = reactive<Filters>(load())

const save = (): void => {
  writeStored(KEY, filters)
}

function toggleIn<T>(list: T[], value: T): void {
  const i = list.indexOf(value)
  if (i === -1) list.push(value)
  else list.splice(i, 1)
}

export function useModelFilters() {
  const toggleProvider = (kind: ModelKind, id: Provider): void => {
    toggleIn(filters[kind].providers, id)
    save()
  }
  const toggleTag = (kind: ModelKind, slug: string): void => {
    toggleIn(filters[kind].tags, slug)
    save()
  }
  const clear = (kind: ModelKind): void => {
    filters[kind].providers.splice(0)
    filters[kind].tags.splice(0)
    save()
  }
  const hasActive = (kind: ModelKind): boolean => filters[kind].providers.length > 0 || filters[kind].tags.length > 0

  return { filters, toggleProvider, toggleTag, clear, hasActive }
}
