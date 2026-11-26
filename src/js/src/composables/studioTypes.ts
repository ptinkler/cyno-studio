import type { ComputedRef, Ref } from 'vue'
import type { components } from '../api/schema'
import type { Conversation, ConversationMessage, ConversationSummary } from './chatConversationsApi'
import type { Character } from './charactersApi'
import type { Instruction, InstructionGroup } from './chatSettingsApi'
import type { Mode } from './composerPrefs'
import type { InheritedDefault } from './useChatDefaults'

// The shapes the Studio's composables pass around: its shared state, and a message in the shown chat.

type Schemas = components['schemas']

export type Space = Schemas['Space']
export type Spend = Schemas['Spend']

/**
 * A message in the shown chat: one the server sent, or the user's own prompt before the server has saved it
 * (it has a string id then, and is replaced by the server's copy as the turn starts).
 */
export type UiMessage = Omit<ConversationMessage, 'id' | 'forks'> & {
  id: number | string
  /** Only the chat's own messages carry the chats that were branched from them. */
  forks?: ConversationMessage['forks']
}

/** Which view a thread opens on. */
export type ThreadKind = 'chat' | 'gallery'

/** The Studio's shared refs: what the thread-level composables read and write. */
export interface StudioState {
  threads: Ref<ConversationSummary[]>
  spaces: Ref<Space[]>
  active: Ref<string | null>
  activeThread: Ref<Conversation | null>
  messages: Ref<UiMessage[]>
  loading: Ref<boolean>
  spend: Ref<Spend | null>
  newKind: Ref<ThreadKind>
  sending: ComputedRef<boolean>
}

/** What a generated card carries when it is shown in a gallery: the card and where it lives. */
/** How long a video may be, as a filter: any, up to 5 s, over 5 up to 10 s, over 10 s. */
export type LengthFilter = 'any' | 'short' | 'medium' | 'long'

export interface GenerationItem {
  id: string
  kind: string | null
  conversation_id: string
  message_id: number | null
  file?: string | null
  /** The full-size file's URL, when the card already knows it. */
  url?: string
  prompt?: string | null
  /** The prompt as the user wrote it, when what was sent was reworded. */
  original_prompt?: string | null
  model?: string | null
  params?: Record<string, unknown> | null
  status?: string
  favourite?: boolean | null
  /** The small picture shown in a grid (the full file when there is no smaller one). */
  preview?: string
  /** A file in the chat's folder that no message records: it can be opened but not managed. */
  orphan?: boolean
  cost?: number | null
  created_at?: string | null
  /** A content filter blocked it (when it failed). */
  moderated?: boolean | null
  error?: string | null
  /** Pollo bills in credits; everything else in dollars (`cost`). */
  credits?: number | null
  /** What was sent to the provider and what came back, as the server recorded them. */
  request?: unknown
  response?: unknown
  conversation_title?: string | null
}

/** "Edit this image" / "animate this image": which file to attach, the mode to switch to, and the chat it lives in. */
export interface ImagePick {
  file?: string | null | undefined
  mode?: Mode | undefined
  conversation_id?: string | undefined
}

/** A request to make a card's picture again: with another model, prompt, or the picture itself as the reference. */
export interface RegenerateRequest {
  mediaId: string
  model?: string | null
  prompt?: string
  edit?: boolean
  replace?: boolean
  /** The chat's pictures to give the model as references (the whole set; omit to leave them as they were). */
  refs?: string[]
}

export type InstructionKind = 'snippet' | 'group'

/** Open the editor on a snippet or group (null id = a new one). */
export interface InstructionEditEvent {
  kind: InstructionKind
  id: number | null
}

/** One instruction snippet or group, as the inspector's buttons name it. */
export interface InstructionTarget {
  kind: InstructionKind
  id: number
}

/** What the inspector shows of the instructions attached to the thread, by kind. */
export interface InstructionsPane {
  list: readonly Instruction[]
  groups: readonly InstructionGroup[]
  snippetIds: readonly number[]
  groupIds: readonly number[]
  summary: string
  inheritedSnippets: readonly InheritedDefault[]
  inheritedGroups: readonly InheritedDefault[]
  hiddenSnippets: readonly InheritedDefault[]
  hiddenGroups: readonly InheritedDefault[]
  pausedSnippets: readonly number[]
  pausedGroups: readonly number[]
}

/** What the inspector shows of the characters attached to the thread. */
export interface CharactersPane {
  list: readonly Character[]
  ids: readonly number[]
  names: string
  /** Whether the picked models can use characters, and if not why. */
  support: { ok: boolean; reason: string | null }
  inherited: readonly InheritedDefault[]
  hidden: readonly InheritedDefault[]
}

/** What is left to spend with each provider: dollars, except Pollo's credits. A provider with no key is null. */
export interface Balances {
  pollo: number | null
  openrouter: number | null
  venice: number | null
  veniceCredits: number | null
  veniceDiem: number | null
}
