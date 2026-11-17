<script setup lang="ts">
import { vTip } from '../../directives/tip'
import { useDropdown } from '../../composables/useDropdown'

// The chats branched off at a message: "⑂ 2 branches", opening a list of them
withDefaults(
  defineProps<{
    forks: readonly { id: string; title: string }[]
    /** Which edge the list lines up with. */
    align?: 'left' | 'right' | undefined
  }>(),
  { align: 'left' },
)
const emit = defineEmits<{ open: [id: string] }>()

const { open, root, toggle, close } = useDropdown()

function pick(id: string): void {
  close()
  emit('open', id)
}
</script>

<template>
  <span ref="root" class="fork-list">
    <button v-tip="'Chats branched off here'" class="fork-toggle" @click="toggle">
      ⑂ {{ forks.length }} branch{{ forks.length === 1 ? '' : 'es' }}
    </button>
    <span v-if="open" class="fork-menu" :class="align">
      <button v-for="f in forks" :key="f.id" v-tip="f.title" class="fork-item" @click="pick(f.id)">
        {{ f.title }}
      </button>
    </span>
  </span>
</template>

<style scoped>
.fork-list {
  position: relative;
  display: inline-flex;
}

.fork-toggle {
  background: none;
  border: none;
  color: var(--accent);
  font-size: 0.8rem;
  padding: 0.2rem 0.4667rem;
  border-radius: 0.4rem;
  cursor: pointer;
  white-space: nowrap;
}

.fork-toggle:hover {
  background: var(--surface2);
}

.fork-menu {
  position: absolute;
  top: 100%;
  left: 0;
  z-index: var(--z-menu);
  display: flex;
  flex-direction: column;
  min-width: 12rem;
  max-width: 18.6667rem;
  padding: 0.2667rem;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 0.5333rem;
  box-shadow: var(--shadow-pop);
}

.fork-menu.right {
  left: auto;
  right: 0;
}

.fork-item {
  background: none;
  border: none;
  color: var(--text);
  text-align: left;
  font-size: 0.8rem;
  padding: 0.4rem 0.5333rem;
  border-radius: 0.4rem;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fork-item:hover {
  background: var(--saccent-soft);
}
</style>
