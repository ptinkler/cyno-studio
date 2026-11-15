// "Use settings" (gallery): fill the composer from a past generation so the
// user can tweak and press Generate. Fills only — never fires (unlike retry).

const AUDIO_KEYS = [
  'voice',
  'speed',
  'volume',
  'pitch',
  'instrumental',
  'vocal_gender',
  'style',
  'title',
  'negative_prompt',
  'duration',
]

// A generation's stored params back into the composer's options for its kind
function applyVideoOptions(opts, p) {
  if (p.generate_audio != null) opts.generate_audio = p.generate_audio
  // A generation made on Auto goes back to Auto ('') — its stored duration is
  // what Auto worked out to (the clip's length), not a length that was chosen.
  opts.duration = p.duration_auto ? '' : (p.duration ?? opts.duration)
}
function applyOptions(settings, kind, p) {
  if (kind === 'audio') {
    for (const k of AUDIO_KEYS) if (p[k] != null) settings.audioOpts[k] = p[k]
    return
  }
  const opts = kind === 'video' ? settings.videoOpts : settings.imageOpts
  for (const k of ['aspect_ratio', 'resolution']) if (p[k]) opts[k] = p[k]
  if (kind === 'video') applyVideoOptions(opts, p)
}

// Put a generation's reference images back as attachments (character refs
// come back with the characters, not as files)
function restoreRefs(item, { clearAttachments, addChatMedia, addChatImage }) {
  clearAttachments()
  const p = item.params || {}
  // Reference-to-video: re-attach each named ref with its kind, in order, so
  // the [@name] pills resolve again (image1, video1…).
  if (p.ref_items?.length) {
    for (const r of p.ref_items) {
      if (r.file && !r.file.startsWith?.('char:')) addChatMedia(r.file, r.type, item.conversation_id)
    }
    return
  }
  const files = [...(p.refs || []), p.first_frame, p.last_frame].filter(f => f && !f.startsWith('char:'))
  for (const f of new Set(files)) addChatImage(f, item.conversation_id)
}

export function useStudioReuse({ draft, settings, attachments }) {
  const { selected, mode } = settings
  function applyGenerationSettings(item) {
    const kind = ['video', 'audio'].includes(item.kind) ? item.kind : 'image'
    const text = item.original_prompt || item.prompt
    if (text) draft.value = text
    const model = item.model || item.params?.model
    if (model) selected[kind] = model
    mode.value = kind
    applyOptions(settings, kind, item.params || {})
    restoreRefs(item, attachments)
  }
  return { applyGenerationSettings }
}
