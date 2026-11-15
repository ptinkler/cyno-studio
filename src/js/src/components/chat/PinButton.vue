<!-- The pin on a picture: pins it as a reference sent with every new image in the chat. Top-left, shown on
     hover (of the attachment or card holding it), always shown once pinned. -->
<script setup>
defineProps({ pinned: { type: Boolean, default: false } })
defineEmits(['toggle'])
</script>

<template>
  <button
    :class="['pin-btn', { on: pinned }]"
    :title="
      pinned
        ? 'Pinned: sent as a reference with every new image. Click to unpin'
        : 'Pin as a reference: send it with every new image in this chat'
    "
    :aria-pressed="pinned"
    @click.stop="$emit('toggle')"
  >
    <svg class="ic sm"><use href="#s-pin" /></svg>
  </button>
</template>

<style scoped>
/* Pin as reference: top-left, shown on hover, always shown once pinned */
.pin-btn {
  position: absolute;
  top: 6px;
  left: 6px;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.65);
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  opacity: 0;
  transition:
    opacity 0.15s,
    color 0.15s;
}
.attachment:hover .pin-btn,
.media-item:hover .pin-btn,
.pin-btn:focus-visible,
.pin-btn.on {
  opacity: 1;
}
.pin-btn.on {
  background: var(--saccent);
  color: #fff;
}
@media (hover: none) {
  .pin-btn {
    opacity: 1;
  }
}
</style>
