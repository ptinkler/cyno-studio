<script setup lang="ts">
import { vTip } from '../../directives/tip'
import { computed, ref, nextTick } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { GenerationItem, ImagePick, RegenerateRequest, UiMessage } from '../../composables/studioTypes'
import { useCopy } from '../../composables/useClipboard'
import { shortModel } from '../../utils/format'
import ChatAttachments from './ChatAttachments.vue'
import ChatMediaCard from './ChatMediaCard.vue'
import CostChip from './CostChip.vue'
import InfoTip from '../InfoTip.vue'
import ForkList from './ForkList.vue'
import PromptBox from './PromptBox.vue'
import ReplyControls from './ReplyControls.vue'
import VersionStepper from './VersionStepper.vue'

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
  delete: []
  fork: []
  'open-chat': [id: string]
}>()

marked.setOptions({ gfm: true, breaks: true })
// A link in a reply opens in a new tab (the chat is not left behind), and that page gets no handle back to this one
DOMPurify.addHook('afterSanitizeAttributes', node => {
  if (node.tagName === 'A' && node.hasAttribute('href')) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

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
const hasMedia = computed(() => props.message.media.length > 0)

// The bar under the words: Copy, Edit text, Redo text, the wordings' ‹ ›, and
// which model wrote them. A reply with no pictures also keeps its whole-reply
// controls here (one row); otherwise those go under the pictures.
const showCopy = computed(() => !streaming.value && !!displayText.value)
const showEditText = computed(() => !streaming.value && canRewordNow.value && !!displayText.value)
const canRedoText = computed(() => !streaming.value && canRewordNow.value && hasMedia.value)
const showRedoText = computed(() => canRedoText.value && !!displayText.value)
// A reply that is only pictures has no words to sit under, so Redo text goes under the pictures instead
const showRedoFoot = computed(() => canRedoText.value && !displayText.value)
const REDO_TEXT_TITLE = 'Redo text'
const showWordings = computed(() => textVersions.value > 1 && !streaming.value)
const showModel = computed(() => !!modelShort.value && showTextModel.value)
const showTextBar = computed(
  () => !hasMedia.value || showCopy.value || showRedoText.value || showWordings.value || showModel.value,
)

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

// The row under the pictures only appears when it has something in it
const hasReplyControls = computed(
  () =>
    showRedoFoot.value ||
    props.canRetry ||
    props.canBranch ||
    siblings.value.length > 1 ||
    !!props.message.forks?.length ||
    !!props.message.cost,
)
const showFoot = computed(() => hasMedia.value && (streaming.value || hasReplyControls.value))

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
        <InfoTip v-if="modeTag" :text="`Sent in ${modeTag} mode`"
          ><span class="mode-tag">{{ modeTag }}</span></InfoTip
        >
        <VersionStepper
          v-if="siblings.length > 1"
          class="branch-nav"
          :shown="branchIndex"
          :count="siblings.length"
          :enabled="canSwitch"
          prev-title="Previous version"
          next-title="Next version"
          @step="goBranch"
        />
        <button
          v-if="message.content"
          v-tip="'Copy prompt'"
          class="iconbtn boxed"
          :class="{ on: copiedKey === 'prompt' }"
          aria-label="Copy prompt"
          @click="copy(message.content, 'prompt')"
        >
          <svg class="ic"><use :href="copiedKey === 'prompt' ? '#s-check' : '#s-copy'" /></svg>
        </button>
        <template v-if="canEdit">
          <button v-tip="'Edit prompt'" class="iconbtn boxed" aria-label="Edit prompt" @click="startEdit">
            <svg class="ic"><use href="#s-pencil" /></svg>
          </button>
          <button v-tip="'Resend'" class="iconbtn boxed" aria-label="Resend" @click="emit('resend')">
            <svg class="ic"><use href="#s-repeat" /></svg>
          </button>
          <button v-tip="'Branch from here'" class="iconbtn boxed" aria-label="Branch from here" @click="emit('fork')">
            <svg class="ic"><use href="#s-branch" /></svg>
          </button>
          <button
            v-tip="'Delete prompt'"
            class="iconbtn boxed danger"
            aria-label="Delete prompt"
            @click="emit('delete')"
          >
            <svg class="ic"><use href="#s-trash" /></svg>
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

        <div v-if="message.status === 'error' && message.error && !errorShownOnMedia" class="msg-error">
          ⚠ {{ message.error }}
        </div>

        <!-- Controls for the words sit under the words, not under the pictures -->
        <div v-if="showTextBar" class="act-row text-bar">
          <button
            v-if="showCopy"
            v-tip="'Copy reply'"
            class="iconbtn boxed"
            :class="{ on: copiedKey === 'reply' }"
            aria-label="Copy reply"
            @click="copy(displayText, 'reply')"
          >
            <svg class="ic"><use :href="copiedKey === 'reply' ? '#s-check' : '#s-copy'" /></svg>
          </button>
          <button
            v-if="showEditText"
            v-tip="'Edit text'"
            class="iconbtn boxed"
            aria-label="Edit text"
            @click="textBox = { text: '' }"
          >
            <svg class="ic"><use href="#s-textedit" /></svg>
          </button>
          <button
            v-if="showRedoText"
            v-tip="REDO_TEXT_TITLE"
            class="iconbtn boxed"
            :aria-label="REDO_TEXT_TITLE"
            @click="emit('reword', '')"
          >
            <svg class="ic"><use href="#s-textredo" /></svg>
          </button>
          <VersionStepper
            v-if="showWordings"
            class="text-ver"
            label="text"
            :shown="textShown"
            :count="textVersions"
            :enabled="canSwitch"
            prev-title="Previous text"
            next-title="Next text"
            title="Text versions"
            @step="stepText"
          />
          <ReplyControls
            v-if="!hasMedia"
            :message="message"
            :streaming="streaming"
            :can-retry="canRetry"
            :can-switch="canSwitch"
            :can-branch="canBranch"
            @stop="emit('stop')"
            @retry="emit('retry')"
            @fork="emit('fork')"
            @branch="id => emit('branch', id)"
            @open-chat="id => emit('open-chat', id)"
          />
          <span class="meta-spacer"></span>
          <span v-if="showModel" v-tip="message.model ?? undefined" class="meta-info model">
            <svg class="ic sm"><use href="#s-chat" /></svg>{{ modelShort }}
          </span>
          <CostChip v-if="message.cost && !hasMedia" :total="message.cost" :media="message.media" />
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

        <div v-if="hasMedia" class="media-grid" :class="{ single: message.media.length === 1 }">
          <ChatMediaCard
            v-for="item in message.media"
            :key="item.id"
            :item="item"
            :message="message"
            :conv-id="convId"
            :can-switch="canSwitch"
            @open-media="emit('open-media', $event)"
            @media-version="emit('media-version', $event)"
            @use-image="emit('use-image', $event)"
            @regenerate="emit('regenerate', $event)"
          />
        </div>

        <!-- Controls for the reply as a whole, under everything it made -->
        <div v-if="showFoot" class="act-row msg-meta">
          <button
            v-if="showRedoFoot"
            v-tip="REDO_TEXT_TITLE"
            class="iconbtn boxed"
            :aria-label="REDO_TEXT_TITLE"
            @click="emit('reword', '')"
          >
            <svg class="ic"><use href="#s-textredo" /></svg>
          </button>
          <ReplyControls
            :message="message"
            :streaming="streaming"
            :can-retry="canRetry"
            :can-switch="canSwitch"
            :can-branch="canBranch"
            @stop="emit('stop')"
            @retry="emit('retry')"
            @fork="emit('fork')"
            @branch="id => emit('branch', id)"
            @open-chat="id => emit('open-chat', id)"
          />
          <span class="meta-spacer"></span>
          <CostChip v-if="message.cost" :total="message.cost" :media="message.media" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped src="./chatButtons.css"></style>
<style scoped src="./ChatMessage.css"></style>
