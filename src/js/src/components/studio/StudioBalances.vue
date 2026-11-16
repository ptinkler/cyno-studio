<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Balances, Spend, UiMessage } from '../../composables/studioTypes'
import { shortModel, fmtCost, creditsToUsd } from '../../utils/format'

const props = withDefaults(
  defineProps<{
    balances?: Balances | undefined
    spend?: Spend | null | undefined
    messages?: readonly UiMessage[] | undefined
  }>(),
  {
    balances: () => ({ openrouter: null, venice: null, veniceCredits: null, pollo: null }),
    spend: null,
    messages: () => [],
  },
)
const emit = defineEmits<{ usage: [] }>()

const open = ref(false)
const fmtCredits = (value: number | null): string => (value === null ? '—' : Math.round(value).toLocaleString())
const fmtBal = (value: number | null): string => (value === null ? '—' : `$${value.toFixed(2)}`)

const pills = computed(() => [
  {
    id: 'pollo',
    label: 'Pollo',
    value: props.balances.pollo === null ? '—' : fmtBal(creditsToUsd(props.balances.pollo)),
    tip: `Pollo balance (${fmtCredits(props.balances.pollo)} credits)`,
  },
  { id: 'openrouter', label: 'OpenRouter', value: fmtBal(props.balances.openrouter), tip: 'OpenRouter balance' },
  { id: 'venice', label: 'Venice', value: fmtBal(props.balances.venice), tip: 'Venice balance' },
])

const label = computed(() => {
  const s = props.spend
  if (!s) return ''
  // Pollo's credits count in dollars too, so one figure covers every provider
  const credits = s.credits + s.inherited_credits
  return fmtCost(s.usd + s.inherited_usd + creditsToUsd(credits))
})

// USD per model for this thread's own messages (inherited spend is one line)
const byModel = computed(() => {
  const totals = new Map<string, number>()
  for (const m of props.messages) {
    if (!m.cost) continue
    const key = m.model ?? 'unknown'
    totals.set(key, (totals.get(key) ?? 0) + m.cost)
  }
  return [...totals].map(([model, usd]) => ({ model, usd })).sort((a, b) => b.usd - a.usd)
})
</script>

<template>
  <div class="bals">
    <button v-if="label" class="bseg spent" title="Thread spend" @click="open = !open">
      Spent <b>{{ label }}</b>
    </button>
    <a
      v-for="p in pills"
      :key="p.id"
      class="bseg"
      :class="p.id"
      :title="`${p.tip} — click for usage`"
      href="/usage"
      @click.prevent="emit('usage')"
    >
      {{ p.label }} <b>{{ p.value }}</b>
    </a>

    <div v-if="open" class="pop-back" @click="open = false"></div>
    <div v-if="open" class="pop">
      <div class="pop-title">Spent in this thread</div>
      <div v-for="r in byModel" :key="r.model" class="row">
        <span class="m">{{ shortModel(r.model) }}</span
        ><b>{{ fmtCost(r.usd) }}</b>
      </div>
      <div v-if="spend?.inherited_usd || spend?.inherited_credits" class="row">
        <span class="m">Inherited from the branched chat</span>
        <b>{{ fmtCost((spend.inherited_usd || 0) + creditsToUsd(spend.inherited_credits)) }}</b>
      </div>
      <div v-if="spend?.credits" class="row">
        <span class="m">Pollo ({{ spend.credits }} cr)</span><b>{{ fmtCost(creditsToUsd(spend.credits)) }}</b>
      </div>
      <div v-if="!byModel.length && !spend?.credits" class="row"><span class="m">Nothing yet</span></div>
      <button class="pop-link" @click="((open = false), emit('usage'))">Full usage →</button>
    </div>
  </div>
</template>

<style scoped>
.bals {
  position: relative;
  display: inline-flex;
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  overflow: visible;
}
.bseg {
  text-decoration: none;
  font: inherit;
  font-size: 0.8rem;
  color: var(--smuted);
  background: none;
  border: 0;
  border-left: 1px solid var(--sborder);
  padding: 0.2rem 0.6rem;
  white-space: nowrap;
  cursor: pointer;
}
.bseg:first-child {
  border-left: 0;
  border-radius: 0.4667rem 0 0 0.4667rem;
}
.bseg:last-of-type {
  border-radius: 0 0.4667rem 0.4667rem 0;
}
.bseg:hover {
  background: var(--saccent-soft);
  color: var(--sfg);
}
.bseg b {
  color: var(--sfg);
  font-weight: 600;
}
.pop-back {
  position: fixed;
  inset: 0;
  z-index: 40;
}
.pop {
  position: absolute;
  top: calc(100% + 0.4rem);
  right: 0;
  z-index: 41;
  min-width: 17.3333rem;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r-lg);
  padding: 0.6667rem 0.8rem;
  box-shadow: var(--shadow-pop);
  font-size: 0.8333rem;
  color: var(--sfg);
}
.pop-title {
  font-weight: 600;
  margin-bottom: 0.4rem;
}
.row {
  display: flex;
  justify-content: space-between;
  gap: 1.0667rem;
  padding: 2px 0;
}
.m {
  color: var(--smuted);
}
.pop-link {
  margin-top: 0.5333rem;
  background: none;
  border: 0;
  color: var(--saccent);
  cursor: pointer;
  padding: 0;
  font: inherit;
}
</style>
