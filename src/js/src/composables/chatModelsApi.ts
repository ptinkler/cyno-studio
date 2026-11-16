import type { components } from '../api/schema'
import { api } from './useApi'

// The model catalogue: every provider's models by kind, shaped by the backend (`chat/model_schemas.py`).
// A row the backend could not parse is left out of the list, never half-typed.
type Schemas = components['schemas']

export type ModelCatalogue = Schemas['ModelCatalogue']
export type TextModel = Schemas['TextModel']
export type ImageModel = Schemas['ImageModel']
export type VideoModel = Schemas['VideoModel']
export type AudioModel = Schemas['AudioModel']
export type ModelKind = 'text' | 'image' | 'video' | 'audio'
export type Model = TextModel | ImageModel | VideoModel | AudioModel

export const fetchChatModels = (refresh = false) =>
  refresh ? api.get('/api/chat/models?refresh=true') : api.get('/api/chat/models')

// Which kind a catalogue row is, from the fields every row of that kind has (the backend's models guarantee them)
export const isTextModel = (m: Model): m is TextModel => 'supports_tools' in m
export const isImageModel = (m: Model): m is ImageModel => 'conversational' in m
export const isVideoModel = (m: Model): m is VideoModel => 'frame_images' in m
