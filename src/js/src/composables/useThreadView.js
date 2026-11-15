import { ref, computed, watch } from 'vue'
import { MODES } from './useComposerSettings'

// A thread's two views, Chat and Gallery: which one shows, the prompt draft each keeps, and what the gallery composer offers.
export function useThreadView({ route, activeKind, draft, lane, messages, mode }) {
  // Every thread has two views: the chat conversation and its generations
  // gallery. A thread's `kind` ('chat' | 'gallery') only picks which it opens on,
  // unless the URL pins a tab (/studio/:id/chat|gallery).
  const threadView = ref('chat')
  watch(
    activeKind,
    k => {
      if (!route.params.view) threadView.value = k
    },
    { immediate: true },
  )

  // A gallery is for straight generations: only Image and Video modes (no
  // Auto/Text — the chat model is never involved), sent exactly as written.
  const inGallery = computed(() => threadView.value === 'gallery')
  // Each view keeps its own prompt draft, and gallery sends run beside the chat
  const draftStash = { chat: '', gallery: '' }
  watch(
    threadView,
    (v, old) => {
      if (old) draftStash[old] = draft.value
      if (old && old !== v) draft.value = draftStash[v]
      lane.value = v === 'gallery' ? 'gallery' : null
    },
    { immediate: true },
  )
  const chatMessages = computed(() => messages.value.filter(m => !m.lane))
  const composerModes = computed(() =>
    inGallery.value ? MODES.filter(m => m.id === 'image' || m.id === 'video') : MODES,
  )
  watch(
    [inGallery, mode],
    () => {
      if (inGallery.value && mode.value !== 'image' && mode.value !== 'video') mode.value = 'image'
    },
    { immediate: true },
  )
  return { threadView, inGallery, chatMessages, composerModes }
}
