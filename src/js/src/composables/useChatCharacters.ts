import { computed, reactive, ref, watch } from 'vue'
import type { Ref } from 'vue'
import type { Character } from './charactersApi'
import type { ImageModel, TextModel, VideoModel } from './chatModelsApi'
import type { Mode } from './composerPrefs'
import type { ComposerSettings } from './useComposerSettings'
import { patchConversation } from './useChat'
import { chatImageModelTakesCharacters, fetchCharacters } from './useCharacters'
import type { ShowToast } from './useToast'
import { messageOf } from '../utils/errors'

// Replace the item with the same id in a list, or add it
export function upsert<T extends { id: unknown }>(list: T[], item: T): void {
  const i = list.findIndex(x => x.id === item.id)
  if (i === -1) list.push(item)
  else list.splice(i, 1, item)
}

/** A picture to start a new character from: a file already in a chat. */
export interface CharacterSeed {
  kind: 'chat'
  conversationId: string
  file: string
  preview: string
}

interface BlockerContext {
  mode: Mode
  selected: { image: string }
  textInfo: TextModel | undefined
  imageInfo: ImageModel | undefined
  videoInfo: VideoModel | undefined
}

// Why the current mode and models can't use characters, or null if they can
// (mirrors Turn._characters_usable in web/chat/turn.py). Unknown models (catalogue still
// loading) count as able, like on the server.
function videoBlocker(videoInfo: VideoModel | undefined): string | null {
  // Only video models that take reference images (Venice refs→video, motion control)
  return videoInfo && (videoInfo.reference_images || videoInfo.family === 'motion')
    ? null
    : "This video model doesn't take reference images, so it can't use characters."
}

function imageBlocker({ mode, selected, textInfo, imageInfo }: BlockerContext): string | null {
  if (!selected.image) return 'Pick an image model to use characters.'
  if (imageInfo && !chatImageModelTakesCharacters(imageInfo)) {
    return `${imageInfo.name} can't take reference images, so it can't use characters.`
  }
  if (mode === 'auto' && textInfo && !textInfo.supports_tools) {
    return `${textInfo.name} can't call tools, so Auto mode can't use characters.`
  }
  return null
}

function characterBlocker(ctx: BlockerContext): string | null {
  if (ctx.mode === 'text') return null
  return ctx.mode === 'video' ? videoBlocker(ctx.videoInfo) : imageBlocker(ctx)
}

interface CharacterHooks {
  convId: Ref<string | null>
  /** The composer settings: the mode and model picks decide whether characters are used. */
  settings: Pick<ComposerSettings, 'mode' | 'selected' | 'textInfo' | 'imageInfo' | 'videoInfo'>
  ensureConversation: () => Promise<string>
  showToast: ShowToast
  /** The ids its defaults attach, on top of its own. */
  inheritedIds?: Ref<readonly number[]> | undefined
}

// Characters for the open chat: every saved one plus the chat's own (ad
// hoc) ones, which are attached, and the editor's state.
export function useChatCharacters({ convId, settings, ensureConversation, showToast, inheritedIds }: CharacterHooks) {
  const characters = ref<Character[]>([])
  const characterIds = ref<number[]>([]) // attached to this chat itself (or the next new one)
  const charEditor = reactive<{
    open: boolean
    character: Character | null
    conversationId: string | null
    seed: readonly CharacterSeed[]
  }>({ open: false, character: null, conversationId: null, seed: [] })
  const attachedCharacters = computed(() =>
    [...new Set([...(inheritedIds?.value ?? []), ...characterIds.value])].flatMap(
      id => characters.value.find(c => c.id === id) ?? [],
    ),
  )
  const characterNames = computed(() => attachedCharacters.value.map(c => c.name).join(', '))
  // When they can't be used, attached characters stay attached but unused
  const characterSupport = computed(() => {
    const reason = characterBlocker({
      mode: settings.mode.value,
      selected: settings.selected,
      textInfo: settings.textInfo.value,
      imageInfo: settings.imageInfo.value,
      videoInfo: settings.videoInfo.value,
    })
    return reason ? { ok: false, reason } : { ok: true, reason: null }
  })

  // A chat's own (ad hoc) characters only come back when asked for by chat id,
  // so reload when the open chat changes (a refresh opens it after the first load)
  let loadSeq = 0
  async function loadCharacters(): Promise<void> {
    const seq = ++loadSeq
    try {
      const list = await fetchCharacters({ conversationId: convId.value })
      if (seq === loadSeq) characters.value = list
    } catch {
      /* 401 handled by auth prompt */
    }
  }
  watch(convId, loadCharacters)

  async function setCharacters(ids: number[]): Promise<void> {
    characterIds.value = ids
    if (!convId.value) return // new chats get them on creation
    try {
      await patchConversation(convId.value, { character_ids: ids })
    } catch (e) {
      showToast(`Couldn't update characters: ${messageOf(e)}`, 'error')
    }
  }

  function editCharacter(character: Character): void {
    Object.assign(charEditor, { open: true, character, conversationId: null, seed: [] })
  }

  // Characters made in a chat belong to it (ad hoc) until saved
  async function newCharacter(seed: readonly CharacterSeed[] = []): Promise<void> {
    let id: string
    try {
      id = await ensureConversation()
    } catch (e) {
      showToast(messageOf(e), 'error')
      return
    }
    Object.assign(charEditor, { open: true, character: null, conversationId: id, seed })
  }

  // The chat model used (or made) some: they're attached now
  function onCharactersUsed(used: readonly Character[], ids: number[]): void {
    for (const c of used) upsert(characters.value, c)
    characterIds.value = ids
  }

  function onCharacterSaved(saved: Character): void {
    upsert(characters.value, saved)
    if (charEditor.character?.id === saved.id) charEditor.character = saved
    // Made here: the server attached it to this chat
    if (saved.conversation_id === convId.value && !characterIds.value.includes(saved.id)) {
      characterIds.value = [...characterIds.value, saved.id]
    }
  }

  function onCharacterDeleted(id: number): void {
    characters.value = characters.value.filter(c => c.id !== id)
    characterIds.value = characterIds.value.filter(x => x !== id) // the server detaches it too
  }

  return {
    characters,
    characterIds,
    charEditor,
    attachedCharacters,
    characterNames,
    characterSupport,
    loadCharacters,
    setCharacters,
    editCharacter,
    newCharacter,
    onCharactersUsed,
    onCharacterSaved,
    onCharacterDeleted,
  }
}
