import { asRecord, readStored } from '../utils/storage'

// What the chat composer remembers in this browser, and the shapes its option objects have.

export type Mode = 'auto' | 'text' | 'image' | 'video' | 'audio'

export const MODES: readonly { id: Mode; label: string; icon: string }[] = [
  { id: 'auto', label: 'Auto', icon: '✦' },
  { id: 'text', label: 'Chat', icon: '💬' },
  { id: 'image', label: 'Image', icon: '🖼' },
  { id: 'video', label: 'Video', icon: '🎬' },
  { id: 'audio', label: 'Audio', icon: '🔊' },
]

export const isMode = (value: unknown): value is Mode => MODES.some(m => m.id === value)

/** A slider stop: a count, or null for "all". */
export type Step = number | null

// Memory slider stops: how many past messages the chat model gets (null = all)
export const MEMORY_STEPS: readonly Step[] = [2, 4, 6, 10, 14, 20, 30, 40, 60, 80, 100, null]
export const DEFAULT_MEMORY = 20
// Image slider stops: how many recent chat images go with each request (null = all)
export const IMAGE_STEPS: readonly Step[] = [0, 1, 2, 3, 4, 6, 8, 10, 12, 16, 20, null]
export const DEFAULT_IMAGES = 6 // mirrors DEFAULT_IMAGE_LIMIT in web/chat/constants.py

// --- The option objects ----------------------------------------------------------------------------------------
// Each is described once, by field and kind of value; its type and its reader of stored (untrusted) JSON follow.

interface Kinds {
  text: string
  flag: boolean
  amount: number | null
  /** A number once picked, '' while left on auto. */
  length: string | number
}

type Shape = Record<string, keyof Kinds>
type ValuesOf<S extends Shape> = { -readonly [K in keyof S]: Kinds[S[K]] }

const CHECKS: { [K in keyof Kinds]: (value: unknown) => boolean } = {
  text: value => typeof value === 'string',
  flag: value => typeof value === 'boolean',
  amount: value => value === null || typeof value === 'number',
  length: value => typeof value === 'string' || typeof value === 'number',
}

/** The fields of `raw` that have the kind of value `shape` says; anything else is left out. */
function readShape<S extends Shape>(shape: S, raw: unknown): Partial<ValuesOf<S>> {
  const source = asRecord(raw)
  const out: Record<string, unknown> = {}
  for (const [field, kind] of Object.entries(shape)) {
    if (CHECKS[kind](source[field])) out[field] = source[field]
  }
  // Every value in `out` passed the check for its field's kind
  return out as Partial<ValuesOf<S>>
}

// '' = let the chat model choose (Auto), else the media model's default
const IMAGE_SHAPE = { aspect_ratio: 'text', resolution: 'text' } as const
const VIDEO_SHAPE = { aspect_ratio: 'text', resolution: 'text', duration: 'length', generate_audio: 'flag' } as const
const AUDIO_SHAPE = {
  voice: 'text',
  speed: 'amount',
  volume: 'amount',
  pitch: 'amount',
  instrumental: 'flag',
  vocal_gender: 'text',
  style: 'text',
  title: 'text',
  negative_prompt: 'text',
  duration: 'length',
} as const

export type ImageOpts = ValuesOf<typeof IMAGE_SHAPE>
export type VideoOpts = ValuesOf<typeof VIDEO_SHAPE>
export type AudioOpts = ValuesOf<typeof AUDIO_SHAPE>

export const defaultImageOpts = (): ImageOpts => ({ aspect_ratio: '', resolution: '' })
export const defaultVideoOpts = (): VideoOpts => ({
  aspect_ratio: '',
  resolution: '',
  duration: '',
  generate_audio: true,
})
export const defaultAudioOpts = (): AudioOpts => ({
  voice: '',
  speed: null,
  volume: null,
  pitch: null,
  instrumental: false,
  vocal_gender: '',
  style: '',
  title: '',
  negative_prompt: '',
  duration: '',
})

// Stored options laid over the defaults, so a missing or odd field never leaves a hole
export const imageOptsFrom = (raw: unknown): ImageOpts => ({ ...defaultImageOpts(), ...readShape(IMAGE_SHAPE, raw) })
export const videoOptsFrom = (raw: unknown): VideoOpts => ({ ...defaultVideoOpts(), ...readShape(VIDEO_SHAPE, raw) })
export const audioOptsFrom = (raw: unknown): AudioOpts => ({ ...defaultAudioOpts(), ...readShape(AUDIO_SHAPE, raw) })

// --- The remembered picks --------------------------------------------------------------------------------------

export type PickKind = 'text' | 'image' | 'video' | 'audio'

export interface Prefs {
  /** The model last picked per kind; a kind is absent until one was picked ('' is a deliberate "None"). */
  models: Partial<Record<PickKind, string>>
  mode: Mode
  /** The memory / image slider values; absent until set (null is "all"). */
  memory?: Step
  images?: Step
  imageOpts: ImageOpts
  videoOpts: VideoOpts
  audioOpts: AudioOpts
}

export const PREFS_KEY = 'chat.prefs'

const hasStep = (value: unknown): value is Step => value === null || typeof value === 'number'

export function loadPrefs(): Prefs {
  const stored = asRecord(readStored(PREFS_KEY))
  const models: Prefs['models'] = {}
  for (const kind of ['text', 'image', 'video', 'audio'] as const) {
    const pick = stored[kind]
    if (typeof pick === 'string') models[kind] = pick
  }
  const prefs: Prefs = {
    models,
    mode: isMode(stored['mode']) ? stored['mode'] : 'auto',
    imageOpts: imageOptsFrom(stored['imageOpts']),
    videoOpts: videoOptsFrom(stored['videoOpts']),
    audioOpts: audioOptsFrom(stored['audioOpts']),
  }
  const { memory, images } = stored
  if ('memory' in stored && hasStep(memory)) prefs.memory = memory
  if ('images' in stored && hasStep(images)) prefs.images = images
  return prefs
}

// --- Sliders ---------------------------------------------------------------------------------------------------

/** The slider stop for a remembered value, else for the default. */
export function stepIndex(steps: readonly Step[], remembered: Step | undefined, fallback: number): number {
  const i = steps.indexOf(remembered === undefined ? fallback : remembered)
  return i === -1 ? steps.indexOf(fallback) : i
}

/** The stop for a saved value (null = "All"), or undefined when it isn't one of them. */
export function stepFor(steps: readonly Step[], value: Step | undefined): number | undefined {
  const i = steps.indexOf(value ?? null)
  return i === -1 ? undefined : i
}
