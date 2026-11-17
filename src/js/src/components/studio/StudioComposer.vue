<script setup lang="ts">
import { vTip } from '../../directives/tip'
import { ref, computed } from 'vue'
import type { CreditEstimate } from '../../composables/useStudioPrompt'
import type { Attachment } from '../../composables/useChatAttachments'
import type { Mode } from '../../composables/composerPrefs'
import { fmtCost, creditsToUsd } from '../../utils/format'
import { takeFiles } from '../../utils/files'
import { buildRefItems } from '../../utils/refItems'
import type { RefItem, RefMode } from '../../utils/refItems'
import { useMentionEditor } from '../../composables/useMentionEditor'
import ComposerAttachments from './ComposerAttachments.vue'

const props = withDefaults(
  defineProps<{
    modes?: readonly { id: Mode; label: string; icon: string }[] | undefined
    mode?: Mode | undefined
    draft?: string | undefined
    sending?: boolean | undefined
    canSend?: boolean | undefined
    attachments?: readonly Attachment[] | undefined
    uploading?: boolean | undefined
    enhancing?: boolean | undefined
    /** Pollo's price for the current setup, or null. */
    estimate?: CreditEstimate | null | undefined
    /** Keys of attachments the selected model can't use (dimmed, not sent). */
    unused?: ReadonlySet<string> | undefined
    /** The selected video model takes a source video (Recast / motion models). */
    videoInput?: boolean | undefined
    /** The selected video model takes an audio track (lip-sync models). */
    audioInput?: boolean | undefined
    /** The selected video model's reference-to-video config (image/video/audio refs the prompt mentions as [@name]), or null. */
    refMode?: RefMode | null | undefined
  }>(),
  {
    modes: () => [],
    mode: 'auto',
    draft: '',
    sending: false,
    canSend: false,
    attachments: () => [],
    uploading: false,
    enhancing: false,
    estimate: null,
    unused: () => new Set<string>(),
    videoInput: false,
    audioInput: false,
    refMode: null,
  },
)
const emit = defineEmits<{
  'update:draft': [text: string]
  'update:mode': [mode: Mode]
  send: []
  files: [files: File[]]
  remove: [attachment: Attachment]
  clear: []
  library: []
  enhance: []
}>()

const drag = ref(false)
const aud = ref<HTMLInputElement | null>(null) // hidden audio-clip file input (audio mode)
// Audio mode with a voice-clone model: the only attachment is the reference clip
const audioClip = computed(() => props.mode === 'audio' && props.audioInput)
const mediaMode = computed(() => props.mode === 'image' || props.mode === 'video')
const refsActive = computed(() => !!props.refMode && props.mode === 'video')
const refItems = computed(() =>
  refsActive.value && props.refMode ? buildRefItems(props.attachments, props.refMode) : [],
)
const placeholder = computed(() =>
  refsActive.value && refItems.value.length
    ? 'Describe what to change… Type @ to add a reference'
    : 'Describe what you want to create…',
)
function removeUnused(): void {
  for (const attachment of props.attachments) {
    if (props.unused.has(attachment.key)) emit('remove', attachment)
  }
}

const { ed, atMenu, insertMention, toggleMentionMenu, syncDraft, onKey, onCopy, onCut, onPaste, focusPrompt } =
  useMentionEditor({
    draft: () => props.draft,
    refItems,
    canMention: () => refsActive.value && refItems.value.length > 0,
    onUpdate: text => {
      emit('update:draft', text)
    },
    onFiles: files => {
      emit('files', files)
    },
    onSend: () => {
      emit('send')
    },
  })

// Click-to-insert: map each attachment to its ref so clicking its thumbnail
// drops the [@name] pill into the prompt.
const refByKey = computed<Record<string, RefItem>>(() => Object.fromEntries(refItems.value.map(r => [r.key, r])))
function insertAtt(attachment: Attachment): void {
  const item = refByKey.value[attachment.key]
  if (item) insertMention(item)
}

function onVideo(event: Event): void {
  emit('files', takeFiles(event))
}
function onDrop(event: DragEvent): void {
  drag.value = false
  emit('files', [...(event.dataTransfer?.files ?? [])])
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
            v-tip="'Mention a reference'"
            class="clip at"
            aria-label="Mention a reference"
            @mousedown.prevent
            @click="toggleMentionMenu"
          >
            @
          </button>
          <div v-if="atMenu" class="atmenu" @mouseleave="atMenu = false">
            <button v-for="r in refItems" :key="r.key" @click="insertMention(r)">
              <img v-if="r.type === 'image'" :src="r.preview ?? undefined" alt="" />
              <span v-else class="pill-ic">{{ r.type === 'audio' ? '🔊' : '🎞' }}</span>{{ r.label }}
            </button>
          </div>
        </div>
        <button
          v-if="!mediaMode && mode !== 'audio'"
          v-tip="'Add images'"
          class="clip"
          aria-label="Add images"
          @click="emit('library')"
        >
          <svg class="ic"><use href="#s-clip" /></svg>
        </button>
        <input ref="aud" type="file" accept="audio/*" hidden @change="onVideo" />
        <button
          v-if="mode === 'image' || mode === 'video'"
          class="clip enh"
          :disabled="!props.draft.trim() || enhancing"
          title="Enhance prompt"
          @click="emit('enhance')"
        >
          {{ enhancing ? '…' : '✨' }}
        </button>
        <span class="note">{{ uploading ? 'Uploading…' : '' }}</span>
        <span
          v-if="estimate && (mediaMode || mode === 'audio')"
          v-tip="
            estimate.full_credits > estimate.credits
              ? `Pollo's estimate: ${estimate.credits} credits (${estimate.full_credits} before discount)`
              : `Pollo's estimate: ${estimate.credits} credits`
          "
          class="est"
          >≈ {{ fmtCost(creditsToUsd(estimate.credits)) }}</span
        >
        <button class="sendbtn" :disabled="!canSend" @click="emit('send')">{{ sending ? 'Sending…' : 'Send' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.est {
  font-size: 0.8333rem;
  color: var(--saccent);
  white-space: nowrap;
}
.compose {
  padding: 0.5333rem 1.4667rem 1.3333rem;
}
.cbox {
  position: relative;
  max-width: var(--measure);
  margin: 0 auto;
  border: 1px solid var(--sborder);
  background: var(--sbg);
  border-radius: var(--r-lg);
  padding: 0.6667rem 0.8rem 0.5333rem;
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
  gap: 0.4rem;
  flex: 0 0 auto;
}
.ed {
  width: 100%;
  min-width: 0;
  min-height: 1.4667rem;
  color: var(--sfg);
  max-height: 45dvh;
  overflow-y: auto;
  padding: 0.3333rem 0.4667rem;
  border: 1px solid var(--sborder2);
  border-radius: 0.4rem;
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
  gap: 0.4rem;
  vertical-align: middle;
  margin: 0 2px;
  padding: 2px 0.6667rem 2px 0.2rem;
  border: 1px solid var(--sborder);
  border-radius: 0.5333rem;
  background: var(--saccent-soft);
  color: var(--saccent);
  font-size: 0.86em;
  user-select: none;
  white-space: nowrap;
}
.pill img {
  width: 1.3333rem;
  height: 1.3333rem;
  border-radius: 0.3333rem;
  object-fit: cover;
}
.pill-ic {
  font-size: 0.9333rem;
}
.cbar {
  display: flex;
  align-items: center;
  gap: 0.6667rem;
  padding-top: 0.4rem;
}
.atwrap {
  position: relative;
}
.clip.at {
  font-size: 1.2rem;
  font-weight: 700;
}
.atmenu {
  position: absolute;
  bottom: 2.6667rem;
  left: 0;
  z-index: var(--z-menu);
  min-width: 10rem;
  max-height: 16rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r-lg);
  padding: 0.2667rem;
  box-shadow: var(--shadow-pop);
}
.atmenu button {
  display: inline-flex;
  align-items: center;
  gap: 0.4667rem;
  text-align: left;
  border: none;
  background: none;
  color: var(--sfg);
  font: inherit;
  font-size: 0.8667rem;
  padding: 0.4rem 0.6rem;
  border-radius: 0.4667rem;
  cursor: pointer;
}
.atmenu button:hover {
  background: var(--shover);
}
.atmenu img {
  width: 1.4667rem;
  height: 1.4667rem;
  border-radius: 0.3333rem;
  object-fit: cover;
}
.clip {
  width: 2rem;
  height: 2rem;
  display: grid;
  place-items: center;
  border-radius: 0.5333rem;
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
  font-size: 0.8rem;
  color: var(--sfaint);
}
.sendbtn {
  min-height: 2rem;
  padding: 0.3333rem 0.9333rem;
  border: none;
  border-radius: var(--r);
  background: var(--saccent-fill);
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
