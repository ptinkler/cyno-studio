import { ref, computed } from 'vue'
import { patchConversation } from './useChat'
import { useChatDefaults } from './useChatDefaults'

// The defaults (global + space) a thread inherits, which of them are hidden or paused on this thread, and the
// calls that change that.
export function useStudioDefaults({ active, showToast }) {
  // Defaults (global + space) a thread inherits, less any hidden here, plus pauses
  const defaults = useChatDefaults()
  const { inherited: allInherited, globalSettings, loadDefaults, setCurrentSpace } = defaults
  const NO_HIDDEN = () => ({ character: [], instruction: [], instruction_group: [] })
  const NO_PAUSED = () => ({ instruction: [], instruction_group: [] })
  const hiddenDefaults = ref(NO_HIDDEN())
  const paused = ref(NO_PAUSED())
  const splitInherited = hidden =>
    Object.fromEntries(
      Object.entries(allInherited.value).map(([kind, list]) => [
        kind,
        list.filter(x => hidden === (hiddenDefaults.value[kind] || []).includes(x.id)),
      ]),
    )
  const inheritedDefaults = computed(() => splitInherited(false))
  const hiddenInherited = computed(() => splitInherited(true))
  const inheritedInstructionIds = computed(() => ({
    snippets: inheritedDefaults.value.instruction.map(x => x.id),
    groups: inheritedDefaults.value.instruction_group.map(x => x.id),
  }))
  const inheritedCharacterIds = computed(() => inheritedDefaults.value.character.map(x => x.id))
  const pausedInstructionIds = computed(() => ({
    snippets: paused.value.instruction,
    groups: paused.value.instruction_group,
  }))
  const DEFAULT_KIND = { snippet: 'instruction', group: 'instruction_group' }
  async function setDefaultHidden({ kind: picked, id }, hide) {
    const kind = DEFAULT_KIND[picked] || picked
    const ids = hiddenDefaults.value[kind].filter(x => x !== id)
    hiddenDefaults.value = { ...hiddenDefaults.value, [kind]: hide ? [...ids, id] : ids }
    if (!active.value) return
    try {
      await patchConversation(active.value, { hidden_defaults: hiddenDefaults.value })
    } catch (e) {
      showToast(`Couldn't update the thread: ${e.message}`, 'error')
    }
  }
  async function setPaused({ kind: picked, id }, pause) {
    const kind = DEFAULT_KIND[picked] || picked
    const ids = paused.value[kind].filter(x => x !== id)
    paused.value = { ...paused.value, [kind]: pause ? [...ids, id] : ids }
    if (!active.value) return
    try {
      await patchConversation(active.value, { paused_instructions: paused.value })
    } catch (e) {
      showToast(`Couldn't update the thread: ${e.message}`, 'error')
    }
  }

  return {
    globalSettings,
    loadDefaults,
    setCurrentSpace,
    hiddenDefaults,
    paused,
    NO_HIDDEN,
    NO_PAUSED,
    inheritedDefaults,
    hiddenInherited,
    inheritedInstructionIds,
    inheritedCharacterIds,
    pausedInstructionIds,
    setDefaultHidden,
    setPaused,
  }
}
