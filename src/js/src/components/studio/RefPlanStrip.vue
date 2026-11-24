<script setup lang="ts">
import { vTip } from '../../directives/tip'
import type { PlannedRef, RefState } from '../../composables/useRefPlan'

defineProps<{ refs: readonly PlannedRef[] }>()
defineEmits<{ toggle: [ref: string] }>()

const SOURCES = { pin: 'Pinned image', recent: 'Recent chat image', character: 'Character image' }
const NOTES: Record<RefState, string> = {
  sent: 'Will be sent. Click to leave it out.',
  off: 'Left out. Click to send it.',
  capped: 'Over the Images sent limit, so it is not sent. Click to leave it out for good.',
  dropped: 'The image model takes fewer references, so it is not sent. Click to leave out another instead.',
}
</script>

<template>
  <div v-if="refs.length" class="refplan">
    <span class="rp-label">References</span>
    <button
      v-for="r in refs"
      :key="r.ref"
      v-tip="`${SOURCES[r.source]}. ${NOTES[r.state]}`"
      class="rp"
      :class="r.state"
      :aria-pressed="r.state === 'sent'"
      @click="$emit('toggle', r.ref)"
    >
      <img :src="r.url" alt="" />
    </button>
  </div>
</template>

<style scoped>
.refplan {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  padding: 0 0.2rem 0.5rem;
}
.rp-label {
  font-size: 0.8rem;
  color: var(--smuted);
  margin-right: 0.2rem;
}
.rp {
  width: 2.4rem;
  height: 2.4rem;
  padding: 0;
  border-radius: 0.5rem;
  overflow: hidden;
  cursor: pointer;
  border: 2px solid var(--saccent);
  background: none;
}
.rp img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.rp.off,
.rp.capped,
.rp.dropped {
  border-color: var(--sborder);
  opacity: 0.4;
  filter: grayscale(1);
}
</style>
