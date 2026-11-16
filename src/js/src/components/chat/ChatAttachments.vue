<script setup lang="ts">
import type { MediaCard } from '../../composables/chatConversationsApi'
import { chatMediaPreviewUrl, chatMediaUrl } from '../../composables/chatFilesApi'
import type { GenerationItem, UiMessage } from '../../composables/studioTypes'
import { bigView, canPinMedia } from '../../utils/chatMedia'
import PinButton from './PinButton.vue'

const props = defineProps<{ message: UiMessage; convId: string }>()
const emit = defineEmits<{
  'open-media': [item: GenerationItem]
  'use-image': [pick: { file: string | null | undefined; mode: 'image' | 'video' }]
  pin: [pick: { mediaId: string; pinned: boolean }]
}>()

// A card with no file yet (still rendering) has nothing to show
const fileOf = (item: MediaCard): string => item.file ?? ''
const mediaUrl = (item: MediaCard): string => chatMediaUrl(props.convId, fileOf(item))
// What's shown in the chat: a scaled-down copy (a big chat's full images add up)
const mediaPreview = (item: MediaCard): string => chatMediaPreviewUrl(props.convId, fileOf(item))
const canPin = (item: MediaCard): boolean => canPinMedia(item, props.message)
const big = (item: MediaCard): GenerationItem => bigView(item, props.message, props.convId)
</script>

<template>
  <div v-if="message.media?.length" class="attachments">
    <div v-for="item in message.media" :key="item.id" class="attachment">
      <PinButton
        v-if="canPin(item)"
        :pinned="!!item.pinned"
        @toggle="emit('pin', { mediaId: item.id, pinned: !item.pinned })"
      />
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
          title="Attach this picture and switch to Image mode"
          @click="emit('use-image', { file: item.file, mode: 'image' })"
        >
          <svg class="ic sm"><use href="#s-image" /></svg>
        </button>
        <button
          title="Attach this picture and switch to Video mode"
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
  gap: 6px;
  margin-bottom: 6px;
}
.attachment {
  position: relative;
}
.use-btns {
  position: absolute;
  top: 6px;
  right: 6px;
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}
.use-btns button {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
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
  width: 120px;
  height: 120px;
  object-fit: cover;
  border-radius: 12px;
  cursor: zoom-in;
  border: 1px solid var(--border);
}
/* Lip-sync audio track attached to a user message */
.attachment-audio {
  width: 240px;
  height: 40px;
  vertical-align: middle;
}
</style>
