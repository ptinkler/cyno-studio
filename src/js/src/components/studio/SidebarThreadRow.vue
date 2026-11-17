<script setup lang="ts">
import { vTip } from '../../directives/tip'
import type { ConversationSummary } from '../../composables/chatConversationsApi'
import { typedValue, vFocusSelect } from '../../utils/focusSelect'

withDefaults(
  defineProps<{
    thread: ConversationSummary
    renaming?: boolean | undefined
    renameText?: string | undefined
    /** The pinned list shows "Unpin" and is always lit; elsewhere it toggles. */
    pinned?: boolean | undefined
    alwaysPinned?: boolean | undefined
  }>(),
  { renaming: false, renameText: '', pinned: false, alwaysPinned: false },
)
const emit = defineEmits<{
  open: []
  pin: []
  'start-rename': []
  'commit-rename': []
  'cancel-rename': []
  delete: []
  'update:renameText': [text: string]
}>()

// Icon per thread kind: the gallery icon (same as "New gallery") vs the chat icon.
const threadIcon = (thread: ConversationSummary): string => (thread.kind === 'gallery' ? '#s-image' : '#s-chat')
</script>

<template>
  <input
    v-if="renaming"
    v-focus-select
    class="nrename"
    :value="renameText"
    @input="emit('update:renameText', typedValue($event))"
    @keydown.enter.prevent="emit('commit-rename')"
    @keydown.esc="emit('cancel-rename')"
    @blur="emit('cancel-rename')"
  />
  <a v-else class="nitem" :href="`/${thread.id}`" @click.prevent="emit('open')">
    <svg class="ic"><use :href="threadIcon(thread)" /></svg><span class="lbl">{{ thread.title || 'Untitled' }}</span>
  </a>
  <div class="nactions">
    <template v-if="renaming">
      <button
        v-tip="'Confirm rename'"
        class="nact"
        aria-label="Confirm rename"
        @mousedown.prevent
        @click="emit('commit-rename')"
      >
        <svg class="ic sm"><use href="#s-check" /></svg>
      </button>
      <button
        v-tip="'Cancel rename'"
        class="nact"
        aria-label="Cancel rename"
        @mousedown.prevent
        @click="emit('cancel-rename')"
      >
        <svg class="ic sm"><use href="#s-close" /></svg>
      </button>
    </template>
    <template v-else>
      <button v-tip="'Rename'" class="nact" aria-label="Rename" @click.stop="emit('start-rename')">
        <svg class="ic sm"><use href="#s-pencil" /></svg>
      </button>
      <button
        v-tip="alwaysPinned || pinned ? 'Unpin' : 'Pin'"
        class="nact"
        :class="{ on: alwaysPinned || pinned }"
        :aria-label="alwaysPinned || pinned ? 'Unpin chat' : 'Pin chat'"
        :aria-pressed="alwaysPinned || pinned"
        @click.stop="emit('pin')"
      >
        <svg class="ic sm"><use href="#s-pin" /></svg>
      </button>
      <button v-tip="'Delete'" class="nact danger" aria-label="Delete chat" @click.stop="emit('delete')">
        <svg class="ic sm"><use href="#s-trash" /></svg>
      </button>
    </template>
  </div>
</template>

<style scoped>
.nitem {
  display: flex;
  align-items: center;
  gap: 0.6667rem;
  flex: 1;
  min-width: 0;
  padding: 0.4667rem 0.6667rem;
  color: var(--smuted);
  background: none;
  border: none;
  cursor: pointer;
  text-decoration: none;
}
.nitem .ic {
  color: var(--sfaint);
}
.nitem .lbl {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nrename {
  flex: 1;
  min-width: 0;
  margin: 0.2rem 0.4rem;
  padding: 0.4rem 0.5333rem;
  border: 1px solid var(--saccent);
  border-radius: 0.4667rem;
  background: var(--spanel2, var(--sbg2));
  color: var(--sfg);
  outline: none;
  font: inherit;
}
</style>
