import { ref, computed, watch } from 'vue'
import type { Ref } from 'vue'
import { MODES } from './composerPrefs'
import type { Mode } from './composerPrefs'
import type { ThreadKind, UiMessage } from './studioTypes'

type ThreadView = 'chat' | 'gallery'

interface ThreadViewHooks {
  route: { params: Record<string, unknown> }
  activeKind: Ref<ThreadKind>
  draft: Ref<string>
  lane: Ref<'gallery' | null>
  messages: Ref<UiMessage[]>
  mode: Ref<Mode>
}

// A thread's two views, Chat and Gallery: which one shows, the prompt draft each keeps, and what the gallery composer offers.
export function useThreadView({ route, activeKind, draft, lane, messages, mode }: ThreadViewHooks) {
  // Every thread has two views: the chat conversation and its generations
  // gallery. A thread's `kind` ('chat' | 'gallery') only picks which it opens on,
  // unless the URL pins a tab (/studio/:id/chat|gallery).
  const threadView = ref<ThreadView>('chat')
  watch(
    activeKind,
    kind => {
      if (!route.params['view']) threadView.value = kind
    },
    { immediate: true },
  )

  // A gallery is for straight generations: only Image and Video modes (no
  // Auto/Text — the chat model is never involved), sent exactly as written.
  const inGallery = computed(() => threadView.value === 'gallery')
  // Each view keeps its own prompt draft, and gallery sends run beside the chat
  const draftStash: Record<ThreadView, string> = { chat: '', gallery: '' }
  watch(
    threadView,
    (view, old: ThreadView | undefined) => {
      if (old) draftStash[old] = draft.value
      if (old && old !== view) draft.value = draftStash[view]
      lane.value = view === 'gallery' ? 'gallery' : null
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
