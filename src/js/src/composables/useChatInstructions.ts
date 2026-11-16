import { computed, ref } from 'vue'
import type { Ref } from 'vue'
import type { Conversation } from './chatConversationsApi'
import type { Instruction, InstructionGroup } from './chatSettingsApi'
import { fetchInstructions, patchConversation } from './useChat'
import type { ShowToast } from './useToast'
import { messageOf } from '../utils/errors'

interface InstructionHooks {
  convId: Ref<string | null>
  /** The open chat, kept in step with what is attached. */
  conversation: Ref<Conversation | null>
  showToast: ShowToast
  /** The snippet and group ids its defaults attach, on top of its own. */
  inherited?: Ref<{ snippets: readonly number[]; groups: readonly number[] }> | undefined
}

// Saved instruction snippets and groups, and the ones attached to the open
// chat (or to the next new one: the defaults, until the user changes them).
// A chat holds any number of snippets and groups; both are flattened and
// de-duped server-side into what the model is sent (see _conversation_instructions).
export function useChatInstructions({ convId, conversation, showToast, inherited }: InstructionHooks) {
  const instructions = ref<Instruction[]>([]) // all saved snippets
  const groups = ref<InstructionGroup[]>([]) // all saved groups
  const instructionIds = ref<number[]>([]) // snippets attached to this chat
  const groupIds = ref<number[]>([]) // groups attached to this chat

  const withInherited = (kind: 'snippets' | 'groups', own: readonly number[]): number[] => [
    ...new Set([...(inherited?.value[kind] ?? []), ...own]),
  ]
  const attachedInstructions = computed(() =>
    withInherited('snippets', instructionIds.value).flatMap(id => instructions.value.find(i => i.id === id) ?? []),
  )
  const attachedGroups = computed(() =>
    withInherited('groups', groupIds.value).flatMap(id => groups.value.find(g => g.id === id) ?? []),
  )
  // Groups first, then individual snippets — what the sidebar summary shows
  const attachmentSummary = computed(() =>
    [...attachedGroups.value.map(g => g.name), ...attachedInstructions.value.map(i => i.name)].join(', '),
  )

  async function loadInstructions(): Promise<void> {
    try {
      const data = await fetchInstructions()
      instructions.value = data.instructions
      groups.value = data.groups
      // ChatView owns new-chat seeding (it also knows the pending space), so
      // loading the catalogue never changes what's attached here.
    } catch {
      /* 401 handled by auth prompt */
    }
  }

  async function patch(fields: { instruction_ids: number[] } | { instruction_group_ids: number[] }): Promise<void> {
    if (!convId.value) return // new chats get them on creation
    try {
      await patchConversation(convId.value, fields)
      if (conversation.value) Object.assign(conversation.value, fields)
    } catch (e) {
      showToast(`Couldn't update instructions: ${messageOf(e)}`, 'error')
    }
  }

  function setInstructions(ids: number[]): void {
    instructionIds.value = ids
    void patch({ instruction_ids: ids })
  }

  function setGroups(ids: number[]): void {
    groupIds.value = ids
    void patch({ instruction_group_ids: ids })
  }

  // The chat model saved and attached a snippet (create_instruction tool)
  function onInstructionUsed(item: Instruction | null | undefined, ids: number[]): void {
    if (item) {
      const i = instructions.value.findIndex(x => x.id === item.id)
      if (i === -1) instructions.value.push(item)
      else instructions.value.splice(i, 1, item)
    }
    instructionIds.value = ids
  }

  // The management dialog created/edited/deleted snippets or groups
  async function onInstructionsChanged(): Promise<void> {
    await loadInstructions()
    // Drop anything that no longer exists from this chat's attachments
    instructionIds.value = instructionIds.value.filter(id => instructions.value.some(i => i.id === id))
    groupIds.value = groupIds.value.filter(id => groups.value.some(g => g.id === id))
  }

  return {
    instructions,
    groups,
    instructionIds,
    groupIds,
    attachedInstructions,
    attachedGroups,
    attachmentSummary,
    loadInstructions,
    setInstructions,
    setGroups,
    onInstructionUsed,
    onInstructionsChanged,
  }
}
