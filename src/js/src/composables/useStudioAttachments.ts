import { computed, watch } from 'vue'
import type { Ref } from 'vue'
import type { VideoModel } from './chatModelsApi'
import { readVideoDuration, unusedKeys } from './studioAttachments'
import type { ComposerSettings } from './useComposerSettings'
import { useChatAttachments, MAX_ATTACHMENTS } from './useChatAttachments'
import type { ShowToast } from './useToast'

type RefKind = 'video' | 'audio'

const refModeImageLimit = (refMode: NonNullable<VideoModel['ref_mode']>): number =>
  refMode.limits?.image ?? refMode.max ?? MAX_ATTACHMENTS

// How many images a video model takes (its catalogue entry `v`, undefined while that is loading)
function videoImageLimit(v: VideoModel | undefined): number {
  if (!v) return MAX_ATTACHMENTS
  // Reference-to-video: as many images as the model's ref_mode allows.
  if (v.ref_mode) return refModeImageLimit(v.ref_mode)
  if (v.reference_images) return MAX_ATTACHMENTS
  return v.frame_images.includes('last_frame') ? 2 : 1
}

interface StudioAttachmentHooks {
  active: Ref<string | null>
  settings: Pick<ComposerSettings, 'selected' | 'mode' | 'videoInfo' | 'durationOptions' | 'clipDuration'>
  showToast: ShowToast
  ensureConversation: () => Promise<string>
}

// The composer's attachments on top of the chat layer: how many of each kind the selected model takes, which
// attachments it can't use, and the clip length a reference-to-video send follows.
export function useStudioAttachments({ active, settings, showToast, ensureConversation }: StudioAttachmentHooks) {
  const { selected, mode } = settings

  // Images the next message may carry: a video model takes one start frame (two with
  // first+last frame) unless it's a reference-image model; others take the usual max
  const imageLimit = (): number =>
    mode.value === 'video' ? videoImageLimit(settings.videoInfo.value) : MAX_ATTACHMENTS
  // Video / audio reference caps — a ref_mode model takes several (its per-type
  // limit); everything else takes one.
  const refTypeLimit = (kind: RefKind): number => {
    const model = mode.value === 'video' ? settings.videoInfo.value : undefined
    return model?.ref_mode ? (model.ref_mode.limits?.[kind] ?? model.ref_mode.max ?? 1) : 1
  }
  const attach = useChatAttachments({
    convId: active,
    ensureConversation,
    showToast,
    limit: imageLimit,
    videoLimit: () => refTypeLimit('video'),
    audioLimit: () => refTypeLimit('audio'),
  })
  const { attachments } = attach

  // Attachments the selected video model can't take (kept in the composer so a
  // model switch never loses them, but shown as unused and left out of the send).
  // Only video mode is strict; chat/auto/image use attachments as they always did.
  const unusedAttachments = computed<Set<string>>(() => {
    const info = mode.value === 'video' ? settings.videoInfo.value : undefined
    if (!info) return new Set()
    const caps = { image: imageLimit(), video: refTypeLimit('video'), audio: refTypeLimit('audio') }
    return unusedKeys(attachments.value, info, caps)
  })

  // Reference-to-video with a source clip (recast): the output runs as long as
  // the clip, so on Auto the length is the clip's, snapped to what the model
  // allows. Picking a length by hand overrides it. Read client-side.
  watch(
    () => [
      selected.video,
      attachments.value
        .filter(a => a.video && a.preview)
        .map(a => a.key)
        .join(),
    ],
    async () => {
      settings.clipDuration.value = null
      if (mode.value !== 'video' || !settings.videoInfo.value?.ref_mode) return
      const clip = attachments.value.find(a => a.video && a.preview)
      if (!clip) return
      const seconds = await readVideoDuration(clip.preview)
      if (!seconds) return
      const options = settings.durationOptions.value
      settings.clipDuration.value = options.length
        ? options.reduce((best, option) => (Math.abs(option - seconds) < Math.abs(best - seconds) ? option : best))
        : Math.round(seconds)
    },
    { deep: true },
  )

  return { ...attach, unusedAttachments, imageLimit }
}
