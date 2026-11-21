import { reactive } from 'vue'
import type { ComputedRef } from 'vue'
import { fetchOpenRouterCredits, fetchVeniceBalance } from './useChat'
import { useSessionCredits } from './useSessionCredits'

interface Balances {
  openrouter: number | null
  venice: number | null
  veniceCredits: number | null
  veniceDiem: number | null
  pollo: ComputedRef<number | null>
}

// What's left to spend with each provider the chat uses: OpenRouter and
// Venice in dollars (plus Venice's plan credits, also dollars, and DIEM), Pollo in credits. `providers`: which keys the server has.
export function useChatBalances(providers: { openrouter?: boolean; venice?: boolean }) {
  const { creditsRemaining, refreshBalance: refreshPollo } = useSessionCredits()
  const balances = reactive<Balances>({
    openrouter: null,
    venice: null,
    veniceCredits: null,
    veniceDiem: null,
    pollo: creditsRemaining,
  })

  async function refresh(): Promise<void> {
    void refreshPollo(true)
    if (providers.openrouter) {
      try {
        balances.openrouter = (await fetchOpenRouterCredits()).remaining
      } catch {
        /* shown as — */
      }
    }
    if (providers.venice) {
      try {
        const { usd, credits, diem } = await fetchVeniceBalance()
        balances.venice = usd
        balances.veniceCredits = credits
        balances.veniceDiem = diem
      } catch {
        /* shown as — */
      }
    }
  }

  return { balances, refresh }
}
