// Pure helpers for the Studio composer's attachments: what a video model accepts, and which
// attachments it can't use.

export const attKind = a => (a.audio ? 'audio' : a.video ? 'video' : 'image')

// What a video model takes, by attachment kind
export function acceptedKinds(info) {
  const types = new Set(info.ref_mode?.types || [])
  return {
    image: types.has('image') || !!info.reference_images || !!info.frame_images?.length,
    video: types.has('video') || !!info.video_input,
    audio: types.has('audio') || !!info.audio_input,
  }
}

// Keys of attachments the model can't use: a kind it doesn't take, or past its per-kind cap
export function unusedKeys(list, info, caps) {
  const accepts = acceptedKinds(info)
  const seen = { image: 0, video: 0, audio: 0 }
  const out = new Set()
  for (const a of list) {
    const kind = attKind(a)
    seen[kind]++
    if (!accepts[kind] || seen[kind] > caps[kind]) out.add(a.key)
  }
  return out
}

// The length (s) of a video file, read from its metadata in the browser (null if it can't be read).
export function readVideoDuration(url) {
  return new Promise(resolve => {
    const v = document.createElement('video')
    v.preload = 'metadata'
    v.onloadedmetadata = () => resolve(v.duration || null)
    v.onerror = () => resolve(null)
    v.src = url
  })
}
