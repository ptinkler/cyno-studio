import type { MediaCard } from '../composables/chatConversationsApi'
import { chatMediaUrl } from '../composables/chatFilesApi'
import type { GenerationItem } from '../composables/studioTypes'

// Small rules about the media on a chat message, shared by its attachments and its generated cards.

// What the big view (GenerationModal) needs: everything the card knows, plus where it lives, so its actions
// can act on the right message. A prompt the server hasn't saved yet has no message id to act on.
export const bigView = (item: MediaCard, message: { id: number | string }, convId: string): GenerationItem => ({
  ...item,
  url: chatMediaUrl(convId, item.file ?? ''),
  message_id: typeof message.id === 'number' ? message.id : null,
  conversation_id: convId,
})
