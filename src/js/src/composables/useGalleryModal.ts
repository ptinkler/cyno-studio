import { ref, computed } from 'vue'
import type { Studio } from './useStudio'
import { chatMediaUrl, chatMediaPreviewUrl } from './chatFilesApi'
import type { GenerationItem } from './studioTypes'

/** What the "use this image" buttons hand over: the file, the mode to switch to and the chat it lives in. */
type ImagePick = Parameters<Studio['useImage']>[0]

// The generation shown in the big-view card modal, opened from a thread's gallery (with manage actions —
// regenerate, delete) or from Favourites (view only), and what the modal's buttons do.
export function useGalleryModal({
  studio,
  genQueue,
  openThreadView,
}: {
  studio: Pick<
    Studio,
    | 'messages'
    | 'favourites'
    | 'favouriteMedia'
    | 'regenerateMedia'
    | 'applyGenerationSettings'
    | 'send'
    | 'useImage'
    | 'deleteExchange'
    | 'newCharacter'
  >
  genQueue: { refresh: () => Promise<void> }
  openThreadView: (id: string) => void
}) {
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
  const galleryItem = ref<GenerationItem | null>(null)
  const galleryManage = ref(false)

  const messageOf = (item: GenerationItem) => messages.value.find(m => m.id === item.message_id)

  function openGeneration(item: GenerationItem): void {
    galleryItem.value = item
    galleryManage.value = true
  }

  async function onGalleryFavourite(item: GenerationItem): Promise<void> {
    if (item.message_id === null) return
    await favouriteMedia({ message_id: item.message_id }, { mediaId: item.id, favourite: !item.favourite })
  }

  // Modal "Retry" / "Regenerate". A failed item retries in place (backend only
  // allows regenerating errored media); a successful one re-rolls as a fresh
  // generation with the same settings (apply + send), leaving the original.
  function regenerateFromModal(item: GenerationItem): void {
    if (item.status === 'error') {
      const msg = messageOf(item)
      if (msg) void regenerateMedia(msg, { mediaId: item.id })
    } else {
      applyGenerationSettings(item)
      void send()
    }
    void genQueue.refresh()
    galleryItem.value = null
  }

  // "Use settings": fill the composer from this generation (model, mode, options,
  // prompt), close the modal, and leave it for the user to tweak and Generate.
  function useSettingsFromModal(item: GenerationItem): void {
    applyGenerationSettings(item)
    galleryItem.value = null
  }

  // "Picture/Video from this": attach the image, switch mode, and close the modal.
  function useImageFromModal(pick: ImagePick): void {
    galleryItem.value = null
    useImage(pick)
  }

  async function deleteFromModal(item: GenerationItem): Promise<void> {
    const msg = messageOf(item)
    galleryItem.value = null
    if (msg) await deleteExchange(msg)
  }

  // Favourites: the cross-thread gallery of starred generations.
  const favItems = computed(() =>
    favourites.value.flatMap(card =>
      card.file
        ? [
            {
              ...card,
              url: chatMediaUrl(card.conversation_id, card.file),
              preview:
                card.kind === 'image'
                  ? chatMediaPreviewUrl(card.conversation_id, card.file)
                  : chatMediaUrl(card.conversation_id, card.file),
            },
          ]
        : [],
    ),
  )

  function openFavourite(item: GenerationItem): void {
    galleryItem.value = item
    galleryManage.value = false
  }

  async function onFavUnstar(item: GenerationItem): Promise<void> {
    if (item.message_id === null) return
    await favouriteMedia({ message_id: item.message_id }, { mediaId: item.id, favourite: false })
    if (galleryItem.value?.id === item.id) galleryItem.value = null
  }

  function openThreadFromModal(convId: string): void {
    galleryItem.value = null
    openThreadView(convId)
  }

  // "Make a character from this picture": the editor starts with it as the first image
  function makeCharacterFromModal(item: GenerationItem): void {
    galleryItem.value = null
    if (!item.file) return
    void newCharacter([
      {
        kind: 'chat',
        conversationId: item.conversation_id,
        file: item.file,
        preview: chatMediaPreviewUrl(item.conversation_id, item.file),
      },
    ])
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
