import type { Ref } from 'vue'
import type { components } from '../api/schema'
import type { Conversation } from './chatConversationsApi'
import { deleteDialogOptions } from './studioDelete'
import type { StudioState, ThreadKind, UiMessage } from './studioTypes'
import type { ComposerSettings } from './useComposerSettings'
import { confirmDialog } from './useDialog'
import {
  fetchConversations,
  fetchConversation,
  fetchConversationSpend,
  fetchSpaces,
  createConversation,
  patchConversation,
  deleteChatExchange,
  fetchDeleteInfo,
  switchChatBranch,
  forkConversation,
} from './useChat'
import type { ShowToast } from './useToast'
import { messageOf } from '../utils/errors'

type Schemas = components['schemas']

/** What an open thread carries that other composables own: its instructions, characters and defaults. */
export interface ThreadLink {
  instructionIds: Ref<number[]>
  instructionGroupIds: Ref<number[]>
  characterIds: Ref<number[]>
  hiddenDefaults: Ref<Schemas['HiddenDefaults']>
  paused: Ref<Schemas['PausedInstructions']>
  NO_HIDDEN: () => Schemas['HiddenDefaults']
  NO_PAUSED: () => Schemas['PausedInstructions']
}

interface ThreadHooks {
  state: StudioState
  settings: Pick<ComposerSettings, 'selected' | 'applyChat'>
  link: ThreadLink
  /** Follows the thread's pending media. */
  polling: { ensure: () => void }
  showToast: ShowToast
}

/** A chat and its messages, as the server answers when one is opened, branched or has a prompt deleted. */
interface ShownChat {
  conversation: Conversation
  messages: readonly UiMessage[]
}

// Which thread is open and what's in it: the lists, opening / creating / forking a thread, branches, deleting.
// `state` is the Studio's shared refs; `link` is everything an open thread carries that other composables own
// (its instructions, characters, defaults) and `polling` follows its pending media.
export function useStudioThreads({ state, settings, link, polling, showToast }: ThreadHooks) {
  const { threads, spaces, active, activeThread, messages, loading, spend, newKind, sending } = state
  const { selected, applyChat } = settings
  const { instructionIds, instructionGroupIds, characterIds, hiddenDefaults, paused, NO_HIDDEN, NO_PAUSED } = link
  let forking = false

  async function loadLists(): Promise<void> {
    try {
      const [chats, spaceList] = await Promise.all([fetchConversations(), fetchSpaces()])
      threads.value = chats.conversations
      spaces.value = spaceList.spaces
    } catch {
      /* auth prompt handles 401 */
    }
  }

  async function refreshSpend(id: string | null): Promise<void> {
    if (!id) {
      spend.value = null
      return
    }
    try {
      spend.value = await fetchConversationSpend(id)
    } catch {
      spend.value = null
    }
  }

  function showChat(data: ShownChat): void {
    activeThread.value = data.conversation
    messages.value = [...data.messages]
  }

  function newThread(kind: ThreadKind = 'chat'): void {
    active.value = null
    activeThread.value = null
    messages.value = []
    instructionIds.value = []
    instructionGroupIds.value = []
    characterIds.value = []
    hiddenDefaults.value = NO_HIDDEN()
    paused.value = NO_PAUSED()
    spend.value = null
    newKind.value = kind === 'gallery' ? 'gallery' : 'chat'
  }

  async function openThread(id: string): Promise<boolean> {
    active.value = id
    loading.value = true
    try {
      // GET returns { conversation, messages }; unwrap so activeThread holds the
      // conversation itself (its kind/settings/instructions live there, not on
      // the envelope). showChat does the same during a streamed turn.
      const { conversation: conv, messages: shown } = await fetchConversation(id)
      activeThread.value = conv
      messages.value = shown
      applyChat(conv)
      instructionIds.value = conv.instruction_ids
      instructionGroupIds.value = conv.instruction_group_ids
      characterIds.value = conv.character_ids
      hiddenDefaults.value = { ...NO_HIDDEN(), ...conv.hidden_defaults }
      paused.value = { ...NO_PAUSED(), ...conv.paused_instructions }
      void refreshSpend(id)
      polling.ensure()
      return true
    } catch {
      // The thread doesn't exist (e.g. a stale URL) — fall back to a clean new
      // thread rather than leaving `active` pointing at a bad id, which would
      // make every later action 404 ("Conversation not found").
      newThread()
      return false
    } finally {
      loading.value = false
    }
  }

  async function ensureThread(): Promise<string> {
    if (active.value) return active.value
    const conv = await createConversation({
      kind: newKind.value,
      text_model: selected.text || null,
      image_model: selected.image || null,
      video_model: selected.video || null,
      instruction_ids: instructionIds.value,
      instruction_group_ids: instructionGroupIds.value,
      character_ids: characterIds.value,
      hidden_defaults: hiddenDefaults.value,
      paused_instructions: paused.value,
    })
    threads.value.unshift(conv)
    active.value = conv.id
    activeThread.value = conv
    messages.value = []
    return conv.id
  }

  // Switch a thread between Chat and Gallery (its default landing view).
  async function setThreadKind(kind: string): Promise<void> {
    const next: ThreadKind = kind === 'gallery' ? 'gallery' : 'chat'
    if (!active.value) {
      newKind.value = next
      return
    }
    try {
      await patchConversation(active.value, { kind: next })
      if (activeThread.value) activeThread.value.kind = next
      const thread = threads.value.find(x => x.id === active.value)
      if (thread) thread.kind = next
    } catch (e) {
      showToast(messageOf(e), 'error')
    }
  }

  // The server finds the turn from either a prompt or one of its replies (the gallery hands us the reply holding
  // the media), and deletes a reply with no prompt on its own.
  async function deleteExchange(msg: UiMessage): Promise<void> {
    if (sending.value) return
    const id = msg.id
    if (typeof id !== 'number') return // a message the server hasn't saved yet
    try {
      const result = await confirmDialog(deleteDialogOptions(await fetchDeleteInfo(id)))
      if (!result) return
      showChat(await deleteChatExchange(id, { deleteMedia: result.checked }))
    } catch (e) {
      showToast(messageOf(e), 'error')
    }
  }

  async function switchBranch(messageId: number): Promise<void> {
    if (sending.value || !active.value) return
    try {
      showChat(await switchChatBranch(active.value, messageId))
      polling.ensure()
    } catch (e) {
      showToast(messageOf(e), 'error')
    }
  }

  async function forkFrom(msg: UiMessage): Promise<void> {
    if (sending.value || forking || !active.value || typeof msg.id !== 'number') return
    forking = true
    showToast('Branching into a new thread…', 'info')
    try {
      const conv = await forkConversation(active.value, msg.id)
      threads.value.unshift(conv)
      await openThread(conv.id)
      showToast('Branched into a new thread', 'success')
    } catch (e) {
      showToast(messageOf(e), 'error')
    } finally {
      forking = false
    }
  }

  return {
    loadLists,
    refreshSpend,
    showChat,
    openThread,
    newThread,
    ensureThread,
    setThreadKind,
    deleteExchange,
    switchBranch,
    forkFrom,
  }
}
