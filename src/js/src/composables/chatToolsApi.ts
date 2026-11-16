import type { components } from '../api/schema'
import { api } from './useApi'

// Composer helpers: price a generation, rewrite a prompt, list voices, stop a running reply.
type Schemas = components['schemas']

export type Voice = Schemas['Voice']

// Pollo's credit estimate for a generation ({ estimate: { credits, full_credits } | null })
export const estimateChatCost = (data: Schemas['EstimateRequest']) => api.post('/api/chat/estimate', data)
export const enhanceChatPrompt = (data: Schemas['EnhancePrompt']) => api.post('/api/chat/enhance-prompt', data)
// Pollo's official TTS voices: { voices: [{ voiceId, voiceName, language, gender, ... }], total }
export const fetchAudioVoices = (pageSize = 50) => api.get(`/api/chat/audio/voices?page_size=${String(pageSize)}`)
// Stop a running reply; `cancelled` says whether it was still running
export const cancelChatMessage = (messageId: number) => api.post(`/api/chat/messages/${String(messageId)}/cancel`)
