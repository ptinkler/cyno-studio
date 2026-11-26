import type { components } from '../api/schema'
import { api, apiDownload } from './useApi'

// The media library (see web/media/): every upload and creation — library uploads and chats' uploads and
// creations. Using an item somewhere copies it there (importMediaTo…).
type Schemas = components['schemas']

export type LibraryEntry = Schemas['LibraryEntry']
/** The list's filters; `null` / `undefined` / '' / 'all' leave a filter off. */
export interface MediaFilters {
  kind?: string | null | undefined
  source?: string | null | undefined
  origin?: string | null | undefined
  q?: string | null | undefined
}

const enc = encodeURIComponent

export async function fetchMedia() {
  const { items } = await api.get('/api/media')
  return items
}

/**
 * A page of the library with its filters applied server-side (for the Media page's infinite scroll).
 * Returns { items, total } — total is how many match before paging. `all`/'' filter values and null
 * params are left off.
 */
export async function fetchMediaPage({
  offset = 0,
  limit = 0,
  ...filters
}: { offset?: number; limit?: number } & MediaFilters = {}) {
  const params = { offset, limit, ...filters }
  const qs = new URLSearchParams(
    Object.entries(params)
      .filter(([, value]) => value != null && value !== '' && value !== 'all')
      .map(([key, value]) => [key, String(value)]),
  ).toString()
  const { items, total } = await (qs ? api.get(`/api/media?${qs}`) : api.get('/api/media'))
  return { items, total }
}

export const uploadMedia = (file: Blob) => api.upload('/api/media/upload', file)
export const deleteMediaMany = (ids: readonly string[]) => api.post('/api/media/bulk-delete', { ids: [...ids] })
export const downloadMediaMany = (ids: readonly string[]) =>
  apiDownload('/api/media/bulk-download', { ids: [...ids] }, 'media.zip')
// Identical files (the same picture in the library, a chat or a character) share one copy on disk
export const mergeDuplicateFiles = () => api.post('/api/media/merge-duplicates')
export const deleteMedia = (mediaId: string) => api.delete(`/api/media/${enc(mediaId)}`)

/** Chat generations a content filter blocked: { moderated, black } counts, and clearing them all. */
export const fetchBlockedCounts = () => api.get('/api/media/blocked')
export const clearBlocked = () => api.post('/api/media/blocked/clear')

/** Copy an image or video into a chat; answers with the attachment's file name there. */
export async function importMediaToChat(mediaId: string, conversationId: string): Promise<Schemas['ImportedFile']> {
  const result = await api.post('/api/media/import', {
    media_id: mediaId,
    target: 'chat',
    conversation_id: conversationId,
  })
  // The server answers a chat import with the file, a character import with the character
  if (!('file' in result)) throw new Error('Unexpected answer to a chat import')
  return result
}

/** Copy an image into a character; answers with the updated character. */
export async function importMediaToCharacter(mediaId: string, characterId: number): Promise<Schemas['CharacterInfo']> {
  const result = await api.post('/api/media/import', {
    media_id: mediaId,
    target: 'character',
    character_id: characterId,
  })
  if (!('images' in result)) throw new Error('Unexpected answer to a character import')
  return result
}
