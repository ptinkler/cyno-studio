<script setup lang="ts">
import { computed, inject, nextTick, ref, watch } from 'vue'
import { showToastKey, noToast } from '../../injection'
import BaseDialog from '../BaseDialog.vue'
import CharacterPicker from '../characters/CharacterPicker.vue'
import InstructionPicker from './InstructionPicker.vue'
import type { Character } from '../../composables/charactersApi'
import type { ChatSettings, Instruction, InstructionGroup } from '../../composables/chatSettingsApi'
import type { Space } from '../../composables/studioTypes'
import { confirmDialog } from '../../composables/useDialog'
import { createSpace, deleteSpace, updateSettings, updateSpace } from '../../composables/useChat'
import { sameIds } from '../../utils/defaults'
import { messageOf } from '../../utils/errors'

// Settings for one bucket of new-chat defaults: a space (its name, and the
// characters and instructions chats made in it start with), a new space, or
// the global defaults every new chat starts with. Saving closes it; emits
// `changed` with what was saved so the list can reload.
const props = withDefaults(
  defineProps<{
    /** A space, 'new' or 'global'; null while closed. */
    target?: Space | 'new' | 'global' | null | undefined
    globalSettings?: ChatSettings | null | undefined
    characters?: readonly Character[] | undefined
    instructions?: readonly Instruction[] | undefined
    groups?: readonly InstructionGroup[] | undefined
  }>(),
  { target: null, globalSettings: null, characters: () => [], instructions: () => [], groups: () => [] },
)
const emit = defineEmits<{ close: []; changed: [saved: ChatSettings | Space | null] }>()
const showToast = inject(showToastKey, noToast)

const name = ref('')
const charIds = ref<number[]>([])
const snippetIds = ref<number[]>([])
const groupIds = ref<number[]>([])
const saving = ref(false)
const nameInput = ref<HTMLInputElement | null>(null)

const isGlobal = computed(() => props.target === 'global')
const isNew = computed(() => props.target === 'new')
const space = computed(() => (typeof props.target === 'object' ? props.target : null))
const title = computed(() => {
  if (isGlobal.value) return 'Defaults for every chat'
  return isNew.value ? 'New space' : `“${space.value?.name ?? ''}” settings`
})

const bucket = computed<ChatSettings | Space | null>(() => (isGlobal.value ? props.globalSettings : space.value))
const bucketLists = (b: ChatSettings | Space | null) => ({
  chars: b?.default_character_ids ?? [],
  snippets: b?.default_instruction_ids ?? [],
  groups: b?.default_instruction_group_ids ?? [],
})
const listsChanged = computed(() => {
  const was = bucketLists(bucket.value)
  return (
    !sameIds(charIds.value, was.chars) ||
    !sameIds(snippetIds.value, was.snippets) ||
    !sameIds(groupIds.value, was.groups)
  )
})
const savedName = computed(() => space.value?.name ?? '')
const nameChanged = computed(() => !isGlobal.value && name.value.trim() !== savedName.value)
const dirty = computed(() => nameChanged.value || listsChanged.value)

watch(
  () => props.target,
  async target => {
    if (!target) return
    const lists = bucketLists(bucket.value)
    name.value = savedName.value
    charIds.value = [...lists.chars]
    snippetIds.value = [...lists.snippets]
    groupIds.value = [...lists.groups]
    if (!isGlobal.value) {
      await nextTick()
      nameInput.value?.focus()
    }
  },
)

async function close(): Promise<void> {
  const discard = await confirmDialog({ title: 'Discard unsaved changes?', confirmLabel: 'Discard', danger: true })
  if (!dirty.value || discard) emit('close')
}

async function save(): Promise<void> {
  const lists = {
    default_character_ids: charIds.value,
    default_instruction_ids: snippetIds.value,
    default_instruction_group_ids: groupIds.value,
  }
  if (!isGlobal.value && !name.value.trim()) {
    showToast('Give the space a name', 'error')
    return
  }
  saving.value = true
  try {
    const data = { name: name.value.trim(), ...lists }
    const current = space.value
    const saved = isGlobal.value
      ? await updateSettings(lists)
      : current
        ? await updateSpace(current.id, data)
        : await createSpace(data)
    emit('changed', saved)
    emit('close')
  } catch (e) {
    showToast(`Save failed: ${messageOf(e)}`, 'error')
  } finally {
    saving.value = false
  }
}

async function remove(): Promise<void> {
  const current = space.value
  if (!current) return
  const confirmed = await confirmDialog({
    title: `Delete the space “${current.name}”?`,
    message: 'Its chats are kept and move to Chats.',
    confirmLabel: 'Delete',
    danger: true,
  })
  if (!confirmed) return
  try {
    await deleteSpace(current.id)
    emit('changed', null)
    emit('close')
  } catch (e) {
    showToast(`Delete failed: ${messageOf(e)}`, 'error')
  }
}
</script>

<template>
  <BaseDialog :open="!!target" :title="title" form @close="close" @submit="save">
    <p class="sub">
      <template v-if="isGlobal">Every chat uses these characters and instructions.</template>
      <template v-else>Every chat in this space uses these, on top of the ones for all chats.</template>
    </p>

    <template v-if="!isGlobal">
      <label for="space-name">Name</label>
      <input id="space-name" ref="nameInput" v-model="name" maxlength="255" placeholder="e.g. Fantasy novel" />
    </template>

    <label>Default characters</label>
    <CharacterPicker
      :model-value="charIds"
      :characters="characters"
      :allow-create="false"
      @update:model-value="charIds = $event"
    />

    <label>Default instructions</label>
    <InstructionPicker
      :instructions="instructions"
      :groups="groups"
      :snippet-ids="snippetIds"
      :group-ids="groupIds"
      :manageable="false"
      @update:snippet-ids="snippetIds = $event"
      @update:group-ids="groupIds = $event"
    />

    <template #actions>
      <button v-if="!isGlobal && !isNew" type="button" class="btn btn-danger" @click="remove">Delete space</button>
      <span class="spacer"></span>
      <button type="button" class="btn btn-secondary" @click="close">Cancel</button>
      <button class="btn btn-primary" :disabled="saving || (!isNew && !dirty) || (!isGlobal && !name.trim())">
        {{ isNew ? 'Create space' : 'Save' }}
      </button>
    </template>
  </BaseDialog>
</template>

<style scoped>
.sub {
  font-size: 0.8rem;
  color: var(--text2);
  line-height: 1.45;
}

label {
  margin-top: 4px;
}
</style>
