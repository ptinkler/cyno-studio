import { computed, watch } from 'vue'
import { useChatAttachments, MAX_ATTACHMENTS } from './useChatAttachments'
import { unusedKeys, readVideoDuration } from './studioAttachments'

// How many images a video model takes (its catalogue entry `v`, null while that is loading)
function videoImageLimit(v) {
  if (!v) return MAX_ATTACHMENTS
  // Reference-to-video: as many images as the model's ref_mode allows.
  if (v.ref_mode) return v.ref_mode.limits?.image ?? v.ref_mode.max ?? MAX_ATTACHMENTS
  if (v.reference_images) return v.max_refs || MAX_ATTACHMENTS
  return v.frame_images?.includes('last_frame') ? 2 : 1
}

// The composer's attachments on top of the chat layer: how many of each kind the selected model takes, which
// attachments it can't use, and the clip length a reference-to-video send follows.
export function useStudioAttachments({ active, settings, showToast, ensureConversation }) {
  const { selected, mode } = settings

  // Images the next message may carry: a video model takes one start frame (two with
  // first+last frame) unless it's a reference-image model; others take the usual max
  const imageLimit = () => (mode.value === 'video' ? videoImageLimit(settings.videoInfo.value) : MAX_ATTACHMENTS)
  // Video / audio reference caps — a ref_mode model takes several (its per-type
  // limit); everything else takes one.
  const refTypeLimit = kind => {
    const v = mode.value === 'video' ? settings.videoInfo.value : null
    return v?.ref_mode ? (v.ref_mode.limits?.[kind] ?? v.ref_mode.max ?? 1) : 1
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
  const unusedAttachments = computed(() => {
    const info = mode.value === 'video' ? settings.videoInfo.value : null
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
      const vid = attachments.value.find(a => a.video && a.preview)
      if (!vid) return
      const secs = await readVideoDuration(vid.preview)
      if (!secs) return
      const opts = settings.durationOptions.value || []
      settings.clipDuration.value = opts.length
        ? opts.reduce((p, c) => (Math.abs(c - secs) < Math.abs(p - secs) ? c : p))
        : Math.round(secs)
    },
    { deep: true },
  )

  return { ...attach, unusedAttachments, imageLimit }
}
