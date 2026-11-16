/**
 * Catalogue models for tests: complete, typed rows like the backend serves, with only what a test cares
 * about spelled out. Checked against the generated types, so a fixture can't drift from the real shape.
 */
import type {
  Conversation,
  ConversationMessage,
  ConversationView,
  MediaCard,
  ShownMessage,
} from '../composables/chatConversationsApi'
import type { Generation } from '../composables/chatFilesApi'
import type { ListedCharacter } from '../composables/charactersApi'
import type { LibraryEntry } from '../composables/mediaApi'
import type { Instruction, InstructionGroup } from '../composables/chatSettingsApi'
import type { Attachment } from '../composables/useChatAttachments'
import type { GenerationItem, Space, UiMessage } from '../composables/studioTypes'
import type { AudioModel, ImageModel, TextModel, VideoModel } from '../composables/chatModelsApi'

type Given<M> = Partial<M> & { id: string }

export const textModel = (given: Given<TextModel>): TextModel => ({
  name: given.id,
  tags: [],
  input_modalities: ['text'],
  supports_tools: false,
  ...given,
})

export const imageModel = (given: Given<ImageModel>): ImageModel => ({
  name: given.id,
  tags: [],
  input_modalities: ['text'],
  conversational: false,
  ...given,
})

export const videoModel = (given: Given<VideoModel>): VideoModel => ({
  name: given.id,
  tags: [],
  frame_images: [],
  ...given,
})

export const audioModel = (given: Given<AudioModel>): AudioModel => ({
  name: given.id,
  tags: [],
  options: [],
  ...given,
})

/** A chat's remembered composer settings, complete as the backend always serves them. */
export const composerSettings = (
  given: Partial<NonNullable<Conversation['settings']>> = {},
): NonNullable<Conversation['settings']> => ({
  mode: 'auto',
  history_limit: null,
  image_limit: 6,
  audio_model: null,
  image_options: {},
  video_options: {},
  audio_options: {},
  ref_choices: { on: [], off: [] },
  ...given,
})

/** A chat as the backend serves it, complete; only what a test cares about needs spelling out. */
export const conversation = (given: Partial<Conversation> = {}): Conversation => ({
  id: 'c1',
  title: 'New chat',
  text_model: null,
  image_model: null,
  video_model: null,
  instruction_ids: [],
  instruction_group_ids: [],
  space_id: null,
  current_leaf_id: null,
  character_ids: [],
  forked_from_id: null,
  forked_from_message_id: null,
  pinned: false,
  kind: 'chat',
  settings: null,
  hidden_defaults: { character: [], instruction: [], instruction_group: [] },
  paused_instructions: { instruction: [], instruction_group: [] },
  import_source: null,
  created_at: null,
  updated_at: null,
  ...given,
})

/** A message in the shown chat, complete as the server sends it; only what a test cares about needs spelling out. */
export const uiMessage = (given: Partial<UiMessage> = {}): UiMessage => ({
  id: 1,
  conversation_id: 'c1',
  parent_id: null,
  role: 'assistant',
  content: '',
  media: [],
  model: null,
  mode: null,
  lane: null,
  status: 'done',
  error: null,
  cost: null,
  text_versions: 0,
  text_shown: 0,
  created_at: null,
  siblings: [],
  ...given,
})

/** A composer attachment (a picked picture, clip or track), uploaded and ready unless the test says otherwise. */
export const attachment = (given: Partial<Attachment> = {}): Attachment => ({
  key: 'a1',
  file: 'a1.png',
  preview: '',
  video: false,
  audio: false,
  uploading: false,
  ...given,
})

/** A thread in the sidebar list (a chat's summary is a chat without its messages). */
export const thread = conversation

/** A space (folder of threads) with no defaults attached. */
export const space = (given: Partial<Space> = {}): Space => ({
  id: 1,
  name: 'Novel',
  default_character_ids: [],
  default_instruction_ids: [],
  default_instruction_group_ids: [],
  created_at: null,
  updated_at: null,
  ...given,
})

/** One generated or uploaded picture/clip on a reply, finished unless the test says otherwise. */
export const mediaCard = (given: Partial<MediaCard> = {}): MediaCard => ({
  id: 'm1',
  kind: 'image',
  source: 'generated',
  status: 'done',
  file: 'img_a.png',
  ...given,
})

/** A card as the gallery and the big view hold it: where it lives, and what it is. */
export const generationItem = (given: Partial<GenerationItem> = {}): GenerationItem => ({
  id: 'm1',
  kind: 'image',
  conversation_id: 'c1',
  message_id: 1,
  file: 'img_a.png',
  status: 'done',
  ...given,
})

/** An entry in the queue dock: one in-flight or finished generation, anywhere. */
export const generation = (given: Partial<Generation> = {}): Generation => ({
  media_id: 'm1',
  message_id: 1,
  conversation_id: 'c1',
  conversation_title: 'A chat',
  kind: 'image',
  prompt: null,
  model: null,
  status: 'done',
  file: 'a.png',
  error: null,
  moderated: false,
  created_at: null,
  ...given,
})

/** A character as the library lists it (a library one unless the test says it is a chat's own). */
export const character = (given: Partial<ListedCharacter> & { id: number; name: string }): ListedCharacter => ({
  description: '',
  images: [],
  adhoc: false,
  conversation_id: null,
  conversation_title: null,
  created_at: null,
  updated_at: null,
  ...given,
})

/** A row of the media library (an uploaded picture unless the test says otherwise). */
export const libraryEntry = (given: Partial<LibraryEntry> & { id: string }): LibraryEntry => ({
  kind: 'image',
  source: 'upload',
  origin: 'library',
  name: given.id.replace(/^\w+:/, ''),
  url: `/full/${given.id}`,
  thumb_url: `/thumb/${given.id}`,
  created_at: null,
  duration: null,
  ...given,
})

/** An instruction snippet. */
export const instruction = (given: Partial<Instruction> & { id: number; name: string }): Instruction => ({
  content: '',
  created_at: null,
  updated_at: null,
  ...given,
})

/** A group of instruction snippets. */
export const instructionGroup = (
  given: Partial<InstructionGroup> & { id: number; name: string },
): InstructionGroup => ({
  snippet_ids: [],
  created_at: null,
  updated_at: null,
  ...given,
})

/** A message as the turn stream and the chat endpoints send it, complete; the id is the server's number. */
export const shownMessage = (given: Partial<ShownMessage> = {}): ShownMessage => ({
  id: 1,
  conversation_id: 'c1',
  parent_id: null,
  role: 'assistant',
  content: '',
  media: [],
  model: null,
  mode: null,
  lane: null,
  status: 'done',
  error: null,
  cost: null,
  text_versions: 0,
  text_shown: 0,
  created_at: null,
  siblings: [],
  ...given,
})

/** A message in a loaded chat: the same, plus the chats branched from it. */
export const serverMessage = (given: Partial<ConversationMessage> = {}): ConversationMessage => ({
  ...shownMessage(),
  forks: [],
  ...given,
})

/** A chat as it comes back when opened: the chat plus what it has cost and where it was branched from. */
export const openConversation = (
  given: Partial<ConversationView['conversation']> = {},
): ConversationView['conversation'] => ({
  ...conversation(),
  forked_from: null,
  spend: { usd: 0, credits: 0, inherited_usd: 0, inherited_credits: 0 },
  ...given,
})
