import { confirmDialog, promptDialog } from './useDialog'
import { patchConversation, deleteConversation, createSpace, updateSpace, deleteSpace } from './useChat'

// What the sidebar does to threads (favourite, rename, delete, move) and spaces (add, rename, delete).
export function useStudioSidebar({ threads, spaces, active, activeThread, showToast, newThread, loadLists }) {
  async function toggleFav(t) {
    const next = !t.pinned
    try {
      await patchConversation(t.id, { pinned: next })
      t.pinned = next
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  // Rename from the sidebar's inline editor (no prompt). `name` is the new title.
  async function renameThread(t, name) {
    const title = (name ?? '').trim()
    if (!title || title === (t.title || '')) return
    try {
      await patchConversation(t.id, { title })
      t.title = title
      if (activeThread.value?.id === t.id) activeThread.value.title = title
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  async function removeThread(t) {
    const r = await confirmDialog({
      title: `Delete “${t.title || 'Untitled'}”?`,
      message: "The conversation is removed. This can't be undone.",
      confirmLabel: 'Delete',
      danger: true,
      checkbox: { label: 'Also delete all its media (images, videos, uploads)', checked: true },
    })
    if (!r) return
    try {
      await deleteConversation(t.id, { deleteMedia: r.checked })
      threads.value = threads.value.filter(x => x.id !== t.id)
      if (active.value === t.id) newThread()
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  async function moveThread(t, spaceId) {
    try {
      await patchConversation(t.id, { space_id: spaceId })
      t.space_id = spaceId
    } catch (e) {
      showToast(e.message, 'error')
    }
  }

  async function addSpace() {
    const name = await promptDialog({ title: 'New space', label: 'Name', confirmLabel: 'Create' })
    if (!name?.trim()) return
    try {
      const space = await createSpace({ name: name.trim() })
      spaces.value = [...spaces.value, space]
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  async function renameSpace(s, name) {
    if (!name?.trim()) return
    try {
      await updateSpace(s.id, { name: name.trim() })
      s.name = name.trim()
    } catch (e) {
      showToast(e.message, 'error')
    }
  }
  async function removeSpace(s) {
    const ok = await confirmDialog({
      title: `Delete space “${s.name}”?`,
      message: 'Its threads move to Unfiled.',
      confirmLabel: 'Delete',
      danger: true,
    })
    if (!ok) return
    try {
      await deleteSpace(s.id)
      await loadLists()
    } catch (e) {
      showToast(e.message, 'error')
    }
  }

  return {
    toggleFav,
    renameThread,
    removeThread,
    moveThread,
    addSpace,
    renameSpace,
    removeSpace,
  }
}
