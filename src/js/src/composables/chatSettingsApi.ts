import type { components } from '../api/schema'
import { api } from './useApi'

// The settings side of the chat API: provider status and balances, global defaults, instruction
// snippets and groups, and spaces. Types come from the backend's models (`make gen-api`).
type Schemas = components['schemas']

export type Instruction = Schemas['Instruction']
export type InstructionGroup = Schemas['InstructionGroup']
export type Space = Schemas['Space']
export type ChatSettings = Schemas['ChatSettings']
export type PolloBalance = Schemas['PolloBalance']

const id = (value: number): string => String(value)

// Which providers have a key, and what's left to spend with each
export const fetchChatStatus = () => api.get('/api/chat/status')
export const fetchOpenRouterCredits = () => api.get('/api/chat/credits')
export const fetchVeniceBalance = () => api.get('/api/chat/venice-balance')
// Pollo credits remaining.
export const fetchBalance = () => api.get('/api/chat/pollo-balance')

// Custom instructions: snippets, and groups that bundle them (attachable per chat)
export const fetchInstructions = () => api.get('/api/chat/instructions')
export const createInstruction = (data: Schemas['InstructionIn']) => api.post('/api/chat/instructions', data)
export const updateInstruction = (instructionId: number, data: Schemas['InstructionIn']) =>
  api.put(`/api/chat/instructions/${id(instructionId)}`, data)
export const deleteInstruction = (instructionId: number) => api.delete(`/api/chat/instructions/${id(instructionId)}`)
export const createInstructionGroup = (data: Schemas['InstructionGroupIn']) =>
  api.post('/api/chat/instruction-groups', data)
export const updateInstructionGroup = (groupId: number, data: Schemas['InstructionGroupIn']) =>
  api.put(`/api/chat/instruction-groups/${id(groupId)}`, data)
export const deleteInstructionGroup = (groupId: number) => api.delete(`/api/chat/instruction-groups/${id(groupId)}`)

// Spaces: chat-only groupings with their own default characters/instructions
export const fetchSpaces = () => api.get('/api/chat/spaces')
export const createSpace = (data: Schemas['SpaceIn']) => api.post('/api/chat/spaces', data)
export const updateSpace = (spaceId: number, data: Schemas['SpaceIn']) =>
  api.put(`/api/chat/spaces/${id(spaceId)}`, data)
export const deleteSpace = (spaceId: number) => api.delete(`/api/chat/spaces/${id(spaceId)}`)

// Global defaults bucket (characters + instructions added to every new chat)
export const fetchSettings = () => api.get('/api/chat/settings')
export const updateSettings = (data: Schemas['DefaultsIn']) => api.put('/api/chat/settings', data)
// The text model that names new chats ('' / null = the chat's own model)
export const setTitleModel = (titleModel: string | null) =>
  api.put('/api/chat/settings/title-model', { title_model: titleModel })
// Starred models per picker kind
export const setModelFavourites = (modelFavourites: Schemas['ModelFavouritesIn']['model_favourites']) =>
  api.put('/api/chat/settings/model-favourites', { model_favourites: modelFavourites })
