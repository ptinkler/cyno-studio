<script setup lang="ts">
import { vTip } from '../../directives/tip'
import { ref, computed } from 'vue'
import type { Instruction, InstructionGroup } from '../../composables/chatSettingsApi'
import type { InheritedDefault } from '../../composables/useChatDefaults'
import { instructionColor } from '../../utils/format'
import { defaultIcon as fromIcon, defaultTitle as fromTitle } from '../../utils/defaults'
import PickDialog from '../PickDialog.vue'
import type { PickItem } from '../PickDialog.vue'

type Kind = 'snippet' | 'group'

/** A chip or card was acted on: which kind of thing, and which one (null = a new one). */
interface Target {
  kind: Kind
  id: number
}

/** One card in the pick dialog. */
interface InstructionCard extends PickItem {
  id: number
  type: Kind
  kind: 'default' | 'own'
}

// Attached instruction groups and snippets as chips, plus a dialog to pick
// more (names aren't unique, so each card shows a preview of its text). Editing and creating happen in InstructionEditor (and the Instructions page); this
// only attaches/detaches, and emits 'edit' ({ kind, id }: a chip was
// clicked) or 'manage' to open that dialog.
const props = withDefaults(
  defineProps<{
    /** All saved snippets. */
    instructions?: readonly Instruction[] | undefined
    /** All saved groups. */
    groups?: readonly InstructionGroup[] | undefined
    /** Attached snippet ids. */
    snippetIds?: readonly number[] | undefined
    /** Attached group ids. */
    groupIds?: readonly number[] | undefined
    /** Show the "Manage & create…" item. */
    manageable?: boolean | undefined
    /** Attached by the chat's defaults: shown, but changed in the defaults, not here. */
    inheritedSnippets?: readonly InheritedDefault[] | undefined
    inheritedGroups?: readonly InheritedDefault[] | undefined
    /** Defaults switched off in this chat: offered in the menu to switch back on. */
    hiddenSnippets?: readonly InheritedDefault[] | undefined
    hiddenGroups?: readonly InheritedDefault[] | undefined
    /** Attached but paused in this chat (own or inherited): shown dimmed, not sent. */
    pausedSnippets?: readonly number[] | undefined
    pausedGroups?: readonly number[] | undefined
  }>(),
  {
    instructions: () => [],
    groups: () => [],
    snippetIds: () => [],
    groupIds: () => [],
    manageable: true,
    inheritedSnippets: () => [],
    inheritedGroups: () => [],
    hiddenSnippets: () => [],
    hiddenGroups: () => [],
    pausedSnippets: () => [],
    pausedGroups: () => [],
  },
)
// 'hide' / 'unhide': a default switched off / on in this chat only
// 'pause' / 'resume': an attachment paused / resumed in this chat
const emit = defineEmits<{
  'update:snippetIds': [ids: number[]]
  'update:groupIds': [ids: number[]]
  manage: []
  edit: [target: { kind: Kind; id: number | null }]
  hide: [target: Target]
  unhide: [target: Target]
  pause: [target: Target]
  resume: [target: Target]
}>()

const open = ref(false)
const close = (): void => {
  open.value = false
}
const toggle = (): void => {
  open.value = !open.value
}

const snippetById = computed(() => new Map(props.instructions.map(s => [s.id, s])))
const groupById = computed(() => new Map(props.groups.map(g => [g.id, g])))
const inheritedGroupIds = computed(() => [...props.inheritedGroups, ...props.hiddenGroups].map(x => x.id))
const inheritedSnippetIds = computed(() => [...props.inheritedSnippets, ...props.hiddenSnippets].map(x => x.id))

/** The items a default list names, each with where it comes from. */
function fromDefaults<T>(list: readonly InheritedDefault[], byId: ReadonlyMap<number, T>): (T & { from: string })[] {
  return list.flatMap(x => {
    const item = byId.get(x.id)
    return item ? [{ ...item, from: x.from }] : []
  })
}
const defaultGroups = computed(() => fromDefaults(props.inheritedGroups, groupById.value))
const defaultSnippets = computed(() => fromDefaults(props.inheritedSnippets, snippetById.value))
const hiddenGroupItems = computed(() => fromDefaults(props.hiddenGroups, groupById.value))
const hiddenSnippetItems = computed(() => fromDefaults(props.hiddenSnippets, snippetById.value))
const attachedGroups = computed(() =>
  props.groupIds.filter(id => !inheritedGroupIds.value.includes(id)).flatMap(id => groupById.value.get(id) ?? []),
)
const attachedSnippets = computed(() =>
  props.snippetIds.filter(id => !inheritedSnippetIds.value.includes(id)).flatMap(id => snippetById.value.get(id) ?? []),
)
const anyAttached = computed(
  () =>
    defaultGroups.value.length > 0 ||
    defaultSnippets.value.length > 0 ||
    attachedGroups.value.length > 0 ||
    attachedSnippets.value.length > 0,
)
const unattachedGroups = computed(() =>
  props.groups.filter(g => !props.groupIds.includes(g.id) && !inheritedGroupIds.value.includes(g.id)),
)
const unattachedSnippets = computed(() =>
  props.instructions.filter(s => !props.snippetIds.includes(s.id) && !inheritedSnippetIds.value.includes(s.id)),
)

function unhide(kind: Kind, item: { id: number }): void {
  emit('unhide', { kind, id: item.id })
}

function groupTitle(group: InstructionGroup): string {
  const n = group.snippet_ids.length
  return `Group — ${String(n)} snippet${n === 1 ? '' : 's'}`
}

const attachGroup = (g: InstructionGroup): void => {
  emit('update:groupIds', [...props.groupIds, g.id])
}
const detachGroup = (g: InstructionGroup): void => {
  emit(
    'update:groupIds',
    props.groupIds.filter(id => id !== g.id),
  )
}
const attachSnippet = (s: Instruction): void => {
  emit('update:snippetIds', [...props.snippetIds, s.id])
}
const detachSnippet = (s: Instruction): void => {
  emit(
    'update:snippetIds',
    props.snippetIds.filter(id => id !== s.id),
  )
}

const isPaused = (kind: Kind, id: number): boolean =>
  (kind === 'group' ? props.pausedGroups : props.pausedSnippets).includes(id)

function togglePause(kind: Kind, item: { id: number }): void {
  if (isPaused(kind, item.id)) emit('resume', { kind, id: item.id })
  else emit('pause', { kind, id: item.id })
}

// Open the editor for a new snippet / group (same modal as editing one)
function create(kind: Kind): void {
  close()
  emit('edit', { kind, id: null })
}

function manage(): void {
  close()
  emit('manage')
}

const sourceLabel = (from: string): string => `${fromIcon(from)} ${fromTitle(from)}`

// Every group and snippet as a card: in use (own, or from the defaults) or not
const preview = (text: string): string => text.replace(/\s+/g, ' ').trim().slice(0, 140)
const groupCard = (g: InstructionGroup, on: boolean, from?: string): InstructionCard => ({
  key: `g${from ? 'd' : ''}${String(g.id)}`,
  id: g.id,
  type: 'group',
  section: 'Groups',
  icon: '📦',
  name: g.name,
  sub: groupTitle(g),
  ...(from ? { from: sourceLabel(from) } : {}),
  on,
  kind: from ? 'default' : 'own',
})
const snippetCard = (sn: Instruction, on: boolean, from?: string): InstructionCard => ({
  key: `s${from ? 'd' : ''}${String(sn.id)}`,
  id: sn.id,
  type: 'snippet',
  section: 'Snippets',
  dot: instructionColor(sn.name),
  name: sn.name,
  sub: preview(sn.content),
  ...(from ? { from: sourceLabel(from) } : {}),
  on,
  kind: from ? 'default' : 'own',
})
const cards = computed<InstructionCard[]>(() => [
  ...attachedGroups.value.map(g => groupCard(g, true)),
  ...defaultGroups.value.map(g => groupCard(g, true, g.from)),
  ...hiddenGroupItems.value.map(g => groupCard(g, false, g.from)),
  ...unattachedGroups.value.map(g => groupCard(g, false)),
  ...attachedSnippets.value.map(sn => snippetCard(sn, true)),
  ...defaultSnippets.value.map(sn => snippetCard(sn, true, sn.from)),
  ...hiddenSnippetItems.value.map(sn => snippetCard(sn, false, sn.from)),
  ...unattachedSnippets.value.map(sn => snippetCard(sn, false)),
])

// A default one is hidden or brought back; one of this chat's own is detached or attached
function toggleGroup(item: InstructionCard, group: InstructionGroup): void {
  if (item.kind === 'default') {
    if (item.on) emit('hide', { kind: 'group', id: group.id })
    else unhide('group', group)
  } else if (item.on) detachGroup(group)
  else attachGroup(group)
}

function toggleSnippet(item: InstructionCard, snippet: Instruction): void {
  if (item.kind === 'default') {
    if (item.on) emit('hide', { kind: 'snippet', id: snippet.id })
    else unhide('snippet', snippet)
  } else if (item.on) detachSnippet(snippet)
  else attachSnippet(snippet)
}

function onToggle(item: InstructionCard): void {
  if (item.type === 'group') {
    const group = groupById.value.get(item.id)
    if (group) toggleGroup(item, group)
    return
  }
  const snippet = snippetById.value.get(item.id)
  if (snippet) toggleSnippet(item, snippet)
}
</script>

<template>
  <div class="ins-picker">
    <div class="chips">
      <span
        v-for="g in defaultGroups"
        :key="`dg${g.id}`"
        v-tip="`${g.name} · ${fromTitle(g.from)}`"
        class="chip group inherited"
        :class="{ paused: isPaused('group', g.id) }"
      >
        <button
          v-tip="isPaused('group', g.id) ? `Resume ${g.name}` : `Pause ${g.name} for now`"
          class="chip-pause"
          @click="togglePause('group', g)"
        >
          {{ isPaused('group', g.id) ? '▶' : '⏸' }}
        </button>
        <button class="chip-main" @click="emit('edit', { kind: 'group', id: g.id })">
          <span class="chip-name">📦 {{ g.name }}</span>
        </button>
        <span class="chip-src">{{ fromIcon(g.from) }}</span>
        <button
          v-tip="`Hide ${g.name} in this chat`"
          class="chip-x"
          :aria-label="`Hide ${g.name} in this chat`"
          @click="emit('hide', { kind: 'group', id: g.id })"
        >
          ✕
        </button>
      </span>
      <span
        v-for="s in defaultSnippets"
        :key="`ds${s.id}`"
        v-tip="`${s.name} · ${fromTitle(s.from)}`"
        class="chip inherited"
        :class="{ paused: isPaused('snippet', s.id) }"
      >
        <button
          v-tip="isPaused('snippet', s.id) ? `Resume ${s.name}` : `Pause ${s.name} for now`"
          class="chip-pause"
          @click="togglePause('snippet', s)"
        >
          {{ isPaused('snippet', s.id) ? '▶' : '⏸' }}
        </button>
        <button class="chip-main" @click="emit('edit', { kind: 'snippet', id: s.id })">
          <span class="dot" :style="{ background: instructionColor(s.name) }"></span>
          <span class="chip-name">{{ s.name }}</span>
        </button>
        <span class="chip-src">{{ fromIcon(s.from) }}</span>
        <button
          v-tip="`Hide ${s.name} in this chat`"
          class="chip-x"
          :aria-label="`Hide ${s.name} in this chat`"
          @click="emit('hide', { kind: 'snippet', id: s.id })"
        >
          ✕
        </button>
      </span>
      <span
        v-for="g in attachedGroups"
        :key="`g${g.id}`"
        v-tip="`${g.name} · ${groupTitle(g)}`"
        class="chip group"
        :class="{ paused: isPaused('group', g.id) }"
      >
        <button
          v-tip="isPaused('group', g.id) ? `Resume ${g.name}` : `Pause ${g.name} for now`"
          class="chip-pause"
          @click="togglePause('group', g)"
        >
          {{ isPaused('group', g.id) ? '▶' : '⏸' }}
        </button>
        <button class="chip-main" @click="emit('edit', { kind: 'group', id: g.id })">
          <span class="chip-name">📦 {{ g.name }}</span>
        </button>
        <button v-tip="`Detach ${g.name}`" class="chip-x" :aria-label="`Detach ${g.name}`" @click="detachGroup(g)">
          ✕
        </button>
      </span>
      <span
        v-for="s in attachedSnippets"
        :key="`s${s.id}`"
        v-tip="s.name"
        class="chip"
        :class="{ paused: isPaused('snippet', s.id) }"
      >
        <button
          v-tip="isPaused('snippet', s.id) ? `Resume ${s.name}` : `Pause ${s.name} for now`"
          class="chip-pause"
          @click="togglePause('snippet', s)"
        >
          {{ isPaused('snippet', s.id) ? '▶' : '⏸' }}
        </button>
        <button class="chip-main" @click="emit('edit', { kind: 'snippet', id: s.id })">
          <span class="dot" :style="{ background: instructionColor(s.name) }"></span>
          <span class="chip-name">{{ s.name }}</span>
        </button>
        <button v-tip="`Detach ${s.name}`" class="chip-x" :aria-label="`Detach ${s.name}`" @click="detachSnippet(s)">
          ✕
        </button>
      </span>
      <button class="add" @click="toggle">
        {{ anyAttached ? '＋' : '＋ Add instructions' }}
      </button>
    </div>

    <PickDialog
      :open="open"
      title="Instructions"
      :items="cards"
      empty="No instructions saved yet"
      search-placeholder="Search instructions"
      @toggle="onToggle"
      @close="close"
    >
      <template v-if="manageable" #actions>
        <button type="button" class="btn btn-secondary" @click="create('snippet')">+ New snippet</button>
        <button type="button" class="btn btn-secondary" @click="create('group')">+ New group</button>
        <button type="button" class="btn btn-secondary" @click="manage">All instructions</button>
      </template>
    </PickDialog>
  </div>
</template>

<style scoped>
.ins-picker {
  position: relative;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.chip {
  display: inline-flex;
  align-items: center;
  max-width: 11.3333rem; /* long names are cut short; the full name is in the tooltip */
  border: 1px solid var(--border);
  border-radius: 66.6rem;
  background: var(--surface2);
  font-size: 0.8rem;
  overflow: hidden;
}

.chip-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Attached by the chat's defaults: no ✕ — the icon says where from */
.chip.inherited {
  background: transparent;
}

/* Paused: still attached, but dimmed and struck through — not sent for now */
.chip.paused .chip-main {
  opacity: 0.5;
}

.chip.paused .chip-name {
  text-decoration: line-through;
}

.chip-pause {
  flex-shrink: 0;
  background: none;
  border: none;
  color: var(--text2);
  cursor: pointer;
  padding: 0 2px 0 0.4667rem;
  font-size: 0.8rem;
  line-height: 1;
}

.chip-pause:hover {
  color: var(--text);
}

/* The icon already carries the left padding of the chip */
.chip-pause + .chip-main {
  padding-left: 0.2667rem;
}

.chip-src {
  flex-shrink: 0;
  padding: 0 0 0 2px;
  font-size: 0.8rem;
  opacity: 0.75;
}

.dot {
  flex-shrink: 0;
  width: 0.4667rem;
  height: 0.4667rem;
  border-radius: 50%;
}

.chip.group {
  border-color: var(--accent2);
}

.chip-main {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: 0.4rem;
  padding: 0.2rem 0.2667rem 0.2rem 0.6667rem;
  color: var(--text);
  background: none;
  border: none;
  font: inherit;
  cursor: pointer;
}

.chip-main:hover {
  text-decoration: underline;
}

.chip-x {
  flex-shrink: 0;
  background: none;
  border: none;
  color: var(--text2);
  cursor: pointer;
  padding: 0 0.5333rem 0 0.2667rem;
  font-size: 0.7333rem;
}

.chip-x:hover {
  color: var(--text);
}

.add {
  padding: 0.2667rem 0.6667rem;
  border-radius: 66.6rem;
  border: 1px dashed var(--border);
  background: none;
  color: var(--text2);
  cursor: pointer;
  font-size: 0.8rem;
}

.add:hover {
  color: var(--text);
  border-color: var(--accent);
}
</style>
