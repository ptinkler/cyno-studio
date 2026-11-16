import { apiGet, apiPost, apiDelete, apiUpload } from './useApi'
import { useAuth } from './useAuth'

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
// Pollo's official TTS voices: { voices: [{voiceId, voiceName, language, gender, ...}], total }
export const fetchAudioVoices = (params = '') => apiGet(`/api/chat/audio/voices${params}`)
export const estimateChatCost = data => apiPost('/api/chat/estimate', data)
export const enhanceChatPrompt = data => apiPost('/api/chat/enhance-prompt', data)
export const cancelChatMessage = id => apiPost(`/api/chat/messages/${id}/cancel`)
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

/**
 * POST a turn and feed each SSE event to `onEvent`. Resolves when the
 * stream ends. Aborting `signal` only stops listening — the server keeps
 * the turn running (use cancelChatMessage to actually stop it).
 */
export async function streamTurn(path, body, onEvent, signal) {
  const res = await fetch(path, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (res.status === 401) {
    useAuth().promptLogin()
    throw new Error('API key required')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `API error: ${res.status}`)
  }
  await readSSE(res.body, onEvent)
}

export async function readSSE(stream, onEvent) {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const data = block
        .split('\n')
        .filter(l => l.startsWith('data: '))
        .map(l => l.slice(6))
        .join('\n')
      if (data) onEvent(JSON.parse(data))
    }
  }
}

export const sendChatMessage = (convId, body, onEvent, signal) =>
  streamTurn(`/api/chat/conversations/${enc(convId)}/messages`, body, onEvent, signal)

export const retryChatMessage = (convId, body, onEvent, signal) =>
  streamTurn(`/api/chat/conversations/${enc(convId)}/retry`, body, onEvent, signal)

export const editChatMessage = (convId, body, onEvent, signal) =>
  streamTurn(`/api/chat/conversations/${enc(convId)}/edit`, body, onEvent, signal)

// Write a reply's words again, keeping the pictures it already made.
// Body: turn settings + message_id, and `instruction` to edit the words (empty = redo them)
export const rewordChatMessage = (convId, body, onEvent, signal) =>
  streamTurn(`/api/chat/conversations/${enc(convId)}/reword`, body, onEvent, signal)
