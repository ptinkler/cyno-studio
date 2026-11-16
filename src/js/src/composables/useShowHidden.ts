import { ref, watch } from 'vue'
import { readFlag, writeFlag } from '../utils/storage'

// "Show hidden": models the catalogue marks `hidden` (not enabled for this API
// key, or retired) are left out of model pickers unless this is on. One remembered
// setting shared by the chat pickers and the Generate page.
const KEY = 'models.showHidden'

const showHidden = ref(readFlag(KEY))
watch(showHidden, on => {
  writeFlag(KEY, on)
})

export function useShowHidden() {
  return { showHidden }
}
