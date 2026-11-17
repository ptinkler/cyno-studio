// Display formatting shared by the chat views

/** "openai/gpt-image-1" → "gpt-image-1" (Pollo's "pollo/<key>" likewise). */
export const shortModel = (id: string | null | undefined): string => (id ?? '').split('/').pop() ?? ''

/** OpenRouter dollar cost; sub-cent amounts keep 4 decimals. '' for none. */
export const fmtCost = (cost: number | null | undefined): string => {
  if (!cost) return ''
  return cost < 0.01 ? `$${cost.toFixed(4)}` : `$${cost.toFixed(2)}`
}

/** Pollo bills in credits; its API converts them to USD at this fixed rate. */
export const POLLO_USD_PER_CREDIT = 0.06
export const creditsToUsd = (credits: number | null | undefined): number => (credits ?? 0) * POLLO_USD_PER_CREDIT

const HUE_STEPS = 360

// A steady colour for an instruction snippet, from its name: the dot that
// tells snippets apart when their chips are cut short
export function instructionColor(name: string | null | undefined): string {
  let hue = 0
  for (const ch of name ?? '') hue = (hue * 31 + (ch.codePointAt(0) ?? 0)) % HUE_STEPS
  return `hsl(${String(hue)} 70% 62%)`
}

const SECONDS_PER_MINUTE = 60

// Seconds as m:ss ("0:05", "1:12")
export const fmtDuration = (seconds: number): string =>
  `${String(Math.floor(seconds / SECONDS_PER_MINUTE))}:${String(Math.round(seconds % SECONDS_PER_MINUTE)).padStart(2, '0')}`

/** Less than this left over (in dollars) is rounding, not a cost. */
const COST_EPSILON = 0.00005

interface PricedPicture {
  model?: string | null | undefined
  cost?: number | null | undefined
  credits?: number | null | undefined
  versions?: readonly { cost?: number | null | undefined }[] | null | undefined
}

export interface CostRow {
  label: string
  value: string
}

const costRow = (label: string, cost: number | null | undefined): CostRow[] =>
  cost ? [{ label, value: fmtCost(cost) }] : []

/** One picture's rows for the breakdown, and what of the total they account for. */
function pictureRows(item: PricedPicture): { rows: CostRow[]; paid: number } {
  const name = shortModel(item.model) || 'Picture'
  const earlier = (item.versions ?? []).reduce((sum, v) => sum + (v.cost ?? 0), 0)
  const credits = item.credits
    ? [{ label: name, value: `${String(item.credits)} credit${item.credits === 1 ? '' : 's'}` }]
    : []
  return {
    rows: [...costRow(name, item.cost), ...credits, ...costRow(`${name}, earlier versions`, earlier)],
    paid: (item.cost ?? 0) + earlier,
  }
}

/**
 * What a reply's one total is made of: the text, then every picture or clip (and the earlier versions of it
 * that were paid for). Whatever the pictures don't account for is the text, including the wordings it was
 * rewritten from. Credits (Pollo) are listed but aren't part of the dollar total.
 */
export function costRows(total: number, media: readonly PricedPicture[]): CostRow[] {
  const pictures = media.map(pictureRows)
  const text = total - pictures.reduce((sum, p) => sum + p.paid, 0)
  return [...(text > COST_EPSILON ? costRow('Text', text) : []), ...pictures.flatMap(p => p.rows)]
}
