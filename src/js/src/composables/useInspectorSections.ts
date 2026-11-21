import { reactive } from 'vue'
import { asStrings, readStored, writeStored } from '../utils/storage'

// Which inspector sections are folded away, by title. A per-browser convenience, so localStorage.
const STORE_KEY = 'studio.inspector.collapsed'

const collapsed = reactive(new Set(asStrings(readStored(STORE_KEY))))

export function useInspectorSections() {
  const isCollapsed = (title: string): boolean => collapsed.has(title)

  function toggle(title: string): void {
    if (!collapsed.delete(title)) collapsed.add(title)
    writeStored(STORE_KEY, [...collapsed])
  }

  return { isCollapsed, toggle }
}
