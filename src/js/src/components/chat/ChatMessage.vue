<script setup lang="ts">
import { computed, ref, nextTick } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { GenerationItem, ImagePick, RegenerateRequest, UiMessage } from '../../composables/studioTypes'
import { useCopy } from '../../composables/useClipboard'
import { shortModel, fmtCost } from '../../utils/format'
import ChatAttachments from './ChatAttachments.vue'
import ChatMediaCard from './ChatMediaCard.vue'
import ForkList from './ForkList.vue'
import PromptBox from './PromptBox.vue'

const props = withDefaults(
  defineProps<{
    message: UiMessage
    convId: string
    canRetry?: boolean | undefined
    canEdit?: boolean | undefined
    /** The ‹ › arrows are usable (not mid-reply). */
    canSwitch?: boolean | undefined
    /** ⑂ Branch on a reply (prompts go with canEdit). */
    canBranch?: boolean | undefined
    /** Edit / Redo a finished reply's text in place. */
    canReword?: boolean | undefined
  }>(),
  { canRetry: false, canEdit: false, canSwitch: false, canBranch: false, canReword: false },
)
const emit = defineEmits<{
  retry: []
  'open-media': [item: GenerationItem]
  stop: []
  edit: [text: string]
  resend: []
  regenerate: [request: RegenerateRequest]
  branch: [id: number]
  'use-image': [pick: ImagePick]
  reword: [instruction: string]
  'text-version': [index: number]
  'media-version': [pick: { mediaId: string; index: number }]
  pin: [pick: { mediaId: string; pinned: boolean }]
  delete: []
  fork: []
  'open-chat': [id: string]
}>()

marked.setOptions({ gfm: true, breaks: true })

const isUser = computed(() => props.message.role === 'user')
const streaming = computed(() => props.message.status === 'streaming')
// Models sometimes echo a "[generated image: <prompt>]" line in their reply
// (older chat history recorded media that way). The image itself is shown
// below, so hide those lines — display only; the stored reply is untouched.
const MEDIA_NOTE_LINE =
  /^[ \t]*\[(?:generated (?:image|video)|(?:image|video) (?:rendering|failed))\b[^\n]*\][ \t]*$/gim
const displayText = computed(() =>
  props.message.content
    .replace(MEDIA_NOTE_LINE, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim(),
)
const html = computed(() => {
  if (!displayText.value) return ''
  return DOMPurify.sanitize(marked.parse(displayText.value, { async: false }))
})
// Image/Video mode failures already show on the media card — don't repeat them
const errorShownOnMedia = computed(() =>
  props.message.media.some(m => m.status === 'error' && m.error === props.message.error),
)
const modelShort = computed(() => shortModel(props.message.model))
// Media-only replies (Image/Video mode) have no text model to name
const showTextModel = computed(() => !!props.message.content || !props.message.media.length)

// Prompts sent outside Auto mode say so — an edit or retry reruns them in that mode
const MODE_TAGS: Readonly<Record<string, string>> = { image: '🖼 Image', video: '🎬 Video', text: '💬 Text only' }
const modeTag = computed(() => MODE_TAGS[props.message.mode ?? ''] ?? '')

// The reply's text on its own: Edit (say how to change it) or Redo (write it
// again) replaces just the words; the pictures stay. Each wording is kept and
// the ‹ › under the text switch between them, apart from the pictures' own.
const textVersions = computed(() => props.message.text_versions)
const textShown = computed(() => props.message.text_shown)
const hasPendingMedia = computed(() => props.message.media.some(m => m.status === 'pending'))
const canRewordNow = computed(() => props.canReword && !hasPendingMedia.value)
const textBox = ref<{ text: string } | null>(null) // while the Edit text box is open

function submitTextEdit(): void {
  const text = textBox.value?.text.trim()
  if (!text) return
  textBox.value = null
  emit('reword', text)
}
function stepText(by: number): void {
  const next = textShown.value + by
  if (next >= 0 && next < textVersions.value) emit('text-version', next)
}

// Branches: other versions of this turn (from edits/retries)
const siblings = computed(() => props.message.siblings)
const branchIndex = computed(() => siblings.value.indexOf(Number(props.message.id)))
function goBranch(step: number): void {
  const id = siblings.value[branchIndex.value + step]
  if (id !== undefined) emit('branch', id)
}

const editing = ref(false)
const editText = ref('')
const editBox = ref<HTMLTextAreaElement | null>(null)
const EDIT_BOX_MAX_PX = 320

function fitEditBox(): void {
  const el = editBox.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${String(Math.min(el.scrollHeight, EDIT_BOX_MAX_PX))}px`
}

function startEdit(): void {
  editText.value = props.message.content
  editing.value = true
  void nextTick(() => {
    const el = editBox.value
    if (!el) return
    fitEditBox()
    el.focus({ preventScroll: true })
    el.setSelectionRange(el.value.length, el.value.length)
    el.closest('.msg')?.scrollIntoView({ block: 'nearest' })
  })
}

function submitEdit(): void {
  const text = editText.value.trim()
  if (!text && !props.message.media.length) return
  editing.value = false
  if (text !== props.message.content.trim()) emit('edit', text)
}

function onEditKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submitEdit()
  }
  if (event.key === 'Escape') editing.value = false
}

const { copiedKey, copy } = useCopy()
</script>

<template>
  <div class="msg" :class="isUser ? 'msg-user' : 'msg-assistant'">
    <div v-if="!isUser" class="avatar">✦</div>

    <div class="msg-body">
      <!-- User attachments sit above their text, like Gemini -->
      <ChatAttachments
        v-if="isUser && message.media?.length"
        :message="message"
        :conv-id="convId"
        @open-media="emit('open-media', $event)"
        @use-image="emit('use-image', $event)"
        @pin="emit('pin', $event)"
      />

      <div v-if="isUser && editing" class="edit-box">
        <textarea ref="editBox" v-model="editText" rows="1" @input="fitEditBox" @keydown="onEditKeydown"></textarea>
        <div class="edit-actions">
          <span class="edit-note">Sends as a new branch — the original stays available with the ‹ › arrows.</span>
          <button class="meta-btn" @click="editing = false">Cancel</button>
          <button class="edit-send" :disabled="!editText.trim() && !message.media?.length" @click="submitEdit">
            Send
          </button>
        </div>
      </div>
      <div v-else-if="isUser && message.content" class="bubble">{{ message.content }}</div>
      <div
        v-if="
          isUser && !editing && (canEdit || message.content || siblings.length > 1 || modeTag || message.forks?.length)
        "
        class="user-actions"
      >
        <ForkList
          v-if="message.forks?.length"
          :forks="message.forks"
          align="right"
          @open="id => emit('open-chat', id)"
        />
        <span
          v-if="modeTag"
          class="mode-tag"
          :title="`Last run in ${modeTag} mode — retrying or editing uses the mode selected now`"
          >{{ modeTag }}</span
        >
        <span v-if="siblings.length > 1" class="branch-nav">
          <button
            class="meta-btn"
            :disabled="!canSwitch || branchIndex <= 0"
            title="Previous version"
            @click="goBranch(-1)"
          >
            ‹
          </button>
          <span>{{ branchIndex + 1 }}/{{ siblings.length }}</span>
          <button
            class="meta-btn"
            :disabled="!canSwitch || branchIndex >= siblings.length - 1"
            title="Next version"
            @click="goBranch(1)"
          >
            ›
          </button>
        </span>
        <button v-if="message.content" class="meta-btn" title="Copy prompt" @click="copy(message.content, 'prompt')">
          {{ copiedKey === 'prompt' ? '✓' : '⧉' }}
        </button>
        <template v-if="canEdit">
          <button class="meta-btn" title="Edit and resend" @click="startEdit">✎</button>
          <button class="meta-btn" title="Resend this prompt for a different response" @click="emit('resend')">
            ↻
          </button>
          <button
            class="meta-btn"
            title="Start a new chat from here: everything up to this prompt and its reply, nothing after"
            @click="emit('fork')"
          >
            ⑂
          </button>
          <button
            class="meta-btn"
            title="Delete this prompt and its reply from the chat (images and videos stay in Media)"
            @click="emit('delete')"
          >
            🗑
          </button>
        </template>
      </div>

      <template v-if="!isUser">
        <!-- eslint-disable-next-line vue/no-v-html -- sanitised with DOMPurify (see `html`) -->
        <div v-if="html" class="markdown" v-html="html"></div>
        <div v-else-if="streaming && !message.media?.length" class="thinking">
          <span></span><span></span><span></span>
        </div>
        <span v-if="streaming && html" class="cursor"></span>
        <div v-if="textVersions > 1 && !streaming" class="text-ver">
          <button
            class="meta-btn"
            :disabled="!canSwitch || textShown <= 0"
            title="Earlier wording (the pictures stay as they are)"
            @click="stepText(-1)"
          >
            ‹
          </button>
          <span title="Wordings of this reply's text — the one shown is what the chat continues from"
            >text {{ textShown + 1 }}/{{ textVersions }}</span
          >
          <button
            class="meta-btn"
            :disabled="!canSwitch || textShown >= textVersions - 1"
            title="Later wording (the pictures stay as they are)"
            @click="stepText(1)"
          >
            ›
          </button>
        </div>
        <PromptBox
          v-if="textBox"
          v-model="textBox.text"
          class="text-box"
          placeholder="How should the text change? e.g. shorter, funnier, in French…"
          hint="Rewrites the text only — the pictures stay"
          submit-label="Edit"
          @submit="submitTextEdit"
          @cancel="textBox = null"
        />

        <div v-if="message.media?.length" class="media-grid" :class="{ single: message.media.length === 1 }">
          <ChatMediaCard
            v-for="item in message.media"
            :key="item.id"
            :item="item"
            :message="message"
            :conv-id="convId"
            :can-switch="canSwitch"
            @open-media="emit('open-media', $event)"
            @media-version="emit('media-version', $event)"
            @pin="emit('pin', $event)"
            @use-image="emit('use-image', $event)"
            @regenerate="emit('regenerate', $event)"
          />
        </div>

        <div v-if="message.status === 'error' && message.error && !errorShownOnMedia" class="msg-error">
          ⚠ {{ message.error }}
        </div>

        <div class="msg-meta">
          <span v-if="siblings.length > 1" class="branch-nav">
            <button
              class="meta-btn"
              :disabled="!canSwitch || branchIndex <= 0"
              title="Previous version"
              @click="goBranch(-1)"
            >
              ‹
            </button>
            <span>{{ branchIndex + 1 }}/{{ siblings.length }}</span>
            <button
              class="meta-btn"
              :disabled="!canSwitch || branchIndex >= siblings.length - 1"
              title="Next version"
              @click="goBranch(1)"
            >
              ›
            </button>
          </span>
          <button v-if="streaming" class="meta-btn" @click="emit('stop')">■ Stop</button>
          <template v-else>
            <button v-if="displayText" class="meta-btn" title="Copy reply" @click="copy(displayText, 'reply')">
              {{ copiedKey === 'reply' ? '✓' : '⧉' }}
            </button>
            <template v-if="canRewordNow">
              <button
                v-if="displayText"
                class="meta-btn"
                title="Edit text: say how to change these words and they are replaced here. The pictures stay; the old words are kept (‹ › on the text)."
                @click="textBox = { text: '' }"
              >
                <svg class="ic sm"><use href="#s-pencil" /></svg> Edit text
              </button>
              <button
                v-if="message.media?.length"
                class="meta-btn"
                title="Redo text: write these words again and replace them here. The pictures stay; the old words are kept (‹ › on the text)."
                @click="emit('reword', '')"
              >
                <svg class="ic sm"><use href="#s-refresh" /></svg> Redo text
              </button>
            </template>
            <button
              v-if="canRetry"
              class="meta-btn"
              title="Retry: a fresh version of this whole reply, pictures included, kept beside this one — use ‹ › to compare."
              @click="emit('retry')"
            >
              <svg class="ic sm"><use href="#s-refresh" /></svg> Retry
            </button>
            <button
              v-if="canBranch"
              class="meta-btn"
              title="Start a new chat from here: everything up to this reply, nothing after"
              @click="emit('fork')"
            >
              ⑂
            </button>
          </template>
          <ForkList v-if="message.forks?.length" :forks="message.forks" @open="id => emit('open-chat', id)" />
          <span class="meta-spacer"></span>
          <span v-if="modelShort && showTextModel" class="meta-info model" :title="message.model ?? undefined"
            >💬 {{ modelShort }}</span
          >
          <span v-if="message.cost" class="meta-info" title="Total OpenRouter cost for this reply (text + media)"
            >total {{ fmtCost(message.cost) }}</span
          >
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped src="./chatButtons.css"></style>
<style scoped src="./ChatMessage.css"></style>
