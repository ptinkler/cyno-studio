<script setup lang="ts">
import { ref } from 'vue'
import { composerSettingsKey, injectRequired } from '../../injection'
import { useRouter } from 'vue-router'
import PresetEditor from './PresetEditor.vue'

const { presets, loadPreset, activePresetId } = injectRequired(composerSettingsKey)
const router = useRouter()
const creating = ref(false)

// The box shows the preset the setup matches; change anything and it goes back
// to "Presets". Choosing one loads it.
async function onPick(event: Event): Promise<void> {
  const select = event.target
  if (!(select instanceof HTMLSelectElement)) return
  const value = select.value
  if (value === '__manage') {
    select.value = activePresetId.value
    await router.push('/presets')
    return
  }
  const preset = presets.value.find(p => p.id === value)
  if (preset) await loadPreset(preset)
  select.value = activePresetId.value // not matching after all (an option got adjusted): back to the prompt
}
</script>

<template>
  <div class="presets">
    <label class="ifield">
      <span class="fcap">Preset</span>
      <select :value="activePresetId" aria-label="Presets" @change="onPick">
        <option value="">{{ presets.length ? 'None' : 'None saved yet' }}</option>
        <option v-for="p in presets" :key="p.id" :value="p.id">{{ p.name }}</option>
        <option value="__manage">Manage presets…</option>
      </select>
    </label>
    <button class="add" title="Save as preset" @click="creating = true">+</button>
    <PresetEditor :open="creating" @close="creating = false" />
  </div>
</template>

<style scoped>
.presets {
  display: flex;
  gap: 0.4rem;
  margin-bottom: 0.5333rem;
}
.presets .ifield {
  flex: 1;
  min-width: 0;
}
.add {
  width: 2rem;
  flex: 0 0 auto;
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  background: var(--spanel2);
  color: var(--smuted);
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
}
.add:hover {
  border-color: var(--saccent);
  color: var(--saccent);
}
</style>
