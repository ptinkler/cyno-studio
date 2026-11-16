<script setup lang="ts">
import { ref } from 'vue'
import { composerSettingsKey, injectRequired } from '../../injection'
import type { StoredPreset } from '../../composables/composerPresets'
import PresetEditor from './PresetEditor.vue'
import { presetSummary } from '../../utils/presets'

defineEmits<{ close: [] }>()
const { presets } = injectRequired(composerSettingsKey)

const editorOpen = ref(false)
const editing = ref<StoredPreset | null>(null)
function edit(preset: StoredPreset | null): void {
  editing.value = preset
  editorOpen.value = true
}
</script>

<template>
  <div class="page">
    <div class="pwrap">
      <div class="phead">
        <div>
          <h1>Presets</h1>
          <p class="sub">
            Saved sets of models and media options. Load one from the Presets box above the models in the inspector.
          </p>
        </div>
        <div class="hactions">
          <button class="btn btn-primary" @click="edit(null)">
            <svg class="ic"><use href="#s-plus" /></svg> New preset
          </button>
          <button class="btn" @click="$emit('close')">
            <svg class="ic"><use href="#s-chevL" /></svg> Back
          </button>
        </div>
      </div>

      <div v-if="!presets.length" class="empty">No presets yet. Create one here, or save the current setup with +.</div>
      <div v-else class="grid">
        <button v-for="p in presets" :key="p.id" class="gcard card" @click="edit(p)">
          <h3>{{ p.name }}</h3>
          <p class="desc">{{ presetSummary(p) }}</p>
        </button>
      </div>
    </div>

    <PresetEditor :open="editorOpen" :preset="editing" @close="editorOpen = false" />
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(12.6667rem, 1fr));
  gap: 0.6667rem;
}
.card {
  padding: 0.6667rem 0.8rem;
}
.card h3 {
  font-size: 0.9rem;
  font-weight: 600;
}
.desc {
  font-size: 0.8rem;
  color: var(--smuted);
  margin-top: 0.2rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
