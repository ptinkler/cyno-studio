<script setup lang="ts">
import { ref, computed, onMounted, inject } from 'vue'
import { showToastKey, noToast } from '../../injection'
import { fetchRequestLog } from '../../composables/chatFilesApi'
import { useCopy } from '../../composables/useClipboard'

type Entry = Awaited<ReturnType<typeof fetchRequestLog>>['entries'][number]

const emit = defineEmits<{ close: [] }>()

const LOG_SIZE = 200
const HTTP_ERROR = 400
const showToast = inject(showToastKey, noToast)
const { copiedKey, copy } = useCopy()

const entries = ref<Entry[]>([])
const loading = ref(true)
const failedOnly = ref(false)
const open = ref<ReadonlySet<string>>(new Set())

const ok = (entry: Entry): boolean => !entry.error && (entry.status ?? 0) < HTTP_ERROR
const shown = computed(() => entries.value.filter(e => !failedOnly.value || !ok(e)))
const key = (entry: Entry, index: number): string => `${entry.at}-${String(index)}`

async function load(): Promise<void> {
  loading.value = true
  try {
    entries.value = (await fetchRequestLog(LOG_SIZE)).entries
  } catch (e) {
    showToast(`Couldn't load the request log: ${e instanceof Error ? e.message : String(e)}`, 'error')
  } finally {
    loading.value = false
  }
}
function toggle(k: string): void {
  const next = new Set(open.value)
  if (!next.delete(k)) next.add(k)
  open.value = next
}
const flagged = (entry: Entry): boolean => Object.values(entry.flags ?? {}).some(v => v.toLowerCase() === 'true')
const fmtTime = (iso: string): string =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' })
const json = (entry: Entry): string => JSON.stringify(entry, null, 2)
onMounted(load)
</script>

<template>
  <div class="page">
    <div class="pwrap wide">
      <div class="phead">
        <div>
          <h1>Request log</h1>
          <p class="sub">
            What was sent to Venice, OpenRouter and Pollo and what came back, newest first. Click one to see both.
          </p>
        </div>
        <div class="hactions">
          <label class="failed"><input v-model="failedOnly" type="checkbox" /> Failures only</label>
          <button class="btn" @click="load">
            <svg class="ic"><use href="#s-refresh" /></svg> Refresh
          </button>
          <button class="btn" @click="emit('close')">
            <svg class="ic"><use href="#s-chevL" /></svg> Back
          </button>
        </div>
      </div>

      <p v-if="loading" class="sub">Loading…</p>
      <p v-else-if="!shown.length" class="sub">
        {{ entries.length ? 'No failures.' : 'No requests yet — send something in a chat.' }}
      </p>

      <div v-for="(e, i) in shown" :key="key(e, i)" class="entry" :class="{ bad: !ok(e) }">
        <button class="row" @click="toggle(key(e, i))">
          <span class="status" :class="ok(e) ? 'good' : 'fail'">{{ e.status ?? '—' }}</span>
          <span class="when">{{ fmtTime(e.at) }}</span>
          <span class="provider">{{ e.provider }}</span>
          <span class="path">{{ e.path }}</span>
          <span class="model">{{ e.model }}</span>
          <span v-if="flagged(e)" class="flag" :title="JSON.stringify(e.flags)">⚑ flagged</span>
          <span class="secs">{{ e.seconds != null ? `${e.seconds}s` : '' }}</span>
        </button>
        <p v-if="e.error" class="err">{{ e.error }}</p>
        <div v-if="open.has(key(e, i))" class="detail">
          <button class="btn btn-sm" @click="copy(json(e), key(e, i))">
            {{ copiedKey === key(e, i) ? '✓ Copied' : '⧉ Copy JSON' }}
          </button>
          <h4>Sent</h4>
          <pre>{{ json(e.request) }}</pre>
          <h4>Response</h4>
          <pre v-if="e.response != null">{{ typeof e.response === 'string' ? e.response : json(e.response) }}</pre>
          <p v-else class="sub">Nothing recorded (the connection failed, or the provider sent no body).</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.failed {
  font-size: 0.8rem;
  color: var(--smuted);
  display: inline-flex;
  align-items: center;
  gap: 0.3333rem;
  text-transform: none;
  letter-spacing: 0;
  font-weight: 400;
  cursor: pointer;
}
.entry {
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  margin-bottom: 0.4rem;
  overflow: hidden;
  background: var(--sbg);
}
.entry.bad {
  border-color: color-mix(in srgb, var(--sdanger) 45%, transparent);
}
.row {
  display: flex;
  align-items: center;
  gap: 0.6667rem;
  width: 100%;
  padding: 0.5333rem 0.8rem;
  background: none;
  border: none;
  color: var(--sfg);
  cursor: pointer;
  text-align: left;
  font-size: 0.8333rem;
  font-variant-numeric: tabular-nums;
}
.row:hover {
  background: var(--shover);
}
.status {
  font-weight: 700;
  min-width: 2.2667rem;
}
.status.good {
  color: var(--ssuccess);
}
.status.fail {
  color: var(--sdanger);
}
.when {
  color: var(--sfaint);
}
.provider {
  font-weight: 600;
}
.path,
.model {
  color: var(--smuted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.path {
  flex: 1;
  min-width: 0;
}
.flag {
  color: var(--swarn);
}
.secs {
  color: var(--sfaint);
  margin-left: auto;
}
.err {
  padding: 0.4rem 0.8rem;
  color: var(--sdanger);
  font-size: 0.8rem;
}
.detail {
  padding: 0.6667rem 0.8rem;
  border-top: 1px solid var(--sborder2);
}
.detail h4 {
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--sfaint);
  margin: 0.6667rem 0 0.2667rem;
}
.detail pre {
  background: var(--sbg2);
  border-radius: var(--r);
  padding: 0.6667rem;
  overflow-x: auto;
  font-size: 0.8rem;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
