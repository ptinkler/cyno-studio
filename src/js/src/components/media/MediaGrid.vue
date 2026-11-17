<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import type { LibraryEntry } from '../../composables/mediaApi'
import { mediaOrigin } from '../../composables/useMedia'
import { fmtDuration } from '../../utils/format'
import { reloadImageLater } from '../../utils/imageRetry'

// A grid of media-library items with infinite scroll: tiles are added a
// small batch at a time as you near the bottom, and each tile's small
// server-made thumbnail loads only when the tile is near the screen.
// With `selectable`, clicking toggles an item's selection ('toggle', with
// the click event, e.g. for shift-click ranges); otherwise it opens it
// ('open'). `checkboxes`: each tile's tick circle shows on hover, and
// clicking it toggles that item even when not `selectable` — so selecting
// can start from any tile.
const props = withDefaults(
  defineProps<{
    items?: readonly LibraryEntry[] | undefined
    selected?: ReadonlySet<string> | undefined
    selectable?: boolean | undefined
    checkboxes?: boolean | undefined
    pageSize?: number | undefined
    /** The caller has more rows it can load (server-side paging): once the last loaded tile is revealed, reaching the sentinel asks for them ('more'). */
    hasMore?: boolean | undefined
  }>(),
  {
    items: () => [],
    selected: () => new Set<string>(),
    selectable: false,
    checkboxes: false,
    pageSize: 20,
    hasMore: false,
  },
)
const emit = defineEmits<{ toggle: [item: LibraryEntry, event: MouseEvent]; open: [item: LibraryEntry]; more: [] }>()

const shown = ref(props.pageSize)
const visible = computed(() => props.items.slice(0, shown.value))
// New filters or search start from the top again; a page appended to the end
// (same first item, longer) keeps the current scroll position.
watch(
  () => props.items,
  (next, prev) => {
    const appended = next.length > prev.length && next[0] === prev[0]
    if (!appended) shown.value = props.pageSize
  },
)

// Add the next batch when the sentinel after the last tile comes within
// ~a row of the screen. Without IntersectionObserver (old browsers, tests) show all.
const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null
watch(sentinel, el => {
  observer?.disconnect()
  if (!el) return
  if (typeof IntersectionObserver === 'undefined') {
    shown.value = Infinity
    return
  }
  const watching = new IntersectionObserver(
    entries => {
      if (!entries.some(e => e.isIntersecting)) return
      // Reveal the next batch of already-loaded tiles; once they're all shown,
      // ask the caller for another server page.
      if (shown.value < props.items.length) shown.value += props.pageSize
      else if (props.hasMore) emit('more')
      // Still in range after the new page (a tall screen)? Observing afresh
      // reports the current state again, so it keeps filling.
      void nextTick(() => {
        if (!sentinel.value) return
        watching.unobserve(sentinel.value)
        watching.observe(sentinel.value)
      })
    },
    { rootMargin: '300px 0px' },
  )
  observer = watching
  watching.observe(el)
})
onBeforeUnmount(() => observer?.disconnect())

function onTileClick(item: LibraryEntry, event: MouseEvent): void {
  if (props.selectable) {
    emit('toggle', item, event)
  } else {
    event.preventDefault()
    emit('open', item)
  }
}

// A thumbnail that fails (e.g. the server was busy) is retried once, then
// the tile shows a placeholder
const retried = ref(new Set<string>())
const failed = ref(new Set<string>())
function onThumbError(item: LibraryEntry, event: Event): void {
  if (!retried.value.has(item.id)) {
    retried.value = new Set(retried.value).add(item.id)
    if (event.target instanceof HTMLImageElement) reloadImageLater(event.target, item.thumb_url, 2000)
  } else {
    failed.value = new Set(failed.value).add(item.id)
  }
}
</script>

<template>
  <div class="media-grid">
    <component
      :is="selectable ? 'button' : 'a'"
      v-for="item in visible"
      :key="item.id"
      :type="selectable ? 'button' : undefined"
      :href="selectable ? undefined : item.url"
      class="tile"
      :class="{ selected: props.selected.has(item.id) }"
      :title="[item.prompt || item.name, mediaOrigin(item)].filter(Boolean).join(' — ')"
      @click="onTileClick(item, $event)"
    >
      <span v-if="failed.has(item.id)" class="no-thumb">{{ item.kind === 'video' ? '🎬' : '🖼' }}</span>
      <img v-else :src="item.thumb_url" alt="" loading="lazy" decoding="async" @error="onThumbError(item, $event)" />
      <span v-if="item.kind === 'video'" class="badge video">▶</span>
      <span class="badge source">{{ item.source === 'upload' ? '⬆' : '✨' }}</span>
      <span v-if="item.kind === 'video' && item.duration" class="duration">{{ fmtDuration(item.duration) }}</span>
      <span
        v-if="selectable || checkboxes"
        class="check"
        :class="{ hover: !selectable }"
        role="checkbox"
        :aria-checked="props.selected.has(item.id)"
        :aria-label="`Select ${item.name}`"
        @click.stop="emit('toggle', item, $event)"
        >{{ props.selected.has(item.id) ? '✓' : '' }}</span
      >
    </component>
    <div v-if="visible.length < props.items.length || hasMore" ref="sentinel" class="sentinel" aria-hidden="true"></div>
  </div>
</template>

<style scoped>
.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--tile-xs), 1fr));
  gap: 0.5333rem;
}

.tile {
  display: block;
  text-decoration: none;
  color: inherit;
  position: relative;
  aspect-ratio: 1;
  padding: 0;
  border: 2px solid transparent;
  border-radius: 0.6667rem;
  overflow: hidden;
  background: var(--surface2);
  cursor: pointer;
}

.tile:hover {
  border-color: var(--border);
}

.tile.selected {
  border-color: var(--accent);
}

.tile img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  pointer-events: none;
}

.no-thumb {
  display: grid;
  place-items: center;
  height: 100%;
  font-size: 1.6rem;
  opacity: 0.5;
}

.sentinel {
  grid-column: 1 / -1;
  height: 1px;
}

.badge {
  position: absolute;
  top: 0.3333rem;
  font-size: 0.7333rem;
  padding: 1px 0.4rem;
  border-radius: 0.4rem;
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
}

.badge.video {
  left: 0.3333rem;
}

.badge.source {
  right: 0.3333rem;
}

.duration {
  position: absolute;
  right: 0.3333rem;
  bottom: 0.3333rem;
  font-size: 0.7333rem;
  padding: 1px 0.4rem;
  border-radius: 0.4rem;
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
  font-variant-numeric: tabular-nums;
}

.check {
  position: absolute;
  top: 0.3333rem;
  left: 50%;
  transform: translateX(-50%);
  width: 1.4667rem;
  height: 1.4667rem;
  border-radius: 50%;
  border: 2px solid #fff;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  font-size: 0.8rem;
  line-height: 1.2rem;
}

/* Until something is selected, the circle only shows on hover (or keyboard focus) */
.check.hover {
  opacity: 0;
  transition: opacity 0.12s;
}

.tile:hover .check.hover,
.tile:focus-visible .check.hover {
  opacity: 1;
}

.check:hover {
  border-color: var(--accent2);
}

.tile.selected .check {
  background: var(--accent);
  border-color: var(--accent);
}
</style>
