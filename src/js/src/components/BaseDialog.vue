<script lang="ts">
// Open dialogs' Esc handlers, newest last, shared by every dialog on the page
const openStack: ((event: KeyboardEvent) => void)[] = []
</script>

<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'

// A modal's shell: the backdrop, the card with its title and ✕, Esc and
// backdrop clicks to close. Slots: `head` (beside the title), the body, and
// `actions` (the button row). `form`: the card is a <form> (Enter submits;
// `submit` is emitted). Emits `close` — the parent decides whether to.
const props = withDefaults(
  defineProps<{
    open?: boolean | undefined
    title?: string | undefined
    /** For screen readers; the title by default. */
    label?: string | undefined
    width?: string | undefined
    form?: boolean | undefined
  }>(),
  { open: false, title: '', label: '', width: '32rem', form: false },
)
const emit = defineEmits<{ close: []; submit: [] }>()

// Open dialogs, newest last: Esc closes only the top one (a picker opened
// from inside another dialog mustn't close both)
function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape' && openStack.at(-1) === onKey) emit('close')
}
function release(): void {
  window.removeEventListener('keydown', onKey)
  const i = openStack.indexOf(onKey)
  if (i !== -1) openStack.splice(i, 1)
}
watch(
  () => props.open,
  open => {
    if (open) {
      openStack.push(onKey)
      window.addEventListener('keydown', onKey)
    } else release()
  },
  { immediate: true },
)
onBeforeUnmount(release)
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="backdrop" @click.self="emit('close')">
      <component
        :is="form ? 'form' : 'div'"
        class="dialog"
        role="dialog"
        aria-modal="true"
        :aria-label="label || title"
        :style="{ width: `min(${width}, 100%)` }"
        @submit.prevent="emit('submit')"
      >
        <div class="head">
          <h3>{{ title }}</h3>
          <slot name="head" />
          <button type="button" class="iconbtn x" title="Close" @click="emit('close')">✕</button>
        </div>
        <div class="body"><slot /></div>
        <div v-if="$slots['actions']" class="actions"><slot name="actions" /></div>
      </component>
    </div>
  </Teleport>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  background: rgba(0, 0, 0, 0.6);
  display: grid;
  place-items: center;
  padding: 1.0667rem;
}

.dialog {
  max-height: calc(100dvh - 2.1333rem);
  display: flex;
  flex-direction: column;
  background: var(--sbg);
  border: 1px solid var(--sborder);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-modal);
  padding: 0.9333rem 1.2rem 1.0667rem;
}

.head {
  display: flex;
  align-items: center;
  gap: 0.5333rem;
  margin-bottom: 0.8rem;
}

.head h3 {
  flex: 1;
  min-width: 0;
  font-size: 1rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.x {
  flex-shrink: 0;
  width: 1.8667rem;
  height: 1.8667rem;
  margin-right: -6px;
  font-size: 0.8667rem;
}

.body {
  display: flex;
  flex-direction: column;
  gap: 0.6667rem;
  min-height: 0;
  overflow-y: auto;
  font-size: 0.9rem;
}

.actions {
  display: flex;
  align-items: center;
  gap: 0.5333rem;
  padding-top: 0.9333rem;
}

.actions :slotted(.spacer) {
  flex: 1;
}
</style>
