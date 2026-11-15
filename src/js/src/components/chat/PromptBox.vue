<!-- A small prompt box under a picture or reply: one text, a hint, Cancel and a submit button.
     Enter submits, Esc cancels. -->
<script setup>
defineProps({
  placeholder: { type: String, default: '' },
  hint: { type: String, default: '' },
  submitLabel: { type: String, default: 'Redo' },
})
defineEmits(['submit', 'cancel'])
const text = defineModel({ type: String, default: '' })

const vFocusSelect = { mounted: el => (el.focus(), el.select()) }
</script>

<template>
  <div class="prompt-box">
    <textarea
      v-model="text"
      v-focus-select
      rows="2"
      :placeholder="placeholder"
      @keydown.enter.exact.prevent="$emit('submit')"
      @keydown.esc="$emit('cancel')"
    ></textarea>
    <div class="prompt-box-actions">
      <span class="prompt-box-hint">{{ hint }}</span>
      <button class="meta-btn" @click="$emit('cancel')">Cancel</button>
      <button class="edit-send" :disabled="!text.trim()" @click="$emit('submit')">{{ submitLabel }}</button>
    </div>
  </div>
</template>

<style scoped src="./chatButtons.css"></style>
<style scoped>
/* The prompt box the pencil (Edit) and Redo open on a picture's card */
.prompt-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
}
.prompt-box textarea {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
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
  color: var(--muted);
  font-size: 0.75rem;
}
</style>
