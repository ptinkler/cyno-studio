import { nextTick, onBeforeUnmount, ref } from 'vue'
import type { Ref } from 'vue'

interface DropdownHooks {
  onOpen?: () => void
  onClose?: () => void
  /** A template ref, focused once the pop-up is open. */
  focus?: Ref<HTMLElement | null>
}

// A pop-up's open state, closed by any mousedown outside `root` (bind it to
// the element holding both the button and the pop-up) and on unmount.
// `onOpen` / `onClose` run as it opens / closes; `focus` is focused once it's open.
export function useDropdown({ onOpen, onClose, focus }: DropdownHooks = {}) {
  const open = ref(false)
  const root = ref<HTMLElement | null>(null)

  function onDocDown(event: MouseEvent): void {
    if (root.value && event.target instanceof Node && !root.value.contains(event.target)) close()
  }

  async function show(): Promise<void> {
    if (open.value) return
    open.value = true
    onOpen?.()
    document.addEventListener('mousedown', onDocDown)
    await nextTick()
    focus?.value?.focus()
  }

  function close(): void {
    if (!open.value) return
    open.value = false
    document.removeEventListener('mousedown', onDocDown)
    onClose?.()
  }

  const toggle = (): void => {
    if (open.value) close()
    else void show()
  }

  onBeforeUnmount(close)
  return { open, root, show, close, toggle }
}
