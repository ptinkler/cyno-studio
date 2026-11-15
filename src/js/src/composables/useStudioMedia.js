import {
  fetchChatLibrary,
  favouriteChatMedia,
  pinChatMedia,
  regenerateChatMedia,
  rewordChatMessage,
  showChatMediaVersion,
  showChatTextVersion,
} from './useChat'

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
}) {
  // Cards whose regenerate request is in flight: a double click on "Try
  // again" would otherwise start (and pay for) two generations
  const regenerating = new Set()
  async function regenerateMedia(msg, { mediaId, model, prompt, edit, replace }) {
    if (regenerating.has(mediaId)) return
    regenerating.add(mediaId)
    if (!model) {
      const kind = (msg.media || []).find(i => i.id === mediaId)?.kind
      if (kind && selected[kind]) model = selected[kind]
    }
    try {
      replaceMessage(await regenerateChatMedia(msg.id, mediaId, { model, prompt, edit, replace }))
      polling.ensure()
    } catch (e) {
      showToast(e.message, 'error')
    } finally {
      regenerating.delete(mediaId)
    }
  }
  // Write a reply's words again, keeping the pictures it already made.
  // With an instruction the model edits its words; without, it redoes them.
  // The old words stay as a version (the ‹ › on the text).
  async function reword(msg, instruction = '') {
    if (sending.value || messageIndex(msg.id) === -1) return
    await runTurn(
      rewordChatMessage,
      active.value,
      { ...turnSettings(), message_id: msg.id, instruction: instruction || '' },
      null,
    )
  }
  // Make another of a card's pictures the real one (free: nothing is generated)
  async function showMediaVersion(msg, { mediaId, index }) {
    if (sending.value) return
    try {
      replaceMessage(await showChatMediaVersion(msg.id, mediaId, index))
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  // Flip a reply's text to another wording (free: nothing is generated)
  async function showTextVersion(msg, index) {
    if (sending.value) return
    try {
      replaceMessage(await showChatTextVersion(msg.id, index))
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  async function pinMedia(msg, { mediaId, pinned: on }) {
    try {
      const { media } = await pinChatMedia(msg.id, mediaId, on)
      const current = messages.value[messageIndex(msg.id)]
      if (current) replaceMessage({ ...current, media })
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  // Star/un-star a generation (bookmark for the Favourites gallery). `msg` may
  // be a real message (in-thread) or a library row carrying { message_id }.
  async function favouriteMedia(msg, { mediaId, favourite: on }) {
    const messageId = msg.id ?? msg.message_id
    try {
      const { media } = await favouriteChatMedia(messageId, mediaId, on)
      const current = messages.value[messageIndex(messageId)]
      if (current) replaceMessage({ ...current, media })
      // Reflect it in the open favourites gallery without a full reload
      const f = favourites.value.find(i => i.id === mediaId)
      if (f) f.favourite = on
      if (!on) favourites.value = favourites.value.filter(i => i.id !== mediaId)
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  async function loadFavourites() {
    try {
      const { items } = await fetchChatLibrary()
      favourites.value = (items || []).filter(i => i.favourite && i.file)
    } catch {
      favourites.value = []
    }
  }

  return {
    regenerateMedia,
    reword,
    showMediaVersion,
    showTextVersion,
    pinMedia,
    favouriteMedia,
    loadFavourites,
  }
}
