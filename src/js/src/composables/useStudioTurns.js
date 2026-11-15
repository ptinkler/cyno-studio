import { reactive } from 'vue'
import { sendChatMessage, retryChatMessage, editChatMessage, cancelChatMessage } from './useChat'
import { upsert } from './useChatCharacters'

// How long send() waits for a turn before handing the composer back. runTurn marks a chat thread as sending
// within this time (which then blocks a second send); a gallery send never blocks, so it can go again at once.
const SEND_HANDOFF_MS = 400

// Sending and the streamed turn that follows (the same protocol as ChatView): send / retry / edit / stop.
// `state` is the Studio's shared refs; `composer` is the draft's side (attachments, limits, settings to send);
// `thread` and `used` are the pieces a turn calls back into.
export function useStudioTurns({ state, composer, thread, used, polling, refreshAfterBilling, showToast }) {
  const { threads, active, activeThread, messages, streamingId, draft, lane, sending, sendingIds, canSend } = state
  const { attachments, unusedAttachments, imageLimit, clearAttachments, turnSettings } = composer
  const { openThread, ensureThread, messageIndex } = thread
  const aborts = new Map() // thread id -> AbortController of its live turn

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
      used.onCharactersUsed(ev.characters || [], ev.character_ids || [])
    },
    instructions(ev) {
      used.onInstructionUsed(ev.instruction, ev.instruction_ids || [])
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

  // A turn that failed before it started: say so, and put the thread back as it was
  function onTurnFailed(e, id, body, tempUser) {
    showToast(e.message, 'error')
    if (active.value !== id) return
    if (body.message_id != null) openThread(id)
    else if (tempUser) messages.value = messages.value.filter(m => m !== tempUser)
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
      if (e.name !== 'AbortError' && !started) onTurnFailed(e, id, body, tempUser)
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

  async function stop() {
    if (!streamingId.value) return
    try {
      await cancelChatMessage(streamingId.value)
    } catch {
      aborts.get(active.value)?.abort()
    }
  }

  return { runTurn, send, retry, editMessage, resendMessage, stop }
}
