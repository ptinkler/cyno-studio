import { computed, ref } from 'vue'
import type { components } from '../api/schema'
import { fetchSettings, updateSettings, fetchSpaces, updateSpace } from './useChat'
import { ALL_CHATS } from '../utils/defaults'

// Shared, app-wide state for the two "settings buckets": the global defaults
// (every chat) and each space's own defaults (stacked on top for chats in that
// space). They apply live — a chat uses its defaults plus what's attached to
// it — so `inherited` is what the chat in context gets from them. A module-level singleton so the chat view and
// the characters page read/toggle the same state.

type Schemas = components['schemas']
type GlobalSettings = Schemas['ChatSettings']
type Space = Schemas['Space']

/** What a bucket can hold defaults for. */
export type DefaultKind = 'character' | 'instruction' | 'instruction_group'
type DefaultKey = `default_${DefaultKind}_ids`

export const DEFAULT_KINDS: readonly DefaultKind[] = ['character', 'instruction', 'instruction_group']

/** Where a default comes from: the bucket's name ("All chats" or a space). */
export interface InheritedDefault {
  id: number
  from: string
}

/** Where an item is a default. */
export interface Membership {
  global: boolean
  spaceIds: number[]
}

const EMPTY = (): GlobalSettings => ({
  default_character_ids: [],
  default_instruction_ids: [],
  default_instruction_group_ids: [],
  title_model: null,
})

const globalSettings = ref<GlobalSettings>(EMPTY())
const spaces = ref<Space[]>([])
const currentSpaceId = ref<number | null>(null) // the space of the chat currently in context (set by ChatView)
let loaded = false // whether the buckets have been fetched at least once

const key = (kind: DefaultKind): DefaultKey => `default_${kind}_ids`

// Just the three id-lists of a bucket (drops name/timestamps)
const bucketLists = (b: Pick<GlobalSettings, DefaultKey>): Pick<GlobalSettings, DefaultKey> => ({
  default_character_ids: b.default_character_ids,
  default_instruction_ids: b.default_instruction_ids,
  default_instruction_group_ids: b.default_instruction_group_ids,
})

const toggled = (ids: readonly number[], id: number): number[] =>
  ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id]

export function useChatDefaults() {
  const currentSpace = computed(() => spaces.value.find(s => s.id === currentSpaceId.value) ?? null)
  const spaceById = (id: number): Space | null => spaces.value.find(s => s.id === id) ?? null

  // What the chat in context gets from its defaults, per kind: [{ id, from }],
  // `from` naming the bucket ("All chats" wins when an id is in both)
  const inherited = computed(() => {
    const out = {} as Record<DefaultKind, InheritedDefault[]>
    for (const kind of DEFAULT_KINDS) {
      const seen = new Map<number, string>()
      for (const id of globalSettings.value[key(kind)]) seen.set(id, ALL_CHATS)
      const space = currentSpace.value
      for (const id of space?.[key(kind)] ?? []) if (!seen.has(id)) seen.set(id, space?.name ?? '')
      out[kind] = [...seen].map(([id, from]) => ({ id, from }))
    }
    return out
  })

  async function loadDefaults(): Promise<void> {
    try {
      globalSettings.value = { ...EMPTY(), ...(await fetchSettings()) }
    } catch {
      /* 401 handled elsewhere */
    }
    try {
      spaces.value = (await fetchSpaces()).spaces
    } catch {
      /* 401 handled elsewhere */
    }
    loaded = true
  }

  // Load once — for views (character editor, media view) that show the toggles
  // without otherwise needing the buckets, so membership shows correctly.
  async function ensureLoaded(): Promise<void> {
    if (!loaded) await loadDefaults()
  }

  const inGlobal = (kind: DefaultKind, id: number): boolean => globalSettings.value[key(kind)].includes(id)
  const inSpace = (kind: DefaultKind, id: number): boolean => !!currentSpace.value?.[key(kind)].includes(id)

  // Toggles re-read the current bucket from the server before writing, so a
  // stale local copy can never clobber it (the editor may be open in a view
  // that hadn't loaded the buckets).
  async function toggleGlobal(kind: DefaultKind, id: number): Promise<void> {
    const latest = { ...EMPTY(), ...(await fetchSettings()) }
    globalSettings.value = await updateSettings({ ...bucketLists(latest), [key(kind)]: toggled(latest[key(kind)], id) })
  }

  async function toggleSpace(kind: DefaultKind, id: number): Promise<void> {
    const spaceId = currentSpaceId.value
    if (spaceId === null) return
    const fresh = (await fetchSpaces()).spaces
    spaces.value = fresh
    const space = fresh.find(s => s.id === spaceId)
    if (!space) return
    const updated = await updateSpace(space.id, {
      name: space.name,
      ...bucketLists(space),
      [key(kind)]: toggled(space[key(kind)], id),
    })
    const i = spaces.value.findIndex(s => s.id === space.id)
    if (i !== -1) spaces.value.splice(i, 1, updated)
  }

  // Where an item is a default: { global, spaceIds }
  function membership(kind: DefaultKind, id: number): Membership {
    return {
      global: globalSettings.value[key(kind)].includes(id),
      spaceIds: spaces.value.filter(s => s[key(kind)].includes(id)).map(s => s.id),
    }
  }

  // Make an item a default exactly where `want` says ({ global, spaceIds }),
  // writing only the buckets that change — each re-read first, as above
  async function setMembership(kind: DefaultKind, id: number, want: Membership): Promise<void> {
    const latest = { ...EMPTY(), ...(await fetchSettings()) }
    if (latest[key(kind)].includes(id) !== want.global) {
      const ids = toggled(latest[key(kind)], id)
      globalSettings.value = await updateSettings({ ...bucketLists(latest), [key(kind)]: ids })
    }
    const fresh = (await fetchSpaces()).spaces
    for (const space of fresh) {
      if (space[key(kind)].includes(id) === want.spaceIds.includes(space.id)) continue
      const updated = await updateSpace(space.id, {
        name: space.name,
        ...bucketLists(space),
        [key(kind)]: toggled(space[key(kind)], id),
      })
      fresh.splice(fresh.indexOf(space), 1, updated)
    }
    spaces.value = [...fresh]
  }

  // Global ∪ current-space default ids for a kind (de-duped), for seeding
  function defaultIds(kind: DefaultKind): number[] {
    const ids = [...globalSettings.value[key(kind)], ...(currentSpace.value?.[key(kind)] ?? [])]
    return [...new Set(ids)]
  }

  function setCurrentSpace(id: number | null | undefined): void {
    currentSpaceId.value = id ?? null
  }

  return {
    globalSettings,
    spaces,
    currentSpace,
    currentSpaceId,
    spaceById,
    inherited,
    loadDefaults,
    ensureLoaded,
    inGlobal,
    inSpace,
    toggleGlobal,
    toggleSpace,
    membership,
    setMembership,
    defaultIds,
    setCurrentSpace,
  }
}
