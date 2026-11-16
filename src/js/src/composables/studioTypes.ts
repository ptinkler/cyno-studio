import type { ComputedRef, Ref } from 'vue'
import type { components } from '../api/schema'
import type { Conversation, ConversationMessage, ConversationSummary } from './chatConversationsApi'

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
export interface GenerationItem {
  id: string
  kind: string | null
  conversation_id: string
  message_id: number | null
  file?: string | null
  prompt?: string | null
  /** The prompt as the user wrote it, when what was sent was reworded. */
  original_prompt?: string | null
  model?: string | null
  params?: Record<string, unknown> | null
  status?: string
  favourite?: boolean | null
}
