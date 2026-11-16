import { shortModel } from './format'

type MediaKind = 'image' | 'video' | 'audio'

interface MediaOptions {
  aspect_ratio?: string | null
  resolution?: string | null
}

/** A saved Generate-page preset: the mode it opens in, a model per kind and the options for images and video. */
export interface Preset {
  mode?: string
  models?: Partial<Record<MediaKind, string | null>>
  imageOpts?: MediaOptions
  videoOpts?: MediaOptions
}

const MEDIA_KINDS: readonly string[] = ['image', 'video', 'audio']

const capitalised = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1)

const kindOf = (preset: Preset): MediaKind =>
  preset.mode !== undefined && MEDIA_KINDS.includes(preset.mode) ? (preset.mode as MediaKind) : 'video'

const optionsOf = (preset: Preset, kind: MediaKind): MediaOptions =>
  ({ image: preset.imageOpts, video: preset.videoOpts, audio: undefined })[kind] ?? {}

// One line for a card: "Video · seedance25 · 16:9 · 720p"
export function presetSummary(preset: Preset): string {
  const kind = kindOf(preset)
  const options = optionsOf(preset, kind)
  return [capitalised(kind), shortModel(preset.models?.[kind]) || 'no model', options.aspect_ratio, options.resolution]
    .filter(Boolean)
    .join(' · ')
}
