import { onBeforeUnmount, ref } from 'vue'
import type { Ref } from 'vue'

// Below this width the side panels would leave no room for the chat: they start as rails and open over it
// (the matching rule is in components/studio/studio.css)
export const NARROW_QUERY = '(max-width: 900px)'

/** Whether the window is narrow now; `onNarrow` runs each time it becomes so. */
export function useNarrowScreen(onNarrow: () => void): Ref<boolean> {
  const query = window.matchMedia(NARROW_QUERY) as MediaQueryList | undefined
  const narrow = ref(query?.matches ?? false)
  function changed(event: MediaQueryListEvent): void {
    narrow.value = event.matches
    if (event.matches) onNarrow()
  }
  query?.addEventListener('change', changed)
  onBeforeUnmount(() => {
    query?.removeEventListener('change', changed)
  })
  return narrow
}
