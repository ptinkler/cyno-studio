import type { AudioOpts, ImageOpts, Mode, PickKind, VideoOpts } from './composerPrefs'
import { audioOptsFrom, imageOptsFrom, isMode, videoOptsFrom } from './composerPrefs'
import { asRecord, readStored, writeStored } from '../utils/storage'

// Presets: a named snapshot of the models + media options + mode, loaded in one click. Per browser
// (localStorage), like the rest of the composer prefs.

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

export function readPresets(): StoredPreset[] {
  const stored = readStored(PRESETS_KEY)
  return Array.isArray(stored) ? stored.flatMap(item => presetFrom(item) ?? []) : []
}

export function storePresets(presets: readonly StoredPreset[]): void {
  writeStored(PRESETS_KEY, presets)
}

const bySortedKeys = (_key: string, value: unknown): unknown =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => (a < b ? -1 : 1)))
    : value

/** A setup's identity, independent of key order: equal keys mean the same models, mode and options. */
export const snapshotKey = (s: Snapshot): string =>
  JSON.stringify([s.mode, s.models, s.imageOpts, s.videoOpts, s.audioOpts], bySortedKeys)
