import { reactive } from 'vue'

// A card's reference images can stop existing: a character's images belong to the server that made them, so
// an exported chat's cards point at characters that aren't here, and a deleted character leaves the same
// hole. Whether an image is there is only known by asking for it, so each address is asked about once.
const status = reactive(new Map<string, 'ok' | 'missing'>())
const asked = new Set<string>()

/** Whether this address has been found not to serve an image. */
export const isMissing = (url: string): boolean => status.get(url) === 'missing'

/** Record that an image failed to load (an <img> that errored). */
export function markMissing(url: string): void {
  status.set(url, 'missing')
}

/** Find out, once, whether the image at `url` loads. Until it answers it counts as there. */
export function probeRef(url: string): void {
  if (asked.has(url)) return
  asked.add(url)
  const probe = new Image()
  probe.onload = () => {
    status.set(url, 'ok')
  }
  probe.onerror = () => {
    markMissing(url)
  }
  probe.src = url
}
