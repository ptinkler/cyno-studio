<script setup lang="ts">
import InspectorSection from './InspectorSection.vue'
import { composerSettingsKey, injectRequired } from '../../injection'
import type { Catalogues } from '../../composables/useComposerSettings'
import ModelPicker from '../chat/ModelPicker.vue'
import StudioPresets from './StudioPresets.vue'

withDefaults(defineProps<{ models: Catalogues; loading?: boolean | undefined }>(), { loading: false })
// Shared composer settings (not a prop) — binding to its slice is intended
const { selected } = injectRequired(composerSettingsKey)
</script>

<template>
  <InspectorSection title="Models">
    <StudioPresets />
    <div class="pickers">
      <ModelPicker
        v-model="selected.text"
        :models="models.text"
        label="Chat"
        kind="text"
        :loading="loading"
        :allow-none="false"
      />
      <ModelPicker v-model="selected.image" :models="models.image" label="Image" kind="image" :loading="loading" />
      <ModelPicker v-model="selected.video" :models="models.video" label="Video" kind="video" :loading="loading" />
      <ModelPicker v-model="selected.audio" :models="models.audio" label="Audio" kind="audio" :loading="loading" />
    </div>
  </InspectorSection>
</template>
