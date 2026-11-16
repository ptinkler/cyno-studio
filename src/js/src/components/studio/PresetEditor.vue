<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { composerSettingsKey, chatModelsKey, injectRequired } from '../../injection'
import type { Snapshot, StoredPreset } from '../../composables/composerPresets'
import BaseDialog from '../BaseDialog.vue'
import ModelPicker from '../chat/ModelPicker.vue'
import { confirmDialog } from '../../composables/useDialog'
import { MODES } from '../../composables/useComposerSettings'

const props = withDefaults(
  defineProps<{
    open?: boolean | undefined
    /** null = a new one. */
    preset?: StoredPreset | null | undefined
  }>(),
  { open: false, preset: null },
)
const emit = defineEmits<{ close: [] }>()
const { snapshot, savePreset, updatePreset, deletePreset, loadPreset } = injectRequired(composerSettingsKey)
const models = injectRequired(chatModelsKey)

// Reactive state can't go through structuredClone, so a plain JSON round trip copies the settings
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const settingsOf = (src: Snapshot): Snapshot =>
  clone({
    mode: src.mode,
    models: src.models,
    imageOpts: src.imageOpts,
    videoOpts: src.videoOpts,
    audioOpts: src.audioOpts,
  })

const name = ref('')
const d = reactive<Snapshot>(settingsOf(snapshot()))
const nameInput = ref<HTMLInputElement | null>(null)
const isNew = computed(() => !props.preset)

function fill(src: Snapshot): void {
  Object.assign(d, settingsOf(src))
}
watch(
  () => props.open,
  async open => {
    if (!open) return
    name.value = props.preset?.name ?? ''
    fill(props.preset ?? snapshot())
    await nextTick()
    nameInput.value?.focus()
  },
)

// What the picked image / video model offers
const imageInfo = computed(() => models.image.find(m => m.id === d.models.image))
const videoInfo = computed(() => models.video.find(m => m.id === d.models.video))
const imageRatios = computed(() => imageInfo.value?.aspect_ratios ?? [])
const imageResolutions = computed(() => imageInfo.value?.resolutions ?? [])
const videoRatios = computed(() => videoInfo.value?.aspect_ratios ?? [])
const videoResolutions = computed(() => videoInfo.value?.resolutions ?? [])
const videoLengths = computed(() => videoInfo.value?.durations ?? [])

function save(): void {
  const trimmed = name.value.trim()
  if (!trimmed) return
  const data = settingsOf(d)
  if (props.preset) updatePreset(props.preset.id, { name: trimmed, ...data })
  else savePreset(trimmed, data)
  emit('close')
}
async function remove(): Promise<void> {
  const { preset } = props
  if (!preset) return
  const ok = await confirmDialog({ title: `Delete “${preset.name}”?`, confirmLabel: 'Delete', danger: true })
  if (!ok) return
  deletePreset(preset.id)
  emit('close')
}
async function load(): Promise<void> {
  if (props.preset) await loadPreset(props.preset)
  emit('close')
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="props.preset ? props.preset.name : 'New preset'"
    label="Preset"
    width="520px"
    @close="emit('close')"
  >
    <p class="sub">
      A saved set of models and media options, loaded in one click from the Presets box above the models.
      {{ isNew ? 'It starts from your current setup — change anything below.' : '' }}
    </p>

    <label for="preset-name">Name</label>
    <input
      id="preset-name"
      ref="nameInput"
      v-model="name"
      maxlength="60"
      placeholder="e.g. Recast – Seedance 2.5"
      @keydown.enter="save"
    />

    <label for="preset-mode">Mode</label>
    <select id="preset-mode" v-model="d.mode">
      <option v-for="m in MODES" :key="m.id" :value="m.id">{{ m.label }}</option>
    </select>

    <label>Models</label>
    <div class="pickers">
      <ModelPicker v-model="d.models.text" :models="models.text" label="Chat" kind="text" :allow-none="false" />
      <ModelPicker v-model="d.models.image" :models="models.image" label="Image" kind="image" />
      <ModelPicker v-model="d.models.video" :models="models.video" label="Video" kind="video" />
      <ModelPicker v-model="d.models.audio" :models="models.audio" label="Audio" kind="audio" />
    </div>

    <label>Image options</label>
    <div class="row">
      <select v-model="d.imageOpts.aspect_ratio" :disabled="!imageRatios.length">
        <option value="">Ratio: auto</option>
        <option v-for="r in imageRatios" :key="r" :value="r">{{ r }}</option>
      </select>
      <select v-model="d.imageOpts.resolution" :disabled="!imageResolutions.length">
        <option value="">Res: default</option>
        <option v-for="r in imageResolutions" :key="r" :value="r">{{ r }}</option>
      </select>
    </div>

    <label>Video options</label>
    <div class="row">
      <select v-model="d.videoOpts.aspect_ratio" :disabled="!videoRatios.length">
        <option value="">Ratio: auto</option>
        <option v-for="r in videoRatios" :key="r" :value="r">{{ r }}</option>
      </select>
      <select v-model="d.videoOpts.resolution" :disabled="!videoResolutions.length">
        <option value="">Res: default</option>
        <option v-for="r in videoResolutions" :key="r" :value="r">{{ r }}</option>
      </select>
    </div>
    <div class="row">
      <select v-model="d.videoOpts.duration" :disabled="!videoLengths.length">
        <option value="">Length: auto</option>
        <option v-for="n in videoLengths" :key="n" :value="n">{{ n }}s</option>
      </select>
      <select v-model="d.videoOpts.generate_audio" :disabled="!videoInfo?.generate_audio">
        <option :value="true">Audio: on</option>
        <option :value="false">Audio: off</option>
      </select>
    </div>

    <button v-if="!isNew" type="button" class="btn btn-secondary replace" @click="fill(snapshot())">
      Replace with the current setup
    </button>

    <template #actions>
      <button v-if="!isNew" class="btn btn-danger" @click="remove">Delete</button>
      <button v-if="!isNew" class="btn btn-secondary" @click="load">Load</button>
      <span class="spacer"></span>
      <button class="btn btn-secondary" @click="emit('close')">Cancel</button>
      <button class="btn btn-primary" :disabled="!name.trim()" @click="save">{{ isNew ? 'Create' : 'Save' }}</button>
    </template>
  </BaseDialog>
</template>

<style scoped>
.sub {
  font-size: 0.8rem;
  color: var(--text2);
  margin-bottom: 8px;
  line-height: 1.45;
}
label {
  margin-top: 4px;
}
input,
select {
  width: 100%;
}
.pickers {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row {
  display: flex;
  gap: 8px;
}
.row select {
  flex: 1;
  min-width: 0;
}
.replace {
  align-self: flex-start;
}
</style>
