<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { GenerationItem, ImagePick, RegenerateRequest, UiMessage } from '../../composables/studioTypes'
import ChatMessage from '../chat/ChatMessage.vue'

const props = withDefaults(
  defineProps<{
    messages?: readonly UiMessage[] | undefined
    active?: string | null | undefined
    sending?: boolean | undefined
    lastAssistantId?: number | string | null | undefined
  }>(),
  { messages: () => [], active: null, sending: false, lastAssistantId: null },
)
defineEmits<{
  retry: [message: UiMessage]
  edit: [message: UiMessage, text: string]
  resend: [message: UiMessage]
  branch: [id: number]
  'use-image': [pick: ImagePick]
  reword: [message: UiMessage, instruction: string]
  'text-version': [message: UiMessage, index: number]
  'media-version': [message: UiMessage, pick: { mediaId: string; index: number }]
  regenerate: [message: UiMessage, request: RegenerateRequest]
  pin: [message: UiMessage, pick: { mediaId: string; pinned: boolean }]
  delete: [message: UiMessage]
  fork: [message: UiMessage]
  'open-chat': [id: string]
  stop: []
  'open-media': [item: GenerationItem]
}>()

const NEAR_BOTTOM_PX = 200
const scroller = ref<HTMLElement | null>(null)
function scrollToBottom(force = false): void {
  void nextTick(() => {
    const el = scroller.value
    if (!el) return
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
    if (force || near) el.scrollTop = el.scrollHeight
  })
}
// Follow new messages, and streaming text on the last one
watch(
  () => props.messages.length,
  () => {
    scrollToBottom(true)
  },
)
watch(
  () => props.messages.at(-1)?.content,
  () => {
    scrollToBottom()
  },
)
watch(
  () => props.active,
  () => {
    scrollToBottom(true)
  },
)
</script>

<template>
  <div ref="scroller" class="feed">
    <div v-if="!props.messages.length" class="empty">
      {{ active ? 'No messages yet.' : 'Start a new thread — type below.' }}
    </div>
    <div v-else class="finner">
      <ChatMessage
        v-for="m in messages"
        :key="m.id"
        :message="m"
        :conv-id="active || ''"
        :can-retry="m.id === lastAssistantId && !sending"
        :can-edit="m.role === 'user' && typeof m.id === 'number' && !sending"
        :can-switch="!sending"
        :can-branch="typeof m.id === 'number' && !sending && m.status !== 'streaming'"
        :can-reword="m.role === 'assistant' && typeof m.id === 'number' && !sending && m.status !== 'streaming'"
        @retry="$emit('retry', m)"
        @edit="content => $emit('edit', m, content)"
        @resend="$emit('resend', m)"
        @branch="$emit('branch', $event)"
        @use-image="$emit('use-image', $event)"
        @reword="instruction => $emit('reword', m, instruction)"
        @text-version="index => $emit('text-version', m, index)"
        @media-version="payload => $emit('media-version', m, payload)"
        @regenerate="payload => $emit('regenerate', m, payload)"
        @pin="payload => $emit('pin', m, payload)"
        @delete="$emit('delete', m)"
        @fork="$emit('fork', m)"
        @open-chat="$emit('open-chat', $event)"
        @stop="$emit('stop')"
        @open-media="$emit('open-media', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
.feed {
  flex: 1;
  overflow-y: auto;
  padding: 1.2rem 1.4667rem;
}
.empty {
  color: var(--sfaint);
}
.finner {
  max-width: 54.6667rem;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 0.2667rem;
}
</style>
