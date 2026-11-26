<script setup lang="ts">
import { vTip } from '../../directives/tip'
import { computed, ref } from 'vue'
import type { GenerationItem, LengthFilter } from '../../composables/studioTypes'
import { reloadImageLater } from '../../utils/imageRetry'
import { readText, writeText } from '../../utils/storage'
import SelectionBar from './SelectionBar.vue'
import GenerationFilters from './GenerationFilters.vue'

const props = withDefaults(
  defineProps<{
    items?: readonly GenerationItem[] | undefined
    empty?: string | undefined
    /** The Favourites page is already favourites-only, so it hides the ★ filter. */
    favFilter?: boolean | undefined
    /** Shows Select, for picking several finished files and deleting them together. */
    selectable?: boolean | undefined
    /** Filters the page adds in the Filter popover that are switched on (they count on its badge). */
    extraActive?: number | undefined
  }>(),
  { items: () => [], empty: 'Nothing here yet.', favFilter: true, selectable: false, extraActive: 0 },
)
const emit = defineEmits<{
  open: [item: GenerationItem]
  favourite: [item: GenerationItem]
  deleteMany: [items: GenerationItem[]]
  downloadMany: [items: GenerationItem[]]
}>()

// Picking: only finished files can be picked (a pending or failed tile has no file to delete)
const picking = ref(false)
const picked = ref<ReadonlySet<string>>(new Set())
const pickable = (item: GenerationItem): boolean => item.status !== 'pending' && item.status !== 'error' && !!item.file
const pickedItems = computed(() => props.items.filter(it => picked.value.has(it.id)))
function togglePicking(): void {
  picking.value = !picking.value
  picked.value = new Set()
}
function onThumb(item: GenerationItem): void {
  if (!picking.value) {
    emit('open', item)
    return
  }
  const next = new Set(picked.value)
  if (!next.delete(item.id)) next.add(item.id)
  picked.value = next
}
function pickAll(): void {
  picked.value = new Set(shown.value.filter(pickable).map(it => it.id))
}
function deletePicked(): void {
  emit('deleteMany', pickedItems.value)
  togglePicking()
}
const clearPicked = (): void => {
  picked.value = new Set()
}

type Size = 's' | 'm' | 'l'
const SIZES: readonly Size[] = ['s', 'm', 'l']
const SIZE_KEY = 'studio.gallerySize'
const MIN_COLUMN_PX: Readonly<Record<Size, number>> = { s: 100, m: 150, l: 230 }
const isSize = (value: string | null): value is Size => value === 's' || value === 'm' || value === 'l'
const stored = readText(SIZE_KEY)
const size = ref<Size>(isSize(stored) ? stored : 'm')
function setSize(next: Size): void {
  size.value = next
  writeText(SIZE_KEY, next)
}
const minCol = computed(() => `${String(MIN_COLUMN_PX[size.value])}px`)

const kind = ref('all') // all | image | video
const favOnly = ref(false)
const model = ref('')
const length = ref<LengthFilter>('any')

// A video's length in seconds, when its settings say
const seconds = (it: GenerationItem): number | null => {
  const value = Number(it.params?.['duration'])
  return Number.isFinite(value) && value > 0 ? value : null
}
const inLength = (it: GenerationItem, wanted: LengthFilter): boolean => {
  const s = seconds(it)
  if (wanted === 'any') return true
  if (s === null) return false
  return wanted === 'short' ? s <= 5 : wanted === 'medium' ? s > 5 && s <= 10 : s > 10
}
const modelNames = computed(() => [...new Set(props.items.flatMap(it => it.model ?? []))].sort())
const hasLengths = computed(() => props.items.some(it => it.kind === 'video' && seconds(it) !== null))
const shown = computed(() =>
  props.items.filter(it => {
    if (kind.value !== 'all' && it.kind !== kind.value) return false
    if (favOnly.value && !it.favourite) return false
    if (model.value && it.model !== model.value) return false
    return inLength(it, length.value)
  }),
)
// A preview that fails once falls back to the full file, then retries once
// (a half-written file or a dropped connection), instead of staying blank
const RETRY_MS = 1500
function onImgError(event: Event, item: GenerationItem): void {
  const img = event.target
  if (!(img instanceof HTMLImageElement) || !item.url) return
  if (!img.dataset['fb'] && img.src !== new URL(item.url, location.href).href) {
    img.dataset['fb'] = '1'
    img.src = item.url
  } else if (!img.dataset['retry']) {
    img.dataset['retry'] = '1'
    reloadImageLater(img, item.url, RETRY_MS)
  }
}
const inProgress = computed(() => props.items.filter(it => it.status === 'pending').length)
</script>

<template>
  <div class="gpage">
    <div class="gens">
      <div class="gbar">
        <div class="gleft">
          <span class="gcount">{{ shown.length }} item{{ shown.length === 1 ? '' : 's' }}</span>
          <span v-if="inProgress" class="ginprog"><span class="dot"></span>{{ inProgress }} generating</span>
        </div>
        <div class="gtools">
          <GenerationFilters
            v-model:kind="kind"
            v-model:fav-only="favOnly"
            v-model:model="model"
            v-model:length="length"
            :models="modelNames"
            :lengths="hasLengths"
            :fav-filter="favFilter"
            :extra-active="extraActive"
          >
            <!-- Filters the page using the grid adds (e.g. unused files) -->
            <slot name="filters"></slot>
          </GenerationFilters>
          <button
            v-if="selectable"
            v-tip="picking ? 'Done selecting' : 'Select several'"
            class="iconbtn boxed"
            :class="{ on: picking }"
            :aria-label="picking ? 'Done selecting' : 'Select several'"
            :aria-pressed="picking"
            @click="togglePicking"
          >
            <svg class="ic"><use href="#s-selectall" /></svg>
          </button>
          <div class="seg" role="group" aria-label="Card size">
            <button v-for="s in SIZES" :key="s" :class="{ on: size === s }" @click="setSize(s)">
              {{ s.toUpperCase() }}
            </button>
          </div>
        </div>
      </div>
      <div v-if="!props.items.length" class="empty">{{ empty }}</div>
      <div v-else-if="!shown.length" class="empty">Nothing matches these filters.</div>
      <div v-else class="grid" :style="{ '--min': minCol }">
        <div
          v-for="(item, i) in shown"
          :key="item.id + '-' + i"
          v-tip="item.prompt || item.file || undefined"
          class="cell"
          :class="[item.status, { picked: picked.has(item.id) }]"
        >
          <div v-if="item.status === 'pending'" class="thumb state pending">
            <div class="spinner"></div>
            <div class="slabel">{{ item.kind === 'image' ? 'Creating image…' : 'Rendering video…' }}</div>
            <div v-if="item.prompt" class="sprompt">{{ item.prompt }}</div>
          </div>
          <button
            v-else-if="item.status === 'error'"
            v-tip="'Failed: open for details'"
            type="button"
            class="thumb state errored"
            @click="emit('open', item)"
          >
            <div class="slabel">{{ item.moderated ? 'Blocked' : 'Failed' }}</div>
            <div v-if="item.prompt" class="sprompt">{{ item.prompt }}</div>
            <div class="shint">Click for details</div>
          </button>
          <template v-else>
            <a class="thumb" :href="item.url" @click.prevent="onThumb(item)">
              <img
                v-if="item.kind === 'image'"
                :src="item.preview || item.url"
                loading="lazy"
                alt=""
                @error="onImgError($event, item)"
              />
              <video v-else :src="item.url" preload="metadata" muted playsinline></video>
              <span v-if="item.kind === 'video'" class="vtag">▶</span>
            </a>
            <span v-if="picking" class="tick" :class="{ on: picked.has(item.id) }">✓</span>
            <button
              v-if="!picking"
              v-tip="item.favourite ? 'Unfavourite' : 'Favourite'"
              class="fav"
              :class="{ on: item.favourite }"
              :aria-label="item.favourite ? 'Unfavourite' : 'Favourite'"
              @click.stop="emit('favourite', item)"
            >
              <svg class="ic"><use href="#s-star" /></svg>
            </button>
          </template>
        </div>
      </div>
    </div>
    <SelectionBar
      v-if="selectable && picking"
      :count="picked.size"
      @select-all="pickAll"
      @download="emit('downloadMany', pickedItems)"
      @delete="deletePicked"
      @clear="clearPicked"
    />
  </div>
</template>

<style scoped>
.gpage {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.gens {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0.8rem 1.0667rem 1.0667rem;
}
.gbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
  padding-bottom: 0.8rem;
}
.gleft {
  display: inline-flex;
  align-items: center;
  gap: 0.6667rem;
  flex-wrap: wrap;
}
.gcount {
  font-size: 0.8rem;
  color: var(--smuted);
}
.ginprog {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  color: var(--saccent);
}
.ginprog .dot {
  width: 0.4667rem;
  height: 0.4667rem;
  border-radius: 50%;
  background: var(--saccent);
  animation: pulse 1.1s ease-in-out infinite;
}
.gtools {
  display: inline-flex;
  align-items: center;
  gap: 0.5333rem;
  margin-left: auto;
}
.empty {
  color: var(--smuted);
  text-align: center;
  padding: 2.6667rem 0;
  font-size: 0.8667rem;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--min, 10rem), 1fr));
  gap: 0.6667rem;
}
.cell {
  position: relative;
  aspect-ratio: 1;
}
.thumb {
  width: 100%;
  height: 100%;
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  overflow: hidden;
  background: var(--sbg2);
  cursor: pointer;
  padding: 0;
  display: block;
}
.cell.picked .thumb {
  border-color: var(--saccent);
  outline: 2px solid var(--saccent);
}
.tick {
  position: absolute;
  top: 0.4rem;
  right: 0.4rem;
  display: grid;
  place-items: center;
  width: 1.3333rem;
  height: 1.3333rem;
  border-radius: 50%;
  border: 1px solid var(--sborder);
  background: var(--sbg2);
  color: transparent;
  font-size: 0.8rem;
  pointer-events: none;
}
.tick.on {
  background: var(--saccent);
  border-color: var(--saccent);
  color: #fff;
}
.thumb:hover {
  border-color: var(--saccent);
}
.thumb img,
.thumb video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5333rem;
  cursor: default;
  padding: 0.6667rem;
  text-align: center;
}
.state.errored {
  border-color: var(--sdanger, #e5484d);
  color: var(--sdanger, #e5484d);
  cursor: pointer;
}
.state.errored:hover {
  background: color-mix(in srgb, var(--sdanger, #e5484d) 8%, var(--sbg2));
}
.shint {
  font-size: 0.8rem;
  color: var(--sfaint);
  margin-top: 2px;
}
.slabel {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--smuted);
}
.state.errored .slabel {
  color: var(--sdanger, #e5484d);
}
.sprompt {
  font-size: 0.8rem;
  line-height: 1.35;
  color: var(--sfaint);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.spinner {
  width: 1.6rem;
  height: 1.6rem;
  border: 2.5px solid var(--sborder);
  border-top-color: var(--saccent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.3;
  }
}
.vtag {
  position: absolute;
  bottom: 0.4rem;
  right: 0.4rem;
  font-size: 0.8rem;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
  border-radius: 0.2667rem;
  padding: 1px 0.4rem;
}
.fav {
  position: absolute;
  top: 0.4rem;
  left: 0.4rem;
  width: 1.7333rem;
  height: 1.7333rem;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 0.4667rem;
  background: rgba(0, 0, 0, 0.5);
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.12s;
}
.cell:hover .fav,
.fav.on {
  opacity: 1;
}
.fav.on {
  color: var(--sstar);
}
.fav .ic {
  width: 1rem;
  height: 1rem;
}
</style>
