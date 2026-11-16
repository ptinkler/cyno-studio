import type { Ref } from 'vue'
import type { components } from '../api/schema'
import type { ShownMessage, MediaCard } from './chatConversationsApi'
import type { LibraryCard } from './chatFilesApi'
import type { TurnSettingsBody } from './useComposerSettings'
import type { UiMessage } from './studioTypes'
import type { TurnStarter } from './useStudioTurns'
import {
  fetchChatLibrary,
  favouriteChatMedia,
  pinChatMedia,
  regenerateChatMedia,
  rewordChatMessage,
  showChatMediaVersion,
  showChatTextVersion,
} from './useChat'
import type { ShowToast } from './useToast'
import { messageOf } from '../utils/errors'

type Schemas = components['schemas']

/** A message to act on: one in the chat, or (for favourites) a gallery row that carries the message's id. */
type MessageRef = { id: number | string } | { message_id: number }

interface MediaHooks {
  messages: Ref<UiMessage[]>
  messageIndex: (id: number | string | null | undefined) => number
  replaceMessage: (fresh: ShownMessage) => void
  polling: { ensure: () => void }
  showToast: ShowToast
  selected: Record<'image' | 'video' | 'audio', string>
  sending: Ref<boolean>
  runTurn: (
    start: TurnStarter<Schemas['RewordMessage']>,
    id: string,
    body: Schemas['RewordMessage'],
    tempUser: null,
  ) => Promise<void>
  turnSettings: () => TurnSettingsBody
  active: Ref<string | null>
  /** The cross-thread gallery of favourited generations. */
  favourites: Ref<LibraryCard[]>
}

// Actions on a reply's media cards and wordings: regenerate, reword, switch version, pin, favourite.
export function useStudioMedia({
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
}: MediaHooks) {
  const fail = (e: unknown): void => {
    showToast(messageOf(e), 'error')
  }
  // A saved message's id: a prompt the server hasn't saved yet has nothing to act on
  const savedId = (msg: { id: number | string }): number | null => (typeof msg.id === 'number' ? msg.id : null)

  // The model asked for, else the one picked for the card's kind
  const modelFor = (msg: UiMessage, mediaId: string, asked: string | null | undefined): string | null | undefined => {
    if (asked) return asked
    const kind = msg.media.find(i => i.id === mediaId)?.kind
    return kind ? selected[kind] : undefined
  }

  // Cards whose regenerate request is in flight: a double click on "Try
  // again" would otherwise start (and pay for) two generations
  const regenerating = new Set<string>()
  async function regenerateMedia(
    msg: UiMessage,
    { mediaId, ...options }: { mediaId: string } & Schemas['RegenerateMedia'],
  ): Promise<void> {
    const id = savedId(msg)
    if (id === null || regenerating.has(mediaId)) return
    regenerating.add(mediaId)
    const model = modelFor(msg, mediaId, options.model)
    try {
      replaceMessage(await regenerateChatMedia(id, mediaId, { ...options, ...(model ? { model } : {}) }))
      polling.ensure()
    } catch (e) {
      fail(e)
    } finally {
      regenerating.delete(mediaId)
    }
  }

  // Write a reply's words again, keeping the pictures it already made.
  // With an instruction the model edits its words; without, it redoes them.
  // The old words stay as a version (the ‹ › on the text).
  async function reword(msg: UiMessage, instruction = ''): Promise<void> {
    const id = savedId(msg)
    if (sending.value || id === null || messageIndex(msg.id) === -1 || !active.value) return
    await runTurn(rewordChatMessage, active.value, { ...turnSettings(), message_id: id, instruction }, null)
  }

  // Make another of a card's pictures the real one (free: nothing is generated)
  async function showMediaVersion(
    msg: UiMessage,
    { mediaId, index }: { mediaId: string; index: number },
  ): Promise<void> {
    const id = savedId(msg)
    if (sending.value || id === null) return
    try {
      replaceMessage(await showChatMediaVersion(id, mediaId, index))
    } catch (e) {
      fail(e)
    }
  }

  // Flip a reply's text to another wording (free: nothing is generated)
  async function showTextVersion(msg: UiMessage, index: number): Promise<void> {
    const id = savedId(msg)
    if (sending.value || id === null) return
    try {
      replaceMessage(await showChatTextVersion(id, index))
    } catch (e) {
      fail(e)
    }
  }

  // The message as it is now, with another set of cards
  function withMedia(messageId: number, media: MediaCard[]): void {
    const current = messages.value[messageIndex(messageId)]
    if (current) replaceMessage({ ...current, id: messageId, media, siblings: current.siblings })
  }

  async function pinMedia(msg: UiMessage, { mediaId, pinned }: { mediaId: string; pinned: boolean }): Promise<void> {
    const id = savedId(msg)
    if (id === null) return
    try {
      withMedia(id, (await pinChatMedia(id, mediaId, pinned)).media)
    } catch (e) {
      fail(e)
    }
  }

  // Star/un-star a generation (bookmark for the Favourites gallery). `msg` may
  // be a real message (in-thread) or a library row carrying { message_id }.
  async function favouriteMedia(
    msg: MessageRef,
    { mediaId, favourite }: { mediaId: string; favourite: boolean },
  ): Promise<void> {
    const messageId = 'message_id' in msg ? msg.message_id : savedId(msg)
    if (messageId === null) return
    try {
      withMedia(messageId, (await favouriteChatMedia(messageId, mediaId, favourite)).media)
      // Reflect it in the open favourites gallery without a full reload
      const card = favourites.value.find(i => i.id === mediaId)
      if (card) card.favourite = favourite
      if (!favourite) favourites.value = favourites.value.filter(i => i.id !== mediaId)
    } catch (e) {
      fail(e)
    }
  }

  async function loadFavourites(): Promise<void> {
    try {
      const { items } = await fetchChatLibrary()
      favourites.value = items.filter(i => i.favourite && i.file)
    } catch {
      favourites.value = []
    }
  }

  return { regenerateMedia, reword, showMediaVersion, showTextVersion, pinMedia, favouriteMedia, loadFavourites }
}
