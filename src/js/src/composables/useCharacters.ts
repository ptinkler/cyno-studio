import type { ImageModel } from './chatModelsApi'

// Characters (see web/characters.py): the API wrappers are typed in charactersApi.ts and re-exported here.
export {
  fetchCharacters,
  createCharacter,
  updateCharacter,
  deleteCharacter,
  promoteCharacter,
  uploadCharacterImage,
  copyChatImageToCharacter,
  characterImageUrl,
  characterAvatar,
} from './charactersApi'

// Characters need a model that takes reference images (their whole point is
// keeping a look consistent). Mirrors the server's checks: _characters_usable
// in web/chat/turn.py.

/** A chat image model (catalogue entry) that can use characters. */
export const chatImageModelTakesCharacters = (
  info: Pick<ImageModel, 'conversational' | 'input_modalities'> | null | undefined,
): boolean => !!info && (info.conversational || info.input_modalities.includes('image'))
