import { confirmDialog } from './useDialog'
import { ref, reactive, computed, watch, onScopeDispose } from 'vue'
import {
  fetchConversations,
  fetchConversation,
  fetchConversationSpend,
  fetchChatStatus,
  fetchSpaces,
  fetchChatModels,
  createConversation,
  patchConversation,
  sendChatMessage,
  retryChatMessage,
  editChatMessage,
  enhanceChatPrompt,
  estimateChatCost,
  deleteChatExchange,
  fetchDeleteInfo,
  switchChatBranch,
  forkConversation,
  cancelChatMessage,
} from './useChat'
import { upsert, useChatCharacters } from './useChatCharacters'
import { useChatInstructions } from './useChatInstructions'
import { useMessagePolling } from './useMessagePolling'
import { useChatAttachments, MAX_ATTACHMENTS } from './useChatAttachments'
import { useChatBalances } from './useChatBalances'
import { unusedKeys, readVideoDuration } from './studioAttachments'
import { useStudioDefaults } from './useStudioDefaults'
import { useStudioMedia } from './useStudioMedia'
import { useStudioSidebar } from './useStudioSidebar'

// All of Studio's state + behaviour, kept out of the view so the components
// stay presentational. `settings` is a useComposerSettings() instance (shared
// with the inspector's model pickers); `models` is its catalogue, filled here.
// How long send() waits for a turn before handing the composer back. runTurn marks a chat thread as sending
// within this time (which then blocks a second send); a gallery send never blocks, so it can go again at once.
const SEND_HANDOFF_MS = 400

export function useStudio({ models, settings, showToast }) {
  const { selected, mode, turnSettings, applyChat, applyDefaults } = settings

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
  const aborts = new Map() // thread id -> AbortController of its live turn
  let forking = false

  // Image attachments (image-edit refs / video first frame) — reused chat layer
  // Images the next message may carry: a video model takes one start frame (two with
  // first+last frame) unless it's a reference-image model; others take the usual max
  const imageLimit = () => {
    if (mode.value !== 'video') return MAX_ATTACHMENTS
    const v = settings.videoInfo.value
    if (!v) return MAX_ATTACHMENTS
    // Reference-to-video: as many images as the model's ref_mode allows.
    if (v.ref_mode) return v.ref_mode.limits?.image ?? v.ref_mode.max ?? MAX_ATTACHMENTS
    if (v.reference_images) return v.max_refs || MAX_ATTACHMENTS
    return v.frame_images?.includes('last_frame') ? 2 : 1
  }
  // Video / audio reference caps — a ref_mode model takes several (its per-type
  // limit); everything else takes one.
  const refTypeLimit = kind => {
    const v = mode.value === 'video' ? settings.videoInfo.value : null
    return v?.ref_mode ? (v.ref_mode.limits?.[kind] ?? v.ref_mode.max ?? 1) : 1
  }
  const attach = useChatAttachments({
    convId: active,
    ensureConversation: ensureThread,
    showToast,
    limit: imageLimit,
    videoLimit: () => refTypeLimit('video'),
    audioLimit: () => refTypeLimit('audio'),
  })
  const {
    attachments,
    addFiles,
    addFromLibrary,
    addChatImage,
    addChatMedia,
    remove: removeAttachment,
    clear: clearAttachments,
    uploading,
  } = attach

  // Attachments the selected video model can't take (kept in the composer so a
  // model switch never loses them, but shown as unused and left out of the send).
  // Only video mode is strict; chat/auto/image use attachments as they always did.
  const unusedAttachments = computed(() => {
    const info = mode.value === 'video' ? settings.videoInfo.value : null
    if (!info) return new Set()
    const caps = { image: imageLimit(), video: refTypeLimit('video'), audio: refTypeLimit('audio') }
    return unusedKeys(attachments.value, info, caps)
  })

  // Reference-to-video with a source clip (recast): the output runs as long as
  // the clip, so on Auto the length is the clip's, snapped to what the model
  // allows. Picking a length by hand overrides it. Read client-side.
  watch(
    () => [
      selected.video,
      attachments.value
        .filter(a => a.video && a.preview)
        .map(a => a.key)
        .join(),
    ],
    async () => {
      settings.clipDuration.value = null
      if (mode.value !== 'video' || !settings.videoInfo.value?.ref_mode) return
      const vid = attachments.value.find(a => a.video && a.preview)
      if (!vid) return
      const secs = await readVideoDuration(vid.preview)
      if (!secs) return
      const opts = settings.durationOptions.value || []
      settings.clipDuration.value = opts.length
        ? opts.reduce((p, c) => (Math.abs(c - secs) < Math.abs(p - secs) ? c : p))
        : Math.round(secs)
    },
    { deep: true },
  )

  const {
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
  } = useStudioDefaults({ active, showToast })
  // Tell the defaults singleton which space is in context (for editors' add-to toggles)
  watch(
    () => activeThread.value?.space_id ?? null,
    id => setCurrentSpace(id),
    { immediate: true },
  )

  // Instructions + characters attached to the thread (plus the inherited defaults)
  const instr = useChatInstructions({
    convId: active,
    conversation: activeThread,
    showToast,
    inherited: inheritedInstructionIds,
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
  const editingInstruction = ref(null)

  const chars = useChatCharacters({
    convId: active,
    settings,
    ensureConversation: ensureThread,
    showToast,
    inheritedIds: inheritedCharacterIds,
  })
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

  const messageIndex = id => messages.value.findIndex(m => m.id === id)
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

  function replaceMessage(fresh) {
    const i = messageIndex(fresh.id)
    if (i !== -1) messages.value.splice(i, 1, fresh)
  }
  function showChat(data) {
    if (data.conversation) activeThread.value = data.conversation
    messages.value = data.messages || []
  }

  const polling = useMessagePolling({ messages, streamingId, replace: replaceMessage, onFinished: refreshAfterBilling })

  // Something was billed (a reply or generation landed): refresh every figure
  // that depends on it instead of waiting for a reload
  function refreshAfterBilling() {
    loadLists()
    refreshSpend(active.value)
    refreshBalances()
  }
  // Balances also drift outside this tab (other devices, other chats): re-check
  // when the tab is shown again and every couple of minutes while it is. Both
  // are torn down with the scope that created them — a listener and a timer
  // that outlive it would keep firing against a dead component.
  const onShown = () => document.visibilityState === 'visible' && refreshBalances()
  document.addEventListener('visibilitychange', onShown)
  const balanceTimer = setInterval(onShown, 120000)
  onScopeDispose(() => {
    document.removeEventListener('visibilitychange', onShown)
    clearInterval(balanceTimer)
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

  // Sending (same streamed-turn protocol as ChatView)
  const TURN_EVENTS = {
    start(ev, tempUser) {
      if (ev.user_message) {
        const i = tempUser ? messages.value.indexOf(tempUser) : messageIndex(ev.user_message.id)
        if (i !== -1) messages.value.splice(i, 1, ev.user_message)
      }
      // A reply being written again is already in the list: replace it rather
      // than pushing a duplicate (its content comes back blank, ready for deltas).
      const at = messageIndex(ev.assistant_message.id)
      if (at === -1) messages.value.push(ev.assistant_message)
      else messages.value.splice(at, 1, ev.assistant_message)
      if (!ev.assistant_message.lane) streamingId.value = ev.assistant_message.id
    },
    delta(ev) {
      const m = messages.value[messageIndex(streamingId.value)]
      if (m) m.content += ev.text
    },
    media(ev) {
      const m = messages.value[messageIndex(ev.message_id)]
      if (!m) return
      const list = m.media || (m.media = [])
      const prev = list.find(x => x.id === ev.item.id)
      upsert(list, ev.item)
      // Flipped pending → done: announce it (the gallery queue has no toast of its own).
      if (ev.item.status === 'done' && (!prev || prev.status === 'pending')) {
        showToast(`${ev.item.kind === 'video' ? 'Video' : 'Image'} ready`, 'success')
        refreshAfterBilling()
      }
    },
    characters(ev) {
      onCharactersUsed(ev.characters || [], ev.character_ids || [])
    },
    instructions(ev) {
      onInstructionUsed(ev.instruction, ev.instruction_ids || [])
    },
    title(ev) {
      if (activeThread.value) activeThread.value.title = ev.title
      const t = threads.value.find(x => x.id === active.value)
      if (t) t.title = ev.title
    },
    done(ev) {
      const i = messageIndex(ev.message?.id)
      if (i !== -1) messages.value.splice(i, 1, ev.message)
    },
  }

  const setSending = (id, on) => {
    const next = new Set(sendingIds.value)
    if (on) next.add(id)
    else next.delete(id)
    sendingIds.value = next
  }

  async function runTurn(fn, id, body, tempUser) {
    const gallery = body.lane === 'gallery'
    if (!gallery) setSending(id, true)
    const ctl = new AbortController()
    if (!gallery) aborts.set(id, ctl)
    let started = false
    // Once the user opens another thread the stream must not touch the shown
    // messages; the server keeps going and polling picks the result up.
    const onEvent = ev => {
      started ||= ev.type === 'start'
      if (active.value === id && !(gallery && ev.type === 'delta')) TURN_EVENTS[ev.type]?.(ev, tempUser)
    }
    try {
      await fn(id, body, onEvent, ctl.signal)
    } catch (e) {
      if (e.name === 'AbortError' || started) return
      showToast(e.message, 'error')
      if (active.value !== id) return
      if (body.message_id != null) openThread(id)
      else if (tempUser) messages.value = messages.value.filter(m => m !== tempUser)
    } finally {
      if (!gallery) {
        setSending(id, false)
        aborts.delete(id)
        if (active.value === id) streamingId.value = null
      }
      polling.ensure()
      refreshAfterBilling()
    }
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

  // Set from the moment Send is pressed until the turn is under way. `sending`
  // only switches on inside runTurn, after ensureThread() (a network call for a
  // new thread) — without this a second Enter/click in that gap passed
  // canSend and sent, and paid for, the prompt twice.
  let submitting = false
  async function send() {
    if (!canSend.value || submitting) return
    submitting = true
    try {
      await sendNow()
    } finally {
      submitting = false
    }
  }
  async function sendNow() {
    const content = draft.value.trim()
    const sent = attachments.value.filter(a => a.file && !unusedAttachments.value.has(a.key))
    const nImages = sent.filter(a => !a.video && !a.audio).length
    if (nImages > imageLimit()) {
      return showToast(
        `This video model takes ${imageLimit()} image${imageLimit() === 1 ? '' : 's'} — remove some, or pick a reference-image model (e.g. a “Ref” model)`,
        'error',
      )
    }
    const id = await ensureThread()
    const tempUser = reactive({
      id: `tmp-${Date.now()}`,
      role: 'user',
      content,
      lane: lane.value,
      status: 'done',
      media: sent.map(a => ({
        id: a.key,
        kind: a.audio ? 'audio' : a.video ? 'video' : 'image',
        status: 'done',
        file: a.file,
      })),
    })
    messages.value.push(tempUser)
    draft.value = ''
    clearAttachments()
    // Don't wait for the whole reply: once runTurn has started (chat turns are
    // then guarded by `sending`) a gallery send can go again straight away.
    const turn = runTurn(
      sendChatMessage,
      id,
      { ...turnSettings(), content, attachments: sent.map(a => a.file), lane: lane.value },
      tempUser,
    )
    await Promise.race([turn, new Promise(r => setTimeout(r, SEND_HANDOFF_MS))])
  }

  async function retry(msg) {
    const i = messageIndex(msg.id)
    if (sending.value || i === -1) return
    messages.value = messages.value.slice(0, i)
    await runTurn(retryChatMessage, active.value, { ...turnSettings(), message_id: msg.id }, null)
  }
  async function editMessage(msg, content) {
    const i = messageIndex(msg.id)
    if (sending.value || i === -1) return
    const tempUser = reactive({ ...msg, id: `tmp-${Date.now()}`, content, siblings: [] })
    messages.value = [...messages.value.slice(0, i), tempUser]
    await runTurn(editChatMessage, active.value, { ...turnSettings(), message_id: msg.id, content }, tempUser)
  }
  const resendMessage = msg => editMessage(msg, msg.content || '')

  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`
  function deleteDetail({ other_versions: versions, other_messages: after }) {
    const removes = [versions && plural(versions, 'other version'), after && plural(after, 'message')].filter(Boolean)
    const where = versions ? ' that followed them' : ' on other branches'
    return removes.length ? `This also removes ${removes.join(' and ')}${after ? where : ''}.` : ''
  }
  // The files the "also delete" box decides on, named so it's clear what goes:
  // only what this turn generated (uploads stay), and nothing at all when the
  // generation failed — then there's no box to tick.
  const MEDIA_WORDS = { image: 'image', video: 'video', audio: 'audio clip' }
  function deleteMediaLabel(media) {
    const parts = Object.entries(media || {})
      .filter(([, n]) => n > 0)
      .map(([kind, n]) => plural(n, MEDIA_WORDS[kind] || 'file'))
    if (!parts.length) return ''
    const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}` : parts[0]
    return `Also delete the ${list} it made`
  }
  // Deleting works on the prompt; given a reply (the gallery hands us the
  // message holding the media) it deletes the prompt that produced it.
  async function deleteExchange(msg) {
    if (sending.value) return
    const promptId = msg.role === 'assistant' && msg.parent_id ? msg.parent_id : msg.id
    try {
      const info = await fetchDeleteInfo(promptId)
      const mediaLabel = deleteMediaLabel(info.media)
      const r = await confirmDialog({
        title: 'Delete this prompt and its reply?',
        message: [deleteDetail(info), mediaLabel && 'Unticked, those files stay in your Media library.']
          .filter(Boolean)
          .join(' '),
        confirmLabel: 'Delete',
        danger: true,
        checkbox: mediaLabel ? { label: mediaLabel, checked: true } : null,
      })
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
  // "Use settings" (gallery): fill the composer from a past generation so the
  // user can tweak and press Generate. Fills only — never fires (unlike retry).
  function applyGenerationSettings(item) {
    const kind = ['video', 'audio'].includes(item.kind) ? item.kind : 'image'
    const text = item.original_prompt || item.prompt
    if (text) draft.value = text
    const model = item.model || item.params?.model
    if (model) selected[kind] = model
    mode.value = kind
    applyOptions(kind, item.params || {})
    restoreRefs(item)
  }
  const AUDIO_KEYS = [
    'voice',
    'speed',
    'volume',
    'pitch',
    'instrumental',
    'vocal_gender',
    'style',
    'title',
    'negative_prompt',
    'duration',
  ]
  function applyOptions(kind, p) {
    if (kind === 'audio') {
      for (const k of AUDIO_KEYS) if (p[k] != null) settings.audioOpts[k] = p[k]
      return
    }
    const opts = kind === 'video' ? settings.videoOpts : settings.imageOpts
    for (const k of ['aspect_ratio', 'resolution']) if (p[k]) opts[k] = p[k]
    if (kind !== 'video') return
    if (p.generate_audio != null) opts.generate_audio = p.generate_audio
    // A generation made on Auto goes back to Auto ('') — its stored duration is
    // what Auto worked out to (the clip's length), not a length that was chosen.
    opts.duration = p.duration_auto ? '' : (p.duration ?? opts.duration)
  }
  // Put a generation's reference images back as attachments (character refs
  // come back with the characters, not as files)
  function restoreRefs(item) {
    clearAttachments()
    const p = item.params || {}
    // Reference-to-video: re-attach each named ref with its kind, in order, so
    // the [@name] pills resolve again (image1, video1…).
    if (p.ref_items?.length) {
      for (const r of p.ref_items) {
        if (r.file && !r.file.startsWith?.('char:')) addChatMedia(r.file, r.type, item.conversation_id)
      }
      return
    }
    const files = [...(p.refs || []), p.first_frame, p.last_frame].filter(f => f && !f.startsWith('char:'))
    for (const f of new Set(files)) addChatImage(f, item.conversation_id)
  }
  // Pollo's own price for what's set up in the composer (Pollo models only)
  const estimate = ref(null)
  let estimateTimer = null
  let estimateSeq = 0
  async function refreshEstimate() {
    const kind = mode.value
    const model = ['image', 'video', 'audio'].includes(kind) ? selected[kind] : null
    const seq = ++estimateSeq
    if (!model?.startsWith('pollo/')) {
      estimate.value = null
      return
    }
    const t = turnSettings()
    const o = { video: t.video_options, audio: {}, image: t.image_options }[kind]
    const audio = kind === 'audio' ? { prompt: draft.value.trim(), audio_options: t.audio_options } : {}
    try {
      const r = await estimateChatCost({
        model,
        kind,
        ...o,
        ...audio,
        n_images: attachments.value.filter(a => !a.video && !a.audio).length,
      })
      if (seq === estimateSeq) estimate.value = r.estimate
    } catch {
      if (seq === estimateSeq) estimate.value = null
    }
  }
  watch(
    () =>
      JSON.stringify([
        mode.value,
        selected.image,
        selected.video,
        selected.audio,
        turnSettings(),
        attachments.value.length,
        mode.value === 'audio' ? draft.value : '',
      ]),
    () => {
      clearTimeout(estimateTimer)
      estimateTimer = setTimeout(refreshEstimate, 400)
    },
    { immediate: true },
  )
  // Enhance button: rewrite the draft with the text model. Only on request —
  // sending never alters the prompt.
  const enhancing = ref(false)
  async function enhanceDraft() {
    const prompt = draft.value.trim()
    if (!prompt || enhancing.value) return
    if (!selected.text) return showToast('Pick a text model to enhance prompts', 'error')
    enhancing.value = true
    try {
      const r = await enhanceChatPrompt({
        prompt,
        model: selected.text,
        kind: mode.value === 'video' ? 'video' : 'image',
      })
      draft.value = r.prompt
    } catch (e) {
      showToast(e.message, 'error')
    } finally {
      enhancing.value = false
    }
  }
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
  async function stop() {
    if (!streamingId.value) return
    try {
      await cancelChatMessage(streamingId.value)
    } catch {
      aborts.get(active.value)?.abort()
    }
  }
  // "Edit this image" / "animate this image": attach it and switch to that mode
  function useImage({ file, mode: target, conversation_id: fromConv } = {}) {
    if (file && !addChatImage(file, fromConv)) return
    if (target) mode.value = target
  }
  const { toggleFav, renameThread, removeThread, moveThread, addSpace, renameSpace, removeSpace } = useStudioSidebar({
    threads,
    spaces,
    active,
    activeThread,
    showToast,
    newThread,
    loadLists,
  })

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
