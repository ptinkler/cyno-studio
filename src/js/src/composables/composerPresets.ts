import type { AudioOpts, ImageOpts, Mode, PickKind, VideoOpts } from './composerPrefs'
import { audioOptsFrom, imageOptsFrom, isMode, videoOptsFrom } from './composerPrefs'
import { fetchSettings, setPresets } from './chatSettingsApi'
import { asRecord, readStored, writeStored } from '../utils/storage'

// Presets: a named snapshot of the models + media options + mode, loaded in one click. Saved on the server with
// the user's settings so they follow the user to any browser; localStorage caches them for the first paint (and
// held them before they were saved on the server).

export interface Snapshot {
  mode: Mode
  models: Record<PickKind, string>
  imageOpts: ImageOpts
  videoOpts: VideoOpts
  audioOpts: AudioOpts
}

export interface StoredPreset extends Snapshot {
  id: string
  name: string
}

const PRESETS_KEY = 'studio.presets'

function modelsFrom(raw: unknown): Record<PickKind, string> {
  const stored = asRecord(raw)
  const pick = (kind: PickKind): string => {
    const id = stored[kind]
    return typeof id === 'string' ? id : ''
  }
  return { text: pick('text'), image: pick('image'), video: pick('video'), audio: pick('audio') }
}

/** A stored preset as a complete one, or null when it has no id, name or mode to go by. */
export function presetFrom(raw: unknown): StoredPreset | null {
  const stored = asRecord(raw)
  const { id, name, mode } = stored
  if (typeof id !== 'string' || typeof name !== 'string' || !isMode(mode)) return null
  return {
    id,
    name,
    mode,
    models: modelsFrom(stored['models']),
    imageOpts: imageOptsFrom(stored['imageOpts']),
    videoOpts: videoOptsFrom(stored['videoOpts']),
    audioOpts: audioOptsFrom(stored['audioOpts']),
  }
}

const presetsFrom = (raw: unknown): StoredPreset[] =>
  Array.isArray(raw) ? raw.flatMap(item => presetFrom(item) ?? []) : []

/** This browser's cached presets. */
export const readPresets = (): StoredPreset[] => presetsFrom(readStored(PRESETS_KEY))

/** Cache the presets here and save them on the server (a failed save keeps the cached copy). */
export function storePresets(presets: readonly StoredPreset[]): void {
  writeStored(PRESETS_KEY, presets)
  setPresets(presets.map(p => ({ ...p }))).catch(() => undefined)
}

/**
 * The server's presets, or null to keep this browser's: when it has never saved any, the cached ones are uploaded
 * (a one-off move from browser-only presets); when it can't be reached, the cache stands.
 */
export async function serverPresets(cached: readonly StoredPreset[]): Promise<StoredPreset[] | null> {
  try {
    const { presets } = await fetchSettings()
    if (Array.isArray(presets)) {
      const list = presetsFrom(presets)
      writeStored(PRESETS_KEY, list)
      return list
    }
    if (cached.length) storePresets(cached)
  } catch {
    /* signed out or offline */
  }
  return null
}

const bySortedKeys = (_key: string, value: unknown): unknown =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => (a < b ? -1 : 1)))
    : value

/** A setup's identity, independent of key order: equal keys mean the same models, mode and options. */
export const snapshotKey = (s: Snapshot): string =>
  JSON.stringify([s.mode, s.models, s.imageOpts, s.videoOpts, s.audioOpts], bySortedKeys)
