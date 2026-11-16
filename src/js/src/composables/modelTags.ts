// Capability tags (mirrors web/providers/model_tags.py TAGS, same order): the
// labels, and one colour per tag. The model picker's row badges and its filter
// menu both read these, so a tag looks the same everywhere.

export const TAG_LABELS: Readonly<Record<string, string>> = {
  img2vid: 'Image→Video',
  text2vid: 'Text→Video',
  ref2vid: 'References→Video',
  video_refs: 'Video refs (recast)',
  first_last: 'First+Last frame',
  video_edit: 'Video edit',
  video_extend: 'Video extend',
  motion: 'Motion / recast',
  lipsync: 'Lip sync',
  upscale: 'Upscale',
  bg_remove: 'Background remove',
  subtitle_remove: 'Subtitle remove',
  face_swap: 'Face swap',
  audio: 'Makes audio',
  tts: 'Text→Speech',
  music: 'Music',
  text2img: 'Text→Image',
  image_edit: 'Image edit',
  tools: 'Image tools',
  vision: 'Vision',
  functions: 'Tools / functions',
}

/** A tag's label, or the slug itself for one this build doesn't know. */
export const tagLabel = (slug: string): string => TAG_LABELS[slug] ?? slug

// Hues step by the golden angle, so every tag lands well away from the ones
// before it; lightness alternates to pull neighbours further apart.
const GOLDEN_ANGLE = 137.508
const HUE_STEPS = 360
const SLUGS = Object.keys(TAG_LABELS)

export function tagColor(slug: string): string {
  const i = Math.max(0, SLUGS.indexOf(slug))
  return `hsl(${String(Math.round((i * GOLDEN_ANGLE) % HUE_STEPS))} 72% ${i % 2 ? '72' : '62'}%)`
}

export type Provider = 'pollo' | 'venice' | 'openrouter'

// One pastel per provider, defined once in style.css (--p-*) so the picker
// tags, the filter chips and the usage cards all agree.
export const PROVIDER_COLOR: Readonly<Record<Provider, string>> = {
  pollo: 'var(--p-pollo)',
  venice: 'var(--p-venice)',
  openrouter: 'var(--p-openrouter)',
}

// Providers: Pollo ("pollo/…", billed in Pollo credits), Venice ("venice/…",
// billed to the Venice account) and OpenRouter (everything else).
export const ALL_PROVIDERS: Readonly<Record<Provider, { label: string; title: string }>> = {
  pollo: { label: 'Pollo', title: 'Runs on your Pollo account (billed in Pollo credits)' },
  venice: { label: 'Venice', title: 'Runs on your Venice account (billed in Venice credit)' },
  openrouter: { label: 'OpenRouter', title: 'Runs on OpenRouter (billed in OpenRouter credits)' },
}

export const providerOf = (id: string | null | undefined): Provider => {
  const prefix = (id ?? '').split('/')[0]
  return prefix === 'pollo' || prefix === 'venice' ? prefix : 'openrouter'
}
