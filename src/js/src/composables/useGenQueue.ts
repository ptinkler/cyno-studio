// Always-visible generation queue, backed by /api/chat/generations/active.
// It polls for the signed-in user's in-flight generations across *every* thread
// (so progress stays visible after you click away) and resolves ones it is
// already tracking to their final done/failed state. Finished items stay until
// the user clears them. Singleton module state → one poller app-wide.
import { computed, ref } from 'vue'
import type { Generation } from './chatFilesApi'
import { fetchActiveGenerations } from './useChat'
import { asRecord, readStored, writeStored } from '../utils/storage'

const STORE_KEY = 'studio.genQueue'
const POLL_MS = 4000

const isString = (value: unknown): boolean => typeof value === 'string'
const isStringOrNull = (value: unknown): boolean => value === null || typeof value === 'string'
const oneOf =
  (...allowed: unknown[]) =>
  (value: unknown): boolean =>
    allowed.includes(value)

// One check per field of a descriptor. Typed over `keyof Generation`, so a field added to the model can't be skipped.
const FIELD_CHECKS: Record<keyof Generation, (value: unknown) => boolean> = {
  media_id: isString,
  message_id: value => typeof value === 'number',
  conversation_id: isString,
  conversation_title: isString,
  kind: oneOf('image', 'video', 'audio'),
  prompt: isStringOrNull,
  model: isStringOrNull,
  status: oneOf('pending', 'done', 'error'),
  file: isStringOrNull,
  error: isStringOrNull,
  moderated: value => typeof value === 'boolean',
  created_at: isStringOrNull,
}

// What was stored by an earlier visit: kept only when it is a complete descriptor, since the dock reads every field
function isGeneration(value: unknown): value is Generation {
  const stored = asRecord(value)
  return Object.entries(FIELD_CHECKS).every(([key, ok]) => ok(stored[key]))
}

function load(): Generation[] {
  const stored = readStored(STORE_KEY)
  return Array.isArray(stored) ? stored.filter(isGeneration) : []
}

const persist = (): void => {
  writeStored(STORE_KEY, entries.value)
}

// Each entry is a server descriptor: where it is, what it is and how it is going.
const entries = ref<Generation[]>(load())
let timer: ReturnType<typeof setInterval> | undefined
let starts = 0

async function poll(): Promise<void> {
  const known = [...new Set(entries.value.map(e => e.message_id))]
  let items: Generation[]
  try {
    items = (await fetchActiveGenerations(known)).items
  } catch {
    return // offline / transient — keep the last known state
  }
  const byId = new Map(entries.value.map(e => [e.media_id, e]))
  const returned = new Set(items.map(i => i.media_id))
  const queried = new Set(known)
  for (const item of items) {
    const existing = byId.get(item.media_id)
    if (existing) {
      Object.assign(existing, item) // live update (pending → done/failed)
    } else if (item.status === 'pending') {
      // A generation we hadn't seen start (maybe from another thread/device).
      entries.value.push(item)
      byId.set(item.media_id, item)
    }
    // Finished items we never tracked are history — don't backfill them.
  }
  // Drop entries whose message was queried but no longer returned (deleted).
  entries.value = entries.value.filter(e => returned.has(e.media_id) || !queried.has(e.message_id))
  persist()
}

export function useGenQueue() {
  function start(): void {
    starts++
    if (timer === undefined) {
      void poll()
      timer = setInterval(() => void poll(), POLL_MS)
    }
  }
  function stop(): void {
    starts = Math.max(0, starts - 1)
    if (starts === 0 && timer !== undefined) {
      clearInterval(timer)
      timer = undefined
    }
  }
  const refresh = poll // call after kicking off a generation for instant feedback
  function clearDone(): void {
    entries.value = entries.value.filter(e => e.status === 'pending')
    persist()
  }
  function clearOne(mediaId: string): void {
    entries.value = entries.value.filter(e => e.media_id !== mediaId)
    persist()
  }
  const pending = computed(() => entries.value.filter(e => e.status === 'pending').length)
  const done = computed(() => entries.value.filter(e => e.status !== 'pending').length)
  return { entries, pending, done, start, stop, refresh, clearDone, clearOne }
}
