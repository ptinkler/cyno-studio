<script setup lang="ts">
import { vTip } from '../../directives/tip'
import type { MediaCard } from '../../composables/chatConversationsApi'
import { chatMediaPreviewUrl, chatMediaUrl } from '../../composables/chatFilesApi'
import type { GenerationItem, UiMessage } from '../../composables/studioTypes'
import { bigView } from '../../utils/chatMedia'

const props = defineProps<{ message: UiMessage; convId: string }>()
const emit = defineEmits<{
  'open-media': [item: GenerationItem]
  'use-image': [pick: { file: string | null | undefined; mode: 'image' | 'video' }]
}>()

// A card with no file yet (still rendering) has nothing to show
const fileOf = (item: MediaCard): string => item.file ?? ''
const mediaUrl = (item: MediaCard): string => chatMediaUrl(props.convId, fileOf(item))
// What's shown in the chat: a scaled-down copy (a big chat's full images add up)
const mediaPreview = (item: MediaCard): string => chatMediaPreviewUrl(props.convId, fileOf(item))
const big = (item: MediaCard): GenerationItem => bigView(item, props.message, props.convId)
</script>

<template>
  <div v-if="message.media?.length" class="attachments">
    <div v-for="item in message.media" :key="item.id" class="attachment">
      <audio v-if="item.kind === 'audio'" :src="mediaUrl(item)" class="attachment-audio" controls></audio>
      <img
        v-else
        :src="mediaPreview(item)"
        class="attachment-thumb"
        alt="attachment"
        loading="lazy"
        decoding="async"
        @click="emit('open-media', big(item))"
      />
      <span v-if="item.kind !== 'audio'" class="use-btns">
        <button
          v-tip="'Use in Image mode'"
          aria-label="Use in Image mode"
          @click="emit('use-image', { file: item.file, mode: 'image' })"
        >
          <svg class="ic sm"><use href="#s-image" /></svg>
        </button>
        <button
          v-tip="'Use in Video mode'"
          aria-label="Use in Video mode"
          @click="emit('use-image', { file: item.file, mode: 'video' })"
        >
          <svg class="ic sm"><use href="#s-film" /></svg>
        </button>
      </span>
    </div>
  </div>
</template>

<style scoped>
.attachments {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.4rem;
  margin-bottom: 0.4rem;
}
.attachment {
  position: relative;
}
.use-btns {
  position: absolute;
  top: 0.4rem;
  right: 0.4rem;
  display: flex;
  gap: 0.2667rem;
  opacity: 0;
  transition: opacity 0.15s;
}
.use-btns button {
  display: grid;
  place-items: center;
  width: 1.8667rem;
  height: 1.8667rem;
  border: none;
  border-radius: 0.5333rem;
  background: rgba(0, 0, 0, 0.65);
  color: rgba(255, 255, 255, 0.85);
  cursor: pointer;
}
.use-btns button:hover {
  color: #fff;
}
.attachment:hover .use-btns,
.use-btns:focus-within {
  opacity: 1;
}
@media (hover: none) {
  .use-btns {
    opacity: 1;
  }
}
.attachment-thumb {
  width: 8rem;
  height: 8rem;
  object-fit: cover;
  border-radius: 0.8rem;
  cursor: zoom-in;
  border: 1px solid var(--border);
}
/* Lip-sync audio track attached to a user message */
.attachment-audio {
  width: 16rem;
  height: 2.6667rem;
  vertical-align: middle;
}
</style>
