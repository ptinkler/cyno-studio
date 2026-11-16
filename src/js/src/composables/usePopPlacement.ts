import { ref } from 'vue'
import type { Ref } from 'vue'

const MARGIN = 8
const MAX_WIDTH = 420
const NEEDED_BELOW = 320
const MIN_HEIGHT = 180
const GAP = 14
const OFFSET = 6

// A `position: fixed` pop-up placed next to its button (`root`), so a scrolling or narrow container (the chat
// sidebar) can't clip it. It opens upwards when there's more room above, and never runs off the window.
// Call track() when it opens and untrack() when it closes; it re-places itself on resize and scroll.
export function usePopPlacement(root: Ref<HTMLElement | null>) {
  const popStyle = ref<Record<string, string>>({})

  function place(): void {
    if (!root.value) return
    const r = root.value.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    const width = Math.min(MAX_WIDTH, vw - 2 * MARGIN)
    const left = Math.max(MARGIN, Math.min(r.left, vw - width - MARGIN))
    const below = vh - r.bottom - GAP
    const above = r.top - GAP
    const up = below < NEEDED_BELOW && above > below
    popStyle.value = {
      left: `${String(left)}px`,
      width: `${String(width)}px`,
      maxHeight: `${String(Math.max(MIN_HEIGHT, up ? above : below))}px`,
      ...(up ? { bottom: `${String(vh - r.top + OFFSET)}px` } : { top: `${String(r.bottom + OFFSET)}px` }),
    }
  }
  function track(): void {
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true) // any scrolling ancestor moves the button
  }
  function untrack(): void {
    window.removeEventListener('resize', place)
    window.removeEventListener('scroll', place, true)
  }
  return { popStyle, track, untrack }
}
