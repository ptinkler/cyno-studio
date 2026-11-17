<script setup lang="ts">
import { vTip } from '../../directives/tip'

// The bar pinned under a page of selectable media (the Media library, a thread's Generations): how many are
// picked, and what to do with them. Icons only, with a tooltip and an aria-label each.
withDefaults(defineProps<{ count: number; busy?: boolean | undefined; canDownload?: boolean | undefined }>(), {
  busy: false,
  canDownload: true,
})
defineEmits<{ selectAll: []; download: []; delete: []; clear: [] }>()
</script>

<template>
  <div class="selbar" role="toolbar" aria-label="Selection">
    <span class="count">{{ count }} selected</span>
    <button
      v-tip="'Select all'"
      class="iconbtn boxed"
      aria-label="Select all"
      :disabled="busy"
      @click="$emit('selectAll')"
    >
      <svg class="ic"><use href="#s-selectall" /></svg>
    </button>
    <button
      v-if="canDownload"
      v-tip="'Download'"
      class="iconbtn boxed"
      aria-label="Download"
      :disabled="busy || !count"
      @click="$emit('download')"
    >
      <svg class="ic"><use href="#s-download" /></svg>
    </button>
    <button
      v-tip="'Delete'"
      class="iconbtn boxed danger"
      aria-label="Delete"
      :disabled="busy || !count"
      @click="$emit('delete')"
    >
      <svg class="ic"><use href="#s-trash" /></svg>
    </button>
    <button v-tip="'Clear selection'" class="iconbtn boxed" aria-label="Clear selection" @click="$emit('clear')">
      <svg class="ic"><use href="#s-close" /></svg>
    </button>
  </div>
</template>

<style scoped>
.selbar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5333rem 1.2rem;
  border-top: 1px solid var(--sborder2);
  background: var(--spanel2);
}
.count {
  flex: 1;
  color: var(--sfg);
  font-size: 0.8667rem;
}
</style>
