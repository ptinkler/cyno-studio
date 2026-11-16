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
