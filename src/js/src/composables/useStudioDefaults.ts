import { ref, computed } from 'vue'
import type { Ref } from 'vue'
import type { components } from '../api/schema'
import { patchConversation } from './useChat'
import { DEFAULT_KINDS, useChatDefaults } from './useChatDefaults'
import type { DefaultKind, InheritedDefault } from './useChatDefaults'
import type { ShowToast } from './useToast'
import { messageOf } from '../utils/errors'

type Schemas = components['schemas']
type HiddenDefaults = Schemas['HiddenDefaults']
type PausedInstructions = Schemas['PausedInstructions']

type PausableKind = 'instruction' | 'instruction_group'

/** What the pickers call a kind: 'snippet' and 'group' are the instruction kinds. */
type PickedKind = DefaultKind | 'snippet' | 'group'

const defaultKind = (picked: PickedKind): DefaultKind =>
  picked === 'snippet' ? 'instruction' : picked === 'group' ? 'instruction_group' : picked

const pausableKind = (picked: PickedKind): PausableKind | null => {
  const kind = defaultKind(picked)
  return kind === 'character' ? null : kind
}

const NO_HIDDEN = (): HiddenDefaults => ({ character: [], instruction: [], instruction_group: [] })
const NO_PAUSED = (): PausedInstructions => ({ instruction: [], instruction_group: [] })

// The defaults (global + space) a thread inherits, which of them are hidden or paused on this thread, and the
// calls that change that.
export function useStudioDefaults({ active, showToast }: { active: Ref<string | null>; showToast: ShowToast }) {
  // Defaults (global + space) a thread inherits, less any hidden here, plus pauses
  const defaults = useChatDefaults()
  const { inherited: allInherited, globalSettings, loadDefaults, setCurrentSpace } = defaults
  const hiddenDefaults = ref(NO_HIDDEN())
  const paused = ref(NO_PAUSED())
  const splitInherited = (hidden: boolean): Record<DefaultKind, InheritedDefault[]> => {
    const out = {} as Record<DefaultKind, InheritedDefault[]>
    for (const kind of DEFAULT_KINDS) {
      out[kind] = allInherited.value[kind].filter(x => hidden === hiddenDefaults.value[kind].includes(x.id))
    }
    return out
  }
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

  async function setDefaultHidden(
    { kind: picked, id }: { kind: PickedKind; id: number },
    hide: boolean,
  ): Promise<void> {
    const kind = defaultKind(picked)
    const ids = hiddenDefaults.value[kind].filter(x => x !== id)
    hiddenDefaults.value = { ...hiddenDefaults.value, [kind]: hide ? [...ids, id] : ids }
    if (!active.value) return
    try {
      await patchConversation(active.value, { hidden_defaults: hiddenDefaults.value })
    } catch (e) {
      showToast(`Couldn't update the thread: ${messageOf(e)}`, 'error')
    }
  }

  async function setPaused({ kind: picked, id }: { kind: PickedKind; id: number }, pause: boolean): Promise<void> {
    const kind = pausableKind(picked)
    if (kind === null) return // characters aren't paused, only instructions
    const ids = paused.value[kind].filter(x => x !== id)
    paused.value = { ...paused.value, [kind]: pause ? [...ids, id] : ids }
    if (!active.value) return
    try {
      await patchConversation(active.value, { paused_instructions: paused.value })
    } catch (e) {
      showToast(`Couldn't update the thread: ${messageOf(e)}`, 'error')
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
