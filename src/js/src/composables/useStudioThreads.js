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
import { deleteDialogOptions } from './studioDelete'

// Which thread is open and what's in it: the lists, opening / creating / forking a thread, branches, deleting.
// `state` is the Studio's shared refs; `link` is everything an open thread carries that other composables own
// (its instructions, characters, defaults) and `polling` follows its pending media.
export function useStudioThreads({ state, settings, link, polling, showToast }) {
  const { threads, spaces, active, activeThread, messages, loading, spend, newKind, sending } = state
  const { selected, applyChat } = settings
  const { instructionIds, instructionGroupIds, characterIds, hiddenDefaults, paused, NO_HIDDEN, NO_PAUSED } = link
  let forking = false

  async function loadLists() {
    try {
      const [c, s] = await Promise.all([fetchConversations(), fetchSpaces()])
      threads.value = c.conversations || c || []
      spaces.value = s.spaces || s || []
    } catch {
      /* auth prompt handles 401 */
    }
  }
  async function refreshSpend(id) {
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
  function showChat(data) {
    if (data.conversation) activeThread.value = data.conversation
    messages.value = data.messages || []
  }

  async function openThread(id) {
    active.value = id
    loading.value = true
    try {
      // GET returns { conversation, messages }; unwrap so activeThread holds the
      // conversation itself (its kind/settings/instructions live there, not on
      // the envelope). showChat does the same during a streamed turn.
      const data = await fetchConversation(id)
      const conv = data.conversation || data
      activeThread.value = conv
      messages.value = data.messages || []
      applyChat(conv)
      instructionIds.value = conv.instruction_ids || []
      instructionGroupIds.value = conv.instruction_group_ids || []
      characterIds.value = conv.character_ids || []
      hiddenDefaults.value = { ...NO_HIDDEN(), ...conv.hidden_defaults }
      paused.value = { ...NO_PAUSED(), ...conv.paused_instructions }
      refreshSpend(id)
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
  function newThread(kind = 'chat') {
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
  async function ensureThread() {
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
  async function setThreadKind(kind) {
    const k = kind === 'gallery' ? 'gallery' : 'chat'
    if (!active.value) {
      newKind.value = k
      return
    }
    try {
      await patchConversation(active.value, { kind: k })
      if (activeThread.value) activeThread.value.kind = k
      const t = threads.value.find(x => x.id === active.value)
      if (t) t.kind = k
    } catch (e) {
      showToast(e.message, 'error')
    }
  }

  // Deleting works on the prompt; given a reply (the gallery hands us the
  // message holding the media) it deletes the prompt that produced it.
  async function deleteExchange(msg) {
    if (sending.value) return
    const promptId = msg.role === 'assistant' && msg.parent_id ? msg.parent_id : msg.id
    try {
      const r = await confirmDialog(deleteDialogOptions(await fetchDeleteInfo(promptId)))
      if (!r) return
      showChat(await deleteChatExchange(promptId, { deleteMedia: r.checked }))
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  async function switchBranch(messageId) {
    if (sending.value) return
    try {
      showChat(await switchChatBranch(active.value, messageId))
      polling.ensure()
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  async function forkFrom(msg) {
    if (sending.value || forking) return
    forking = true
    showToast('Branching into a new thread…', 'info')
    try {
      const conv = await forkConversation(active.value, msg.id)
      threads.value.unshift(conv)
      await openThread(conv.id)
      showToast('Branched into a new thread', 'success')
    } catch (e) {
      showToast(e.message, 'error')
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
