<script setup lang="ts">
import { computed, ref } from 'vue'
import { costRows, fmtCost } from '../../utils/format'
import type { CostRow } from '../../utils/format'

// A reply's one cost. Hovering (or focusing, or tapping) it opens what the cost is made of.
const props = defineProps<{
  total: number
  media: readonly {
    model?: string | null
    cost?: number | null
    credits?: number | null
    versions?: readonly { cost?: number | null }[] | null
  }[]
}>()

const open = ref(false)
const rows = computed<CostRow[]>(() => costRows(props.total, props.media))
</script>

<template>
  <span
    class="cost"
    @mouseenter="open = true"
    @mouseleave="open = false"
    @focusin="open = true"
    @focusout="open = false"
  >
    <button type="button" class="chip-btn" :aria-expanded="open" aria-label="Cost breakdown" @click="open = !open">
      {{ fmtCost(total) }}
    </button>
    <div v-if="open" class="pop" role="tooltip">
      <div class="pop-title">Cost of this reply</div>
      <div v-for="row in rows" :key="row.label + row.value" class="pop-row">
        <span class="pop-label" :title="row.label">{{ row.label }}</span>
        <span class="pop-value">{{ row.value }}</span>
      </div>
      <div class="pop-row pop-total">
        <span>Total</span>
        <span class="pop-value">{{ fmtCost(total) }}</span>
      </div>
    </div>
  </span>
</template>

<style scoped>
.cost {
  position: relative;
  display: inline-flex;
}
.chip-btn {
  height: 2rem;
  padding: 0 0.6667rem;
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  background: var(--spanel2);
  color: var(--smuted);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
  cursor: default;
}
.chip-btn:hover,
.chip-btn:focus-visible,
.chip-btn[aria-expanded='true'] {
  color: var(--sfg);
  border-color: var(--sfaint);
}
/* Opens upward from the chip's right edge, over what is above the row */
.pop {
  position: absolute;
  right: 0;
  bottom: calc(100% + 0.4rem);
  z-index: 30;
  min-width: 14rem;
  max-width: 21.3333rem;
  padding: 0.5333rem 0.8rem 0.6667rem;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-pop);
  font-size: 0.8rem;
}
.pop-title {
  margin-bottom: 0.4rem;
  color: var(--sfaint);
  font-size: 0.8rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.pop-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 1.0667rem;
  padding: 2px 0;
  color: var(--smuted);
}
.pop-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pop-value {
  color: var(--sfg);
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.pop-total {
  margin-top: 0.2667rem;
  padding-top: 0.4rem;
  border-top: 1px solid var(--sborder);
  color: var(--sfg);
  font-weight: 600;
}
</style>
