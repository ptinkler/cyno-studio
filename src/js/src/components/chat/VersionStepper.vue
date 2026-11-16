<script setup lang="ts">
import { computed } from 'vue'

// ‹ 2/3 › — steps through the versions of a prompt, reply text or picture.
// `shown` is the 0-based version on screen; `enabled` is false mid-reply.
const props = withDefaults(
  defineProps<{
    shown: number
    count: number
    enabled?: boolean | undefined
    prevTitle: string
    nextTitle: string
    /** Word before the numbers, e.g. "text". */
    label?: string | undefined
    /** Hover text on the numbers. */
    title?: string | undefined
  }>(),
  { enabled: false, label: undefined, title: undefined },
)
const emit = defineEmits<{ step: [by: number] }>()

const position = computed(() =>
  [props.label, `${String(props.shown + 1)}/${String(props.count)}`].filter(Boolean).join(' '),
)
</script>

<template>
  <span class="stepper">
    <button :disabled="!enabled || shown <= 0" :title="prevTitle" @click="emit('step', -1)">
      <svg class="ic sm"><use href="#s-chevL" /></svg>
    </button>
    <span :title="title">{{ position }}</span>
    <button :disabled="!enabled || shown >= count - 1" :title="nextTitle" @click="emit('step', 1)">
      <svg class="ic sm"><use href="#s-chev" /></svg>
    </button>
  </span>
</template>

<style scoped>
.stepper {
  display: inline-flex;
  align-items: center;
  height: 30px;
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  background: var(--spanel2);
  color: var(--smuted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.stepper button {
  display: grid;
  place-items: center;
  align-self: stretch;
  width: 26px;
  border: none;
  background: none;
  color: inherit;
  cursor: pointer;
}
.stepper button:first-child {
  border-radius: calc(var(--r) - 1px) 0 0 calc(var(--r) - 1px);
}
.stepper button:last-child {
  border-radius: 0 calc(var(--r) - 1px) calc(var(--r) - 1px) 0;
}
.stepper button:hover:not(:disabled) {
  background: var(--shover);
  color: var(--sfg);
}
.stepper button:disabled {
  opacity: 0.35;
  cursor: default;
}
.stepper span {
  padding: 0 2px;
}
</style>
