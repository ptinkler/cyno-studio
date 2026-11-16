import { ref, computed } from 'vue'
import type { Ref } from 'vue'
import type { ComposerSettings } from './useComposerSettings'
import { attType } from '../utils/refItems'
import type { RefAttachment } from '../utils/refItems'

type AttachmentKind = 'image' | 'video' | 'audio'

const isAttachmentKind = (kind: string): kind is AttachmentKind =>
  kind === 'image' || kind === 'video' || kind === 'audio'

// The attachment picker (+): whether it's open and what it offers for the selected model.
export function useAttachmentPicker({
  settings,
  attachments,
}: {
  settings: Pick<ComposerSettings, 'mode' | 'activeInfo'>
  attachments: Ref<readonly RefAttachment[]>
}) {
  const { mode } = settings
  const pickerOpen = ref(false)
  // What the attachment picker (+) offers, from the selected model: a ref-to-video
  // model takes image+video refs (audio is a chat-only upload, so not in the
  // library picker); a recast/motion model takes a source video + an image;
  // everything else takes images only.
  const activeVideo = computed(() => {
    const info = settings.activeInfo.value
    return mode.value === 'video' && info && 'frame_images' in info ? info : null
  })
  const pickerKinds = computed<string[]>(() => {
    const info = activeVideo.value
    if (!info) return ['image']
    if (info.ref_mode) return (info.ref_mode.types ?? ['image', 'video']).filter(t => t !== 'audio')
    if (info.video_input) return ['image', 'video']
    return ['image']
  })
  // Per-kind caps for the picker = what's left after the current attachments
  const pickerLimits = computed<Record<string, number> | null>(() => {
    const limits = activeVideo.value?.ref_mode?.limits
    if (!limits) return null
    const counts: Record<AttachmentKind, number> = { image: 0, video: 0, audio: 0 }
    for (const attachment of attachments.value) counts[attType(attachment)]++
    const remaining: Record<string, number> = {}
    for (const [kind, cap] of Object.entries(limits)) {
      remaining[kind] = Math.max(cap - (isAttachmentKind(kind) ? counts[kind] : 0), 0)
    }
    return remaining
  })
  const pickerTitle = computed(() => (pickerKinds.value.length > 1 ? 'Add references' : 'Attach images'))
  return { pickerOpen, pickerKinds, pickerLimits, pickerTitle }
}
