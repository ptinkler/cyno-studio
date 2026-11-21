<script setup lang="ts">
import { vTip } from '../../directives/tip'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { composerSettingsKey, injectRequired } from '../../injection'
import type { StoredPreset } from '../../composables/composerPresets'
import { useDropdown } from '../../composables/useDropdown'
import { usePopPlacement } from '../../composables/usePopPlacement'
import { presetSummary } from '../../utils/presets'
import PresetEditor from './PresetEditor.vue'

// The preset picker: shows the preset the setup matches (change anything and it goes back to none), loads one in a
// click, and saves the current setup under a name right in the list.
const { presets, loadPreset, savePreset, activePresetId } = injectRequired(composerSettingsKey)
const router = useRouter()

const nameInput = ref<HTMLInputElement | null>(null)
const newName = ref('')
const { open, root, toggle, show, close } = useDropdown({
  onOpen: () => {
    newName.value = ''
    placement.track()
  },
  onClose: () => {
    placement.untrack()
  },
})
const placement = usePopPlacement(root)
const { popStyle } = placement

const active = computed(() => presets.value.find(p => p.id === activePresetId.value) ?? null)
const sorted = computed(() => [...presets.value].sort((a, b) => a.name.localeCompare(b.name)))

async function pick(preset: StoredPreset): Promise<void> {
  close()
  await loadPreset(preset)
}

function saveCurrent(): void {
  const name = newName.value.trim()
  if (!name) return
  savePreset(name)
  newName.value = ''
  close()
}

// "+": open the list with the name field ready
async function startSave(): Promise<void> {
  await show()
  nameInput.value?.focus()
}

const editorOpen = ref(false)
const editing = ref<StoredPreset | null>(null)
function edit(preset: StoredPreset): void {
  close()
  editing.value = preset
  editorOpen.value = true
}

async function manage(): Promise<void> {
  close()
  await router.push('/presets')
}
</script>

<template>
  <div ref="root" class="presets">
    <button type="button" class="pbtn" :class="{ active: open }" aria-label="Presets" @click="toggle">
      <span class="pcap">Preset</span>
      <span class="pval" :class="{ none: !active }">{{
        active?.name ?? (presets.length ? 'None' : 'None saved')
      }}</span>
      <span class="chev">▾</span>
    </button>
    <button v-tip="'Save current setup as a preset'" class="add" aria-label="Save as preset" @click="startSave">
      +
    </button>

    <div v-if="open" class="ppop" :style="popStyle" @keydown.esc="close">
      <div v-if="sorted.length" class="plist" role="listbox" aria-label="Presets">
        <div v-for="p in sorted" :key="p.id" class="prow" :class="{ on: p.id === activePresetId }">
          <button type="button" class="ppick" role="option" :aria-selected="p.id === activePresetId" @click="pick(p)">
            <span class="pname">{{ p.name }}</span>
            <span class="psum">{{ presetSummary(p) }}</span>
          </button>
          <button v-tip="'Edit'" type="button" class="pedit" :aria-label="`Edit ${p.name}`" @click="edit(p)">
            <svg class="ic"><use href="#s-pencil" /></svg>
          </button>
        </div>
      </div>
      <div v-else class="pempty">No presets yet. Name the current models and options below to save one.</div>

      <form class="psave" @submit.prevent="saveCurrent">
        <input
          ref="nameInput"
          v-model="newName"
          maxlength="60"
          placeholder="Save current setup as…"
          aria-label="New preset name"
        />
        <button class="btn btn-primary btn-sm" type="submit" :disabled="!newName.trim()">Save</button>
      </form>
      <button type="button" class="pmanage" @click="manage">Manage presets…</button>
    </div>

    <PresetEditor :open="editorOpen" :preset="editing" @close="editorOpen = false" />
  </div>
</template>

<style scoped>
.presets {
  display: flex;
  gap: 0.4rem;
  margin-bottom: 0.5333rem;
}
.pbtn {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  padding: 0.3333rem 0.6667rem;
  color: var(--sfg);
  font: inherit;
  cursor: pointer;
  text-align: left;
}
.pbtn:hover,
.pbtn.active {
  border-color: var(--saccent);
}
.pcap {
  font-size: 0.7333rem;
  color: var(--sfaint);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.pval {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.8667rem;
  font-weight: 600;
}
.pval.none {
  color: var(--smuted);
  font-weight: 400;
}
.chev {
  color: var(--smuted);
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
.ppop {
  position: fixed;
  z-index: var(--z-picker);
  width: min(22rem, 92vw);
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-pop);
  overflow: hidden;
}
.plist {
  max-height: 18rem;
  overflow-y: auto;
  padding: 0.2667rem;
}
.prow {
  display: flex;
  align-items: center;
  border-radius: var(--r);
}
.prow:hover {
  background: var(--saccent-soft);
}
.prow.on {
  box-shadow: inset 2px 0 0 var(--saccent);
}
.ppick {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.0667rem;
  background: none;
  border: 0;
  padding: 0.4rem 0.5333rem;
  font: inherit;
  color: var(--sfg);
  text-align: left;
  cursor: pointer;
}
.pname {
  font-size: 0.8667rem;
  font-weight: 600;
}
.psum {
  font-size: 0.7667rem;
  color: var(--smuted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pedit {
  flex: 0 0 auto;
  background: none;
  border: 0;
  padding: 0.4rem;
  color: var(--smuted);
  cursor: pointer;
  opacity: 0;
}
.prow:hover .pedit,
.pedit:focus-visible {
  opacity: 1;
}
.pedit:hover {
  color: var(--saccent);
}
.pempty {
  padding: 0.6667rem 0.8rem;
  font-size: 0.8rem;
  color: var(--smuted);
}
.psave {
  display: flex;
  gap: 0.4rem;
  padding: 0.5333rem;
  border-top: 1px solid var(--sborder2);
}
.psave input {
  flex: 1;
  min-width: 0;
}
.pmanage {
  display: block;
  width: 100%;
  background: none;
  border: 0;
  border-top: 1px solid var(--sborder2);
  padding: 0.4667rem 0.8rem;
  font: inherit;
  font-size: 0.8rem;
  color: var(--saccent);
  text-align: left;
  cursor: pointer;
}
.pmanage:hover {
  background: var(--saccent-soft);
}
</style>
