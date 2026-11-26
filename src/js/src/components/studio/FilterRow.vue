<script setup lang="ts">
// One line of a filter popover: what it filters on, and the control for it
defineProps<{ label: string }>()
</script>

<template>
  <label class="frow">
    <span class="flabel">{{ label }}</span>
    <slot></slot>
  </label>
</template>

<style scoped>
.frow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.2rem;
  min-height: 2rem;
  font-size: 0.8667rem;
}
.flabel {
  color: var(--smuted);
  font-weight: 400;
  text-transform: none;
  letter-spacing: normal;
}
.frow :slotted(select) {
  min-width: 8rem;
  max-width: 12rem;
}
</style>
