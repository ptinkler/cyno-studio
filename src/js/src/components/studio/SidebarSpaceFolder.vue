<!-- A space as a folder row in the sidebar: open/close arrow, name (renamable in place), thread count, and
     its actions. A drop target for threads dragged onto it. The threads inside are the parent's. -->
<script setup>
defineProps({
  space: { type: Object, required: true },
  count: { type: Number, default: 0 },
  open: { type: Boolean, default: false },
  drop: { type: Boolean, default: false }, // a thread is being dragged over it
  renaming: { type: Boolean, default: false },
})
defineEmits([
  'toggle',
  'open',
  'start-rename',
  'commit-rename',
  'cancel-rename',
  'settings',
  'delete',
  'dragover',
  'dragleave',
  'drop',
])
const renameText = defineModel('renameText', { type: String, default: '' })

const vFocusSelect = { mounted: el => (el.focus(), el.select()) }
</script>

<template>
  <div
    class="folder"
    :class="{ open, drop }"
    @dragover.prevent="$emit('dragover')"
    @dragleave="$emit('dragleave')"
    @drop.prevent="$emit('drop')"
  >
    <button class="fchev" @click="$emit('toggle')">
      <svg class="ic sm"><use href="#s-chev" /></svg>
    </button>
    <input
      v-if="renaming"
      v-focus-select
      class="nrename"
      :value="renameText"
      @input="renameText = $event.target.value"
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
          class="nact"
          title="Confirm rename"
          aria-label="Confirm rename"
          @mousedown.prevent
          @click="$emit('commit-rename')"
        >
          <svg class="ic sm"><use href="#s-check" /></svg>
        </button>
        <button
          class="nact"
          title="Cancel rename"
          aria-label="Cancel rename"
          @mousedown.prevent
          @click="$emit('cancel-rename')"
        >
          <svg class="ic sm"><use href="#s-close" /></svg>
        </button>
      </template>
      <template v-else>
        <button class="nact" title="Rename" @click.stop="$emit('start-rename')">
          <svg class="ic sm"><use href="#s-pencil" /></svg>
        </button>
        <button class="nact" title="Space defaults" @click.stop="$emit('settings')">
          <svg class="ic sm"><use href="#s-cog" /></svg>
        </button>
        <button class="nact danger" title="Delete" @click.stop="$emit('delete')">
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
  border-radius: 9px;
}
.folder:hover {
  background: var(--shover);
}
.fchev {
  width: 26px;
  height: 32px;
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
  gap: 9px;
  flex: 1;
  min-width: 0;
  padding: 7px 10px 7px 0;
  color: var(--smuted);
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
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
  font-size: 11px;
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
