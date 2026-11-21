import type { Balances } from '../composables/studioTypes'

type VeniceParts = Pick<Balances, 'venice' | 'veniceCredits' | 'veniceDiem'>

const usd = (value: number): string => `$${value.toFixed(2)}`

/** Spendable dollars: pay-as-you-go USD plus the plan's bundled credits (Venice counts those in dollars too). */
export function veniceTotal({ venice, veniceCredits }: VeniceParts): number | null {
  if (venice === null && veniceCredits === null) return null
  return (venice ?? 0) + (veniceCredits ?? 0)
}

/** What makes up the total, e.g. "$4.76 plan credits + $0.76 USD · 1.5 DIEM". */
export function veniceBreakdown({ venice, veniceCredits, veniceDiem }: VeniceParts): string {
  const parts = [
    veniceCredits ? `${usd(veniceCredits)} plan credits` : '',
    venice !== null ? `${usd(venice)} USD` : '',
  ].filter(Boolean)
  const diem = veniceDiem ? ` · ${String(Math.round(veniceDiem * 100) / 100)} DIEM` : ''
  return parts.length ? parts.join(' + ') + diem : 'unknown'
}
