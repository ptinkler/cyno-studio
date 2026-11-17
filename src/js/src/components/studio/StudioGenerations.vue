<script setup lang="ts">
import { vTip } from '../../directives/tip'
import { computed, inject, ref, watch } from 'vue'
import { confirmDialog } from '../../composables/useDialog'
import { deleteMediaMany, downloadMediaMany } from '../../composables/mediaApi'
import { showToastKey, noToast } from '../../injection'
import { messageOf } from '../../utils/errors'
import type { MediaCard } from '../../composables/chatConversationsApi'
import { fetchMediaPage } from '../../composables/useMedia'
import { chatMediaUrl, chatMediaPreviewUrl } from '../../composables/useChat'
import type { GenerationItem, UiMessage } from '../../composables/studioTypes'
import GenerationGrid from './GenerationGrid.vue'

const props = withDefaults(
  defineProps<{ messages?: readonly UiMessage[] | undefined; convId?: string | undefined }>(),
  { messages: () => [], convId: '' },
)
const emit = defineEmits<{ open: [item: GenerationItem]; favourite: [item: GenerationItem]; deleted: [] }>()
const showToast = inject(showToastKey, noToast)

/** The full file's URL and the small picture the grid shows (the full file for a video), '' when there is no file. */
function mediaUrls(item: MediaCard): { url: string; preview: string } {
  if (!item.file) return { url: '', preview: '' }
  const url = chatMediaUrl(props.convId, item.file)
  return { url, preview: item.kind === 'image' ? chatMediaPreviewUrl(props.convId, item.file) : url }
}

/** What the user typed (the parent message), as opposed to the prompt the model ended up with. */
function typedPrompt(message: UiMessage, originals: ReadonlyMap<number | string, UiMessage>): string {
  if (message.parent_id === null) return ''
  return originals.get(message.parent_id)?.content ?? ''
}

function toCard(
  message: UiMessage,
  item: MediaCard,
  originals: ReadonlyMap<number | string, UiMessage>,
): GenerationItem {
  return {
    ...item,
    message_id: typeof message.id === 'number' ? message.id : null,
    conversation_id: props.convId,
    model: item.model ?? message.model,
    original_prompt: typedPrompt(message, originals),
    cost: message.cost,
    created_at: message.created_at,
    ...mediaUrls(item),
  }
}

// Only generations — uploads on user messages aren't shown here
const isGeneration = (item: MediaCard): boolean =>
  (item.kind === 'image' || item.kind === 'video') && item.source === 'generated'

const items = computed(() => {
  const originals = new Map(props.messages.map(m => [m.id, m]))
  const out = props.messages.flatMap(m => m.media.filter(isGeneration).map(i => toCard(m, i, originals)))
  return out.reverse()
})
// Files in this thread's folder that no message records (loaded on demand: it
// scans the whole library)
const showOrphans = ref(false)
const orphans = ref<GenerationItem[]>([])
const loadingOrphans = ref(false)
async function loadOrphans(): Promise<void> {
  loadingOrphans.value = true
  try {
    const { items: all } = await fetchMediaPage({ origin: 'orphan' })
    orphans.value = all
      .filter(i => i.conversation_id === props.convId)
      .map(i => ({
        ...i,
        conversation_id: props.convId,
        message_id: null,
        status: 'done',
        file: i.name,
        preview: i.thumb_url || i.url,
        orphan: true,
      }))
  } finally {
    loadingOrphans.value = false
  }
}
function toggleOrphans(): void {
  showOrphans.value = !showOrphans.value
  if (showOrphans.value) void loadOrphans()
}
watch(
  () => props.convId,
  () => {
    showOrphans.value = false
    orphans.value = []
  },
)
// Orphans have no message to manage: open the file itself, and no favouriting
function onOpen(item: GenerationItem): void {
  if (item.orphan) window.open(item.url, '_blank', 'noopener')
  else emit('open', item)
}
function onFavourite(item: GenerationItem): void {
  if (!item.orphan) emit('favourite', item)
}
const mediaId = (i: GenerationItem): string => `chat:${i.conversation_id}:${i.file ?? ''}`

// Delete the picked files (not their prompts, which stay in the chat)
async function deleteMany(picked: GenerationItem[]): Promise<void> {
  const n = picked.length
  if (!n) return
  const ok = await confirmDialog({
    title: `Delete ${String(n)} generation${n === 1 ? '' : 's'}?`,
    message: "This removes the files and can't be undone.",
    confirmLabel: 'Delete',
    danger: true,
  })
  if (!ok) return
  try {
    await deleteMediaMany(picked.map(mediaId))
    emit('deleted')
  } catch (e) {
    showToast(messageOf(e), 'error')
  }
}
async function downloadMany(picked: GenerationItem[]): Promise<void> {
  try {
    await downloadMediaMany(picked.map(mediaId))
  } catch (e) {
    showToast(messageOf(e), 'error')
  }
}
const shownItems = computed(() => (showOrphans.value ? orphans.value : items.value))
</script>

<template>
  <GenerationGrid
    :items="shownItems"
    :selectable="!showOrphans"
    :empty="
      showOrphans
        ? loadingOrphans
          ? 'Scanning…'
          : 'No orphaned files in this thread.'
        : 'No generations in this thread yet.'
    "
    @open="onOpen"
    @favourite="onFavourite"
    @delete-many="deleteMany"
    @download-many="downloadMany"
  >
    <!-- Sits with the grid's own filters rather than floating above them -->
    <template #filters>
      <button v-tip="'Unused files'" class="pillbtn" :class="{ on: showOrphans }" @click="toggleOrphans">
        Orphaned<template v-if="showOrphans && !loadingOrphans"> ({{ orphans.length }})</template>
      </button>
    </template>
  </GenerationGrid>
</template>
