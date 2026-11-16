<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import type { Generation } from '../../composables/chatFilesApi'
import { chatMediaUrl, chatMediaPreviewUrl } from '../../composables/useChat'
import { readText, writeText } from '../../utils/storage'

const props = withDefaults(
  defineProps<{
    entries?: readonly Generation[] | undefined
    pending?: number | undefined
    done?: number | undefined
  }>(),
  { entries: () => [], pending: 0, done: 0 },
)
const emit = defineEmits<{ open: [entry: Generation]; clear: []; 'clear-one': [mediaId: string] }>()

const COLLAPSED_KEY = 'studio.genQueue.collapsed'
const collapsed = ref(readText(COLLAPSED_KEY) !== '0')
function toggle(): void {
  collapsed.value = !collapsed.value
  writeText(COLLAPSED_KEY, collapsed.value ? '1' : '0')
}

const root = ref<HTMLElement | null>(null)
// Clicking anywhere else folds the list away, so it never sits over a menu
const onOutside = (event: MouseEvent): void => {
  if (!collapsed.value && root.value && event.target instanceof Node && !root.value.contains(event.target)) {
    collapsed.value = true
  }
}
onMounted(() => {
  document.addEventListener('mousedown', onOutside)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onOutside)
})

const thumb = (entry: Generation): string =>
  entry.kind === 'image'
    ? chatMediaPreviewUrl(entry.conversation_id, entry.file ?? '')
    : chatMediaUrl(entry.conversation_id, entry.file ?? '')
function label(entry: Generation): string {
  if (entry.status === 'pending') return entry.kind === 'video' ? 'Rendering video…' : 'Creating image…'
  if (entry.status === 'error') return entry.moderated ? 'Blocked' : 'Failed'
  return entry.kind === 'video' ? 'Video ready' : 'Image ready'
}
</script>

<template>
  <div v-if="props.entries.length" ref="root" class="qdock" :class="{ collapsed }">
    <div class="qhead" @click="toggle">
      <span class="qtitle">
        <span v-if="pending" class="qspin"></span>
        {{ pending ? `${pending} generating` : 'Generations' }}
      </span>
      <span class="qcount">{{ props.entries.length }}</span>
      <button class="qbtn" :title="collapsed ? 'Expand' : 'Collapse'" @click.stop="toggle">
        {{ collapsed ? '▴' : '▾' }}
      </button>
    </div>

    <!-- One popover above the pill: the list, then the clear strip inside it.
         (The dock is column-reverse, so this sits above the head in the DOM
         order it reads on screen.) -->
    <div v-show="!collapsed" class="qpop">
      <div class="qbody">
        <button
          v-for="e in entries"
          :key="e.media_id"
          type="button"
          class="qrow"
          :class="e.status"
          @click="emit('open', e)"
        >
          <span class="qthumb" :class="e.kind">
            <img v-if="e.status === 'done' && e.file && e.kind === 'image'" :src="thumb(e)" loading="lazy" alt="" />
            <video v-else-if="e.status === 'done' && e.file" :src="thumb(e)" muted preload="metadata"></video>
            <span v-else-if="e.status === 'pending'" class="qspin sm"></span>
            <span v-else class="qfail">✕</span>
          </span>
          <span class="qinfo">
            <span class="qlabel">{{ label(e) }}</span>
            <span class="qsub">{{ e.conversation_title || 'Untitled thread' }}</span>
          </span>
          <span class="qx" title="Remove from queue" @click.stop="emit('clear-one', e.media_id)">×</span>
        </button>
      </div>
      <div v-if="done" class="qfoot">
        <button class="qclear" @click="emit('clear')">Clear {{ done }} finished</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.qdock {
  position: fixed;
  bottom: 16px;
  right: 16px;
  z-index: 60;
  width: 300px;
  max-width: calc(100vw - 32px);
  display: flex;
  flex-direction: column-reverse; /* pill sits at the bottom; the list opens upward */
}
.qdock.collapsed {
  width: auto;
}
.qhead {
  border: 1px solid var(--sborder);
  border-radius: 999px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 10px 10px 12px;
  cursor: pointer;
  background: var(--spanel2);
}
.qtitle {
  flex: 1;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--sfg);
}
.qcount {
  font-size: 11px;
  color: var(--smuted);
  background: var(--shover);
  border-radius: 10px;
  padding: 1px 8px;
}
.qbtn {
  border: none;
  background: transparent;
  color: var(--smuted);
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  padding: 2px 4px;
}
.qpop {
  display: flex;
  flex-direction: column;
  margin-bottom: 6px;
  overflow: hidden;
  border: 1px solid var(--sborder);
  border-radius: var(--r-lg);
  background: var(--spanel2);
  box-shadow: var(--shadow-pop);
}
.qbody {
  max-height: min(55vh, 420px);
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.qrow {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 6px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--sfg);
  cursor: pointer;
  text-align: left;
  font: inherit;
}
.qrow:hover {
  background: var(--shover);
}
.qthumb {
  position: relative;
  flex: 0 0 auto;
  width: 38px;
  height: 38px;
  border-radius: 7px;
  overflow: hidden;
  background: var(--sbg2);
  display: grid;
  place-items: center;
}
.qthumb img,
.qthumb video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.qrow.error .qthumb {
  background: color-mix(in srgb, var(--sdanger) 14%, var(--sbg2));
}
.qfail {
  color: var(--sdanger);
  font-size: 13px;
  font-weight: 700;
}
.qinfo {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.qlabel {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.qrow.error .qlabel {
  color: var(--sdanger);
}
.qrow.pending .qlabel {
  color: var(--saccent);
}
.qsub {
  font-size: 11px;
  color: var(--smuted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.qx {
  flex: 0 0 auto;
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border-radius: 5px;
  color: var(--sfaint);
  font-size: 16px;
  line-height: 1;
}
.qx:hover {
  background: var(--sborder);
  color: var(--sfg);
}
.qfoot {
  flex: 0 0 auto;
  padding: 4px;
  border-top: 1px solid var(--sborder2);
}
.qclear {
  width: 100%;
  padding: 6px;
  border: 0;
  border-radius: var(--r);
  background: transparent;
  color: var(--smuted);
  cursor: pointer;
  font-size: 12px;
}
.qclear:hover {
  background: var(--shover);
  color: var(--sfg);
}
.qspin {
  width: 13px;
  height: 13px;
  border: 2px solid var(--sborder);
  border-top-color: var(--saccent);
  border-radius: 50%;
  animation: qspin 0.8s linear infinite;
}
.qspin.sm {
  width: 18px;
  height: 18px;
}
@keyframes qspin {
  to {
    transform: rotate(360deg);
  }
}
</style>
