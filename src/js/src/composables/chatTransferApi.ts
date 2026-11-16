import type { components } from '../api/schema'
import { api } from './useApi'

// Moving chats in and out: ChatGPT exports (and this app's own) in the server's imports folder, imported in
// the background, and chats downloaded as one zip.
type Schemas = components['schemas']

export type ImportJob = Schemas['ImportJob']

const enc = encodeURIComponent

// The exports in the server's imports folder, and the last import's progress: { folder, files, job }
export const fetchChatGptImport = () => api.get('/api/chat/import/chatgpt')
// Start importing one of them in the background (only what's new since the last import)
export const startChatGptImport = (file: string) => api.post('/api/chat/import/chatgpt', { file })
// Uploading an export into that folder, in chunks: start → { id, chunk_size }, then each chunk at its
// offset → { received }, and the last also → { file }
export const startChatGptUpload = (name: string, size: number) =>
  api.post('/api/chat/import/chatgpt/uploads', { name, size })
export function sendChatGptUploadChunk(uploadId: string, offset: number, blob: Blob) {
  const form = new FormData()
  form.append('offset', String(offset))
  form.append('chunk', blob, 'chunk')
  return api.postForm(`/api/chat/import/chatgpt/uploads/${enc(uploadId)}`, form)
}
export const cancelChatGptUpload = (uploadId: string) => api.delete(`/api/chat/import/chatgpt/uploads/${enc(uploadId)}`)

// Chats as a zip the Import dialog (here or on another server) reads back; no ids = every chat
export const chatExportUrl = (ids: readonly string[] = []) =>
  `/api/chat/export${ids.length ? `?ids=${enc(ids.join(','))}` : ''}`
// Every chat, for picking which to export: { chats: [{ id, title, kind, space, updated_at }] }
export const fetchExportableChats = () => api.get('/api/chat/export/chats')
