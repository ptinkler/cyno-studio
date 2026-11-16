<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { components } from '../../api/schema'
import {
  cancelChatGptUpload,
  chatExportUrl,
  fetchChatGptImport,
  fetchExportableChats,
  sendChatGptUploadChunk,
  startChatGptImport,
  startChatGptUpload,
} from '../../composables/useChat'
import { messageOf } from '../../utils/errors'
import BaseDialog from '../BaseDialog.vue'

type Schemas = components['schemas']

// Import chats from a ChatGPT export, or from this app's own chat export
// (made below, here or on another server): upload the zip (in chunks, then
// it's imported straight away) or pick one already in the server's imports
// folder, and follow the import (it runs on the server; closing this doesn't
// stop it). Emits `imported` when one finishes, so the list can reload.
// The Export tab picks chats and downloads them as one zip.
const props = withDefaults(defineProps<{ visible?: boolean | undefined }>(), { visible: false })
const emit = defineEmits<{ close: []; imported: [] }>()

const POLL_MS = 1500
const CHUNK_TRIES = 4 // per chunk, each after the API's own retries
const CHUNK_RETRY_MS = 5000
const BYTES_PER_MB = 1e6
const BYTES_PER_GB = 1e9

/** An upload in progress. */
interface Upload {
  id: string
  name: string
  size: number
  sent: number
}

const folder = ref('')
const files = ref<Schemas['ImportFile'][]>([])
const selected = ref<string | null>(null)
const job = ref<Schemas['ImportJob'] | null>(null)
const loading = ref(false)
const error = ref('')
const upload = ref<Upload | null>(null)
const picker = ref<HTMLInputElement | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
// Set when the user cancels an upload, read by the chunk loop that is still running
const uploadState = { cancelled: false }
const wasCancelled = (): boolean => uploadState.cancelled // a call, so a check after an await isn't read as always false

// Export: pick chats, download them as one zip
const tab = ref<'import' | 'export'>('import')
const chats = ref<Schemas['ExportableChat'][] | null>(null) // null until loaded
const picked = ref(new Set<string>())
const exportQuery = ref('')
const shownChats = computed(() => {
  const q = exportQuery.value.trim().toLowerCase()
  return (chats.value ?? []).filter(c => !q || c.title.toLowerCase().includes(q))
})
const allShownPicked = computed(
  () => shownChats.value.length > 0 && shownChats.value.every(c => picked.value.has(c.id)),
)
const exportHref = computed(() => chatExportUrl([...picked.value]))

async function openExport(): Promise<void> {
  tab.value = 'export'
  if (chats.value) return
  try {
    chats.value = (await fetchExportableChats()).chats
  } catch (e) {
    error.value = messageOf(e)
    chats.value = []
  }
}

function togglePick(id: string): void {
  const next = new Set(picked.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  picked.value = next
}

function toggleAllShown(): void {
  const next = new Set(picked.value)
  const on = !allShownPicked.value
  for (const chat of shownChats.value) {
    if (on) next.add(chat.id)
    else next.delete(chat.id)
  }
  picked.value = next
}

const running = computed(() => job.value?.state === 'running')
const busy = computed(() => running.value || !!upload.value)
const finished = computed(() => (job.value?.state === 'done' || job.value?.state === 'error') && !!job.value.file)

function fmtSize(bytes: number): string {
  return bytes >= BYTES_PER_GB
    ? `${(bytes / BYTES_PER_GB).toFixed(1)} GB`
    : `${String(Math.max(1, Math.round(bytes / BYTES_PER_MB)))} MB`
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function applyStatus(data: Awaited<ReturnType<typeof fetchChatGptImport>>): void {
  folder.value = data.folder
  files.value = data.files
  const was = job.value?.state
  job.value = data.job
  if (!files.value.some(f => f.name === selected.value)) selected.value = files.value[0]?.name ?? null
  if (was === 'running' && data.job.state !== 'running') emit('imported')
}

async function refresh(): Promise<void> {
  try {
    applyStatus(await fetchChatGptImport())
    error.value = ''
  } catch (e) {
    error.value = messageOf(e)
  }
  clearTimeout(timer)
  if (props.visible && running.value) timer = setTimeout(() => void refresh(), POLL_MS)
}

watch(
  () => props.visible,
  async visible => {
    clearTimeout(timer)
    if (!visible) return
    chats.value = null // fresh list each time it opens
    loading.value = true
    await refresh()
    loading.value = false
  },
)
onBeforeUnmount(() => {
  clearTimeout(timer)
})

// Leaving the page stops an upload
function warnOnLeave(event: BeforeUnloadEvent): void {
  event.preventDefault()
}
watch(upload, (now, before) => {
  if (now && !before) window.addEventListener('beforeunload', warnOnLeave)
  if (!now) window.removeEventListener('beforeunload', warnOnLeave)
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', warnOnLeave)
})

async function sendChunk(id: string, offset: number, blob: Blob): Promise<Schemas['UploadProgress']> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await sendChatGptUploadChunk(id, offset, blob)
    } catch (e) {
      if (attempt >= CHUNK_TRIES || wasCancelled()) throw e
      await new Promise(resolve => setTimeout(resolve, CHUNK_RETRY_MS))
    }
  }
}

function discardUpload(id: string): void {
  cancelChatGptUpload(id).catch(() => undefined)
}

/** Send the file in chunks; the stored name once it is all there. */
async function sendFile(file: File, started: Schemas['UploadStarted']): Promise<string | null> {
  let stored: string | null = null
  for (let offset = 0; offset < file.size && !wasCancelled(); offset += started.chunk_size) {
    const progress = await sendChunk(started.id, offset, file.slice(offset, offset + started.chunk_size))
    if (upload.value) upload.value.sent = progress.received
    stored = progress.file ?? stored
  }
  return stored
}

async function uploadFile(file: File): Promise<void> {
  error.value = ''
  uploadState.cancelled = false
  let id: string | null = null
  try {
    const started = await startChatGptUpload(file.name, file.size)
    id = started.id
    upload.value = { id, name: file.name, size: file.size, sent: 0 }
    const stored = await sendFile(file, started)
    if (wasCancelled()) return
    upload.value = null
    await refresh()
    selected.value = stored
    await start()
  } catch (e) {
    if (wasCancelled()) return // a chunk still on its way when it was cancelled
    error.value = `Upload failed: ${messageOf(e)}`
    if (id) discardUpload(id)
  } finally {
    upload.value = null
  }
}

function onPick(event: Event): void {
  const input = event.target
  if (!(input instanceof HTMLInputElement)) return
  const [file] = input.files ?? []
  input.value = ''
  if (file) void uploadFile(file)
}

function cancelUpload(): void {
  uploadState.cancelled = true
  const id = upload.value?.id
  upload.value = null
  if (id) discardUpload(id)
}

async function start(): Promise<void> {
  if (!selected.value) return
  try {
    job.value = await startChatGptImport(selected.value)
    error.value = ''
  } catch (e) {
    error.value = messageOf(e)
  }
  await refresh()
}
</script>

<template>
  <BaseDialog :open="visible" title="Import / export chats" @close="emit('close')">
    <div class="seg tabs">
      <button :class="{ on: tab === 'import' }" @click="tab = 'import'">Import</button>
      <button :class="{ on: tab === 'export' }" @click="openExport">Export</button>
    </div>

    <template v-if="tab === 'export'">
      <p class="hint">
        Downloads the chats as one zip — every branch, picture and video. Import it here or on another server with
        <strong>Import</strong>. Attached characters and instructions don't travel; spaces go by name.
      </p>
      <input v-model="exportQuery" class="filter" type="search" placeholder="Filter chats…" />
      <div v-if="!chats" class="note">Loading chats…</div>
      <div v-else-if="!chats.length" class="note">No chats yet.</div>
      <ul v-else class="file-list">
        <li class="file-item pick all">
          <label
            ><input type="checkbox" :checked="allShownPicked" @change="toggleAllShown" />
            {{ exportQuery ? 'All matching' : 'All chats' }} ({{ shownChats.length }})</label
          >
        </li>
        <li v-for="c in shownChats" :key="c.id" class="file-item pick">
          <label :title="c.title">
            <input type="checkbox" :checked="picked.has(c.id)" @change="togglePick(c.id)" />
            <span class="file-name">{{ c.title || 'Untitled' }}</span>
            <span class="file-meta"
              ><template v-if="c.space">{{ c.space }} · </template>{{ c.updated_at ? fmtDate(c.updated_at) : '' }}</span
            >
          </label>
        </li>
      </ul>
      <p v-if="error" class="result error">{{ error }}</p>
    </template>

    <template v-else>
      <p class="hint">
        Upload a chat export from this app (Export, here or on another server), or a ChatGPT one (Settings → Data
        controls → Export data, then the zip it emails you) — or copy it into
        <code>{{ folder || 'the imports folder' }}</code> on the server. ChatGPT chats go in a
        <strong>ChatGPT</strong> space. Importing a newer export later only adds what's new; chats you delete here
        aren't imported again.
      </p>
      <input ref="picker" type="file" accept=".zip,application/zip" hidden @change="onPick" />

      <div v-if="loading" class="note">Looking for exports…</div>
      <div v-else-if="!files.length" class="note">No exports yet: upload one below.</div>
      <ul v-else class="file-list">
        <li
          v-for="f in files"
          :key="f.name"
          :class="['file-item', { active: selected === f.name }]"
          :title="f.name"
          @click="!busy && (selected = f.name)"
        >
          <span class="file-name">{{ f.name }}</span>
          <span class="file-meta">{{ fmtSize(f.size) }} · {{ fmtDate(f.modified) }}</span>
        </li>
      </ul>

      <div v-if="upload" class="progress">
        <div class="bar"><span :style="{ width: `${(100 * upload.sent) / upload.size}%` }"></span></div>
        Uploading {{ upload.name }}… {{ fmtSize(upload.sent) }} / {{ fmtSize(upload.size) }}. Keep this tab open; it's
        imported once it's up.
      </div>
      <div v-else-if="job && running" class="progress">
        <div class="bar">
          <span :style="{ width: `${job.total ? (100 * (job.processed ?? 0)) / job.total : 0}%` }"></span>
        </div>
        Importing {{ job.file }}… {{ job.processed || 0 }} / {{ job.total || '?' }} chats
      </div>
      <div v-else-if="job && finished && job.state === 'error'" class="result error">
        Import of {{ job.file }} failed: {{ job.error }}
      </div>
      <div v-else-if="job && finished" class="result">
        <strong>{{ job.file }}</strong
        >: {{ job.new }} new, {{ job.updated }} updated, {{ job.unchanged }} unchanged
        <template v-if="job.deleted">, {{ job.deleted }} deleted here (skipped)</template>. {{ job.images }} images
        copied<template v-if="job.missing_images">, {{ job.missing_images }} not in the export</template>.
        <ul v-if="job.failed?.length" class="failed">
          <li v-for="(f, i) in job.failed" :key="i">{{ f.title || 'Untitled' }}: {{ f.error }}</li>
        </ul>
      </div>
      <p v-if="error" class="result error">{{ error }}</p>
    </template>

    <template v-if="tab === 'export'" #actions>
      <span class="spacer"></span>
      <button class="btn btn-secondary" @click="emit('close')">Close</button>
      <a
        v-if="picked.size"
        class="btn btn-primary"
        :href="exportHref"
        download
        :title="`Download ${picked.size} chat${picked.size === 1 ? '' : 's'} as a zip`"
        >Download {{ picked.size }} chat{{ picked.size === 1 ? '' : 's' }}</a
      >
      <button v-else class="btn btn-primary" disabled>Pick chats to export</button>
    </template>
    <template v-else #actions>
      <button v-if="upload" class="btn btn-secondary" @click="cancelUpload">Cancel upload</button>
      <button v-else class="btn btn-secondary" :disabled="busy" @click="picker?.click()">Upload export…</button>
      <span class="spacer"></span>
      <button class="btn btn-secondary" @click="emit('close')">Close</button>
      <button class="btn btn-primary" :disabled="!selected || busy" @click="start">
        {{ running ? 'Importing…' : 'Import' }}
      </button>
    </template>
  </BaseDialog>
</template>

<style scoped>
.tabs {
  align-self: flex-start;
  margin-bottom: 4px;
}

.filter {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: inherit;
  font: inherit;
  font-size: 0.82rem;
}

.file-item.pick {
  padding: 0;
}

.file-item.pick label {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 8px;
  padding: 6px 12px;
  cursor: pointer;
  align-items: center;
}

.file-item.pick .file-meta {
  grid-column: 2;
}

.file-item.all label {
  font-size: 0.82rem;
  color: var(--text2);
}

a.btn {
  text-decoration: none;
}

.hint,
.note {
  color: var(--text2);
  font-size: 0.82rem;
  line-height: 1.45;
}

.hint code {
  word-break: break-all;
}

.file-list {
  list-style: none;
  padding: 0;
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
}

.file-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 12px;
  cursor: pointer;
  border-bottom: 1px solid var(--border);
}

.file-item:last-child {
  border-bottom: none;
}

.file-item:hover {
  background: var(--surface2);
}

.file-item.active {
  background: var(--saccent-soft);
}

.file-name {
  font-size: 0.82rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-meta {
  font-size: 0.72rem;
  color: var(--text2);
}

.progress,
.result {
  font-size: 0.82rem;
  line-height: 1.45;
}

.result.error {
  color: var(--sdanger);
}

.bar {
  height: 6px;
  border-radius: 3px;
  background: var(--surface2);
  overflow: hidden;
  margin-bottom: 6px;
}

.bar span {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width 0.3s;
}

.failed {
  margin: 6px 0 0;
  padding-left: 18px;
  color: var(--text2);
}
</style>
