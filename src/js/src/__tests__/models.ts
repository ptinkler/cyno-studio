/**
 * Catalogue models for tests: complete, typed rows like the backend serves, with only what a test cares
 * about spelled out. Checked against the generated types, so a fixture can't drift from the real shape.
 */
import type { Conversation } from '../composables/chatConversationsApi'
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
