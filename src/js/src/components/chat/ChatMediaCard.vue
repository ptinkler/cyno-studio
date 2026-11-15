<!-- One generated picture, video or audio clip on a reply: the media, its versions, pending / failed states,
     the caption (model, settings, cost) and the actions on it (redo, edit, copy prompt, show request). -->
<script setup>
import { ref, inject, onMounted, onBeforeUnmount } from 'vue'
import { chatMediaPreviewUrl, chatMediaUrl } from '../../composables/useChat'
import { characterImageUrl } from '../../composables/useCharacters'
import { useCopy } from '../../composables/useClipboard'
import { shortModel, fmtCost } from '../../utils/format'
import { canPinMedia } from '../../utils/chatMedia'
import ModelPicker from './ModelPicker.vue'
import PinButton from './PinButton.vue'
import PromptBox from './PromptBox.vue'
import RequestDialog from './RequestDialog.vue'

const props = defineProps({
  item: { type: Object, required: true }, // one of the reply's media items
  message: { type: Object, required: true }, // the reply holding it
  convId: { type: String, required: true },
  canSwitch: { type: Boolean, default: false }, // ‹ › arrows usable (not mid-reply)
})
const emit = defineEmits(['open-media', 'media-version', 'pin', 'use-image', 'regenerate'])

// Model catalogues, provided by ChatView, for "Try another model"
const KIND_LABEL = { image: 'Image', video: 'Video', audio: 'Audio' }
const KIND_ICON = { image: '🖼', video: '🎬', audio: '🔊' }
const chatModels = inject('chatModels', { image: [], video: [], audio: [] })

// Ticking clock for "rendering 1:23" on pending videos
const now = ref(Date.now())
let timer = null
onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})
onBeforeUnmount(() => clearInterval(timer))

function elapsed() {
  const start = Date.parse(props.message.created_at) || now.value
  const s = Math.max(0, Math.floor((now.value - start) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// The settings a generated item was made with. For Pollo these are what was
// actually sent (defaults included); for OpenRouter only what we asked for —
// the provider fills in the rest without saying.
function specs(item) {
  const p = item.params || {}
  const isVideo = item.kind === 'video'
  return [
    ...(isVideo ? videoSource(p) : []),
    isVideo && p.duration && `${p.duration}s`,
    p.resolution,
    p.aspect_ratio,
    isVideo && p.generate_audio != null && (p.generate_audio ? 'audio' : 'no audio'),
    p.character_names?.length && `👤 ${p.character_names.join(', ')}`,
  ].filter(Boolean)
}

// What a video was made from, besides its prompt
function videoSource(p) {
  const frames = p.last_frame ? 'first+last frame' : p.first_frame && !p.refs?.length && 'from image'
  return [p.source_video && 'from video', frames]
}

// "4 refs", or "2 of 4 refs" when the model took fewer than were picked
// (Venice edit models cap the count; the first ones win)
function refsLabel(p) {
  const n = p.refs.length
  const used = p.refs_used
  return used != null && used < n ? `${used} of ${n} refs` : `${n} ref${n === 1 ? '' : 's'}`
}
function refsTitle(p) {
  const used = p.refs_used
  return used != null && used < p.refs.length
    ? `The model takes ${used} image${used === 1 ? '' : 's'}, so only the first ${used} of these were sent:`
    : 'Based on these images:'
}
// A ref is a chat file or a character image ("char:<id>/<file>")
function refUrl(r) {
  const m = /^char:(\d+)\/(.+)$/.exec(r)
  return m ? characterImageUrl(m[1], m[2]) : chatMediaUrl(props.convId, r)
}

// Hovering "🔗 4 refs" shows the reference images. Teleported and fixed so
// the caption's overflow clipping doesn't cut it off.
const refsPeek = ref(null) // { params, x, y }
function showRefs(e, params) {
  const r = e.currentTarget.getBoundingClientRect()
  refsPeek.value = { params, x: r.left, y: r.top }
}

const mediaUrl = item => chatMediaUrl(props.convId, item.file)
// What's shown in the chat: a scaled-down copy (a big chat's full images add up)
const mediaPreview = item => chatMediaPreviewUrl(props.convId, item.file)

const canPin = item => canPinMedia(item, props.message)
// What the big view (GenerationModal) needs: everything the card knows, plus
// where it lives, so its actions can act on the right message.
const bigView = item => ({
  ...item,
  url: mediaUrl(item),
  message_id: props.message.id,
  conversation_id: props.convId,
})

const canRemake = item =>
  item.status === 'done' && item.source === 'generated' && !!item.prompt && props.message.status !== 'streaming'

// A card's pictures, oldest first. The one showing is the real one — what
// the chat sends as context and references from then on — so the arrows ask
// the server to swap it in (`version_shown` is its place among them all; a
// failed redo has no picture, so it isn't one of them).
const versionsOf = item => item.versions || []
const versionCount = item => versionsOf(item).length + (item.file ? 1 : 0)
const versionAt = item => item.version_shown ?? versionsOf(item).length
const stepVersion = (item, by) => {
  const next = versionAt(item) + by
  if (next >= 0 && next < versionCount(item)) emit('media-version', { mediaId: item.id, index: next })
}

// The box the pencil and Redo open: one prompt, applied to this picture alone.
// `edit` sends the picture back as the reference; Redo just re-runs the words.
const promptBox = ref(null)
const openPrompt = (item, edit) => (promptBox.value = { mediaId: item.id, edit, text: edit ? '' : item.prompt || '' })
function submitPrompt(item) {
  const box = promptBox.value
  if (!box?.text.trim()) return
  promptBox.value = null
  emit('regenerate', {
    mediaId: item.id,
    model: item.model || null,
    prompt: box.text.trim(),
    edit: box.edit,
    replace: true,
  })
}

const { copiedKey, copy } = useCopy()
// The media item whose provider request and response are open (RequestDialog)
const requestItem = ref(null)
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
        @click="emit('open-media', bigView(item))"
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
      <div v-if="specs(item).length" class="pending-specs">{{ specs(item).join(' · ') }}</div>
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

    <!-- Which model made this — the footer only names the chat model -->
    <div v-if="item.model || item.prompt" class="media-caption">
      <span class="caption-text" :title="[item.model, ...specs(item)].join(' · ')">
        {{ KIND_ICON[item.kind] || '🎬' }} {{ shortModel(item.model)
        }}<template v-if="specs(item).length">
          · <span class="caption-specs">{{ specs(item).join(' · ') }}</span></template
        ><template v-if="item.cost"> · {{ fmtCost(item.cost) }}</template
        ><template v-if="item.credits">
          ·
          <span title="Billed to your Pollo account"
            >{{ item.credits }} credit{{ item.credits === 1 ? '' : 's' }}</span
          ></template
        ><template v-if="item.params?.context">
          · <span title="The image model was given the conversation">💬 context</span></template
        ><template v-if="item.params?.refs?.length">
          ·
          <span class="caption-refs" title="" @mouseenter="showRefs($event, item.params)" @mouseleave="refsPeek = null"
            >🔗 {{ refsLabel(item.params) }}</span
          ></template
        ><template v-if="item.params?.upload_notice">
          · <span class="caption-warn" :title="item.params.upload_notice">⚠ backup upload host</span></template
        >
      </span>
      <button
        v-if="canRemake(item) && item.kind === 'image' && item.file"
        class="caption-btn"
        title="Edit this picture: describe the change and it is replaced here"
        @click="openPrompt(item, true)"
      >
        ✎ Edit
      </button>
      <button
        v-if="canRemake(item)"
        class="caption-btn"
        title="Make it again: tweak the prompt and it is replaced here"
        @click="openPrompt(item, false)"
      >
        ↻ Redo
      </button>
      <button
        v-if="item.prompt"
        class="caption-btn"
        :title="`Copy the prompt sent to the ${item.kind} model:\n${item.prompt}`"
        @click="copy(item.prompt, item.id)"
      >
        {{ copiedKey === item.id ? '✓ Copied' : '⧉ Prompt' }}
      </button>
      <button
        v-if="item.request"
        class="caption-btn"
        title="Show exactly what was sent to the provider"
        @click="requestItem = item"
      >
        { } Request
      </button>
    </div>
    <PromptBox
      v-if="promptBox?.mediaId === item.id"
      v-model="promptBox.text"
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
    :error="requestItem.status === 'error' ? requestItem.error : ''"
    @close="requestItem = null"
  />
  <Teleport to="body">
    <div v-if="refsPeek" class="refs-peek" :style="{ left: `${refsPeek.x}px`, top: `${refsPeek.y}px` }">
      <div class="refs-peek-title">{{ refsTitle(refsPeek.params) }}</div>
      <div class="refs-peek-grid">
        <img
          v-for="(r, i) in refsPeek.params.refs"
          :key="r"
          :src="refUrl(r)"
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
.media-caption {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px 4px 10px;
  font-size: 0.72rem;
  color: var(--text2);
  border-top: 1px solid var(--border);
}
.caption-text {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.caption-warn {
  color: var(--yellow);
  cursor: help;
}
.caption-refs {
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
.caption-btn {
  flex-shrink: 0;
  background: none;
  border: none;
  color: var(--text2);
  font-size: 0.72rem;
  padding: 3px 7px;
  border-radius: 6px;
  cursor: pointer;
}
.caption-btn:hover {
  background: var(--surface2);
  color: var(--text);
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
.caption-specs {
  color: var(--text);
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
