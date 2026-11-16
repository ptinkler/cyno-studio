<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { composerSettingsKey, injectRequired } from '../../injection'
import { fetchAudioVoices } from '../../composables/useChat'

type Voice = Awaited<ReturnType<typeof fetchAudioVoices>>['voices'][number]

const VOICE_PAGE = 100
const { audioOpts, audioInfo, showAudioOpts } = injectRequired(composerSettingsKey)
const has = (opt: string): boolean => !!audioInfo.value?.options.includes(opt)

// Pollo's voice list, loaded once the first time a voice-picking model is shown
const voices = ref<Voice[]>([])
const voicesError = ref('')
const wantVoices = computed(() => showAudioOpts.value && has('voice'))
watch(
  wantVoices,
  async want => {
    if (!want || voices.value.length) return
    try {
      voices.value = (await fetchAudioVoices(VOICE_PAGE)).voices
      voicesError.value = ''
    } catch (e) {
      voicesError.value = (e instanceof Error && e.message) || 'Could not load voices'
    }
  },
  { immediate: true },
)
const voiceLabel = (voice: Voice): string => [voice.voiceName, voice.language, voice.gender].filter(Boolean).join(' · ')
</script>

<template>
  <div v-if="showAudioOpts" class="isection">
    <div class="ilabel">Audio options</div>

    <div v-if="has('voice')" class="orow">
      <label class="ifield">
        <span class="fcap">Voice</span>
        <select v-model="audioOpts.voice">
          <option value="">Pick one…</option>
          <option v-for="v in voices" :key="v.voiceId ?? v.voiceName ?? ''" :value="v.voiceId ?? ''">
            {{ voiceLabel(v) }}
          </option>
        </select>
      </label>
    </div>
    <div v-if="voicesError" class="aerr">{{ voicesError }}</div>

    <div v-if="has('tuning')" class="orow">
      <label class="ifield" title="Speed (0.5–2×)">
        <span class="fcap">Speed</span>
        <input v-model.number="audioOpts.speed" type="number" min="0.5" max="2" step="0.1" placeholder="1×" />
      </label>
      <label class="ifield" title="Volume (0.5–2×)">
        <span class="fcap">Volume</span>
        <input v-model.number="audioOpts.volume" type="number" min="0.5" max="2" step="0.1" placeholder="1×" />
      </label>
      <label class="ifield" title="Pitch (semitones)">
        <span class="fcap">Pitch</span>
        <input v-model.number="audioOpts.pitch" type="number" min="-12" max="12" step="1" placeholder="0" />
      </label>
    </div>

    <template v-if="has('instrumental')">
      <div class="orow">
        <label class="audio"><input v-model="audioOpts.instrumental" type="checkbox" /> Instrumental</label>
        <label v-if="!audioOpts.instrumental" class="ifield">
          <span class="fcap">Vocals</span>
          <select v-model="audioOpts.vocal_gender">
            <option value="">Any</option>
            <option value="f">Female</option>
            <option value="m">Male</option>
          </select>
        </label>
      </div>
      <div v-if="has('lyrics')" class="orow">
        <label class="ifield" title="Style and title together: lyrics mode">
          <span class="fcap">Style</span>
          <input v-model="audioOpts.style" placeholder="e.g. synthwave" />
        </label>
        <label class="ifield">
          <span class="fcap">Title</span>
          <input v-model="audioOpts.title" placeholder="Untitled" maxlength="80" />
        </label>
      </div>
      <div class="orow">
        <label class="ifield">
          <span class="fcap">Avoid</span>
          <input v-model="audioOpts.negative_prompt" placeholder="Styles to exclude" />
        </label>
        <label v-if="has('duration')" class="ifield">
          <span class="fcap">Length</span>
          <input v-model.number="audioOpts.duration" type="number" min="1" placeholder="Seconds" />
        </label>
      </div>
    </template>
  </div>
</template>

<style scoped>
.orow + .orow,
.aerr {
  margin-top: 8px;
}
.aerr {
  color: var(--sdanger);
  font-size: 12px;
}
</style>
