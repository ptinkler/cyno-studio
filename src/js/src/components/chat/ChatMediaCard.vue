<script setup lang="ts">
import { ref, computed, inject, onMounted, onBeforeUnmount } from 'vue'
import { chatModelsKey } from '../../injection'
import type { MediaCard } from '../../composables/chatConversationsApi'
import { chatMediaPreviewUrl, chatMediaUrl } from '../../composables/useChat'
import type { GenerationItem, ImagePick, RegenerateRequest, UiMessage } from '../../composables/studioTypes'
import { useCopy } from '../../composables/useClipboard'
import { videoImageLimit } from '../../composables/useStudioAttachments'
import { bigView, canPinMedia } from '../../utils/chatMedia'
import { cardParams, cardRefFiles, cardSpecs, refUrl, refsLabel, refsTitle } from '../../utils/cardSpecs'
import type { CardParams } from '../../utils/cardSpecs'
import { shortModel, fmtCost } from '../../utils/format'
import ModelPicker from './ModelPicker.vue'
import PinButton from './PinButton.vue'
import PromptBox from './PromptBox.vue'
import RequestDialog from './RequestDialog.vue'

const props = withDefaults(
  defineProps<{
    /** One of the reply's media items. */
    item: MediaCard
    /** The reply holding it. */
    message: UiMessage
    convId: string
    /** The ‹ › arrows are usable (not mid-reply). */
    canSwitch?: boolean | undefined
  }>(),
  { canSwitch: false },
)
const emit = defineEmits<{
  'open-media': [item: GenerationItem]
  'media-version': [pick: { mediaId: string; index: number }]
  pin: [pick: { mediaId: string; pinned: boolean }]
  'use-image': [pick: ImagePick]
  regenerate: [request: RegenerateRequest]
}>()

// Model catalogues, provided by ChatView, for "Try another model"
const KIND_LABEL: Readonly<Record<string, string>> = { image: 'Image', video: 'Video', audio: 'Audio' }
const KIND_ICON: Readonly<Record<string, string>> = { image: '#s-image', video: '#s-film', audio: '#s-audio' }
const chatModels = inject(chatModelsKey, { text: [], image: [], video: [], audio: [] })

// Ticking clock for "rendering 1:23" on pending videos
const TICK_MS = 1000
const SECONDS_PER_MINUTE = 60
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now()
  }, TICK_MS)
})
onBeforeUnmount(() => {
  clearInterval(timer)
})

function elapsed(): string {
  const created = Date.parse(props.message.created_at ?? '')
  const start = Number.isNaN(created) ? now.value : created
  const seconds = Math.max(0, Math.floor((now.value - start) / TICK_MS))
  return `${String(Math.floor(seconds / SECONDS_PER_MINUTE))}:${String(seconds % SECONDS_PER_MINUTE).padStart(2, '0')}`
}

// The settings this item was made with (see utils/cardSpecs)
const params = computed(() => cardParams(props.item.params))
const specs = computed(() => cardSpecs(props.item.kind, params.value))

// Hovering "🔗 4 refs" shows the reference images. Teleported and fixed so
// the caption's overflow clipping doesn't cut it off.
const refsPeek = ref<{ params: CardParams; x: number; y: number } | null>(null)
function showRefs(event: MouseEvent, shown: CardParams): void {
  if (!(event.currentTarget instanceof HTMLElement)) return
  const rect = event.currentTarget.getBoundingClientRect()
  refsPeek.value = { params: shown, x: rect.left, y: rect.top }
}

const mediaUrl = (item: MediaCard): string => chatMediaUrl(props.convId, item.file ?? '')
// What's shown in the chat: a scaled-down copy (a big chat's full images add up)
const mediaPreview = (item: MediaCard): string => chatMediaPreviewUrl(props.convId, item.file ?? '')

const canPin = (item: MediaCard): boolean => canPinMedia(item, props.message)
const big = (item: MediaCard): GenerationItem => bigView(item, props.message, props.convId)

const canRemake = (item: MediaCard): boolean =>
  item.status === 'done' && item.source === 'generated' && !!item.prompt && props.message.status !== 'streaming'

// A card's pictures, oldest first. The one showing is the real one — what
// the chat sends as context and references from then on — so the arrows ask
// the server to swap it in (`version_shown` is its place among them all; a
// failed redo has no picture, so it isn't one of them).
const versionsOf = (item: MediaCard) => item.versions ?? []
const versionCount = (item: MediaCard): number => versionsOf(item).length + (item.file ? 1 : 0)
const versionAt = (item: MediaCard): number => item.version_shown ?? versionsOf(item).length
function stepVersion(item: MediaCard, by: number): void {
  const next = versionAt(item) + by
  if (next >= 0 && next < versionCount(item)) emit('media-version', { mediaId: item.id, index: next })
}

// The box the pencil and Redo open: one prompt, applied to this picture alone.
// `edit` sends the picture back as the reference; Redo just re-runs the words.
// Either can take reference pictures too: Redo starts with the ones the card
// was made from (take any away or add more); an edit starts with none, since
// the picture itself is the reference.
interface PromptState {
  mediaId: string
  edit: boolean
  text: string
  /** Pictures it began with, to tell whether they were changed. */
  start: string[]
  refs: string[]
}
const promptBox = ref<PromptState | null>(null)
function openPrompt(item: MediaCard, edit: boolean): void {
  const start = edit ? [] : cardRefFiles(item.params)
  promptBox.value = { mediaId: item.id, edit, text: edit ? '' : (item.prompt ?? ''), start, refs: [...start] }
}
// How many pictures the card's model takes (a video model's own limits; images take the usual most)
function refLimit(item: MediaCard): number | undefined {
  if (item.kind !== 'video') return undefined
  return videoImageLimit(chatModels.video.find(m => m.id === item.model))
}
const sameFiles = (a: readonly string[], b: readonly string[]): boolean =>
  a.length === b.length && a.every((file, i) => file === b[i])
function submitPrompt(item: MediaCard): void {
  const box = promptBox.value
  if (!box?.text.trim()) return
  promptBox.value = null
  // Pictures are sent only when they differ from what the card already had
  const changed = box.edit ? box.refs.length > 0 : !sameFiles(box.refs, box.start)
  emit('regenerate', {
    mediaId: item.id,
    model: item.model ?? null,
    prompt: box.text.trim(),
    edit: box.edit,
    replace: true,
    ...(changed ? { refs: box.refs } : {}),
  })
}

const { copiedKey, copy } = useCopy()
// The media item whose provider request and response are open (RequestDialog)
const requestItem = ref<MediaCard | null>(null)
</script>

<template>
  <div class="media-item" :class="[item.kind, { failed: item.status === 'error' }]">
    <template v-if="item.status === 'done' && item.file">
      <img
        v-if="item.kind === 'image'"
        :src="mediaPreview(item)"
        :alt="item.prompt || 'generated image'"
        loading="lazy"
        decoding="async"
        @click="emit('open-media', big(item))"
      />
      <audio v-else-if="item.kind === 'audio'" :src="mediaUrl(item)" class="media-audio" controls></audio>
      <video v-else :src="mediaUrl(item)" controls loop playsinline preload="metadata"></video>
      <div v-if="versionsOf(item).length" class="ver-nav" @click.stop>
        <button
          :disabled="!canSwitch || versionAt(item) === 0"
          title="Earlier version — it becomes the picture the chat uses"
          @click="stepVersion(item, -1)"
        >
          ‹
        </button>
        <span :title="`Version ${versionAt(item) + 1}: ${item.prompt || ''}`">
          {{ versionAt(item) + 1 }}/{{ versionCount(item) }}
        </span>
        <button
          :disabled="!canSwitch || versionAt(item) >= versionCount(item) - 1"
          title="Later version — it becomes the picture the chat uses"
          @click="stepVersion(item, 1)"
        >
          ›
        </button>
      </div>
      <PinButton
        v-if="canPin(item)"
        :pinned="!!item.pinned"
        @toggle="emit('pin', { mediaId: item.id, pinned: !item.pinned })"
      />
      <div class="media-overlay">
        <template v-if="item.kind === 'image'">
          <button
            class="media-btn"
            title="Attach this picture and switch to Image mode"
            @click.stop="emit('use-image', { file: item.file, mode: 'image' })"
          >
            <svg class="ic"><use href="#s-image" /></svg>
          </button>
          <button
            class="media-btn"
            title="Attach this picture and switch to Video mode"
            @click.stop="emit('use-image', { file: item.file, mode: 'video' })"
          >
            <svg class="ic"><use href="#s-film" /></svg>
          </button>
        </template>
        <a :href="mediaUrl(item)" :download="item.file" class="media-btn" title="Download" @click.stop>
          <svg class="ic"><use href="#s-download" /></svg>
        </a>
      </div>
    </template>

    <div v-else-if="item.status === 'pending'" class="media-pending">
      <div class="shimmer"></div>
      <div class="pending-label">
        <div class="spinner"></div>
        <span v-if="item.kind === 'image'">Creating image…</span>
        <span v-else-if="item.kind === 'audio'">Composing audio… {{ elapsed() }}</span>
        <span v-else>Rendering video… {{ elapsed() }}</span>
      </div>
      <div v-if="specs.length" class="pending-specs">{{ specs.join(' · ') }}</div>
      <div v-if="item.prompt" class="pending-prompt" :title="item.prompt">{{ item.prompt }}</div>
    </div>

    <div v-else class="media-error">
      <strong>
        {{ KIND_LABEL[item.kind] || 'Video' }}
        {{ item.moderated ? 'blocked by moderation' : 'failed' }}
      </strong>
      <span>{{ item.error || 'Unknown error' }}</span>
      <!-- Nothing retries automatically — the user picks -->
      <div v-if="item.source === 'generated' && item.prompt && message.status !== 'streaming'" class="error-actions">
        <button
          v-if="versionsOf(item).length && canSwitch"
          class="retry-btn"
          title="Keep the picture this card had before the attempt that failed"
          @click="emit('media-version', { mediaId: item.id, index: versionsOf(item).length - 1 })"
        >
          ‹ Back to the previous picture
        </button>
        <button
          class="retry-btn primary"
          title="Run the same prompt again, on the model selected now"
          @click="emit('regenerate', { mediaId: item.id, model: null })"
        >
          Try again
        </button>
        <button class="retry-btn" title="Edit the prompt, then run it again" @click="openPrompt(item, false)">
          Try a new prompt…
        </button>
        <ModelPicker
          :model-value="''"
          :models="chatModels[item.kind] || []"
          :kind="item.kind"
          :label="KIND_LABEL[item.kind] || 'Video'"
          :allow-none="false"
          trigger-text="Try another model…"
          @update:model-value="model => model && emit('regenerate', { mediaId: item.id, model })"
        />
      </div>
    </div>

    <!-- Which model made this and with what — the footer only names the chat model -->
    <div v-if="item.model || item.prompt" class="media-caption">
      <div class="foot-info" :title="[item.model, ...specs].join(' · ')">
        <span class="foot-model">
          <svg class="ic sm"><use :href="KIND_ICON[item.kind] || '#s-film'" /></svg>{{ shortModel(item.model) }}
        </span>
        <span v-if="specs.length" class="foot-specs">{{ specs.join(' · ') }}</span>
        <span v-if="item.cost" class="chip">{{ fmtCost(item.cost) }}</span>
        <span v-if="item.credits" class="chip" title="Billed to your Pollo account"
          >{{ item.credits }} credit{{ item.credits === 1 ? '' : 's' }}</span
        >
        <span v-if="params.context" class="chip" title="The image model was given the conversation">
          <svg class="ic sm"><use href="#s-chat" /></svg>context
        </span>
        <span
          v-if="params.refs.length"
          class="chip caption-refs"
          @mouseenter="showRefs($event, params)"
          @mouseleave="refsPeek = null"
        >
          <svg class="ic sm"><use href="#s-link" /></svg>{{ refsLabel(params) }}
        </span>
        <span v-if="params.upload_notice" class="chip caption-warn" :title="params.upload_notice">
          <svg class="ic sm"><use href="#s-warn" /></svg>backup upload host
        </span>
      </div>
      <div class="foot-actions">
        <button
          v-if="canRemake(item) && item.kind === 'image' && item.file"
          class="iconbtn boxed"
          title="Edit this picture: describe the change and it is replaced here"
          @click="openPrompt(item, true)"
        >
          <svg class="ic"><use href="#s-pencil" /></svg>
        </button>
        <button
          v-if="canRemake(item)"
          class="iconbtn boxed"
          title="Make it again: tweak the prompt and it is replaced here"
          @click="openPrompt(item, false)"
        >
          <svg class="ic"><use href="#s-refresh" /></svg>
        </button>
        <button
          v-if="item.prompt"
          class="iconbtn boxed"
          :class="{ on: copiedKey === item.id }"
          :title="`Copy the prompt sent to the ${item.kind} model:\n${item.prompt}`"
          @click="copy(item.prompt, item.id)"
        >
          <svg class="ic"><use :href="copiedKey === item.id ? '#s-check' : '#s-copy'" /></svg>
        </button>
        <button
          v-if="item.request"
          class="iconbtn boxed"
          title="Show exactly what was sent to the provider"
          @click="requestItem = item"
        >
          <svg class="ic"><use href="#s-code" /></svg>
        </button>
      </div>
    </div>
    <PromptBox
      v-if="promptBox?.mediaId === item.id"
      v-model="promptBox.text"
      v-model:refs="promptBox.refs"
      :conv-id="convId"
      :start-refs="promptBox.start"
      :ref-limit="refLimit(item)"
      :placeholder="promptBox.edit ? 'Describe the change…' : 'Prompt for the new version…'"
      :hint="promptBox.edit ? 'Edits this picture' : 'Makes a new one from the prompt alone'"
      :submit-label="promptBox.edit ? 'Edit' : 'Redo'"
      @submit="submitPrompt(item)"
      @cancel="promptBox = null"
    />
  </div>
  <RequestDialog
    v-if="requestItem"
    :request="requestItem.request"
    :response="requestItem.response"
    :error="requestItem.status === 'error' ? (requestItem.error ?? '') : ''"
    @close="requestItem = null"
  />
  <Teleport to="body">
    <div v-if="refsPeek" class="refs-peek" :style="{ left: `${refsPeek.x}px`, top: `${refsPeek.y}px` }">
      <div class="refs-peek-title">{{ refsTitle(refsPeek.params) }}</div>
      <div class="refs-peek-grid">
        <img
          v-for="(r, i) in refsPeek.params.refs"
          :key="r"
          :src="refUrl(convId, r)"
          :alt="r"
          :class="{ unused: refsPeek.params.refs_used != null && i >= refsPeek.params.refs_used }"
        />
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.media-item {
  position: relative;
  border-radius: var(--r-lg);
  overflow: hidden;
  background: var(--sbg);
  border: 1px solid var(--sborder);
}
.media-item img,
.media-item video {
  display: block;
  width: 100%;
  height: auto;
  max-height: 560px;
  object-fit: contain;
  background: #000;
}
.media-item img {
  cursor: zoom-in;
}
.media-overlay {
  position: absolute;
  top: 8px;
  right: 8px;
  opacity: 0;
  transition: opacity 0.2s;
}
.media-item:hover .media-overlay {
  opacity: 1;
}
.media-overlay {
  display: flex;
  gap: 6px;
}
.media-btn {
  border: none;
  cursor: pointer;
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.65);
  color: white;
  text-decoration: none;
  font-size: 1rem;
}
/* Under the picture: what made it (left), what you can do with it (right).
   The two wrap onto separate lines on a narrow card. */
.media-caption {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  padding: 8px 10px;
  font-size: 12px;
  color: var(--smuted);
  border-top: 1px solid var(--sborder);
}
.foot-info {
  display: flex;
  flex: 1 1 200px;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  min-width: 0;
}
.foot-model {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  color: var(--sfg);
  font-size: 13px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.foot-specs {
  color: var(--smuted);
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border: 1px solid var(--sborder);
  border-radius: 6px;
  background: var(--shover);
  color: var(--smuted);
  font-size: 11.5px;
  white-space: nowrap;
}
.foot-actions {
  display: flex;
  gap: 6px;
  margin-left: auto;
}
.chip.caption-warn {
  color: var(--swarn);
  border-color: color-mix(in srgb, var(--swarn) 45%, transparent);
  cursor: help;
}
.chip.caption-refs {
  cursor: default;
}
.refs-peek {
  position: fixed;
  z-index: 1000;
  transform: translateY(calc(-100% - 6px));
  max-width: 340px;
  padding: 8px;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  box-shadow: var(--shadow-pop);
  font-size: 0.72rem;
  color: var(--text2);
  pointer-events: none;
}
.refs-peek-title {
  margin-bottom: 6px;
}
.refs-peek-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.refs-peek-grid img {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 4px;
  background: var(--surface2);
}
.refs-peek-grid img.unused {
  opacity: 0.35;
}
.media-pending {
  position: relative;
  aspect-ratio: 16 / 10;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 16px;
  overflow: hidden;
}
.media-item.image .media-pending {
  aspect-ratio: 1;
}
.shimmer {
  position: absolute;
  inset: 0;
  background: linear-gradient(110deg, transparent 30%, var(--saccent-soft) 50%, transparent 70%);
  background-size: 200% 100%;
  animation: shimmer 1.8s linear infinite;
}
@keyframes shimmer {
  from {
    background-position: 200% 0;
  }
  to {
    background-position: -200% 0;
  }
}
.pending-label {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
}
.pending-specs {
  position: relative;
  font-size: 0.75rem;
  color: var(--accent2);
}
.pending-prompt {
  position: relative;
  font-size: 0.75rem;
  color: var(--text2);
  text-align: center;
  max-width: 90%;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.media-error {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  font-size: 0.82rem;
  color: var(--sdanger);
  background: var(--sdanger-soft);
}
.media-error span {
  color: var(--text2);
  word-break: break-word;
}
/* Failed cards host the model-picker popup, so they mustn't clip it */
.media-item.failed {
  overflow: visible;
}
.media-item.failed .media-error {
  border-radius: var(--r-lg) var(--r-lg) 0 0;
}
.error-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}
.retry-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 4px 10px;
  color: var(--text);
  font-size: 0.78rem;
  cursor: pointer;
}
.retry-btn:hover {
  border-color: var(--accent);
}
/* The one action the card is suggesting */
.retry-btn.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  font-weight: 600;
}
.media-item .media-audio {
  display: block;
  width: 100%;
  min-width: 260px;
}
/* ‹ 1/2 › over a picture that has earlier versions */
.ver-nav {
  position: absolute;
  bottom: 6px;
  left: 6px;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 1px 4px;
  border-radius: 999px;
  background: rgb(0 0 0 / 55%);
  color: #fff;
  font-size: 0.72rem;
  opacity: 0;
  transition: opacity 0.12s;
}
.media-item:hover .ver-nav,
.ver-nav:focus-within {
  opacity: 1;
}
.ver-nav button {
  padding: 0 3px;
  border: none;
  background: none;
  color: inherit;
  font-size: 0.9rem;
  line-height: 1;
  cursor: pointer;
}
.ver-nav button:disabled {
  opacity: 0.35;
  cursor: default;
}
</style>
