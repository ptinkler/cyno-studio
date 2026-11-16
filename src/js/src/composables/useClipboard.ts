import { ref } from 'vue'

/**
 * Copy text to the clipboard. navigator.clipboard only exists in secure contexts (HTTPS / localhost), so over
 * plain HTTP this answers false and the copy buttons do nothing: the app is meant to be served over HTTPS.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false // no clipboard API (insecure context) or permission denied
  }
}

const FEEDBACK_MS = 1500

/** `copiedKey` holds the key of whatever was copied last, for ~1.5s of "✓ Copied" feedback. */
export function useCopy() {
  const copiedKey = ref<string | null>(null)
  let timer: ReturnType<typeof setTimeout> | undefined

  async function copy(text: string | null | undefined, key = 'default'): Promise<boolean> {
    if (!text) return false
    const ok = await copyText(text)
    if (ok) {
      copiedKey.value = key
      clearTimeout(timer)
      timer = setTimeout(() => {
        copiedKey.value = null
      }, FEEDBACK_MS)
    }
    return ok
  }

  return { copiedKey, copy }
}
