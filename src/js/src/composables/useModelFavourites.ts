import { reactive } from 'vue'
import type { ModelKind } from './chatModelsApi'
import { asRecord, asStrings, readStored, writeStored } from '../utils/storage'

// Favourite model ids per picker kind (text | image | video | audio). Per-browser
// convenience, so localStorage is enough; shared across all pickers.
const STORE_KEY = 'chat.favourites'

type Favourites = Record<ModelKind, string[]>

function load(): Favourites {
  const stored = asRecord(readStored(STORE_KEY))
  return {
    text: asStrings(stored['text']),
    image: asStrings(stored['image']),
    video: asStrings(stored['video']),
    audio: asStrings(stored['audio']),
  }
}

const favourites = reactive<Favourites>(load())

export function useModelFavourites() {
  const isFavourite = (kind: ModelKind, id: string): boolean => favourites[kind].includes(id)

  function toggleFavourite(kind: ModelKind, id: string): void {
    const list = favourites[kind]
    const i = list.indexOf(id)
    if (i === -1) list.push(id)
    else list.splice(i, 1)
    writeStored(STORE_KEY, favourites)
  }

  return { favourites, isFavourite, toggleFavourite }
}
