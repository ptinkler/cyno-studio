import type { VideoModel } from './chatModelsApi'
import { attType } from '../utils/refItems'
import type { RefAttachment } from '../utils/refItems'

// Pure helpers for the Studio composer's attachments: what a video model accepts, and which
// attachments it can't use.

type AttachmentKind = 'image' | 'video' | 'audio'

/** What a video model says about the inputs it takes. */
export type VideoInputs = Pick<
  VideoModel,
  'ref_mode' | 'reference_images' | 'frame_images' | 'video_input' | 'audio_input'
>

// What a video model takes, by attachment kind
export function acceptedKinds(info: VideoInputs): Record<AttachmentKind, boolean> {
  const types = new Set(info.ref_mode?.types ?? [])
  return {
    image: types.has('image') || !!info.reference_images || info.frame_images.length > 0,
    video: types.has('video') || !!info.video_input,
    audio: types.has('audio') || !!info.audio_input,
  }
}

// Keys of attachments the model can't use: a kind it doesn't take, or past its per-kind cap
export function unusedKeys(
  list: readonly RefAttachment[],
  info: VideoInputs,
  caps: Readonly<Record<AttachmentKind, number>>,
): Set<string> {
  const accepts = acceptedKinds(info)
  const seen: Record<AttachmentKind, number> = { image: 0, video: 0, audio: 0 }
  const out = new Set<string>()
  for (const attachment of list) {
    const kind = attType(attachment)
    seen[kind]++
    if (!accepts[kind] || seen[kind] > caps[kind]) out.add(attachment.key)
  }
  return out
}

// The length (s) of a video file, read from its metadata in the browser (null if it can't be read).
export function readVideoDuration(url: string): Promise<number | null> {
  return new Promise(resolve => {
    const video = document.createElement('video')
    video.preload = 'metadata'
    video.onloadedmetadata = () => {
      resolve(video.duration || null)
    }
    video.onerror = () => {
      resolve(null)
    }
    video.src = url
  })
}
