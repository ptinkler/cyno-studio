<script setup lang="ts">
import { vTip } from '../../directives/tip'
import { ref, computed, watch, nextTick, inject } from 'vue'
import { showToastKey, noToast } from '../../injection'
import MediaPicker from '../media/MediaPicker.vue'
import BaseDialog from '../BaseDialog.vue'
import DefaultToggles from '../chat/DefaultToggles.vue'
import type { Character } from '../../composables/charactersApi'
import type { CharacterSeed } from '../../composables/useChatCharacters'
import { confirmDialog } from '../../composables/useDialog'
import type { LibraryEntry } from '../../composables/mediaApi'
import { importMediaToCharacter } from '../../composables/useMedia'
import {
  createCharacter,
  updateCharacter,
  deleteCharacter,
  promoteCharacter,
  uploadCharacterImage,
  copyChatImageToCharacter,
  characterImageUrl,
} from '../../composables/useCharacters'
import { takeFiles } from '../../utils/files'
import { messageOf } from '../../utils/errors'

const props = withDefaults(
  defineProps<{
    open?: boolean | undefined
    /** Edit this one; null = create. */
    character?: Character | null | undefined
    /** Create as ad hoc in this chat. */
    conversationId?: string | null | undefined
    /** Images to start a new character with. */
    seed?: readonly CharacterSeed[] | undefined
    /** Show the "add to chat defaults" toggles (chat view only). */
    showDefaults?: boolean | undefined
  }>(),
  { open: false, character: null, conversationId: null, seed: () => [], showDefaults: false },
)
const emit = defineEmits<{ close: []; saved: [character: Character]; deleted: [id: number] }>()

const MAX_IMAGES = 6 // mirrors MAX_IMAGES in web/characters.py
const showToast = inject(showToastKey, noToast)

/** An image in the editor, main first: one already saved, or one to add when the character is saved. */
type EditorImage =
  | { kind: 'saved'; saved: string; key: string }
  | { kind: 'file'; file: File; preview: string; key: number }
  | { kind: 'media'; mediaId: string; preview: string; key: number }
  | (CharacterSeed & { key: number })
type NewImage = Exclude<EditorImage, { kind: 'saved' }>

const name = ref('')
const description = ref('')
const images = ref<EditorImage[]>([])
const dragFrom = ref<number | null>(null) // index of the image being dragged
const saving = ref(false)
const pickerOpen = ref(false)
const nameInput = ref<HTMLInputElement | null>(null)
const toggles = ref<{ commit: (id: number) => Promise<void> } | null>(null) // the "Default for" pills, saved along with the rest
let keySeq = 0

const isNew = computed(() => !props.character)
const total = computed(() => images.value.length)

// The form starts from the character being edited (or empty), plus any seed pictures for a new one
function loadForm(): void {
  name.value = props.character?.name ?? ''
  description.value = props.character?.description ?? ''
  images.value = [
    ...(props.character?.images ?? []).map((saved): EditorImage => ({ kind: 'saved', saved, key: saved })),
    ...props.seed.map((seed): EditorImage => ({ ...seed, key: ++keySeq })),
  ]
}

watch(
  () => props.open,
  open => {
    if (!open) return
    loadForm()
    void nextTick(() => nameInput.value?.focus())
  },
)

function addFiles(files: Iterable<File>): void {
  for (const file of [...files].filter(f => f.type.startsWith('image/'))) {
    if (total.value >= MAX_IMAGES) {
      showToast(`Up to ${String(MAX_IMAGES)} images per character`, 'error')
      return
    }
    images.value.push({ kind: 'file', file, preview: URL.createObjectURL(file), key: ++keySeq })
  }
}

function addFromLibrary(items: readonly LibraryEntry[]): void {
  for (const item of items.slice(0, MAX_IMAGES - total.value)) {
    images.value.push({ kind: 'media', mediaId: item.id, preview: item.thumb_url || item.url, key: ++keySeq })
  }
}

function imageUrl(img: EditorImage): string {
  if (img.kind !== 'saved') return img.preview
  return props.character ? characterImageUrl(props.character.id, img.saved) : ''
}

function removeImage(img: EditorImage): void {
  if (img.kind === 'file') URL.revokeObjectURL(img.preview)
  images.value = images.value.filter(x => x !== img)
}

function moveImage(from: number | null, to: number): void {
  if (from === null || from === to) return
  const list = [...images.value]
  list.splice(to, 0, ...list.splice(from, 1))
  images.value = list
}

// Drag a thumbnail onto another to put it there (images dropped from outside are added)
function onDragStart(event: DragEvent, i: number): void {
  dragFrom.value = i
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onDropOn(event: DragEvent, i: number): void {
  if (dragFrom.value === null) {
    addFiles(event.dataTransfer?.files ?? [])
    return
  }
  moveImage(dragFrom.value, i)
  dragFrom.value = null
}

function addImage(id: number, img: NewImage): Promise<Character> {
  switch (img.kind) {
    case 'chat':
      return copyChatImageToCharacter(id, img.conversationId, img.file)
    case 'media':
      return importMediaToCharacter(img.mediaId, id)
    case 'file':
      return uploadCharacterImage(id, img.file)
  }
}

/** The character as saved, with all of the editor's new images added and in the order shown. */
async function saveImages(start: Character): Promise<Character> {
  let saved = start
  // New images are added at the end; then put everything in the order shown
  const order: string[] = []
  for (const img of images.value) {
    if (img.kind === 'saved') {
      order.push(img.saved)
      continue
    }
    saved = await addImage(saved.id, img)
    const added = saved.images.at(-1)
    if (added !== undefined) order.push(added)
  }
  return order.join('/') === saved.images.join('/') ? saved : updateCharacter(saved.id, { images: order })
}

async function save(): Promise<void> {
  if (!name.value.trim()) {
    showToast('Give the character a name', 'error')
    return
  }
  saving.value = true
  try {
    const fields = { name: name.value.trim(), description: description.value.trim() }
    const kept = images.value.flatMap(img => (img.kind === 'saved' ? img.saved : []))
    const existing = props.character
    const first = existing
      ? await updateCharacter(existing.id, { ...fields, images: kept })
      : await createCharacter({ ...fields, conversation_id: props.conversationId })
    const saved = await saveImages(first)
    await toggles.value?.commit(saved.id)
    emit('saved', saved)
    emit('close')
  } catch (e) {
    showToast(`Save failed: ${messageOf(e)}`, 'error')
  } finally {
    saving.value = false
  }
}

async function promote(): Promise<void> {
  const character = props.character
  if (!character) return
  try {
    emit('saved', await promoteCharacter(character.id))
    showToast(`${character.name} saved — attach it to any chat or generation`, 'success')
  } catch (e) {
    showToast(`Couldn't save: ${messageOf(e)}`, 'error')
  }
}

async function remove(): Promise<void> {
  const character = props.character
  if (!character) return
  const confirmed = await confirmDialog({
    title: `Delete “${character.name}”?`,
    message: 'Its images are deleted too.',
    confirmLabel: 'Delete',
    danger: true,
  })
  if (!confirmed) return
  try {
    await deleteCharacter(character.id)
    emit('deleted', character.id)
    emit('close')
  } catch (e) {
    showToast(`Delete failed: ${messageOf(e)}`, 'error')
  }
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="character ? character.name : 'New character'"
    label="Character"
    width="37.3333rem"
    @close="emit('close')"
  >
    <template #head>
      <span v-if="character?.adhoc || (isNew && conversationId)" v-tip="'Only in this chat until saved'" class="tag"
        >this chat only</span
      >
    </template>
    <p class="sub">
      The description is added to prompts and the images go to the model as references, so the character looks the same
      every time. Drag the images into order: the first is the main one, and when an image model takes fewer images than
      there are, each character's first ones go before the rest.
    </p>

    <label for="char-name">Name</label>
    <input id="char-name" ref="nameInput" v-model="name" maxlength="100" placeholder="e.g. Linh" />
    <label for="char-desc">Description</label>
    <textarea
      id="char-desc"
      v-model="description"
      maxlength="4000"
      placeholder="Appearance and anything that should stay the same: age, hair, build, clothing, style…"
    ></textarea>

    <label
      >Images <span class="count">{{ total }}/{{ MAX_IMAGES }}</span></label
    >
    <div class="images" @dragover.prevent @drop.prevent="addFiles($event.dataTransfer?.files ?? [])">
      <div
        v-for="(img, i) in images"
        :key="img.key"
        v-tip="'Drag to reorder'"
        class="img"
        :class="{ main: i === 0, pending: img.kind !== 'saved', dragging: dragFrom === i }"
        draggable="true"
        @dragstart="onDragStart($event, i)"
        @dragend="dragFrom = null"
        @dragover.prevent
        @drop.prevent.stop="onDropOn($event, i)"
      >
        <img :src="imageUrl(img)" alt="" draggable="false" />
        <span v-if="i === 0" class="main-tag">main</span>
        <span v-else class="pos-tag">{{ i + 1 }}</span>
        <button
          v-if="i > 0"
          v-tip="'Make this the main image'"
          class="img-btn star"
          aria-label="Make this the main image"
          @click="moveImage(i, 0)"
        >
          ★
        </button>
        <button v-tip="'Remove'" class="img-btn x-btn" aria-label="Remove" @click="removeImage(img)">✕</button>
      </div>
      <template v-if="total < MAX_IMAGES">
        <label v-tip="'Upload images'" class="img add">
          ＋
          <span class="add-label">Upload</span>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            hidden
            @change="addFiles(takeFiles($event))"
          />
        </label>
        <button v-tip="'Choose from Media'" type="button" class="img add" @click="pickerOpen = true">
          🗂
          <span class="add-label">Library</span>
        </button>
      </template>
    </div>

    <MediaPicker
      :open="pickerOpen"
      title="Add images to the character"
      :max="MAX_IMAGES - total"
      @pick="addFromLibrary"
      @close="pickerOpen = false"
    />

    <DefaultToggles v-if="showDefaults" ref="toggles" kind="character" :item-id="character?.id ?? null" />

    <template #actions>
      <button v-if="character" class="btn btn-danger" @click="remove">Delete</button>
      <button v-if="character?.adhoc" v-tip="'Save for every chat'" class="btn btn-secondary" @click="promote">
        ⭐ Save to characters
      </button>
      <span class="spacer"></span>
      <button class="btn btn-secondary" @click="emit('close')">Cancel</button>
      <button class="btn btn-primary" :disabled="saving || !name.trim()" @click="save">
        {{ saving ? 'Saving…' : isNew ? 'Create' : 'Save' }}
      </button>
    </template>
  </BaseDialog>
</template>

<style scoped>
.tag {
  font-size: 0.8rem;
  padding: 1px 0.4667rem;
  border-radius: var(--r-sm);
  background: var(--spanel2);
  color: var(--swarn);
}

.sub {
  font-size: 0.8rem;
  color: var(--text2);
  margin-bottom: 0.5333rem;
  line-height: 1.45;
}

label {
  margin-top: 0.2667rem;
}

.count {
  text-transform: none;
  letter-spacing: 0;
}

input,
textarea {
  width: 100%;
}

textarea {
  min-height: 7.3333rem;
}

.images {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(5.6rem, 1fr));
  gap: 0.5333rem;
}

.img {
  position: relative;
  aspect-ratio: 1;
  border-radius: 0.6667rem;
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--surface2);
}

.img.main {
  border-color: var(--accent);
}

.img[draggable='true'] {
  cursor: grab;
}

.img.dragging {
  opacity: 0.4;
}

.img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.img.add {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  font-size: 1.6rem;
  color: var(--text2);
  cursor: pointer;
  border-style: dashed;
  margin: 0;
  text-transform: none;
}

.add-label {
  font-size: 0.8rem;
}

.img.add:hover {
  color: var(--text);
  border-color: var(--accent);
}

.main-tag {
  position: absolute;
  left: 0.2667rem;
  bottom: 0.2667rem;
  font-size: 0.7333rem;
  padding: 1px 0.4rem;
  border-radius: 0.4rem;
  background: var(--saccent-fill);
  color: #fff;
}

.pos-tag {
  position: absolute;
  left: 0.2667rem;
  bottom: 0.2667rem;
  font-size: 0.7333rem;
  padding: 1px 0.4rem;
  border-radius: 0.4rem;
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
}

.img-btn {
  position: absolute;
  top: 0.2667rem;
  width: 1.4667rem;
  height: 1.4667rem;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
  font-size: 0.8rem;
  cursor: pointer;
}

.x-btn {
  right: 0.2667rem;
}

.star {
  left: 0.2667rem;
}
</style>
