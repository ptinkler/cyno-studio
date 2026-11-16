/**
 * Catalogue models for tests: complete, typed rows like the backend serves, with only what a test cares
 * about spelled out. Checked against the generated types, so a fixture can't drift from the real shape.
 */
import type { Conversation } from '../composables/chatConversationsApi'
import type { UiMessage } from '../composables/studioTypes'
import type { AudioModel, ImageModel, TextModel, VideoModel } from '../composables/chatModelsApi'

type Given<M> = Partial<M> & { id: string; name: string }

export const textModel = (given: Given<TextModel>): TextModel => ({
  tags: [],
  input_modalities: ['text'],
  supports_tools: false,
  ...given,
})

export const imageModel = (given: Given<ImageModel>): ImageModel => ({
  tags: [],
  input_modalities: ['text'],
  conversational: false,
  ...given,
})

export const videoModel = (given: Given<VideoModel>): VideoModel => ({
  tags: [],
  frame_images: [],
  ...given,
})

export const audioModel = (given: Given<AudioModel>): AudioModel => ({
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
