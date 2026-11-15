// What the "delete this prompt and its reply?" dialog says, from the server's count of what goes with it.

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

function deleteDetail({ other_versions: versions, other_messages: after }) {
  const removes = [versions && plural(versions, 'other version'), after && plural(after, 'message')].filter(Boolean)
  const where = versions ? ' that followed them' : ' on other branches'
  return removes.length ? `This also removes ${removes.join(' and ')}${after ? where : ''}.` : ''
}

// The files the "also delete" box decides on, named so it's clear what goes:
// only what this turn generated (uploads stay), and nothing at all when the
// generation failed — then there's no box to tick.
const MEDIA_WORDS = { image: 'image', video: 'video', audio: 'audio clip' }
export function deleteMediaLabel(media) {
  const parts = Object.entries(media || {})
    .filter(([, n]) => n > 0)
    .map(([kind, n]) => plural(n, MEDIA_WORDS[kind] || 'file'))
  if (!parts.length) return ''
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}` : parts[0]
  return `Also delete the ${list} it made`
}

// The confirmDialog() options for a delete-info reply ({ other_versions, other_messages, media })
export function deleteDialogOptions(info) {
  const mediaLabel = deleteMediaLabel(info.media)
  return {
    title: 'Delete this prompt and its reply?',
    message: [deleteDetail(info), mediaLabel && 'Unticked, those files stay in your Media library.']
      .filter(Boolean)
      .join(' '),
    confirmLabel: 'Delete',
    danger: true,
    checkbox: mediaLabel ? { label: mediaLabel, checked: true } : null,
  }
}
