<script setup lang="ts">
import { ref } from 'vue'
import type { Directive } from 'vue'
import { imagesIn } from '../../utils/files'
import RefStrip from './RefStrip.vue'

// A box for one prompt. Given a chat (`convId`) it also takes reference
// pictures — pasted, dropped, uploaded or from the library — the way the main
// prompt does; `refs` is the set to send.
const props = withDefaults(
  defineProps<{
    placeholder?: string
    hint?: string
    submitLabel?: string
    convId?: string | undefined
    /** Pictures it begins with. */
    startRefs?: readonly string[] | undefined
    /** How many pictures the model takes. */
    refLimit?: number | undefined
  }>(),
  { placeholder: '', hint: '', submitLabel: 'Redo', convId: undefined, startRefs: () => [], refLimit: undefined },
)
const emit = defineEmits<{ submit: []; cancel: [] }>()
const text = defineModel<string>({ default: '' })
const refs = defineModel<string[]>('refs', { default: () => [] })

const uploading = ref(false)
// RefStrip's exposed methods
const strip = ref<{ addFiles: (list: Iterable<File>) => void; discard: () => void } | null>(null)
const dragging = ref(false)

const vFocusSelect: Directive<HTMLInputElement | HTMLTextAreaElement> = {
  mounted: el => {
    el.focus()
    el.select()
  },
}

function submit(): void {
  if (!uploading.value) emit('submit')
}
function cancel(): void {
  strip.value?.discard()
  emit('cancel')
}
function onPaste(event: ClipboardEvent): void {
  const pictures = imagesIn(event.clipboardData?.files)
  if (!strip.value || !pictures.length) return
  event.preventDefault()
  strip.value.addFiles(pictures)
}
function onDrop(event: DragEvent): void {
  dragging.value = false
  strip.value?.addFiles(event.dataTransfer?.files ?? [])
}
</script>

<template>
  <div
    class="prompt-box"
    :class="{ drag: dragging }"
    @dragover.prevent="dragging = !!props.convId"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <RefStrip
      v-if="props.convId"
      ref="strip"
      v-model="refs"
      v-model:busy="uploading"
      :conv-id="props.convId"
      :start="props.startRefs"
      :limit="props.refLimit"
    />
    <textarea
      v-model="text"
      v-focus-select
      rows="2"
      :placeholder="placeholder"
      @keydown.enter.exact.prevent="submit"
      @keydown.esc="cancel"
      @paste="onPaste"
    ></textarea>
    <div class="prompt-box-actions">
      <span class="prompt-box-hint">{{ uploading ? 'Uploading…' : hint }}</span>
      <button class="meta-btn" @click="cancel">Cancel</button>
      <button class="edit-send" :disabled="!text.trim() || uploading" @click="submit">{{ submitLabel }}</button>
    </div>
  </div>
</template>

<style scoped src="./chatButtons.css"></style>
<style scoped>
/* The prompt box the pencil (Edit) and Redo open on a picture's card */
.prompt-box {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border: 1px solid var(--sborder);
  border-radius: 8px;
  background: var(--spanel2);
}
.prompt-box.drag {
  border-color: var(--saccent);
}
.prompt-box textarea {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--sborder);
  border-radius: 6px;
  background: var(--sbg);
  color: var(--text);
  font: inherit;
  font-size: 0.85rem;
  resize: vertical;
}
.prompt-box-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.prompt-box-hint {
  flex: 1;
  color: var(--smuted);
  font-size: 0.75rem;
}
</style>
