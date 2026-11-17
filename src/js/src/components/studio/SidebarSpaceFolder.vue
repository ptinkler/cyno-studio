<script setup lang="ts">
import { vTip } from '../../directives/tip'
import type { Space } from '../../composables/studioTypes'
import { typedValue, vFocusSelect } from '../../utils/focusSelect'

withDefaults(
  defineProps<{
    space: Space
    count?: number | undefined
    open?: boolean | undefined
    /** A thread is being dragged over it. */
    drop?: boolean | undefined
    renaming?: boolean | undefined
  }>(),
  { count: 0, open: false, drop: false, renaming: false },
)
defineEmits<{
  toggle: []
  open: []
  'start-rename': []
  'commit-rename': []
  'cancel-rename': []
  settings: []
  delete: []
  dragover: []
  dragleave: []
  drop: []
}>()
const renameText = defineModel<string>('renameText', { default: '' })
</script>

<template>
  <div
    class="folder"
    :class="{ open, drop }"
    @dragover.prevent="$emit('dragover')"
    @dragleave="$emit('dragleave')"
    @drop.prevent="$emit('drop')"
  >
    <button class="fchev" aria-label="Show or hide chats" @click="$emit('toggle')">
      <svg class="ic sm"><use href="#s-chev" /></svg>
    </button>
    <input
      v-if="renaming"
      v-focus-select
      class="nrename"
      :value="renameText"
      @input="renameText = typedValue($event)"
      @keydown.enter.prevent="$emit('commit-rename')"
      @keydown.esc="$emit('cancel-rename')"
      @blur="$emit('cancel-rename')"
    />
    <a v-else class="fmain" :href="`/space/${space.id}`" @click.prevent="$emit('open')">
      <svg class="ic"><use href="#s-folder" /></svg><span class="lbl">{{ space.name }}</span
      ><span class="count">{{ count }}</span>
    </a>
    <div class="nactions">
      <template v-if="renaming">
        <button
          v-tip="'Confirm rename'"
          class="nact"
          aria-label="Confirm rename"
          @mousedown.prevent
          @click="$emit('commit-rename')"
        >
          <svg class="ic sm"><use href="#s-check" /></svg>
        </button>
        <button
          v-tip="'Cancel rename'"
          class="nact"
          aria-label="Cancel rename"
          @mousedown.prevent
          @click="$emit('cancel-rename')"
        >
          <svg class="ic sm"><use href="#s-close" /></svg>
        </button>
      </template>
      <template v-else>
        <button v-tip="'Rename'" class="nact" aria-label="Rename" @click.stop="$emit('start-rename')">
          <svg class="ic sm"><use href="#s-pencil" /></svg>
        </button>
        <button v-tip="'Space defaults'" class="nact" aria-label="Space defaults" @click.stop="$emit('settings')">
          <svg class="ic sm"><use href="#s-cog" /></svg>
        </button>
        <button v-tip="'Delete'" class="nact danger" aria-label="Delete" @click.stop="$emit('delete')">
          <svg class="ic sm"><use href="#s-trash" /></svg>
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.folder {
  display: flex;
  align-items: center;
  border-radius: 0.6rem;
}
.folder:hover {
  background: var(--shover);
}
.fchev {
  width: 1.7333rem;
  height: 2.1333rem;
  display: grid;
  place-items: center;
  color: var(--sfaint);
  background: none;
  border: none;
  cursor: pointer;
}
.fchev .ic {
  transition: transform 0.15s;
}
.folder.open .fchev .ic {
  transform: rotate(90deg);
}
.fmain {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex: 1;
  min-width: 0;
  padding: 0.4667rem 0.6667rem 0.4667rem 0;
  color: var(--smuted);
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  /* an <a> (so it opens in a new tab) that must look like the button it replaced */
  text-decoration: none;
  box-sizing: border-box;
}
.fmain .ic {
  color: var(--sfaint);
}
.fmain .lbl {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fmain .count {
  font-size: 0.8rem;
  color: var(--sfaint);
}
.folder.drop {
  background: var(--saccent-soft);
  box-shadow: inset 0 0 0 1px var(--saccent);
}
.folder:hover .nactions,
.folder:focus-within .nactions {
  visibility: visible;
}
</style>
