import type { components } from '../api/schema'
import { api } from './useApi'

// A chat's files and the views over them: attachments, served media URLs, the library of generated media,
// the queue of running generations, and the provider request log.
type Schemas = components['schemas']

export type LibraryCard = Schemas['LibraryCard']
export type Generation = Schemas['Generation']
export type RequestLogEntry = Schemas['RequestLogEntry']

const enc = encodeURIComponent
const num = (value: number): string => String(value)

export const uploadChatAttachment = (convId: string, file: Blob) =>
  api.upload(`/api/chat/conversations/${enc(convId)}/attachments`, file)

// A source video (e.g. Recast / motion models)
export const uploadChatVideoAttachment = (convId: string, file: Blob) =>
  api.upload(`/api/chat/conversations/${enc(convId)}/attachments/video`, file)

// A lip-sync audio track
export const uploadChatAudioAttachment = (convId: string, file: Blob) =>
  api.upload(`/api/chat/conversations/${enc(convId)}/attachments/audio`, file)

// Drop an uploaded-but-unsent attachment's file (the server keeps any still in use)
export const discardChatAttachment = (convId: string, file: string) =>
  api.delete(`/api/chat/conversations/${enc(convId)}/attachments/${enc(file)}`)

export const chatMediaUrl = (convId: string, file: string) => `/api/chat/media/${enc(convId)}/${enc(file)}`
// A chat image scaled down for showing in the chat (the full file is for the lightbox)
export const chatMediaPreviewUrl = (convId: string, file: string) => `${chatMediaUrl(convId, file)}/preview`

// In-flight (and tracked) generations across every thread — powers the queue dock.
// `known` = message ids to resolve even once they've left the pending set.
export const fetchActiveGenerations = (known: readonly number[] = []) =>
  api.post('/api/chat/generations/active', { known: [...known] })

// Every generated image/video across all threads, newest first
export const fetchChatLibrary = () => api.get('/api/chat/library')
export const deleteLibraryItem = (mediaId: string) => api.delete(`/api/chat/library/${enc(mediaId)}`)

// The latest provider requests, newest first
export const fetchRequestLog = (limit = 100) => api.get(`/api/chat/request-log?limit=${num(limit)}`)
