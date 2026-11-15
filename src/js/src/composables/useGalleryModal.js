import { ref, computed } from 'vue'
import { chatMediaUrl, chatMediaPreviewUrl } from './useChat'

// The generation shown in the big-view card modal, opened from a thread's gallery (with manage actions —
// regenerate, delete) or from Favourites (view only), and what the modal's buttons do.
export function useGalleryModal({ studio, genQueue, openThreadView }) {
  const {
    messages,
    favourites,
    favouriteMedia,
    regenerateMedia,
    applyGenerationSettings,
    send,
    useImage,
    deleteExchange,
    newCharacter,
  } = studio
  const galleryItem = ref(null)
  const galleryManage = ref(false)
  function openGeneration(item) {
    galleryItem.value = item
    galleryManage.value = true
  }
  async function onGalleryFavourite(item) {
    await favouriteMedia({ id: item.message_id }, { mediaId: item.id, favourite: !item.favourite })
  }

  // Modal "Retry" / "Regenerate". A failed item retries in place (backend only
  // allows regenerating errored media); a successful one re-rolls as a fresh
  // generation with the same settings (apply + send), leaving the original.
  function regenerateFromModal(item) {
    if (item.status === 'error') {
      const msg = messages.value.find(m => m.id === item.message_id)
      if (msg) regenerateMedia(msg, { mediaId: item.id })
    } else {
      applyGenerationSettings(item)
      send()
    }
    genQueue.refresh()
    galleryItem.value = null
  }
  // "Use settings": fill the composer from this generation (model, mode, options,
  // prompt), close the modal, and leave it for the user to tweak and Generate.
  function useSettingsFromModal(item) {
    applyGenerationSettings(item)
    galleryItem.value = null
  }
  // "Picture/Video from this": attach the image, switch mode, and close the modal.
  function useImageFromModal(e) {
    galleryItem.value = null
    useImage(e)
  }
  async function deleteFromModal(item) {
    const msg = messages.value.find(m => m.id === item.message_id)
    galleryItem.value = null
    if (msg) await deleteExchange(msg)
  }

  // Favourites: the cross-thread gallery of starred generations.
  const favItems = computed(() =>
    (favourites.value || []).map(i => ({
      ...i,
      url: chatMediaUrl(i.conversation_id, i.file),
      preview:
        i.kind === 'image' ? chatMediaPreviewUrl(i.conversation_id, i.file) : chatMediaUrl(i.conversation_id, i.file),
    })),
  )
  function openFavourite(item) {
    galleryItem.value = item
    galleryManage.value = false
  }
  async function onFavUnstar(item) {
    await favouriteMedia({ id: item.message_id }, { mediaId: item.id, favourite: false })
    if (galleryItem.value?.id === item.id) galleryItem.value = null
  }
  function openThreadFromModal(convId) {
    galleryItem.value = null
    openThreadView(convId)
  }
  // "Make a character from this picture" — the lightbox offered this but nothing
  // was listening, so the button did nothing.
  function makeCharacterFromModal(item) {
    galleryItem.value = null
    newCharacter([item.file])
  }

  return {
    galleryItem,
    galleryManage,
    favItems,
    openGeneration,
    onGalleryFavourite,
    openFavourite,
    onFavUnstar,
    regenerateFromModal,
    useSettingsFromModal,
    useImageFromModal,
    deleteFromModal,
    openThreadFromModal,
    makeCharacterFromModal,
  }
}
