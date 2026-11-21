import { reactive } from 'vue'
import type { ModelKind } from './chatModelsApi'
import { fetchSettings, setModelFavourites } from './chatSettingsApi'
import { asRecord, asStrings, readStored, writeStored } from '../utils/storage'

// Favourite model ids per picker kind (text | image | video | audio), shared across all pickers. Saved on the
// server with the user's settings so they follow the user to any browser; localStorage only caches them for the
// first paint (and held them before they were saved on the server).
const STORE_KEY = 'chat.favourites'
const KINDS: readonly ModelKind[] = ['text', 'image', 'video', 'audio']

type Favourites = Record<ModelKind, string[]>

function parse(raw: unknown): Favourites {
  const stored = asRecord(raw)
  return {
    text: asStrings(stored['text']),
    image: asStrings(stored['image']),
    video: asStrings(stored['video']),
    audio: asStrings(stored['audio']),
  }
}

const isEmpty = (f: Favourites): boolean => KINDS.every(kind => f[kind].length === 0)

const favourites = reactive<Favourites>(parse(readStored(STORE_KEY)))
let synced: Promise<void> | null = null

function apply(next: Favourites): void {
  for (const kind of KINDS) favourites[kind].splice(0, Infinity, ...next[kind])
  writeStored(STORE_KEY, favourites)
}

const save = (): Promise<unknown> => setModelFavourites({ ...favourites })

// Load the server's list once. A user who never saved one there keeps (and uploads) what this browser had.
async function sync(): Promise<void> {
  try {
    const server = (await fetchSettings()).model_favourites
    // {} = never saved (a saved list always has every kind, even when all are empty)
    if (Object.keys(server).length) apply(parse(server))
    else if (!isEmpty(favourites)) await save()
  } catch {
    /* signed out or offline: the cached list stands */
  }
}

export function useModelFavourites() {
  synced ??= sync()

  const isFavourite = (kind: ModelKind, id: string): boolean => favourites[kind].includes(id)

  function toggleFavourite(kind: ModelKind, id: string): void {
    const list = favourites[kind]
    const i = list.indexOf(id)
    if (i === -1) list.push(id)
    else list.splice(i, 1)
    writeStored(STORE_KEY, favourites)
    void synced?.then(save).catch(() => undefined)
  }

  return { favourites, isFavourite, toggleFavourite }
}
