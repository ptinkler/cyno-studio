import { tagColor, tagLabel } from '../composables/modelTags'
import { isImageModel, isTextModel, isVideoModel } from '../composables/chatModelsApi'
import type { ImageModel, Model, ModelKind, TextModel, VideoModel } from '../composables/chatModelsApi'
import { chatImageModelTakesCharacters } from '../composables/useCharacters'

// The little labels beside a model in the picker: warnings first, then what it can do and costs.

/** A badge: its label and tooltip, a style class, and for capability tags a colour. */
export interface Badge {
  t: string
  title: string
  cls: string
  color?: string
}

type MaybeBadge = Badge | false | null | undefined | 0 | ''

const UNCENSORED_TITLE = 'Uncensored: the provider marks this model as having no content filtering'
export const UNCENSORED: Badge = { t: 'uncensored', title: UNCENSORED_TITLE, cls: 'uncensored' }
export const MAX_INLINE_BADGES = 2 // more than this and a row's badges fold up

// Venice's privacy levels
export const PRIVACY: Readonly<Record<'private' | 'anonymized', Badge>> = {
  private: { t: 'private', cls: 'private', title: "Private: runs on Venice's own servers and nothing is stored" },
  anonymized: {
    t: 'anonymized',
    cls: 'anonymized',
    title:
      'Anonymized: Venice passes it to a third-party provider without your identity; that provider may keep the prompts and outputs',
  },
}

const PER_MILLION = 1e6

/** A per-token price as dollars per million tokens ("$0.50"), 'free' for none, null when unknown. */
export function perMillion(price: number | string | null | undefined): string | null {
  const n = Number(price)
  if (!price || Number.isNaN(n)) return null
  if (n === 0) return 'free'
  const v = n * PER_MILLION
  return `$${v < 1 ? v.toFixed(2) : v.toFixed(v < 10 ? 1 : 0)}`
}

const CHEAP_USD = 0.1

// Venice prices: per image, or a quote for a ~5s video at the lowest resolution
const fmtPrice = (usd: number): string => `$${usd < CHEAP_USD ? usd.toFixed(3).replace(/0$/, '') : usd.toFixed(2)}`

function flagBadges(m: Model): MaybeBadge[] {
  return [
    // First, so it's the one thing you can't miss
    m.uncensored && UNCENSORED,
    m.privacy && PRIVACY[m.privacy],
    m.hidden && { t: 'hidden', title: m.hidden, cls: 'hidden' },
  ]
}

function textBadges(m: TextModel): MaybeBadge[] {
  const p = perMillion(m.prompt_price)
  const c = perMillion(m.completion_price)
  return [
    p && { t: p === 'free' ? 'free' : `${p}/${c ?? ''}`, title: 'Input/output price per million tokens', cls: 'price' },
  ]
}

function priceBadge(m: Model, kind: ModelKind): MaybeBadge[] {
  if (!m.price) return []
  const basis = m.price.basis
  const title =
    kind === 'video'
      ? `Quoted price for ${basis || 'a default video'} (longer or sharper costs more)`
      : `Price per image${basis ? ` (${basis})` : ''}`
  return [{ t: fmtPrice(m.price.usd), title, cls: 'price' }]
}

function imageBadges(m: ImageModel): MaybeBadge[] {
  return [
    m.conversational && {
      t: 'context',
      title: 'Sees the conversation (text and earlier images), like the Gemini app',
      cls: 'context',
    },
    chatImageModelTakesCharacters(m) && {
      t: 'characters',
      title: 'Can use characters (sends their reference images)',
      cls: 'characters',
    },
  ]
}

function videoBadges(m: VideoModel): MaybeBadge[] {
  const d = m.durations
  return [
    d?.length && { t: `${String(Math.min(...d))}–${String(Math.max(...d))}s`, title: 'Durations', cls: 'duration' },
  ]
}

function kindBadges(m: Model): MaybeBadge[] {
  if (isTextModel(m)) return textBadges(m)
  if (isImageModel(m)) return imageBadges(m)
  if (isVideoModel(m)) return videoBadges(m)
  return []
}

// What each model can do, from the backend's capability tags; each tag has its own colour
const tagBadges = (m: Model): Badge[] =>
  m.tags.map(slug => ({
    t: tagLabel(slug),
    title: `Capability: ${tagLabel(slug)}`,
    cls: 'tag',
    color: tagColor(slug),
  }))

export function modelBadges(m: Model, kind: ModelKind): Badge[] {
  const price = kind === 'text' ? [] : priceBadge(m, kind)
  return [...flagBadges(m), ...price, ...kindBadges(m), ...tagBadges(m)].filter((b): b is Badge => !!b)
}
