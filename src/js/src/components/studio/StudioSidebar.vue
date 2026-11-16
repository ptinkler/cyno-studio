<script setup lang="ts">
import SidebarSpaceFolder from './SidebarSpaceFolder.vue'
import SidebarThreadRow from './SidebarThreadRow.vue'
import { ref, computed } from 'vue'
import type { ConversationSummary } from '../../composables/chatConversationsApi'
import type { Space, ThreadKind } from '../../composables/studioTypes'
import type { NavFilter } from '../../composables/useStudioRoutes'
import { typedValue } from '../../utils/focusSelect'

const props = withDefaults(
  defineProps<{
    threads?: readonly ConversationSummary[] | undefined
    spaces?: readonly Space[] | undefined
    active?: string | null | undefined
    collapsed?: boolean | undefined
    search?: string | undefined
    filter?: NavFilter | 'favourites' | undefined
  }>(),
  { threads: () => [], spaces: () => [], active: null, collapsed: false, search: '', filter: 'all' },
)
const emit = defineEmits<{
  'update:collapsed': [collapsed: boolean]
  'update:search': [search: string]
  'update:filter': [filter: NavFilter | 'favourites']
  open: [id: string]
  new: [kind: ThreadKind]
  pin: [thread: ConversationSummary]
  rename: [thread: ConversationSummary, name: string]
  delete: [thread: ConversationSummary]
  settings: []
  'open-space': [space: Space]
  'add-space': []
  'rename-space': [space: Space, name: string]
  'delete-space': [space: Space]
  'space-settings': [space: Space]
  move: [thread: ConversationSummary, spaceId: number | null]
  media: []
  tools: []
}>()

const openSpaces = ref<ReadonlySet<number>>(new Set())
const pinnedSectionOpen = ref(true)
const spacesSectionOpen = ref(true)
const recentSectionOpen = ref(true)
function toggleSpace(id: number): void {
  const next = new Set(openSpaces.value)
  if (!next.delete(id)) next.add(id)
  openSpaces.value = next
}

// Inline rename (no modal / prompt)
const renamingId = ref<string | null>(null)
const renameText = ref('')
function startRename(thread: ConversationSummary): void {
  renamingId.value = thread.id
  renameText.value = thread.title
}
function commitRename(thread: ConversationSummary): void {
  if (renamingId.value !== thread.id) return // already committed (e.g. Enter then blur)
  const name = renameText.value.trim()
  renamingId.value = null
  if (name && name !== thread.title) emit('rename', thread, name)
}
function cancelRename(): void {
  renamingId.value = null
}
const spaceKey = (space: Space): string => `space:${String(space.id)}`
function startRenameSpace(space: Space): void {
  renamingId.value = spaceKey(space)
  renameText.value = space.name
}
function commitRenameSpace(space: Space): void {
  if (renamingId.value !== spaceKey(space)) return
  const name = renameText.value.trim()
  renamingId.value = null
  if (name && name !== space.name) emit('rename-space', space, name)
}

// Drag a thread onto a space folder (or Recent) to move it
const dragId = ref<string | null>(null)
const dropOn = ref<number | 'unfiled' | null>(null)
function onDrop(spaceId: number | null): void {
  const thread = props.threads.find(t => t.id === dragId.value)
  if (thread && thread.space_id !== spaceId) emit('move', thread, spaceId)
  dragId.value = null
  dropOn.value = null
}

// Chat/Gallery filter the list by a thread's kind; All and Favourites show
// every thread (Favourites swaps the centre pane for the gallery, not the nav).
function matchesKind(thread: ConversationSummary): boolean {
  if (props.filter === 'chat') return thread.kind !== 'gallery'
  if (props.filter === 'gallery') return thread.kind === 'gallery'
  return true
}
const filtered = computed(() => {
  const q = props.search.trim().toLowerCase()
  return props.threads.filter(t => matchesKind(t) && (!q || t.title.toLowerCase().includes(q)))
})
const pinned = computed(() => filtered.value.filter(t => t.pinned))
const bySpace = computed(() => {
  const groups = new Map(props.spaces.map(space => [space.id, { space, items: [] as ConversationSummary[] }]))
  const unfiled: ConversationSummary[] = []
  for (const thread of filtered.value) {
    if (thread.pinned) continue
    const group = thread.space_id === null ? undefined : groups.get(thread.space_id)
    if (group) group.items.push(thread)
    else unfiled.push(thread)
  }
  return { groups: [...groups.values()], unfiled }
})
</script>

<template>
  <aside class="side" :class="{ collapsed }">
    <button
      class="rail"
      type="button"
      title="Expand sidebar"
      aria-label="Expand sidebar"
      @click="emit('update:collapsed', false)"
    >
      <svg class="ic lg chev"><use href="#s-chev" /></svg>
      <span class="rail-label">Studio</span>
      <svg class="ic lg"><use href="#s-plus" /></svg>
      <svg class="ic lg"><use href="#s-chat" /></svg>
    </button>
    <div class="panel">
      <button
        class="panelhead"
        type="button"
        title="Collapse sidebar"
        aria-label="Collapse sidebar"
        @click="emit('update:collapsed', true)"
      >
        <span class="brand"
          ><span class="mk"
            ><svg class="ic"><use href="#s-spark" /></svg
          ></span>
          Studio</span
        >
        <svg class="ic"><use href="#s-chevL" /></svg>
      </button>
      <div class="pbody">
        <div class="newrow">
          <a class="newbtn" href="/" @click.prevent="emit('new', 'chat')">
            <svg class="ic"><use href="#s-plus" /></svg> New chat
          </a>
          <a class="newbtn" href="/?new=gallery" @click.prevent="emit('new', 'gallery')">
            <svg class="ic"><use href="#s-image" /></svg> New gallery
          </a>
        </div>
        <div class="sbox nsearch">
          <svg class="ic"><use href="#s-search" /></svg>
          <input
            :value="search"
            type="search"
            placeholder="Search threads…"
            @input="emit('update:search', typedValue($event))"
          />
        </div>
        <div class="nfilter">
          <button class="pillbtn" :class="{ on: filter === 'all' }" @click="emit('update:filter', 'all')">All</button>
          <button class="pillbtn" :class="{ on: filter === 'chat' }" @click="emit('update:filter', 'chat')">
            Chat
          </button>
          <button class="pillbtn" :class="{ on: filter === 'gallery' }" @click="emit('update:filter', 'gallery')">
            Gallery
          </button>
          <a
            class="pillbtn ficon"
            :class="{ on: filter === 'favourites' }"
            title="Favourites"
            href="/favourites"
            @click.prevent="emit('update:filter', 'favourites')"
          >
            <svg class="ic"><use href="#s-star" /></svg>
          </a>
          <button
            class="pillbtn ficon"
            title="More filters — coming soon"
            aria-label="More filters — coming soon"
            disabled
          >
            <svg class="ic"><use href="#s-filter" /></svg>
          </button>
        </div>

        <template v-if="pinned.length">
          <button
            class="nlabel section-toggle"
            :aria-expanded="pinnedSectionOpen"
            @click="pinnedSectionOpen = !pinnedSectionOpen"
          >
            <svg class="ic sm"><use href="#s-chev" /></svg>
            <span>Pinned</span>
          </button>
          <div
            v-for="t in pinned"
            v-show="pinnedSectionOpen"
            :key="t.id"
            class="nrow"
            :class="{ active: t.id === active }"
          >
            <SidebarThreadRow
              v-model:rename-text="renameText"
              :thread="t"
              :renaming="renamingId === t.id"
              always-pinned
              @open="emit('open', t.id)"
              @pin="emit('pin', t)"
              @start-rename="startRename(t)"
              @commit-rename="commitRename(t)"
              @cancel-rename="cancelRename"
              @delete="emit('delete', t)"
            />
          </div>
        </template>

        <div class="nlabel row">
          <button
            class="section-toggle"
            :aria-expanded="spacesSectionOpen"
            @click="spacesSectionOpen = !spacesSectionOpen"
          >
            <svg class="ic sm"><use href="#s-chev" /></svg>
            <span>Spaces</span>
          </button>
          <button class="addspace" title="New space" aria-label="New space" @click="emit('add-space')">
            <svg class="ic sm"><use href="#s-plus" /></svg>
          </button>
        </div>
        <template v-for="g in bySpace.groups" :key="g.space.id">
          <SidebarSpaceFolder
            v-show="spacesSectionOpen"
            v-model:rename-text="renameText"
            :space="g.space"
            :count="g.items.length"
            :open="openSpaces.has(g.space.id)"
            :drop="dropOn === g.space.id"
            :renaming="renamingId === spaceKey(g.space)"
            @toggle="toggleSpace(g.space.id)"
            @open="emit('open-space', g.space)"
            @start-rename="startRenameSpace(g.space)"
            @commit-rename="commitRenameSpace(g.space)"
            @cancel-rename="cancelRename"
            @settings="emit('space-settings', g.space)"
            @delete="emit('delete-space', g.space)"
            @dragover="dropOn = g.space.id"
            @dragleave="dropOn = null"
            @drop="onDrop(g.space.id)"
          />
          <div v-show="spacesSectionOpen && openSpaces.has(g.space.id)" class="fkids">
            <div
              v-for="t in g.items"
              :key="t.id"
              class="nrow sm"
              :class="{ active: t.id === active }"
              draggable="true"
              @dragstart="dragId = t.id"
            >
              <SidebarThreadRow
                v-model:rename-text="renameText"
                :thread="t"
                :renaming="renamingId === t.id"
                :pinned="t.pinned"
                @open="emit('open', t.id)"
                @pin="emit('pin', t)"
                @start-rename="startRename(t)"
                @commit-rename="commitRename(t)"
                @cancel-rename="cancelRename"
                @delete="emit('delete', t)"
              />
            </div>
            <div v-if="!g.items.length" class="fempty">Empty — drag threads here</div>
          </div>
        </template>

        <button
          class="nlabel section-toggle drop-target"
          :class="{ drop: dropOn === 'unfiled' }"
          :aria-expanded="recentSectionOpen"
          @click="recentSectionOpen = !recentSectionOpen"
          @dragover.prevent="dropOn = 'unfiled'"
          @dragleave="dropOn = null"
          @drop.prevent="onDrop(null)"
        >
          <svg class="ic sm"><use href="#s-chev" /></svg>
          <span>Recent</span>
        </button>
        <div
          v-for="t in bySpace.unfiled"
          v-show="recentSectionOpen"
          :key="t.id"
          class="nrow sm"
          :class="{ active: t.id === active }"
          draggable="true"
          @dragstart="dragId = t.id"
        >
          <SidebarThreadRow
            v-model:rename-text="renameText"
            :thread="t"
            :renaming="renamingId === t.id"
            :pinned="t.pinned"
            @open="emit('open', t.id)"
            @pin="emit('pin', t)"
            @start-rename="startRename(t)"
            @commit-rename="commitRename(t)"
            @cancel-rename="cancelRename"
            @delete="emit('delete', t)"
          />
        </div>
      </div>
      <div class="pfoot">
        <a class="footbtn" href="/media" @click.prevent="emit('media')">
          <svg class="ic"><use href="#s-image" /></svg> Media
        </a>
        <a class="footbtn" href="/tools" @click.prevent="emit('tools')">
          <svg class="ic"><use href="#s-spark" /></svg> Tools &amp; library
        </a>
        <a class="footbtn" href="/settings" @click.prevent="emit('settings')">
          <svg class="ic"><use href="#s-cog" /></svg> Settings
        </a>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.side {
  width: 268px;
  background: var(--sbg);
  border-right: 1px solid var(--sborder);
}
/* These are <a> so they can be opened in a new tab; they must still look and
   sit exactly like the buttons they replaced. */
.newbtn,
.footbtn,
.pillbtn.ficon {
  text-decoration: none;
  box-sizing: border-box;
}
.brand {
  display: flex;
  align-items: center;
  gap: 9px;
  font-weight: 650;
  letter-spacing: -0.02em;
}
.brand .mk {
  width: 24px;
  height: 24px;
  border-radius: 7px;
  background: var(--saccent-soft);
  color: var(--saccent);
  display: grid;
  place-items: center;
}
.pbody {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}
.newrow {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}
.newbtn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid var(--sborder);
  color: var(--sfg);
  border-radius: var(--r);
  background: none;
  cursor: pointer;
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap;
}
.newbtn:hover {
  border-color: var(--sfaint);
  background: var(--spanel2);
}
.newbtn .ic {
  color: var(--saccent);
}
.nsearch {
  margin-bottom: 8px;
}
.nfilter {
  display: flex;
  gap: 4px;
  padding-bottom: 6px;
}
/* Favourites + the filter placeholder are icon-only (text overflowed the rail) */
.nfilter .ficon {
  padding: 4px 7px;
  margin-left: auto;
}
.nfilter .ficon + .ficon {
  margin-left: 0;
}
.nlabel {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--sfaint);
  padding: 13px 10px 5px 0;
  font-weight: 650;
}
.section-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  border: 0;
  background: none;
  text-align: left;
  cursor: pointer;
}
.section-toggle[aria-expanded='true'] .ic {
  transform: rotate(90deg);
}
.section-toggle .ic {
  transition: transform 0.15s;
}
.nlabel.section-toggle {
  color: var(--sfaint);
}
.nlabel.row .section-toggle {
  flex: 1;
  width: auto;
  padding: 0;
  color: var(--sfaint);
  font: inherit;
  text-transform: inherit;
}
.nrow {
  position: relative;
  display: flex;
  align-items: center;
  border-radius: var(--r);
}
.nrow:hover {
  background: var(--shover);
}
.nrow:hover :deep(.nactions),
.nrow:focus-within :deep(.nactions) {
  visibility: visible;
}
.nrow.active {
  background: var(--saccent-soft);
}
.nrow.active :deep(.nitem),
.nrow:hover :deep(.nitem) {
  color: var(--sfg);
}
.nrow.active :deep(.nitem .ic) {
  color: var(--saccent);
}
.nrow.sm :deep(.nitem) {
  padding: 6px 10px;
  font-size: 13px;
}
.side :deep(.nactions) {
  display: flex;
  align-items: center;
  gap: 1px;
  flex: 0 0 82px;
  justify-content: flex-end;
  padding-right: 5px;
  visibility: hidden;
}
.side :deep(.nact) {
  width: 25px;
  height: 25px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  color: var(--sfaint);
  background: none;
  border: none;
  cursor: pointer;
}
.side :deep(.nact:hover) {
  background: var(--sborder);
  color: var(--sfg);
}
.side :deep(.nact.on) {
  color: var(--saccent);
}
.side :deep(.nact.danger),
.side :deep(.nact.danger:hover) {
  color: var(--sdanger);
}
.side :deep(.nact.danger:hover) {
  background: color-mix(in srgb, var(--sdanger) 12%, var(--sbg2));
}
.nrow:hover :deep(.nactions),
.nrow:focus-within :deep(.nactions) {
  visibility: visible;
}
.fkids {
  padding-left: 8px;
  margin-left: 20px;
  border-left: 1px solid var(--sborder2);
}
.fempty {
  padding: 7px 10px;
  color: var(--sfaint);
  font-size: 12px;
  font-style: italic;
}
.nlabel.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.addspace {
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  color: var(--sfaint);
  background: none;
  border: none;
  cursor: pointer;
}
.addspace:hover {
  background: var(--shover);
  color: var(--sfg);
}
.drop-target.drop {
  color: var(--saccent);
  box-shadow: inset 0 0 0 1px var(--saccent);
  border-radius: 7px;
}
.pfoot {
  padding: 8px 10px;
  border-top: 1px solid var(--sborder2);
}
.footbtn {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 7px 10px;
  border-radius: var(--r);
  font-size: 13.5px;
  color: var(--smuted);
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
}
.footbtn:hover {
  background: var(--shover);
  color: var(--sfg);
}
.footbtn .ic {
  color: var(--sfaint);
}
</style>
