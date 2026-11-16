<script setup lang="ts">
import type { Instruction, InstructionGroup } from '../../composables/chatSettingsApi'
import type { InstructionEditEvent, InstructionTarget } from '../../composables/studioTypes'
import type { InheritedDefault } from '../../composables/useChatDefaults'
import InstructionPicker from '../chat/InstructionPicker.vue'

withDefaults(
  defineProps<{
    instructions?: readonly Instruction[] | undefined
    groups?: readonly InstructionGroup[] | undefined
    snippetIds?: readonly number[] | undefined
    groupIds?: readonly number[] | undefined
    summary?: string | undefined
    inheritedSnippets?: readonly InheritedDefault[] | undefined
    inheritedGroups?: readonly InheritedDefault[] | undefined
    hiddenSnippets?: readonly InheritedDefault[] | undefined
    hiddenGroups?: readonly InheritedDefault[] | undefined
    pausedSnippets?: readonly number[] | undefined
    pausedGroups?: readonly number[] | undefined
  }>(),
  {
    instructions: () => [],
    groups: () => [],
    snippetIds: () => [],
    groupIds: () => [],
    summary: '',
    inheritedSnippets: () => [],
    inheritedGroups: () => [],
    hiddenSnippets: () => [],
    hiddenGroups: () => [],
    pausedSnippets: () => [],
    pausedGroups: () => [],
  },
)
defineEmits<{
  'update:snippetIds': [ids: number[]]
  'update:groupIds': [ids: number[]]
  manage: []
  edit: [target: InstructionEditEvent]
  hide: [target: InstructionTarget]
  unhide: [target: InstructionTarget]
  pause: [target: InstructionTarget]
  resume: [target: InstructionTarget]
}>()
</script>

<template>
  <div class="isection">
    <div class="ilabel">Instructions</div>
    <InstructionPicker
      :instructions="instructions"
      :groups="groups"
      :snippet-ids="snippetIds"
      :group-ids="groupIds"
      :inherited-snippets="inheritedSnippets"
      :inherited-groups="inheritedGroups"
      :hidden-snippets="hiddenSnippets"
      :hidden-groups="hiddenGroups"
      :paused-snippets="pausedSnippets"
      :paused-groups="pausedGroups"
      @update:snippet-ids="$emit('update:snippetIds', $event)"
      @update:group-ids="$emit('update:groupIds', $event)"
      @manage="$emit('manage')"
      @edit="$emit('edit', $event)"
      @hide="$emit('hide', $event)"
      @unhide="$emit('unhide', $event)"
      @pause="$emit('pause', $event)"
      @resume="$emit('resume', $event)"
    />
    <div v-if="summary" class="attached">{{ summary }}</div>
  </div>
</template>

<style scoped>
.attached {
  margin-top: 8px;
  font-size: 12px;
  color: var(--smuted);
  line-height: 1.5;
}
</style>
