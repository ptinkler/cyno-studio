import type { Ref } from 'vue'
import type { ConversationSummary } from './chatConversationsApi'
import { confirmDialog, promptDialog } from './useDialog'
import {
  patchConversation,
  deleteConversation,
  fetchConversationDeleteInfo,
  createSpace,
  updateSpace,
  deleteSpace,
} from './useChat'
import type { Space } from './studioTypes'
import type { ShowToast } from './useToast'
import { messageOf } from '../utils/errors'

interface SidebarHooks {
  threads: Ref<ConversationSummary[]>
  spaces: Ref<Space[]>
  active: Ref<string | null>
  activeThread: Ref<{ id: string; title: string } | null>
  showToast: ShowToast
  newThread: () => void
  loadLists: () => Promise<void>
}

// What the sidebar does to threads (favourite, rename, delete, move) and spaces (add, rename, delete).
export function useStudioSidebar({
  threads,
  spaces,
  active,
  activeThread,
  showToast,
  newThread,
  loadLists,
}: SidebarHooks) {
  const fail = (e: unknown): void => {
    showToast(messageOf(e), 'error')
  }

  async function toggleFav(thread: ConversationSummary): Promise<void> {
    const next = !thread.pinned
    try {
      await patchConversation(thread.id, { pinned: next })
      thread.pinned = next
    } catch (e) {
      fail(e)
    }
  }

  // Rename from the sidebar's inline editor (no prompt). `name` is the new title.
  async function renameThread(thread: ConversationSummary, name: string | null | undefined): Promise<void> {
    const title = (name ?? '').trim()
    if (!title || title === thread.title) return
    try {
      await patchConversation(thread.id, { title })
      thread.title = title
      if (activeThread.value?.id === thread.id) activeThread.value.title = title
    } catch (e) {
      fail(e)
    }
  }

  async function removeThread(thread: ConversationSummary): Promise<void> {
    // Characters made in this chat and never saved go with it; saved ones (and their images) stay
    const { characters } = await fetchConversationDeleteInfo(thread.id).catch(() => ({ characters: [] as string[] }))
    const withIt = characters.length
      ? ` Also deleted: ${characters.join(', ')} (made in this chat, not saved as ${characters.length === 1 ? 'a character' : 'characters'}).`
      : ''
    const result = await confirmDialog({
      title: `Delete “${thread.title || 'Untitled'}”?`,
      message: `The conversation is removed. This can't be undone.${withIt}`,
      confirmLabel: 'Delete',
      danger: true,
      checkbox: { label: 'Also delete all its media (images, videos, uploads)', checked: true },
    })
    if (!result) return
    try {
      await deleteConversation(thread.id, { deleteMedia: result.checked })
      threads.value = threads.value.filter(x => x.id !== thread.id)
      if (active.value === thread.id) newThread()
    } catch (e) {
      fail(e)
    }
  }

  async function moveThread(thread: ConversationSummary, spaceId: number | null): Promise<void> {
    try {
      await patchConversation(thread.id, { space_id: spaceId })
      thread.space_id = spaceId
    } catch (e) {
      fail(e)
    }
  }

  async function addSpace(): Promise<void> {
    const name = await promptDialog({ title: 'New space', label: 'Name', confirmLabel: 'Create' })
    if (!name?.trim()) return
    try {
      const space = await createSpace({ name: name.trim() })
      spaces.value = [...spaces.value, space]
    } catch (e) {
      fail(e)
    }
  }

  async function renameSpace(space: Space, name: string | null | undefined): Promise<void> {
    const trimmed = name?.trim()
    if (!trimmed) return
    try {
      await updateSpace(space.id, { name: trimmed })
      space.name = trimmed
    } catch (e) {
      fail(e)
    }
  }

  async function removeSpace(space: Space): Promise<void> {
    const ok = await confirmDialog({
      title: `Delete space “${space.name}”?`,
      message: 'Its threads move to Unfiled.',
      confirmLabel: 'Delete',
      danger: true,
    })
    if (!ok) return
    try {
      await deleteSpace(space.id)
      await loadLists()
    } catch (e) {
      fail(e)
    }
  }

  return { toggleFav, renameThread, removeThread, moveThread, addSpace, renameSpace, removeSpace }
}
