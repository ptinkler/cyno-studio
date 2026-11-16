import { apiGet, apiPost, apiDelete, apiUpload } from './useApi'

const enc = encodeURIComponent

// Status, balances, defaults, instructions and spaces are typed in chatSettingsApi.ts; re-exported so
// everything chat-related is still imported from here.
export {
  fetchChatStatus,
  fetchOpenRouterCredits,
  fetchVeniceBalance,
  fetchInstructions,
  createInstruction,
  updateInstruction,
  deleteInstruction,
  createInstructionGroup,
  updateInstructionGroup,
  deleteInstructionGroup,
  fetchSpaces,
  createSpace,
  updateSpace,
  deleteSpace,
  fetchSettings,
  updateSettings,
  setTitleModel,
} from './chatSettingsApi'

// Conversations and their messages are typed in chatConversationsApi.ts
export {
  fetchConversations,
  fetchConversationSpend,
  fetchSpendBreakdown,
  fetchConversation,
  fetchConversationThumbs,
  createConversation,
  patchConversation,
  deleteConversation,
  fetchChatMessage,
  switchChatBranch,
  forkConversation,
  deleteChatExchange,
  fetchDeleteInfo,
} from './chatConversationsApi'

// Media-card actions: pin, favourite, regenerate, versions
export {
  regenerateChatMedia,
  showChatTextVersion,
  showChatMediaVersion,
  pinChatMedia,
  favouriteChatMedia,
} from './chatMediaApi'

export const fetchChatModels = (refresh = false) => apiGet(`/api/chat/models${refresh ? '?refresh=true' : ''}`)
// In-flight (and tracked) generations across every thread — powers the queue dock.
// `known` = message ids to resolve even once they've left the pending set.
export const fetchActiveGenerations = (known = []) => apiPost('/api/chat/generations/active', { known })
// Every generated image/video across all threads, newest first (see /api/chat/library)
export const fetchChatLibrary = () => apiGet('/api/chat/library')

// ChatGPT exports in the server's imports folder, and the last import's progress: { folder, files, job }
export const fetchChatGptImport = () => apiGet('/api/chat/import/chatgpt')
// Start importing one of them in the background (only what's new since the last import)
export const startChatGptImport = file => apiPost('/api/chat/import/chatgpt', { file })
// Uploading an export into that folder, in chunks: start → { id, chunk_size }, then each chunk at its
// offset → { received }, and the last also → { file }
export const startChatGptUpload = (name, size) => apiPost('/api/chat/import/chatgpt/uploads', { name, size })
export function sendChatGptUploadChunk(id, offset, blob) {
  const form = new FormData()
  form.append('offset', String(offset))
  form.append('chunk', blob, 'chunk')
  return apiPost(`/api/chat/import/chatgpt/uploads/${enc(id)}`, form)
}
// Chats as a zip the Import dialog (here or on another server) reads back; no ids = every chat
export const chatExportUrl = (ids = []) => `/api/chat/export${ids.length ? `?ids=${enc(ids.join(','))}` : ''}`
// Every chat, for picking which to export: { chats: [{ id, title, kind, space, updated_at }] }
export const fetchExportableChats = () => apiGet('/api/chat/export/chats')
export const cancelChatGptUpload = id => apiDelete(`/api/chat/import/chatgpt/uploads/${enc(id)}`)
export const uploadChatAttachment = (convId, file) =>
  apiUpload(`/api/chat/conversations/${enc(convId)}/attachments`, file)

// A source video (e.g. Recast / motion models)
export const uploadChatVideoAttachment = (convId, file) =>
  apiUpload(`/api/chat/conversations/${enc(convId)}/attachments/video`, file)

// A lip-sync audio track
export const uploadChatAudioAttachment = (convId, file) =>
  apiUpload(`/api/chat/conversations/${enc(convId)}/attachments/audio`, file)

// Drop an uploaded-but-unsent attachment's file (the server keeps any still in use)
export const discardChatAttachment = (convId, file) =>
  apiDelete(`/api/chat/conversations/${enc(convId)}/attachments/${enc(file)}`)

export const chatMediaUrl = (convId, file) => `/api/chat/media/${enc(convId)}/${enc(file)}`
// A chat image scaled down for showing in the chat (the full file is for the lightbox)
export const chatMediaPreviewUrl = (convId, file) => `${chatMediaUrl(convId, file)}/preview`

// Composer helpers: estimate, enhance, voices, cancel
export { fetchAudioVoices, estimateChatCost, enhanceChatPrompt, cancelChatMessage } from './chatToolsApi'

// The streamed turns (send, retry, edit, reword) and their event types are in chatStreamApi.ts
export { readSSE, sendChatMessage, retryChatMessage, editChatMessage, rewordChatMessage } from './chatStreamApi'
