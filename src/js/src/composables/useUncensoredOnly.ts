import { ref, watch } from 'vue'
import { readFlag, writeFlag } from '../utils/storage'

// "Uncensored only": narrow the chat model pickers to models their provider
// marks uncensored (Venice). One remembered setting shared by every picker.
const KEY = 'models.uncensoredOnly'

const uncensoredOnly = ref(readFlag(KEY))
watch(uncensoredOnly, on => {
  writeFlag(KEY, on)
})

export function useUncensoredOnly() {
  return { uncensoredOnly }
}
