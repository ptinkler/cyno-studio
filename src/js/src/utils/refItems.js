// What the Studio composer knows about its attachments' roles in a prompt.

export const attType = a => (a.audio ? 'audio' : a.video ? 'video' : 'image')
const cap = s => s.charAt(0).toUpperCase() + s.slice(1)

// Reference-to-video: each allowed attachment becomes a mentionable ref named
// by type + order (image1, video1, audio1…) — the handle the prompt uses as
// [@name]. Caps come from the model's ref_mode ({ types, max, limits }); ordering matches the backend
// (web/chat/turn.py _ref_items) so a pill always resolves to the same
// attachment.
export function buildRefItems(attachments, refMode) {
  const types = new Set(refMode.types || ['image', 'video', 'audio'])
  const limits = refMode.limits || {}
  const counts = {}
  const out = []
  const allowed = (a, type, n) => !a.uploading && types.has(type) && !(limits[type] && n > limits[type])
  for (const a of attachments) {
    const type = attType(a)
    const n = (counts[type] || 0) + 1
    if (!allowed(a, type, n)) continue
    counts[type] = n
    out.push({ key: a.key, name: `${type}${n}`, label: `${cap(type)} ${n}`, type, preview: a.preview })
    if (refMode.max && out.length >= refMode.max) break
  }
  return out
}
