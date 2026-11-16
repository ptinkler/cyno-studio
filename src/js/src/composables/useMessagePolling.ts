import { onBeforeUnmount, onMounted } from 'vue'
import type { Ref } from 'vue'
import type { ShownMessage } from './chatConversationsApi'
import { fetchChatMessage } from './useChat'

const POLL_MS = 3000

/** What polling needs to know about a message in the shown chat (a not-yet-saved local one has a string id). */
export interface PollableMessage {
  id: number | string
  status: string
  media?: readonly { status: string }[] | null | undefined
}

interface PollingHooks {
  /** The shown chat's messages. */
  messages: Ref<readonly PollableMessage[]>
  /** The reply with a live stream, which needs no polling. */
  streamingId: Ref<number | string | null>
  /** Swap in a fresher copy of a message. */
  replace: (fresh: ShownMessage) => void
  /** Something landed (it was billed). */
  onFinished: () => void
}

// A reply's live stream can drop — a background tab gets throttled or
// frozen, you reload, or you open it mid-reply from elsewhere. The server
// keeps working regardless, so poll such replies until they're done, plus
// any rendering video or retried image.
export function useMessagePolling({ messages, streamingId, replace, onFinished }: PollingHooks) {
  let timer: ReturnType<typeof setInterval> | undefined

  function hasPending(m: PollableMessage): boolean {
    if (m.status === 'streaming') return m.id !== streamingId.value // no live stream for it
    return !!m.media?.some(x => x.status === 'pending')
  }

  async function pollOnce(): Promise<void> {
    const pending = messages.value.filter(hasPending)
    if (!pending.length) {
      stop()
      return
    }
    let finished = false
    for (const m of pending) {
      if (typeof m.id !== 'number') continue // not saved yet: nothing on the server to ask about
      try {
        const fresh = await fetchChatMessage(m.id)
        replace(fresh)
        finished ||= !hasPending(fresh)
      } catch {
        /* retry next tick */
      }
    }
    if (finished) onFinished()
  }

  function ensure(): void {
    if (timer !== undefined || !messages.value.some(hasPending)) return
    timer = setInterval(() => void pollOnce(), POLL_MS)
  }

  function stop(): void {
    clearInterval(timer)
    timer = undefined
  }

  // Coming back to the tab: catch up now rather than on the next tick
  function onVisibilityChange(): void {
    if (document.visibilityState === 'visible' && messages.value.some(hasPending)) {
      void pollOnce()
      ensure()
    }
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onVisibilityChange)
  })
  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onVisibilityChange)
    stop()
  })

  return { ensure, stop }
}
