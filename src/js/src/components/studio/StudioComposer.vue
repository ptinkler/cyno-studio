<!-- Studio compose bar: attachments + mode pills + prompt box + send.
     Presentational — attachment list/upload state come from props.
     The prompt is a contenteditable so reference mentions ([@name]) show as
     inline pills; the [@name] text remains the source of truth. -->
<script setup>
import { ref, computed } from 'vue'
import { fmtCost, creditsToUsd } from '../../utils/format'
import { buildRefItems } from '../../utils/refItems'
import { useMentionEditor } from '../../composables/useMentionEditor'
import ComposerAttachments from './ComposerAttachments.vue'

const props = defineProps({
  modes: { type: Array, default: () => [] },
  mode: { type: String, default: 'auto' },
  draft: { type: String, default: '' },
  sending: { type: Boolean, default: false },
  canSend: { type: Boolean, default: false },
  attachments: { type: Array, default: () => [] },
  uploading: { type: Boolean, default: false },
  enhancing: { type: Boolean, default: false },
  // Pollo's price for the current setup: { credits, full_credits } or null
  estimate: { type: Object, default: null },
  // Keys of attachments the selected model can't use (dimmed, not sent)
  unused: { type: Object, default: () => new Set() },
  // The selected video model takes a source video (Recast / motion models)
  videoInput: { type: Boolean, default: false },
  // The selected video model takes an audio track (lip-sync models)
  audioInput: { type: Boolean, default: false },
  // The selected video model's reference-to-video config (image/video/audio
  // refs the prompt mentions as [@name]): { types, max, limits } or null.
  refMode: { type: Object, default: null },
})
const emit = defineEmits(['update:draft', 'update:mode', 'send', 'files', 'remove', 'clear', 'library', 'enhance'])

const drag = ref(false)
const aud = ref(null) // hidden audio-clip file input (audio mode)
// Audio mode with a voice-clone model: the only attachment is the reference clip
const audioClip = computed(() => props.mode === 'audio' && props.audioInput)
const mediaMode = computed(() => props.mode === 'image' || props.mode === 'video')
const refsActive = computed(() => !!props.refMode && props.mode === 'video')
const refItems = computed(() => (refsActive.value ? buildRefItems(props.attachments, props.refMode) : []))
const placeholder = computed(() =>
  refsActive.value && refItems.value.length
    ? 'Describe what to change… Type @ to add a reference'
    : 'Describe what you want to create…',
)
function removeUnused() {
  props.attachments.filter(a => props.unused.has(a.key)).forEach(a => emit('remove', a))
}

const { ed, atMenu, insertMention, toggleMentionMenu, syncDraft, onKey, onCopy, onCut, onPaste, focusPrompt } =
  useMentionEditor({
    draft: () => props.draft,
    refItems,
    canMention: () => refsActive.value && refItems.value.length > 0,
    onUpdate: text => emit('update:draft', text),
    onFiles: files => emit('files', files),
    onSend: () => emit('send'),
  })

// Click-to-insert: map each attachment to its ref so clicking its thumbnail
// drops the [@name] pill into the prompt.
const refByKey = computed(() => Object.fromEntries(refItems.value.map(r => [r.key, r])))
function insertAtt(a) {
  const r = refByKey.value[a.key]
  if (r) insertMention(r)
}

function onVideo(e) {
  emit('files', e.target.files)
  e.target.value = ''
}
function onDrop(e) {
  drag.value = false
  emit('files', e.dataTransfer?.files)
}
defineExpose({ focusPrompt })
</script>

<template>
  <div class="compose" @dragover.prevent="drag = true" @dragleave.prevent="drag = false" @drop.prevent="onDrop">
    <div class="cbox" :class="{ drag }" @click.self="ed?.focus()">
      <ComposerAttachments
        :attachments="attachments"
        :unused="unused"
        :insertable="refByKey"
        :media-mode="mediaMode"
        :audio-clip="audioClip"
        @add-clip="aud?.click()"
        @library="emit('library')"
        @insert="insertAtt"
        @remove="a => emit('remove', a)"
        @clear="emit('clear')"
        @remove-unused="removeUnused"
      />

      <div
        ref="ed"
        class="ed"
        contenteditable="true"
        role="textbox"
        :data-placeholder="placeholder"
        :data-empty="!draft"
        @input="syncDraft"
        @keydown="onKey"
        @paste="onPaste"
        @copy="onCopy"
        @cut="onCut"
      ></div>

      <div class="cbar">
        <div class="modes">
          <button
            v-for="md in modes"
            :key="md.id"
            class="pillbtn"
            :class="{ on: mode === md.id }"
            @click="emit('update:mode', md.id)"
          >
            {{ md.label }}
          </button>
        </div>
        <div v-if="refsActive && refItems.length" class="atwrap">
          <button
            class="clip at"
            title="Mention a reference image or video"
            @mousedown.prevent
            @click="toggleMentionMenu"
          >
            @
          </button>
          <div v-if="atMenu" class="atmenu" @mouseleave="atMenu = false">
            <button v-for="r in refItems" :key="r.key" @click="insertMention(r)">
              <img v-if="r.type === 'image'" :src="r.preview" alt="" />
              <span v-else class="pill-ic">{{ r.type === 'audio' ? '🔊' : '🎞' }}</span
              >{{ r.label }}
            </button>
          </div>
        </div>
        <button
          v-if="!mediaMode && mode !== 'audio'"
          class="clip"
          title="Attach images — pick from Media or upload"
          @click="emit('library')"
        >
          <svg class="ic"><use href="#s-clip" /></svg>
        </button>
        <input ref="aud" type="file" accept="audio/*" hidden @change="onVideo" />
        <button
          v-if="mode === 'image' || mode === 'video'"
          class="clip enh"
          :disabled="!draft.trim() || enhancing"
          title="Enhance the prompt with the text model (optional — sending uses the prompt exactly as written)"
          @click="emit('enhance')"
        >
          {{ enhancing ? '…' : '✨' }}
        </button>
        <span class="note">{{ uploading ? 'Uploading…' : '' }}</span>
        <span
          v-if="estimate && (mediaMode || mode === 'audio')"
          class="est"
          :title="
            estimate.full_credits > estimate.credits
              ? `Pollo's estimate: ${estimate.credits} credits (${estimate.full_credits} before discount)`
              : `Pollo's estimate: ${estimate.credits} credits`
          "
          >≈ {{ fmtCost(creditsToUsd(estimate.credits)) }}</span
        >
        <button class="sendbtn" :disabled="!canSend" @click="emit('send')">{{ sending ? 'Sending…' : 'Send' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.est {
  font-size: 12.5px;
  color: var(--saccent);
  white-space: nowrap;
}
.est.warn {
  color: var(--swarn);
  cursor: help;
}
.compose {
  padding: 8px 22px 20px;
}
.cbox {
  position: relative;
  max-width: 820px;
  margin: 0 auto;
  border: 1px solid var(--sborder);
  background: var(--sbg);
  border-radius: var(--r-lg);
  padding: 10px 12px 8px;
}
.cbox:focus-within {
  border-color: var(--sfaint);
}
.cbox.drag {
  border-color: var(--saccent);
  background: var(--saccent-soft);
}

.modes {
  display: flex;
  gap: 6px;
  flex: 0 0 auto;
}
.ed {
  width: 100%;
  min-width: 0;
  min-height: 22px;
  color: var(--sfg);
  max-height: 45vh;
  overflow-y: auto;
  padding: 5px 7px;
  border: 1px solid var(--sborder2);
  border-radius: 6px;
  background: color-mix(in srgb, var(--shover) 28%, var(--sbg));
  font: inherit;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  cursor: text;
}
.compose .ed:focus-visible {
  outline: none;
  border-color: var(--sfaint);
  box-shadow: none;
}
.ed[data-empty='true']::before {
  content: attr(data-placeholder);
  color: var(--sfaint);
  pointer-events: none;
}
/* Inline reference mention, e.g. [@video1] — styled like the old chip */
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  vertical-align: middle;
  margin: 0 2px;
  padding: 2px 10px 2px 3px;
  border: 1px solid var(--sborder);
  border-radius: 8px;
  background: var(--saccent-soft);
  color: var(--saccent);
  font-size: 0.86em;
  user-select: none;
  white-space: nowrap;
}
.pill img {
  width: 20px;
  height: 20px;
  border-radius: 5px;
  object-fit: cover;
}
.pill-ic {
  font-size: 14px;
}
.cbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 6px;
}
.atwrap {
  position: relative;
}
.clip.at {
  font-size: 18px;
  font-weight: 700;
}
.atmenu {
  position: absolute;
  bottom: 40px;
  left: 0;
  z-index: 20;
  min-width: 150px;
  max-height: 240px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r-lg);
  padding: 4px;
  box-shadow: var(--shadow-pop);
}
.atmenu button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  text-align: left;
  border: none;
  background: none;
  color: var(--sfg);
  font: inherit;
  font-size: 13px;
  padding: 6px 9px;
  border-radius: 7px;
  cursor: pointer;
}
.atmenu button:hover {
  background: var(--shover);
}
.atmenu img {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  object-fit: cover;
}
.clip {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--smuted);
  background: none;
  border: none;
  cursor: pointer;
}
.clip:hover {
  background: var(--shover);
  color: var(--sfg);
}
.note {
  flex: 1;
  font-size: 12px;
  color: var(--sfaint);
}
.sendbtn {
  min-height: 30px;
  padding: 5px 14px;
  border: none;
  border-radius: var(--r);
  background: var(--saccent);
  color: #fff;
  cursor: pointer;
  font-weight: 600;
}
.sendbtn:hover:not(:disabled) {
  filter: brightness(1.08);
}
.sendbtn:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>
