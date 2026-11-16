import type { components } from '../api/schema'
import { api } from './useApi'

// Characters (see web/characters.py): a name, description and a few reference images, attachable to chats
// and generations. Ad-hoc ones belong to the chat they were made in until promoted to saved.
type Schemas = components['schemas']

export type Character = Schemas['CharacterInfo']
export type ListedCharacter = Schemas['ListedCharacter']

const enc = encodeURIComponent
const id = (value: number): string => String(value)

export const fetchCharacters = async ({
  conversationId = null,
  includeAdhoc = false,
}: { conversationId?: string | null; includeAdhoc?: boolean } = {}) => {
  const params = new URLSearchParams()
  if (conversationId) params.set('conversation_id', conversationId)
  if (includeAdhoc) params.set('include_adhoc', 'true')
  const qs = params.toString()
  const { characters } = await (qs ? api.get(`/api/characters?${qs}`) : api.get('/api/characters'))
  return characters
}
export const createCharacter = (data: Schemas['CharacterIn']) => api.post('/api/characters', data)
export const updateCharacter = (characterId: number, data: Schemas['CharacterUpdate']) =>
  api.patch(`/api/characters/${id(characterId)}`, data)
export const deleteCharacter = (characterId: number) => api.delete(`/api/characters/${id(characterId)}`)
export const promoteCharacter = (characterId: number) => api.post(`/api/characters/${id(characterId)}/promote`)
export const uploadCharacterImage = (characterId: number, file: Blob) =>
  api.upload(`/api/characters/${id(characterId)}/images`, file)
export const copyChatImageToCharacter = (characterId: number, conversationId: string, file: string) =>
  api.post(`/api/characters/${id(characterId)}/images/from-chat`, { conversation_id: conversationId, file })

export const characterImageUrl = (characterId: number, file: string) =>
  `/api/characters/${id(characterId)}/images/${enc(file)}`
/** The character's main (first) image, or null. */
export const characterAvatar = (character: Pick<Character, 'id' | 'images'> | null | undefined) => {
  const [main] = character?.images ?? []
  return character && main !== undefined ? characterImageUrl(character.id, main) : null
}
