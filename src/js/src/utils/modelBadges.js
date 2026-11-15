import { TAG_LABELS, tagColor } from '../composables/modelTags'
import { chatImageModelTakesCharacters } from '../composables/useCharacters'

// The little labels beside a model in the picker: warnings first, then what it can do and costs.
// A badge is { t: label, title, cls, color? }.

const UNCENSORED_TITLE = 'Uncensored: the provider marks this model as having no content filtering'
export const UNCENSORED = { t: 'uncensored', title: UNCENSORED_TITLE, cls: 'uncensored' }
export const MAX_INLINE_BADGES = 2 // more than this and a row's badges fold up

// Venice's privacy levels
export const PRIVACY = {
  private: { t: 'private', cls: 'private', title: "Private: runs on Venice's own servers and nothing is stored" },
  anonymized: {
    t: 'anonymized',
    cls: 'anonymized',
    title:
      'Anonymized: Venice passes it to a third-party provider without your identity; that provider may keep the prompts and outputs',
  },
}

export function perMillion(price) {
  const n = Number(price)
  if (!price || Number.isNaN(n)) return null
  if (n === 0) return 'free'
  const v = n * 1e6
  return `$${v < 1 ? v.toFixed(2) : v.toFixed(v < 10 ? 1 : 0)}`
}

// Venice prices: per image, or a quote for a ~5s video at the lowest resolution
const fmtPrice = usd => `$${usd < 0.1 ? usd.toFixed(3).replace(/0$/, '') : usd.toFixed(2)}`

function flagBadges(m) {
  return [
    // First, so it's the one thing you can't miss
    m.uncensored && UNCENSORED,
    PRIVACY[m.privacy],
    m.hidden && { t: 'hidden', title: m.hidden, cls: 'hidden' },
  ]
}

function textBadges(m) {
  const p = perMillion(m.prompt_price)
  const c = perMillion(m.completion_price)
  return [p && { t: p === 'free' ? 'free' : `${p}/${c}`, title: 'Input/output price per million tokens', cls: 'price' }]
}

function priceBadge(m, kind) {
  if (!m.price) return []
  const basis = m.price.basis
  const title =
    kind === 'video'
      ? `Quoted price for ${basis || 'a default video'} (longer or sharper costs more)`
      : `Price per image${basis ? ` (${basis})` : ''}`
  return [{ t: fmtPrice(m.price.usd), title, cls: 'price' }]
}

function imageBadges(m) {
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

function videoBadges(m) {
  const d = m.durations
  return [d?.length && { t: `${Math.min(...d)}–${Math.max(...d)}s`, title: 'Durations', cls: 'duration' }]
}

// What each model can do, from the backend's capability tags; each tag has its own colour
const tagBadges = m =>
  (m.tags || []).map(slug => ({
    t: TAG_LABELS[slug] || slug,
    title: `Capability: ${TAG_LABELS[slug] || slug}`,
    cls: 'tag',
    color: tagColor(slug),
  }))

const KIND_BADGES = { text: textBadges, image: imageBadges, video: videoBadges }

export function modelBadges(m, kind) {
  const price = kind === 'text' ? [] : priceBadge(m, kind)
  return [...flagBadges(m), ...price, ...(KIND_BADGES[kind]?.(m) || []), ...tagBadges(m)].filter(Boolean)
}
