<script setup lang="ts">
import InspectorSection from './InspectorSection.vue'
import type { Character } from '../../composables/charactersApi'
import type { InheritedDefault } from '../../composables/useChatDefaults'
import CharacterPicker from '../characters/CharacterPicker.vue'

const props = withDefaults(
  defineProps<{
    characters?: readonly Character[] | undefined
    characterIds?: readonly number[] | undefined
    names?: string | undefined
    /** Whether the picked models can use characters, and if not why. */
    support?: { ok: boolean; reason: string | null } | undefined
    inherited?: readonly InheritedDefault[] | undefined
    hidden?: readonly InheritedDefault[] | undefined
  }>(),
  {
    characters: () => [],
    characterIds: () => [],
    names: '',
    support: () => ({ ok: true, reason: null }),
    inherited: () => [],
    hidden: () => [],
  },
)
defineEmits<{
  'update:characterIds': [ids: number[]]
  edit: [character: Character]
  create: []
  hide: [id: number]
  unhide: [id: number]
}>()
</script>

<template>
  <InspectorSection title="Characters">
    <p v-if="!props.support.ok" class="warn">{{ props.support.reason }}</p>
    <CharacterPicker
      v-else
      :model-value="characterIds"
      :characters="characters"
      :inherited="inherited"
      :hidden="hidden"
      create-label="＋ New character (this thread)"
      @update:model-value="$emit('update:characterIds', $event)"
      @edit="$emit('edit', $event)"
      @create="$emit('create')"
      @hide="$emit('hide', $event)"
      @unhide="$emit('unhide', $event)"
    />
    <div v-if="names" class="attached">{{ names }}</div>
  </InspectorSection>
</template>

<style scoped>
.warn {
  font-size: 0.8rem;
  color: var(--smuted);
  line-height: 1.5;
}
.attached {
  margin-top: 0.5333rem;
  font-size: 0.8rem;
  color: var(--smuted);
  line-height: 1.5;
}
</style>
