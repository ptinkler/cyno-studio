import type { components } from '../api/schema'
import { api } from './useApi'

// Conversations and their messages: the chat list, one open chat, branching, spend and deletes.
// Types come from the backend's models (`make gen-api`).
type Schemas = components['schemas']

export type Conversation = Schemas['Conversation']
export type ConversationSummary = Schemas['ConversationSummary']
export type ConversationView = Schemas['ConversationView']
export type ShownMessage = Schemas['ShownMessage']
export type ConversationMessage = Schemas['ConversationMessage']
export type MediaCard = Schemas['MediaCard']
export type MediaVersion = Schemas['MediaVersion']

const enc = encodeURIComponent
const id = (value: number): string => String(value)

// Pinned + most recent ({ conversations, more }); with `q`, chats whose title or messages match (each with a `snippet`)
export const fetchConversations = (q = '') =>
  q ? api.get(`/api/chat/conversations?q=${enc(q)}`) : api.get('/api/chat/conversations')
// What a chat has cost: { usd, credits, inherited_usd, inherited_credits }
export const fetchConversationSpend = (convId: string) => api.get(`/api/chat/conversations/${enc(convId)}/spend`)
export const fetchSpendBreakdown = (days: number) => api.get(`/api/chat/spend/breakdown?days=${id(days)}`)
export const fetchConversation = (convId: string) => api.get(`/api/chat/conversations/${enc(convId)}`)
// Newest image file per conversation id, for gallery cover thumbnails: { thumbs: {id: file} }
export const fetchConversationThumbs = (ids: readonly string[]) =>
  api.get(`/api/chat/conversations/thumbs?ids=${enc(ids.join(','))}`)
export const createConversation = (data: Schemas['ConversationCreate'] = {}) =>
  api.post('/api/chat/conversations', data)
export const patchConversation = (convId: string, data: Schemas['ConversationUpdate']) =>
  api.patch(`/api/chat/conversations/${enc(convId)}`, data)
export const deleteConversation = (convId: string, { deleteMedia = true }: { deleteMedia?: boolean } = {}) =>
  api.delete(`/api/chat/conversations/${enc(convId)}?delete_media=${String(deleteMedia)}`)
// What deleting the chat also removes: { characters } made in it and never saved
export const fetchConversationDeleteInfo = (convId: string) =>
  api.get(`/api/chat/conversations/${enc(convId)}/delete-info`)
export const fetchChatMessage = (messageId: number) => api.get(`/api/chat/messages/${id(messageId)}`)
// Show the branch through this message (edits/retries are kept as sibling branches)
export const switchChatBranch = (convId: string, messageId: number) =>
  api.post(`/api/chat/conversations/${enc(convId)}/branch`, { message_id: messageId })
// New chat from a prompt: the messages up to it, it and its reply — nothing after
export const forkConversation = (convId: string, messageId: number) =>
  api.post(`/api/chat/conversations/${enc(convId)}/fork`, { message_id: messageId })
// Delete a prompt's turn (all versions of it and its replies); generated media moves to the library
export const deleteChatExchange = (messageId: number, { deleteMedia = false }: { deleteMedia?: boolean } = {}) =>
  api.delete(`/api/chat/messages/${id(messageId)}?delete_media=${String(deleteMedia)}`)
// What that would also remove: { other_versions, other_messages, media }
export const fetchDeleteInfo = (messageId: number) => api.get(`/api/chat/messages/${id(messageId)}/delete-info`)
