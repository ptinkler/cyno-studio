<script setup lang="ts">
import { ref, computed, watch, nextTick, inject } from 'vue'
import { showToastKey, noToast } from '../../injection'
import BaseDialog from '../BaseDialog.vue'
import DefaultToggles from './DefaultToggles.vue'
import type { Instruction, InstructionGroup } from '../../composables/chatSettingsApi'
import {
  createInstruction,
  updateInstruction,
  deleteInstruction,
  createInstructionGroup,
  updateInstructionGroup,
  deleteInstructionGroup,
} from '../../composables/useChat'
import { confirmDialog } from '../../composables/useDialog'
import { instructionColor } from '../../utils/format'
import { sameIds } from '../../utils/defaults'
import { messageOf } from '../../utils/errors'

type Kind = 'snippet' | 'group'

// Edit one instruction snippet or group (a group bundles snippets), or make a
// new one — the instruction counterpart of CharacterEditor. The full list
// lives on the Instructions page. Saving or deleting closes it.
const props = withDefaults(
  defineProps<{
    /** What to edit (id null for a new one); null = closed. */
    target?: { kind: Kind; id: number | null } | null | undefined
    /** Every snippet (a group's are picked from them). */
    instructions?: readonly Instruction[] | undefined
    groups?: readonly InstructionGroup[] | undefined
  }>(),
  { target: null, instructions: () => [], groups: () => [] },
)
const emit = defineEmits<{
  close: []
  changed: [change: { kind: Kind; item: Instruction | InstructionGroup | null }]
}>()
const showToast = inject(showToastKey, noToast)

const name = ref('')
const content = ref('') // snippet
const memberIds = ref<number[]>([]) // group
const memberQuery = ref('')
const saving = ref(false)
const nameInput = ref<HTMLInputElement | null>(null)
const toggles = ref<{ commit: (id: number) => Promise<void> } | null>(null) // the "Default for" pills, saved along with the rest
const defaultsDirty = ref(false)

const isGroup = computed(() => props.target?.kind === 'group')
const editingId = computed(() => props.target?.id ?? null)
const currentGroup = computed(() =>
  isGroup.value && editingId.value !== null ? props.groups.find(g => g.id === editingId.value) : undefined,
)
const currentSnippet = computed(() =>
  !isGroup.value && editingId.value !== null ? props.instructions.find(s => s.id === editingId.value) : undefined,
)
const current = computed(() => currentGroup.value ?? currentSnippet.value)
const title = computed(() => `${editingId.value === null ? 'New' : 'Edit'} ${isGroup.value ? 'group' : 'snippet'}`)

const snippetById = computed(() => new Map(props.instructions.map(s => [s.id, s])))
const members = computed(() => memberIds.value.flatMap(id => snippetById.value.get(id) ?? []))
const addable = computed(() => {
  const q = memberQuery.value.trim().toLowerCase()
  return props.instructions.filter(s => !memberIds.value.includes(s.id) && s.name.toLowerCase().includes(q))
})

function addMember(snippet: Instruction): void {
  memberIds.value = [...memberIds.value, snippet.id]
  memberQuery.value = ''
}

function removeMember(snippet: Instruction): void {
  memberIds.value = memberIds.value.filter(id => id !== snippet.id)
}

const fieldsDirty = computed(() => {
  const group = currentGroup.value
  const snippet = currentSnippet.value
  if (!group && !snippet) return !!(name.value.trim() || content.value.trim() || memberIds.value.length)
  if (group) return group.name !== name.value || !sameIds(memberIds.value, group.snippet_ids)
  return snippet?.name !== name.value || snippet.content !== content.value
})
const dirty = computed(() => fieldsDirty.value || defaultsDirty.value)

watch(
  () => props.target,
  async target => {
    if (!target) return
    name.value = current.value?.name ?? ''
    content.value = currentSnippet.value?.content ?? ''
    memberIds.value = [...(currentGroup.value?.snippet_ids ?? [])]
    memberQuery.value = ''
    if (!current.value) {
      await nextTick()
      nameInput.value?.focus()
    }
  },
)

async function save(): Promise<void> {
  const target = props.target
  if (!target || !name.value.trim() || saving.value) return
  saving.value = true
  try {
    const id = editingId.value
    let saved: Instruction | InstructionGroup
    if (target.kind === 'group') {
      const data = { name: name.value.trim(), snippet_ids: memberIds.value }
      saved = id === null ? await createInstructionGroup(data) : await updateInstructionGroup(id, data)
    } else {
      const data = { name: name.value.trim(), content: content.value }
      saved = id === null ? await createInstruction(data) : await updateInstruction(id, data)
    }
    await toggles.value?.commit(saved.id)
    emit('changed', { kind: target.kind, item: saved })
    emit('close')
  } catch (e) {
    showToast(`Save failed: ${messageOf(e)}`, 'error')
  } finally {
    saving.value = false
  }
}

async function remove(): Promise<void> {
  const target = props.target
  const id = editingId.value
  const existing = current.value
  if (!target || id === null || !existing) return
  const what =
    target.kind === 'group'
      ? `the group “${existing.name}”? Its snippets are kept.`
      : `“${existing.name}”? It's also taken out of chats, groups and defaults.`
  const confirmed = await confirmDialog({ title: 'Delete', message: what, confirmLabel: 'Delete', danger: true })
  if (!confirmed) return
  try {
    await (target.kind === 'group' ? deleteInstructionGroup(id) : deleteInstruction(id))
    emit('changed', { kind: target.kind, item: null })
    emit('close')
  } catch (e) {
    showToast(`Delete failed: ${messageOf(e)}`, 'error')
  }
}

async function close(): Promise<void> {
  const discard = await confirmDialog({ title: 'Discard unsaved changes?', confirmLabel: 'Discard', danger: true })
  if (!dirty.value || discard) emit('close')
}
</script>

<template>
  <BaseDialog :open="!!target" :title="title" width="540px" form @close="close" @submit="save">
    <input
      ref="nameInput"
      v-model="name"
      class="name"
      maxlength="255"
      :placeholder="isGroup ? 'Group name' : 'Name, e.g. Terse tone'"
      aria-label="Name"
    />

    <textarea
      v-if="!isGroup"
      v-model="content"
      maxlength="20000"
      placeholder="What the chat model should do — a tone, a format, a rule."
      aria-label="Instructions"
    ></textarea>

    <template v-else>
      <div class="members">
        <span v-for="s in members" :key="s.id" class="chip" :title="s.name">
          <span class="dot" :style="{ background: instructionColor(s.name) }"></span>
          <span class="chip-name">{{ s.name }}</span>
          <button type="button" class="chip-x" :title="`Remove ${s.name}`" @click="removeMember(s)">✕</button>
        </span>
        <span v-if="!members.length" class="empty">No snippets in it yet</span>
      </div>
      <div class="adder">
        <input
          v-model="memberQuery"
          type="search"
          placeholder="Add a snippet…"
          aria-label="Add a snippet"
          @keydown.enter.prevent="addable[0] && addMember(addable[0])"
        />
        <div v-if="memberQuery.trim()" class="adder-menu">
          <button v-for="s in addable" :key="s.id" type="button" class="item" @click="addMember(s)">
            <span class="dot" :style="{ background: instructionColor(s.name) }"></span>
            <span class="item-name">{{ s.name }}</span>
          </button>
          <p v-if="!addable.length" class="empty">No other snippets match</p>
        </div>
      </div>
    </template>

    <DefaultToggles
      ref="toggles"
      v-model:dirty="defaultsDirty"
      :kind="isGroup ? 'instruction_group' : 'instruction'"
      :item-id="editingId"
    />

    <template #actions>
      <button v-if="current" type="button" class="btn btn-danger" @click="remove">Delete</button>
      <span class="spacer"></span>
      <button type="button" class="btn btn-secondary" @click="close">Cancel</button>
      <button class="btn btn-primary" :disabled="saving || !dirty || !name.trim()">
        {{ current ? 'Save' : 'Create' }}
      </button>
    </template>
  </BaseDialog>
</template>

<style scoped>
.name {
  padding: 8px 11px;
  font-size: 15px;
  font-weight: 600;
}

textarea {
  min-height: 220px;
  padding: 9px 11px;
}

.members {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
}

.chip {
  display: inline-flex;
  align-items: center;
  max-width: 240px;
  gap: 6px;
  padding: 3px 4px 3px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface2);
  font-size: 0.8rem;
}

.chip-name,
.item-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-name {
  flex: 1;
}

.dot {
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.chip-x {
  flex-shrink: 0;
  background: none;
  border: none;
  color: var(--text2);
  cursor: pointer;
  font-size: 0.7rem;
  padding: 2px 5px;
  border-radius: 999px;
}

.chip-x:hover {
  background: var(--border);
  color: var(--text);
}

.adder {
  position: relative;
}

.adder input {
  width: 100%;
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 0.85rem;
}

.adder-menu {
  position: absolute;
  z-index: 5;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  max-height: 220px;
  overflow-y: auto;
  padding: 4px;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-pop);
  display: flex;
  flex-direction: column;
}

.item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: none;
  border-radius: 6px;
  background: none;
  color: var(--text);
  text-align: left;
  font-size: 0.85rem;
  cursor: pointer;
}

.item:hover {
  background: var(--surface2);
}

.empty {
  font-size: 0.8rem;
  color: var(--text2);
  padding: 4px 2px;
}
</style>
