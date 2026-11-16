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
// in web/chat/turn.py, and the "images" option / Ref mode on the Generate page.

/** A chat image model (catalogue entry) that can use characters. */
export const chatImageModelTakesCharacters = info =>
  !!info && (!!info.conversational || !!info.input_modalities?.includes('image'))

/** A Generate-page model (MODEL_INFO entry) that can use characters, given whether Ref mode is on. */
export function generateModelTakesCharacters(info, refModeOn = false) {
  if (!info) return false
  if (info.type === 'image') return (info.options || []).includes('images')
  return info.type === 'ref' || (!!info.ref_mode && refModeOn)
}
