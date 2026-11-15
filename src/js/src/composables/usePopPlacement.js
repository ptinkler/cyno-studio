import { ref } from 'vue'

const MARGIN = 8
const MAX_WIDTH = 420
const NEEDED_BELOW = 320

// A `position: fixed` pop-up placed next to its button (`root`), so a scrolling or narrow container (the chat
// sidebar) can't clip it. It opens upwards when there's more room above, and never runs off the window.
// Call track() when it opens and untrack() when it closes; it re-places itself on resize and scroll.
export function usePopPlacement(root) {
  const popStyle = ref({})
  function place() {
    if (!root.value) return
    const r = root.value.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    const width = Math.min(MAX_WIDTH, vw - 2 * MARGIN)
    const left = Math.max(MARGIN, Math.min(r.left, vw - width - MARGIN))
    const below = vh - r.bottom - 14
    const above = r.top - 14
    const up = below < NEEDED_BELOW && above > below
    popStyle.value = {
      left: `${left}px`,
      width: `${width}px`,
      maxHeight: `${Math.max(180, up ? above : below)}px`,
      ...(up ? { bottom: `${vh - r.top + 6}px` } : { top: `${r.bottom + 6}px` }),
    }
  }
  function track() {
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true) // any scrolling ancestor moves the button
  }
  function untrack() {
    window.removeEventListener('resize', place)
    window.removeEventListener('scroll', place, true)
  }
  return { popStyle, track, untrack }
}
