<script setup lang="ts">
import { ref, useId } from 'vue'

// A short explanation that touch and keyboard users can reach, unlike a `title` attribute: it opens on hover,
// on focus and on tap or Enter, and Escape closes it. Teleported and fixed so a clipping parent can't cut it off.
const props = withDefaults(defineProps<{ text: string; focusable?: boolean; toggle?: boolean }>(), {
  focusable: true,
  toggle: true,
})

const MARGIN = 8
const MAX_WIDTH = 288
const NEEDS_ROOM = 64
const id = useId()
const trigger = ref<HTMLElement | null>(null)
const spot = ref<{ left: number; top?: number; bottom?: number } | null>(null)

function show(): void {
  const rect = trigger.value?.getBoundingClientRect()
  if (!rect) return
  const left = Math.max(MARGIN, Math.min(rect.left, window.innerWidth - MAX_WIDTH - MARGIN))
  spot.value =
    rect.top > NEEDS_ROOM
      ? { left, bottom: window.innerHeight - rect.top + MARGIN }
      : { left, top: rect.bottom + MARGIN }
}
const hide = (): void => {
  spot.value = null
}
const flip = (): void => {
  if (props.toggle) (spot.value ? hide : show)()
}
</script>

<template>
  <span
    ref="trigger"
    class="infotip"
    :tabindex="focusable ? 0 : undefined"
    :aria-describedby="spot ? id : undefined"
    @mouseenter="show"
    @mouseleave="hide"
    @focusin="show"
    @focusout="hide"
    @click="flip"
    @keydown.esc="hide"
  >
    <slot />
  </span>
  <Teleport to="body">
    <div v-if="spot" :id="id" class="infotip-pop" role="tooltip" :style="spot">{{ text }}</div>
  </Teleport>
</template>

<style scoped>
.infotip {
  display: inline-flex;
}
.infotip:focus-visible {
  outline: 2px solid var(--saccent, currentColor);
  outline-offset: 2px;
  border-radius: var(--r);
}
.infotip-pop {
  position: fixed;
  z-index: var(--z-popover);
  max-width: 18rem;
  padding: 0.4rem 0.6667rem;
  background: var(--stip-bg);
  border: 1px solid var(--stip-border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-tip);
  color: var(--stip-fg);
  font-size: 0.8rem;
  pointer-events: none;
}
</style>
