import { nextTick, onBeforeUnmount, watch } from 'vue'
import type { Ref } from 'vue'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

const FIELDS = 'input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled])'

const focusableIn = (root: HTMLElement): HTMLElement[] =>
  [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(el => el.closest('[hidden], [aria-hidden="true"]') === null)

/** Where focus goes on opening: what asks for it, else the first field (not the ✕ in the header), else the first control. */
const opening = (root: HTMLElement): HTMLElement | undefined =>
  root.querySelector<HTMLElement>('[autofocus]') ?? root.querySelector<HTMLElement>(FIELDS) ?? focusableIn(root)[0]

/**
 * Where Tab (or Shift+Tab) must be sent instead of its default, or `undefined` to let it go: past either end of
 * the dialog's controls it wraps to the other end, and from outside the dialog it comes back in. `null` means
 * there is nothing to land on, so focus stays where it is.
 */
function wrapTarget(root: HTMLElement, backwards: boolean): HTMLElement | null | undefined {
  const items = focusableIn(root)
  if (items.length === 0) return null
  const [first, last] = [items[0], items[items.length - 1]]
  const here = document.activeElement
  const atEdge = here === (backwards ? first : last) || !root.contains(here)
  return atEdge ? (backwards ? last : first) : undefined
}

/**
 * Keeps keyboard focus in a dialog while it is open: focus moves in when it opens (unless something inside
 * already took it, like an autofocused field), Tab and Shift+Tab wrap at the ends instead of leaving for the
 * page behind, and when it closes focus goes back to what opened it.
 */
export function useFocusTrap(container: Ref<HTMLElement | null>, active: Ref<boolean>): void {
  let opener: HTMLElement | null = null

  function onKeydown(event: KeyboardEvent): void {
    const root = container.value
    if (event.key !== 'Tab' || !root) return
    const target = wrapTarget(root, event.shiftKey)
    if (target !== undefined) {
      event.preventDefault()
      target?.focus()
    }
  }

  function release(): void {
    document.removeEventListener('keydown', onKeydown, true)
    if (opener?.isConnected) opener.focus()
    opener = null
  }

  watch(
    active,
    on => {
      if (!on) {
        release()
        return
      }
      opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
      document.addEventListener('keydown', onKeydown, true)
      void nextTick(() => {
        const root = container.value
        if (!root || root.contains(document.activeElement)) return
        const target = opening(root) ?? root
        if (target === root && !root.hasAttribute('tabindex')) root.setAttribute('tabindex', '-1')
        target.focus({ preventScroll: true })
      })
    },
    { immediate: true },
  )
  onBeforeUnmount(release)
}
