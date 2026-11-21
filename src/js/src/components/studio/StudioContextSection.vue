<script setup lang="ts">
import InspectorSection from './InspectorSection.vue'
import { computed } from 'vue'
import { composerSettingsKey, injectRequired } from '../../injection'
import { MEMORY_STEPS, IMAGE_STEPS } from '../../composables/useComposerSettings'
import type { Step } from '../../composables/composerPrefs'

const { mode, memoryIndex, imageIndex, historyLimit, imageLimit } = injectRequired(composerSettingsKey)

const label = (value: Step): string | number => value ?? 'All'
// The filled part of the track, so these read like the video Length slider
const pct = (i: number, steps: readonly Step[]): string =>
  `${String(steps.length > 1 ? (i / (steps.length - 1)) * 100 : 0)}%`
const memoryFill = computed(() => pct(memoryIndex.value, MEMORY_STEPS))
const imageFill = computed(() => pct(imageIndex.value, IMAGE_STEPS))
</script>

<template>
  <InspectorSection v-if="mode !== 'audio'" title="Context">
    <div v-if="mode === 'auto' || mode === 'text'" class="slider">
      <div class="srow">
        <span>Memory</span>
        <span class="sval">{{ label(historyLimit) }} {{ historyLimit === 1 ? 'message' : 'messages' }}</span>
      </div>
      <input
        v-model.number="memoryIndex"
        class="srange"
        type="range"
        min="0"
        :max="MEMORY_STEPS.length - 1"
        :style="{ '--fill': memoryFill }"
      />
    </div>

    <div class="slider">
      <div class="srow">
        <span>Images sent</span>
        <span class="sval">{{ imageLimit === 0 ? 'None' : label(imageLimit) }}</span>
      </div>
      <input
        v-model.number="imageIndex"
        class="srange"
        type="range"
        min="0"
        :max="IMAGE_STEPS.length - 1"
        :style="{ '--fill': imageFill }"
      />
    </div>
  </InspectorSection>
</template>

<style scoped>
.slider + .slider {
  margin-top: 0.9333rem;
}
.srow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.2667rem;
  color: var(--smuted);
  font-size: 0.8333rem;
}
.sval {
  color: var(--saccent);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
</style>
