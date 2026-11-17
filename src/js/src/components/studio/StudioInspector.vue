<script setup lang="ts">
import { vTip } from '../../directives/tip'
import type { Character } from '../../composables/charactersApi'
import type { Catalogues } from '../../composables/useComposerSettings'
import type {
  CharactersPane,
  InstructionEditEvent,
  InstructionsPane,
  InstructionTarget,
} from '../../composables/studioTypes'
import StudioModelSection from './StudioModelSection.vue'
import StudioMediaOptions from './StudioMediaOptions.vue'
import StudioAudioOptions from './StudioAudioOptions.vue'
import StudioContextSection from './StudioContextSection.vue'
import StudioInstructions from './StudioInstructions.vue'
import StudioCharacters from './StudioCharacters.vue'

withDefaults(
  defineProps<{
    models: Catalogues
    modelsLoading?: boolean | undefined
    collapsed?: boolean | undefined
    instructions: InstructionsPane
    characters: CharactersPane
  }>(),
  { modelsLoading: false, collapsed: false },
)
// StudioModelSection / StudioMediaOptions read composer settings via inject
defineEmits<{
  'update:collapsed': [collapsed: boolean]
  'update:snippetIds': [ids: number[]]
  'update:groupIds': [ids: number[]]
  manage: []
  'edit-instruction': [target: InstructionEditEvent]
  'instr-hide': [target: InstructionTarget]
  'instr-unhide': [target: InstructionTarget]
  'instr-pause': [target: InstructionTarget]
  'instr-resume': [target: InstructionTarget]
  'update:characterIds': [ids: number[]]
  'edit-character': [character: Character]
  'create-character': []
  'char-hide': [id: number]
  'char-unhide': [id: number]
}>()
</script>

<template>
  <aside class="side" :class="{ collapsed }">
    <!-- The collapsed rail expands on click. -->
    <button
      v-tip="'Expand inspector'"
      class="rail"
      type="button"
      aria-label="Expand inspector"
      @click="$emit('update:collapsed', false)"
    >
      <svg class="ic lg chev"><use href="#s-chevL" /></svg>
      <span class="rail-label">Inspector</span>
    </button>
    <div class="panel">
      <button v-tip="'Collapse inspector'" class="panelhead" type="button" @click="$emit('update:collapsed', true)">
        <span class="brand">Inspector</span>
        <svg class="ic"><use href="#s-chev" /></svg>
      </button>
      <div class="pbody">
        <StudioModelSection :models="models" :loading="modelsLoading" />
        <StudioMediaOptions />
        <StudioAudioOptions />
        <StudioContextSection />
        <StudioInstructions
          :instructions="instructions.list"
          :groups="instructions.groups"
          :snippet-ids="instructions.snippetIds"
          :group-ids="instructions.groupIds"
          :summary="instructions.summary"
          :inherited-snippets="instructions.inheritedSnippets"
          :inherited-groups="instructions.inheritedGroups"
          :hidden-snippets="instructions.hiddenSnippets"
          :hidden-groups="instructions.hiddenGroups"
          :paused-snippets="instructions.pausedSnippets"
          :paused-groups="instructions.pausedGroups"
          @update:snippet-ids="$emit('update:snippetIds', $event)"
          @update:group-ids="$emit('update:groupIds', $event)"
          @manage="$emit('manage')"
          @edit="$emit('edit-instruction', $event)"
          @hide="$emit('instr-hide', $event)"
          @unhide="$emit('instr-unhide', $event)"
          @pause="$emit('instr-pause', $event)"
          @resume="$emit('instr-resume', $event)"
        />
        <StudioCharacters
          :characters="characters.list"
          :character-ids="characters.ids"
          :names="characters.names"
          :support="characters.support"
          :inherited="characters.inherited"
          :hidden="characters.hidden"
          @update:character-ids="$emit('update:characterIds', $event)"
          @edit="$emit('edit-character', $event)"
          @create="$emit('create-character')"
          @hide="$emit('char-hide', $event)"
          @unhide="$emit('char-unhide', $event)"
        />
      </div>
    </div>
  </aside>
</template>

<style scoped>
.side {
  width: clamp(16rem, 20vw, 22rem);
  background: var(--sbg);
  border-left: 1px solid var(--sborder);
}
.brand {
  font-weight: 600;
}
.pbody {
  flex: 1;
  overflow-y: auto;
  padding: 0.2667rem 0.9333rem 0.6667rem;
}
</style>
