import type { components } from '../api/schema'
import { api } from './useApi'

// Actions on a message's cards and wordings. Each answers with the updated message.
type Schemas = components['schemas']

const enc = encodeURIComponent
const id = (value: number): string => String(value)

// Make this image/video again. `prompt` overrides the one it was made with,
// `edit` sends the picture itself back as the reference (change this image),
// and `replace` swaps it in place, keeping the old one as an earlier version.
export const regenerateChatMedia = (messageId: number, mediaId: string, options: Schemas['RegenerateMedia'] = {}) =>
  api.post(`/api/chat/messages/${id(messageId)}/media/${enc(mediaId)}/regenerate`, options)
// Show one of a reply's wordings (0 = first); its pictures are untouched
export const showChatTextVersion = (messageId: number, index: number) =>
  api.post(`/api/chat/messages/${id(messageId)}/text-version`, { index })
// Make one of a card's pictures the real one (0 = first): the chat uses it from then on
export const showChatMediaVersion = (messageId: number, mediaId: string, index: number) =>
  api.post(`/api/chat/messages/${id(messageId)}/media/${enc(mediaId)}/version`, { index })
// Pinned images go to the image model as references with every new image on this branch
export const pinChatMedia = (messageId: number, mediaId: string, pinned: boolean) =>
  api.post(`/api/chat/messages/${id(messageId)}/media/${enc(mediaId)}/pin`, { pinned })
// Favourite (★) a generation: a bookmark that surfaces it in the Favourites gallery (images + videos)
export const favouriteChatMedia = (messageId: number, mediaId: string, favourite: boolean) =>
  api.post(`/api/chat/messages/${id(messageId)}/media/${enc(mediaId)}/favourite`, { favourite })
