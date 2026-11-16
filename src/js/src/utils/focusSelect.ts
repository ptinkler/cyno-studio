import type { Directive } from 'vue'

/** `v-focus-select`: when the input appears, focus it with its text selected (for rename-in-place). */
export const vFocusSelect: Directive<HTMLInputElement> = {
  mounted(el) {
    el.focus()
    el.select()
  },
}

/** What an input event's field now holds ('' for an event from anywhere else). */
export const typedValue = (event: Event): string => (event.target instanceof HTMLInputElement ? event.target.value : '')
