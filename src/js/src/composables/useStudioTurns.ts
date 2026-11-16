import { reactive } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { TurnEvent, TurnEventOf } from './chatStreamApi'
import type { Character } from './charactersApi'
import type { Instruction } from './chatSettingsApi'
import type { StudioState, UiMessage } from './studioTypes'
import type { TurnSettingsBody } from './useComposerSettings'
import { sendChatMessage, retryChatMessage, editChatMessage, cancelChatMessage } from './useChat'
import { upsert } from './useChatCharacters'
import type { Attachment } from './useChatAttachments'
import type { ShowToast } from './useToast'
import { messageOf } from '../utils/errors'
import { attType } from '../utils/refItems'

// How long send() waits for a turn before handing the composer back. runTurn marks a chat thread as sending
// within this time (which then blocks a second send); a gallery send never blocks, so it can go again at once.
const SEND_HANDOFF_MS = 400

/** Starts one kind of turn (send, retry, edit, reword) and feeds its events to `onEvent`. */
export type TurnStarter<B> = (
  convId: string,
  body: B,
  onEvent: (event: TurnEvent) => void,
  signal?: AbortSignal,
) => Promise<void>

interface TurnHooks {
  state: StudioState & {
    streamingId: Ref<number | string | null>
    draft: Ref<string>
    lane: Ref<'gallery' | null>
    sendingIds: Ref<Set<string | null>>
    canSend: ComputedRef<boolean>
  }
  /** The draft's side: attachments, limits and the settings to send. */
  composer: {
    attachments: Ref<Attachment[]>
    unusedAttachments: ComputedRef<Set<string>>
    imageLimit: () => number
    clearAttachments: () => void
    turnSettings: () => TurnSettingsBody
  }
  thread: {
    openThread: (id: string) => Promise<boolean>
    ensureThread: () => Promise<string>
    messageIndex: (id: number | string | null | undefined) => number
  }
  /** What a turn calls back into when the chat model made or used something. */
  used: {
    onCharactersUsed: (characters: readonly Character[], ids: number[]) => void
    onInstructionUsed: (item: Instruction | null | undefined, ids: number[]) => void
  }
  polling: { ensure: () => void }
  refreshAfterBilling: () => void
  showToast: ShowToast
}

const isSent = (a: Attachment): a is Attachment & { file: string } => a.file !== null

// Sending and the streamed turn that follows (the same protocol as ChatView): send / retry / edit / stop.
// `state` is the Studio's shared refs; `composer` is the draft's side (attachments, limits, settings to send);
// `thread` and `used` are the pieces a turn calls back into.
export function useStudioTurns({ state, composer, thread, used, polling, refreshAfterBilling, showToast }: TurnHooks) {
  const { threads, active, activeThread, messages, streamingId, draft, lane, sending, sendingIds, canSend } = state
  const { attachments, unusedAttachments, imageLimit, clearAttachments, turnSettings } = composer
  const { openThread, ensureThread, messageIndex } = thread
  const aborts = new Map<string, AbortController>() // thread id -> AbortController of its live turn

  // --- What each streamed event does to the shown chat -----------------------------------------------------------

  function onStart(event: TurnEventOf<'start'>, tempUser: UiMessage | null): void {
    if (event.user_message) {
      const i = tempUser ? messages.value.indexOf(tempUser) : messageIndex(event.user_message.id)
      if (i !== -1) messages.value.splice(i, 1, event.user_message)
    }
    // A reply being written again is already in the list: replace it rather
    // than pushing a duplicate (its content comes back blank, ready for deltas).
    const reply = event.assistant_message
    const at = messageIndex(reply.id)
    if (at === -1) messages.value.push(reply)
    else messages.value.splice(at, 1, reply)
    if (!reply.lane) streamingId.value = reply.id
  }

  function onDelta(event: TurnEventOf<'delta'>): void {
    const message = messages.value[messageIndex(streamingId.value)]
    if (message) message.content += event.text
  }

  function onMedia(event: TurnEventOf<'media'>): void {
    const message = messages.value[messageIndex(event.message_id)]
    if (!message) return
    const previous = message.media.find(x => x.id === event.item.id)
    upsert(message.media, event.item)
    // Flipped pending → done: announce it (the gallery queue has no toast of its own).
    if (event.item.status === 'done' && (!previous || previous.status === 'pending')) {
      showToast(`${event.item.kind === 'video' ? 'Video' : 'Image'} ready`, 'success')
      refreshAfterBilling()
    }
  }

  function onTitle(event: TurnEventOf<'title'>): void {
    if (activeThread.value) activeThread.value.title = event.title
    const t = threads.value.find(x => x.id === active.value)
    if (t) t.title = event.title
  }

  function onDone(event: TurnEventOf<'done'>): void {
    if (!event.message) return
    const i = messageIndex(event.message.id)
    if (i !== -1) messages.value.splice(i, 1, event.message)
  }

  function handle(event: TurnEvent, tempUser: UiMessage | null): void {
    switch (event.type) {
      case 'start':
        onStart(event, tempUser)
        break
      case 'delta':
        onDelta(event)
        break
      case 'media':
        onMedia(event)
        break
      case 'characters':
        used.onCharactersUsed(event.characters, event.character_ids)
        break
      case 'instructions':
        used.onInstructionUsed(event.instruction, event.instruction_ids)
        break
      case 'title':
        onTitle(event)
        break
      case 'done':
        onDone(event)
        break
      case 'error':
        break // the turn ends with a `done` that carries the failed message
    }
  }

  // --- Running a turn --------------------------------------------------------------------------------------------

  const setSending = (id: string, on: boolean): void => {
    const next = new Set(sendingIds.value)
    if (on) next.add(id)
    else next.delete(id)
    sendingIds.value = next
  }

  // A turn that failed before it started: say so, and put the thread back as it was
  function onTurnFailed(e: unknown, id: string, body: object, tempUser: UiMessage | null): void {
    showToast(messageOf(e), 'error')
    if (active.value !== id) return
    if ('message_id' in body) void openThread(id)
    else if (tempUser) messages.value = messages.value.filter(m => m !== tempUser)
  }

  async function runTurn<B extends object>(
    start: TurnStarter<B>,
    id: string,
    body: B,
    tempUser: UiMessage | null,
  ): Promise<void> {
    const gallery = 'lane' in body && body.lane === 'gallery'
    if (!gallery) setSending(id, true)
    const controller = new AbortController()
    if (!gallery) aborts.set(id, controller)
    const progress = { started: false } // set from the stream's callback
    // Once the user opens another thread the stream must not touch the shown
    // messages; the server keeps going and polling picks the result up.
    const onEvent = (event: TurnEvent): void => {
      progress.started ||= event.type === 'start'
      if (active.value === id && !(gallery && event.type === 'delta')) handle(event, tempUser)
    }
    try {
      await start(id, body, onEvent, controller.signal)
    } catch (e) {
      if (!(e instanceof Error && e.name === 'AbortError') && !progress.started) onTurnFailed(e, id, body, tempUser)
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

  // --- Send / retry / edit / stop --------------------------------------------------------------------------------

  // The user's prompt as it shows while the turn starts: replaced by the server's copy on the `start` event.
  function localPrompt(id: string, content: string, sent: readonly (Attachment & { file: string })[]): UiMessage {
    return reactive<UiMessage>({
      id: `tmp-${String(Date.now())}`,
      conversation_id: id,
      parent_id: null,
      role: 'user',
      content,
      media: sent.map(a => ({ id: a.key, kind: attType(a), source: 'upload', status: 'done', file: a.file })),
      model: null,
      mode: null,
      lane: lane.value,
      status: 'done',
      error: null,
      cost: null,
      text_versions: 0,
      text_shown: 0,
      created_at: null,
      siblings: [],
    })
  }

  async function sendNow(): Promise<void> {
    const content = draft.value.trim()
    const sent = attachments.value.filter(isSent).filter(a => !unusedAttachments.value.has(a.key))
    const images = sent.filter(a => !a.video && !a.audio).length
    if (images > imageLimit()) {
      showToast(
        `This video model takes ${String(imageLimit())} image${imageLimit() === 1 ? '' : 's'} — remove some, or pick a reference-image model (e.g. a “Ref” model)`,
        'error',
      )
      return
    }
    const id = await ensureThread()
    const tempUser = localPrompt(id, content, sent)
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
    await Promise.race([turn, new Promise(resolve => setTimeout(resolve, SEND_HANDOFF_MS))])
  }

  // Set from the moment Send is pressed until the turn is under way. `sending`
  // only switches on inside runTurn, after ensureThread() (a network call for a
  // new thread) — without this a second Enter/click in that gap passed
  // canSend and sent, and paid for, the prompt twice.
  let submitting = false
  async function send(): Promise<void> {
    if (!canSend.value || submitting) return
    submitting = true
    try {
      await sendNow()
    } finally {
      submitting = false
    }
  }

  async function retry(msg: UiMessage): Promise<void> {
    const i = messageIndex(msg.id)
    if (sending.value || i === -1 || !active.value || typeof msg.id !== 'number') return
    messages.value = messages.value.slice(0, i)
    await runTurn(retryChatMessage, active.value, { ...turnSettings(), message_id: msg.id }, null)
  }

  async function editMessage(msg: UiMessage, content: string): Promise<void> {
    const i = messageIndex(msg.id)
    if (sending.value || i === -1 || !active.value || typeof msg.id !== 'number') return
    const tempUser = reactive<UiMessage>({ ...msg, id: `tmp-${String(Date.now())}`, content, siblings: [] })
    messages.value = [...messages.value.slice(0, i), tempUser]
    await runTurn(editChatMessage, active.value, { ...turnSettings(), message_id: msg.id, content }, tempUser)
  }

  const resendMessage = (msg: UiMessage): Promise<void> => editMessage(msg, msg.content)

  async function stop(): Promise<void> {
    const id = streamingId.value
    if (typeof id !== 'number') return
    try {
      await cancelChatMessage(id)
    } catch {
      if (active.value) aborts.get(active.value)?.abort()
    }
  }

  return { runTurn, send, retry, editMessage, resendMessage, stop }
}
