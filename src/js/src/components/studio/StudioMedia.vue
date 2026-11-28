<script setup lang="ts">
import { ref, computed, inject, onMounted, watch } from 'vue'
import { showToastKey, noToast } from '../../injection'
import { vTip } from '../../directives/tip'
import { confirmDialog } from '../../composables/useDialog'
import MediaGrid from '../media/MediaGrid.vue'
import SelectionBar from './SelectionBar.vue'
import GenerationFilters from './GenerationFilters.vue'
import FilterRow from './FilterRow.vue'
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
const SOURCES: readonly Choice[] = [
  { id: 'all', label: 'Any' },
  { id: 'generated', label: 'Generated' },
  { id: 'upload', label: 'Uploaded' },
]

const ORIGINS: readonly Choice[] = [
  { id: 'all', label: 'Anywhere' },
  { id: 'chat', label: 'Chats' },
  { id: 'library', label: 'Library' },
  { id: 'orphan', label: 'Orphaned' },
]

const items = ref<LibraryEntry[]>([])
const total = ref(0)
const kind = ref('all')
const source = ref('all')
const origin = ref('all')
const extraActive = computed(() => (source.value !== 'all' ? 1 : 0) + (origin.value !== 'all' ? 1 : 0))
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
    const { kept } = await deleteMediaMany([...picked.value])
    clearPicked()
    await load()
    if (kept) {
      showToast(
        `${String(kept)} file${kept === 1 ? ' was' : 's were'} kept: other pictures in the chat use ${kept === 1 ? 'it' : 'them'} as references`,
      )
    }
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
function clearExtra(): void {
  source.value = 'all'
  origin.value = 'all'
}
// Any filter change asks the server again (a Clear changes several at once: one reload)
watch([kind, source, origin], () => void load())
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
      <div class="sbox msearch">
        <svg class="ic"><use href="#s-search" /></svg>
        <input v-model="q" type="search" placeholder="Search prompts…" @keyup.enter="load" />
      </div>
      <GenerationFilters v-model:kind="kind" :fav-filter="false" :extra-active="extraActive" @clear="clearExtra">
        <FilterRow label="Source">
          <select v-model="source">
            <option v-for="o in SOURCES" :key="o.id" :value="o.id">{{ o.label }}</option>
          </select>
        </FilterRow>
        <FilterRow label="From">
          <select v-model="origin">
            <option v-for="o in ORIGINS" :key="o.id" :value="o.id">{{ o.label }}</option>
          </select>
        </FilterRow>
      </GenerationFilters>
      <button v-if="items.length" v-tip="'Select all'" class="iconbtn boxed" aria-label="Select all" @click="selectAll">
        <svg class="ic"><use href="#s-selectall" /></svg>
      </button>
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

    <SelectionBar
      v-if="picked.size"
      :count="picked.size"
      :busy="busy"
      @select-all="selectAll"
      @download="bulkDownload"
      @delete="bulkDelete"
      @clear="clearPicked"
    />

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
  gap: 0.5333rem;
  padding: 0.6667rem 1.2rem;
}
.msearch {
  flex: 1;
  min-width: 12rem;
  max-width: 21.3333rem;
}
.mbody {
  flex: 1;
  overflow-y: auto;
  padding: 0.2667rem 1.2rem 1.6rem;
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
