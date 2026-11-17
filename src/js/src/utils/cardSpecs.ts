import { chatMediaUrl } from '../composables/chatFilesApi'
import { characterImageUrl } from '../composables/charactersApi'
import { asRecord, asStrings } from './storage'

// What a generated card was made with. The server keeps these in the card's open-JSON `params` (they differ
// by model), so each field is read for the type it should have and anything else is left out.

export interface CardParams {
  duration: number | null
  resolution: string
  aspect_ratio: string
  generate_audio: boolean | null
  character_names: string[]
  /** Reference images: chat files or character images ("char:<id>/<file>"). */
  refs: string[]
  /** How many of the refs the model really took (null = all). */
  refs_used: number | null
  first_frame: string
  last_frame: string
  source_video: string
  /** The model was given the conversation, not just the prompt. */
  context: boolean
  /** Set when the file was hosted somewhere other than the first choice. */
  upload_notice: string
}

const text = (value: unknown): string => (typeof value === 'string' ? value : '')
const number = (value: unknown): number | null => (typeof value === 'number' ? value : null)

export function cardParams(raw: Record<string, unknown> | null | undefined): CardParams {
  const p = asRecord(raw)
  return {
    duration: number(p['duration']),
    resolution: text(p['resolution']),
    aspect_ratio: text(p['aspect_ratio']),
    generate_audio: typeof p['generate_audio'] === 'boolean' ? p['generate_audio'] : null,
    character_names: asStrings(p['character_names']),
    refs: asStrings(p['refs']),
    refs_used: number(p['refs_used']),
    first_frame: text(p['first_frame']),
    last_frame: text(p['last_frame']),
    source_video: text(p['source_video']),
    context: !!p['context'],
    upload_notice: text(p['upload_notice']),
  }
}

// What a video was made from, besides its prompt
function videoSource(p: CardParams): string[] {
  const frames = p.last_frame ? 'first+last frame' : p.first_frame && !p.refs.length ? 'from image' : ''
  return [p.source_video ? 'from video' : '', frames]
}

function audioSpec(p: CardParams): string {
  if (p.generate_audio === null) return ''
  return p.generate_audio ? 'audio' : 'no audio'
}

/**
 * The settings a generated item was made with, for display. For Pollo these are what was actually sent
 * (defaults included); for OpenRouter only what we asked for: the provider fills in the rest without saying.
 */
export function cardSpecs(kind: string | null | undefined, p: CardParams): string[] {
  const isVideo = kind === 'video'
  return [
    ...(isVideo ? videoSource(p) : []),
    isVideo && p.duration ? `${String(p.duration)}s` : '',
    p.resolution,
    p.aspect_ratio,
    isVideo ? audioSpec(p) : '',
    p.character_names.length ? `👤 ${p.character_names.join(', ')}` : '',
  ].filter(Boolean)
}

/**
 * "4 refs", or "2 of 4 refs" when the model took fewer than were picked (Venice edit models cap the count; the
 * first ones win). `missing` of them no longer exist (a character's images that didn't travel with an export)
 * and aren't counted.
 */
export function refsLabel(p: CardParams, missing = 0): string {
  const n = p.refs.length - missing
  const used = p.refs_used
  if (n <= 0) return 'refs unavailable'
  return used !== null && used < n ? `${String(used)} of ${String(n)} refs` : `${String(n)} ref${n === 1 ? '' : 's'}`
}

export function refsTitle(p: CardParams, missing = 0): string {
  const used = p.refs_used
  const gone = missing ? ` (${String(missing)} no longer available)` : ''
  return used !== null && used < p.refs.length - missing
    ? `The model takes ${String(used)} image${used === 1 ? '' : 's'}, so only the first ${String(used)} of these were sent${gone}:`
    : `Based on these images${gone}:`
}

/** Where a reference image is served from: a character's, or a file in the chat. */
export function refUrl(convId: string, ref: string): string {
  const match = /^char:(\d+)\/(.+)$/.exec(ref)
  const [, id, file] = match ?? []
  return id !== undefined && file !== undefined ? characterImageUrl(Number(id), file) : chatMediaUrl(convId, ref)
}

const refItemImages = (items: unknown): string[] =>
  Array.isArray(items)
    ? items.flatMap(item => {
        const r = asRecord(item)
        const file = r['file']
        return r['type'] === 'image' && typeof file === 'string' ? [file] : []
      })
    : []

/**
 * The chat's pictures a card was made from, in the order they were given: the frames, the references, the named
 * images. A character's images are left out (they follow the card; the picker only handles chat files).
 */
export function cardRefFiles(raw: Record<string, unknown> | null | undefined): string[] {
  const p = cardParams(raw)
  const named = refItemImages(asRecord(raw)['ref_items'])
  const files = [p.first_frame, p.last_frame, ...p.refs, ...named].filter(f => f && !f.startsWith('char:'))
  return [...new Set(files)]
}
