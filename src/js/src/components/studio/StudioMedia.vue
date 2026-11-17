<script setup lang="ts">
import { ref, inject, onMounted } from 'vue'
import { showToastKey, noToast } from '../../injection'
import { confirmDialog } from '../../composables/useDialog'
import MediaGrid from '../media/MediaGrid.vue'
import type { LibraryEntry, MediaFilters } from '../../composables/mediaApi'
import { fetchMediaPage, deleteMediaMany, downloadMediaMany } from '../../composables/useMedia'
import { messageOf } from '../../utils/errors'

defineEmits<{ close: [] }>()
const showToast = inject(showToastKey, noToast)

const PAGE = 30
interface Choice {
  id: string
  label: string
}
const KINDS: readonly Choice[] = [
  { id: 'all', label: 'All' },
  { id: 'image', label: 'Images' },
  { id: 'video', label: 'Videos' },
]
const SOURCES: readonly Choice[] = [
  { id: 'all', label: 'Any source' },
  { id: 'generated', label: 'Generated' },
  { id: 'upload', label: 'Uploaded' },
]

const ORIGINS: readonly Choice[] = [
  { id: 'all', label: 'Everywhere' },
  { id: 'chat', label: 'Chats' },
  { id: 'library', label: 'Library' },
  { id: 'orphan', label: 'Orphaned' },
]

const items = ref<LibraryEntry[]>([])
const total = ref(0)
const kind = ref('all')
const source = ref('all')
const origin = ref('all')
const q = ref('')
const loading = ref(false)
const preview = ref<LibraryEntry | null>(null)
const picked = ref<ReadonlySet<string>>(new Set()) // ids chosen for a bulk action
const busy = ref(false)
let lastPicked: string | null = null // the tile a shift-click selects a range from
function toggle(item: LibraryEntry, event?: MouseEvent): void {
  const next = new Set(picked.value)
  const from = items.value.findIndex(i => i.id === lastPicked)
  const to = items.value.findIndex(i => i.id === item.id)
  if (event?.shiftKey && from !== -1 && to !== -1) {
    for (const i of items.value.slice(Math.min(from, to), Math.max(from, to) + 1)) next.add(i.id)
  } else if (!next.delete(item.id)) {
    next.add(item.id)
  }
  lastPicked = item.id
  picked.value = next
}
const selectAll = (): void => {
  picked.value = new Set(items.value.map(i => i.id))
}
const clearPicked = (): void => {
  picked.value = new Set()
  lastPicked = null
}
async function bulkDownload(): Promise<void> {
  busy.value = true
  try {
    await downloadMediaMany([...picked.value])
  } catch (e) {
    showToast(messageOf(e), 'error')
  } finally {
    busy.value = false
  }
}
async function bulkDelete(): Promise<void> {
  const n = picked.value.size
  const ok = await confirmDialog({
    title: `Delete ${String(n)} item${n === 1 ? '' : 's'}?`,
    message: "This removes the files and can't be undone.",
    confirmLabel: 'Delete',
    danger: true,
  })
  if (!ok) return
  busy.value = true
  try {
    await deleteMediaMany([...picked.value])
    clearPicked()
    await load()
  } catch (e) {
    showToast(messageOf(e), 'error')
  } finally {
    busy.value = false
  }
}

function params(offset: number): MediaFilters & { offset: number; limit: number } {
  return { offset, limit: PAGE, q: q.value, kind: kind.value, source: source.value, origin: origin.value }
}
async function load(): Promise<void> {
  loading.value = true
  try {
    const { items: page, total: count } = await fetchMediaPage(params(0))
    items.value = page
    total.value = count
  } finally {
    loading.value = false
  }
}
async function loadMore(): Promise<void> {
  if (items.value.length >= total.value) return
  const { items: page } = await fetchMediaPage(params(items.value.length))
  items.value = [...items.value, ...page]
}
function setKind(k: string): void {
  kind.value = k
  void load()
}
function setSource(s: string): void {
  source.value = s
  void load()
}

function setOrigin(o: string): void {
  origin.value = o
  void load()
}

onMounted(load)
</script>

<template>
  <div class="media">
    <div class="mhead">
      <h1>Media library</h1>
      <span v-if="total" class="gcount">{{ total }} item{{ total === 1 ? '' : 's' }}</span>
      <span class="spacer"></span>
      <button class="btn" @click="$emit('close')">
        <svg class="ic"><use href="#s-chevL" /></svg> Back
      </button>
    </div>
    <div class="mbar">
      <div class="seg">
        <button v-for="k in KINDS" :key="k.id" :class="{ on: kind === k.id }" @click="setKind(k.id)">
          {{ k.label }}
        </button>
      </div>
      <div class="seg">
        <button v-for="s in SOURCES" :key="s.id" :class="{ on: source === s.id }" @click="setSource(s.id)">
          {{ s.label }}
        </button>
      </div>
      <div class="seg">
        <button v-for="o in ORIGINS" :key="o.id" :class="{ on: origin === o.id }" @click="setOrigin(o.id)">
          {{ o.label }}
        </button>
      </div>
      <button v-if="items.length" class="btn btn-sm" @click="selectAll">Select all</button>
      <div class="sbox msearch">
        <svg class="ic"><use href="#s-search" /></svg>
        <input v-model="q" type="search" placeholder="Search prompts…" @keyup.enter="load" />
      </div>
    </div>

    <div class="mbody">
      <div v-if="loading && !items.length" class="empty">Loading…</div>
      <div v-else-if="!items.length" class="empty">No media yet.</div>
      <MediaGrid
        v-else
        :items="items"
        :selected="picked"
        checkboxes
        :has-more="items.length < total"
        @open="preview = $event"
        @toggle="toggle"
        @more="loadMore"
      />
    </div>

    <div v-if="picked.size" class="bulkbar">
      <span>{{ picked.size }} selected</span>
      <button class="btn btn-sm" :disabled="busy" @click="bulkDownload">Download</button>
      <button class="btn btn-sm btn-danger-quiet" :disabled="busy" @click="bulkDelete">Delete</button>
      <button class="btn btn-sm btn-quiet" @click="clearPicked">Clear</button>
    </div>

    <div v-if="preview" class="ovl" @click="preview = null">
      <video v-if="preview.kind === 'video'" :src="preview.url" class="pv" controls autoplay @click.stop />
      <img v-else :src="preview.url" class="pv" alt="" @click.stop />
    </div>
  </div>
</template>

<style scoped>
.media {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.mhead {
  display: flex;
  align-items: center;
  gap: 0.6667rem;
  min-height: 3.4667rem;
  padding: 0.6667rem 1.2rem;
  border-bottom: 1px solid var(--sborder2);
}
h1 {
  font-size: 1rem;
  font-weight: 600;
}
.gcount {
  font-size: 0.8rem;
  color: var(--smuted);
}
.spacer {
  flex: 1;
}
.mbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5333rem 0.9333rem;
  padding: 0.6667rem 1.2rem;
}
.msearch {
  flex: 1;
  min-width: 12rem;
  max-width: 21.3333rem;
  margin-left: auto;
}
.mbody {
  flex: 1;
  overflow-y: auto;
  padding: 0.2667rem 1.2rem 1.6rem;
}
.bulkbar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5333rem 1.2rem;
  border-top: 1px solid var(--sborder2);
  background: var(--spanel2);
}
.bulkbar span {
  flex: 1;
  color: var(--sfg);
  font-size: 0.8667rem;
}
.ovl {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.82);
  padding: 2.1333rem;
  cursor: zoom-out;
}
.pv {
  max-width: 92vw;
  max-height: 92dvh;
  border-radius: var(--r);
  cursor: default;
}
</style>
