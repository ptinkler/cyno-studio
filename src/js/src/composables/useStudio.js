import { ref, reactive, computed, watch, onScopeDispose } from 'vue'
import { fetchChatStatus, fetchChatModels } from './useChat'
import { useChatCharacters } from './useChatCharacters'
import { useChatInstructions } from './useChatInstructions'
import { useMessagePolling } from './useMessagePolling'
import { useChatBalances } from './useChatBalances'
import { useStudioAttachments } from './useStudioAttachments'
import { useStudioDefaults } from './useStudioDefaults'
import { useStudioEnhance, useStudioEstimate } from './useStudioPrompt'
import { useStudioMedia } from './useStudioMedia'
import { useStudioReuse } from './useStudioReuse'
import { useStudioSidebar } from './useStudioSidebar'
import { useStudioThreads } from './useStudioThreads'
import { useStudioTurns } from './useStudioTurns'

const BALANCE_REFRESH_MS = 2 * 60 * 1000

// All of Studio's state + behaviour, kept out of the view so the components
// stay presentational. `settings` is a useComposerSettings() instance (shared
// with the inspector's model pickers); `models` is its catalogue, filled here.
// This is the composition root: it owns the shared state and wires the focused composables together
// (attachments, threads, turns, prompt tools, media actions, sidebar).
export function useStudio({ models, settings, showToast }) {
  const { selected, mode, turnSettings, applyDefaults } = settings

  const modelsLoading = ref(true)
  const providers = reactive({ openrouter: true, venice: false })
  const { balances, refresh: refreshBalances } = useChatBalances(providers)
  const threads = ref([])
  const spaces = ref([])
  const active = ref(null)
  const activeThread = ref(null)
  const messages = ref([])
  const loading = ref(false)
  // Threads with a live turn: generation blocks only its own thread, not the app
  const sendingIds = ref(new Set())
  // Which lane the composer feeds: 'gallery' sends are standalone exchanges that
  // never block (or join) the chat, so the gallery view is never "sending".
  const lane = ref(null)
  const sending = computed(() => lane.value !== 'gallery' && sendingIds.value.has(active.value))
  const streamingId = ref(null)
  const draft = ref('')
  const spend = ref(null)
  const favourites = ref([]) // cross-thread gallery of favourited generations
  // The thread being created from scratch opens on this view ('chat' | 'gallery')
  const newKind = ref('chat')

  // The composables below need each other's functions before they exist; these call through at use time.
  const ensureThread = () => threadApi.ensureThread()
  const messageIndex = id => messages.value.findIndex(m => m.id === id)
  function replaceMessage(fresh) {
    const i = messageIndex(fresh.id)
    if (i !== -1) messages.value.splice(i, 1, fresh)
  }

  const att = useStudioAttachments({ active, settings, showToast, ensureConversation: ensureThread })
  const {
    attachments,
    addFiles,
    addFromLibrary,
    addChatImage,
    addChatMedia,
    remove: removeAttachment,
    clear: clearAttachments,
    uploading,
    unusedAttachments,
    imageLimit,
  } = att

  const defaults = useStudioDefaults({ active, showToast })
  const {
    globalSettings,
    loadDefaults,
    hiddenDefaults,
    paused,
    NO_HIDDEN,
    NO_PAUSED,
    inheritedDefaults,
    hiddenInherited,
    pausedInstructionIds,
    setDefaultHidden,
    setPaused,
  } = defaults
  // Instructions + characters attached to the thread (plus the inherited defaults)
  const instr = useChatInstructions({
    convId: active,
    conversation: activeThread,
    showToast,
    inherited: defaults.inheritedInstructionIds,
  })
  const chars = useChatCharacters({
    convId: active,
    settings,
    ensureConversation: ensureThread,
    showToast,
    inheritedIds: defaults.inheritedCharacterIds,
  })
  const {
    instructions,
    groups: instructionGroups,
    instructionIds,
    groupIds: instructionGroupIds,
    attachedInstructions,
    attachedGroups,
    attachmentSummary: instructionSummary,
    loadInstructions,
    setInstructions,
    setGroups,
    onInstructionUsed,
    onInstructionsChanged,
  } = instr
  const {
    characters,
    characterIds,
    charEditor,
    attachedCharacters,
    characterNames,
    characterSupport,
    loadCharacters,
    setCharacters,
    editCharacter,
    newCharacter,
    onCharactersUsed,
    onCharacterSaved,
    onCharacterDeleted,
  } = chars
  const editingInstruction = ref(null)
  // Tell the defaults singleton which space is in context (for editors' add-to toggles)
  watch(
    () => activeThread.value?.space_id ?? null,
    id => defaults.setCurrentSpace(id),
    { immediate: true },
  )

  const lastAssistantId = computed(() => {
    const last = messages.value.filter(m => !m.lane).at(-1)
    return last?.role === 'assistant' ? last.id : null
  })
  const canSend = computed(
    () =>
      (!!draft.value.trim() || attachments.value.some(a => a.file) || !!settings.activeInfo.value?.no_prompt) &&
      !uploading.value &&
      !sending.value,
  )
  const activeTitle = computed(() => threads.value.find(t => t.id === active.value)?.title || 'New thread')
  // Which view the current thread opens on. A saved thread carries its own
  // kind; an unsaved new thread uses the kind picked in the sidebar.
  const activeKind = computed(() => (active.value ? activeThread.value?.kind || 'chat' : newKind.value))

  const polling = useMessagePolling({ messages, streamingId, replace: replaceMessage, onFinished: refreshAfterBilling })
  // Something was billed (a reply or generation landed): refresh every figure
  // that depends on it instead of waiting for a reload
  function refreshAfterBilling() {
    threadApi.loadLists()
    threadApi.refreshSpend(active.value)
    refreshBalances()
  }
  // Balances also drift outside this tab (other devices, other chats): re-check
  // when the tab is shown again and every couple of minutes while it is. Both
  // are torn down with the scope that created them — a listener and a timer
  // that outlive it would keep firing against a dead component.
  const onShown = () => document.visibilityState === 'visible' && refreshBalances()
  document.addEventListener('visibilitychange', onShown)
  const balanceTimer = setInterval(onShown, BALANCE_REFRESH_MS)
  onScopeDispose(() => {
    document.removeEventListener('visibilitychange', onShown)
    clearInterval(balanceTimer)
  })

  const state = { threads, spaces, active, activeThread, messages, loading, spend, newKind, sending }
  const threadApi = useStudioThreads({
    state,
    settings,
    link: {
      instructionIds,
      instructionGroupIds,
      characterIds,
      hiddenDefaults,
      paused,
      NO_HIDDEN,
      NO_PAUSED,
    },
    polling,
    showToast,
  })
  const { loadLists, openThread, newThread, setThreadKind, deleteExchange, switchBranch, forkFrom } = threadApi

  const { runTurn, send, retry, editMessage, resendMessage, stop } = useStudioTurns({
    state: { ...state, streamingId, draft, lane, sendingIds, canSend },
    composer: { attachments, unusedAttachments, imageLimit, clearAttachments, turnSettings },
    thread: { openThread, ensureThread, messageIndex },
    used: { onCharactersUsed, onInstructionUsed },
    polling,
    refreshAfterBilling,
    showToast,
  })

  const estimate = useStudioEstimate({ mode, selected, turnSettings, attachments, draft })
  const { enhancing, enhanceDraft } = useStudioEnhance({ mode, selected, draft, showToast })
  const { applyGenerationSettings } = useStudioReuse({
    draft,
    settings,
    attachments: { clearAttachments, addChatMedia, addChatImage },
  })
  const { regenerateMedia, reword, showMediaVersion, showTextVersion, pinMedia, favouriteMedia, loadFavourites } =
    useStudioMedia({
      messages,
      messageIndex,
      replaceMessage,
      polling,
      showToast,
      selected,
      sending,
      runTurn,
      turnSettings,
      active,
      favourites,
    })
  const { toggleFav, renameThread, removeThread, moveThread, addSpace, renameSpace, removeSpace } = useStudioSidebar({
    threads,
    spaces,
    active,
    activeThread,
    showToast,
    newThread,
    loadLists,
  })

  async function loadModels() {
    modelsLoading.value = true
    try {
      const d = await fetchChatModels()
      Object.assign(models, { text: d.text || [], image: d.image || [], video: d.video || [], audio: d.audio || [] })
      applyDefaults()
    } catch {
      /* leave empty */
    } finally {
      modelsLoading.value = false
    }
  }
  async function loadStatus() {
    try {
      const s = await fetchChatStatus()
      providers.openrouter = s.openrouter ?? s.configured
      providers.venice = !!s.venice
    } catch {
      /* ignore */
    }
    refreshBalances()
  }
  // "Edit this image" / "animate this image": attach it and switch to that mode
  /** @param {{ file?: string, mode?: string, conversation_id?: string }} [pick] */
  function useImage({ file, mode: target, conversation_id: fromConv } = {}) {
    if (file && !addChatImage(file, fromConv)) return
    if (target) mode.value = target
  }

  return {
    modelsLoading,
    threads,
    spaces,
    active,
    activeThread,
    messages,
    loading,
    sending,
    estimate,
    unusedAttachments,
    lane,
    streamingId,
    draft,
    attachments,
    uploading,
    addFiles,
    addFromLibrary,
    enhancing,
    enhanceDraft,
    removeAttachment,
    lastAssistantId,
    canSend,
    activeTitle,
    activeKind,
    newKind,
    favourites,
    loadFavourites,
    favouriteMedia,
    setThreadKind,
    // instructions
    instructions,
    instructionGroups,
    instructionIds,
    instructionGroupIds,
    attachedInstructions,
    attachedGroups,
    instructionSummary,
    loadInstructions,
    setInstructions,
    setGroups,
    onInstructionsChanged,
    editingInstruction,
    // defaults (inherited / hidden / paused)
    inheritedDefaults,
    hiddenInherited,
    pausedInstructionIds,
    setDefaultHidden,
    setPaused,
    loadDefaults,
    globalSettings,
    // characters
    characters,
    characterIds,
    charEditor,
    attachedCharacters,
    characterNames,
    characterSupport,
    loadCharacters,
    setCharacters,
    editCharacter,
    newCharacter,
    onCharacterSaved,
    onCharacterDeleted,
    providers,
    balances,
    spend,
    loadStatus,
    loadModels,
    loadLists,
    openThread,
    newThread,
    send,
    retry,
    editMessage,
    resendMessage,
    switchBranch,
    forkFrom,
    regenerateMedia,
    applyGenerationSettings,
    pinMedia,
    stop,
    deleteExchange,
    useImage,
    reword,
    showTextVersion,
    showMediaVersion,
    toggleFav,
    renameThread,
    removeThread,
    moveThread,
    addSpace,
    renameSpace,
    removeSpace,
  }
}
