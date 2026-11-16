import type { components } from '../api/schema'

// What the Studio composer knows about its attachments' roles in a prompt.

type RefMode = components['schemas']['RefMode']
type RefType = 'image' | 'video' | 'audio'

/** The part of a composer attachment that decides what it can be referenced as. */
export interface RefAttachment {
  key: string
  audio?: boolean
  video?: boolean
  uploading?: boolean
  preview?: string | null
}

export interface RefItem {
  key: string
  name: string // the handle the prompt uses: [@image1]
  label: string
  type: RefType
  preview: string | null | undefined
}

export const attType = (attachment: Pick<RefAttachment, 'audio' | 'video'>): RefType =>
  attachment.audio ? 'audio' : attachment.video ? 'video' : 'image'

const capitalised = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1)

const ALL_TYPES: readonly string[] = ['image', 'video', 'audio']

// Reference-to-video: each allowed attachment becomes a mentionable ref named
// by type + order (image1, video1, audio1…) — the handle the prompt uses as
// [@name]. Caps come from the model's ref_mode ({ types, max, limits }); ordering matches the backend
// (web/chat/turn.py _ref_items) so a pill always resolves to the same
// attachment.
export function buildRefItems(attachments: readonly RefAttachment[], refMode: RefMode): RefItem[] {
  const types = new Set(refMode.types ?? ALL_TYPES)
  const limits = refMode.limits ?? {}
  const counts: Partial<Record<RefType, number>> = {}
  const out: RefItem[] = []
  const allowed = (attachment: RefAttachment, type: RefType, n: number): boolean => {
    const limit = limits[type]
    return !attachment.uploading && types.has(type) && !(limit && n > limit)
  }
  for (const attachment of attachments) {
    const type = attType(attachment)
    const n = (counts[type] ?? 0) + 1
    if (!allowed(attachment, type, n)) continue
    counts[type] = n
    out.push({
      key: attachment.key,
      name: `${type}${String(n)}`,
      label: `${capitalised(type)} ${String(n)}`,
      type,
      preview: attachment.preview,
    })
    if (refMode.max && out.length >= refMode.max) break
  }
  return out
}
