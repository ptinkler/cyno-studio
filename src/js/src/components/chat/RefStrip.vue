<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { showToastKey, noToast } from '../../injection'
import { MAX_ATTACHMENTS, useChatAttachments } from '../../composables/useChatAttachments'
import { imagesIn } from '../../utils/files'
import ComposerAttachments from '../studio/ComposerAttachments.vue'
import MediaPicker from '../media/MediaPicker.vue'

// The reference pictures for one Edit / Redo: the same thumbnails, upload and
// library picker as the main prompt, kept to this one card. `start` is what the
// card already used; the model is the whole set that is left.
const props = withDefaults(
  defineProps<{
    convId: string
    /** Chat files to begin with. */
    start?: readonly string[] | undefined
    /** How many pictures the model takes. */
    limit?: number | undefined
  }>(),
  { start: () => [], limit: MAX_ATTACHMENTS },
)
const files = defineModel<string[]>({ default: () => [] })
/** Something is still uploading. */
const busy = defineModel<boolean>('busy', { default: false })

const showToast = inject(showToastKey, noToast)
const attach = useChatAttachments({
  convId: computed(() => props.convId),
  ensureConversation: () => Promise.resolve(props.convId),
  showToast,
  limit: () => Math.min(props.limit, MAX_ATTACHMENTS),
})
for (const file of props.start) attach.addChatMedia(file)
watch(
  attach.files,
  list => {
    files.value = [...list]
  },
  { immediate: true },
)
watch(
  attach.uploading,
  uploading => {
    busy.value = uploading
  },
  { immediate: true },
)

const picking = ref(false)
const room = computed(() => Math.max(attach.room(), 0))

defineExpose({
  /** Pasted or dropped pictures; anything else is ignored. */
  addFiles: (list: Iterable<File>): void => {
    attach.addFiles(imagesIn(list))
  },
  /** Cancelled: drop what was uploaded for this and never used (the server keeps anything a card still has). */
  discard: (): void => {
    for (const attachment of [...attach.attachments.value]) attach.remove(attachment)
  },
})
</script>

<template>
  <ComposerAttachments
    :attachments="attach.attachments.value"
    media-mode
    @library="picking = true"
    @remove="attach.remove"
    @clear="attach.clear"
  />
  <MediaPicker
    :open="picking"
    title="Add references"
    :max="room"
    @pick="attach.addFromLibrary"
    @close="picking = false"
  />
</template>
