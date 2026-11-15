import { ref, computed } from 'vue'

// The attachment picker (+): whether it's open and what it offers for the selected model.
export function useAttachmentPicker({ settings, attachments }) {
  const { mode } = settings
  const pickerOpen = ref(false)
  // What the attachment picker (+) offers, from the selected model: a ref-to-video
  // model takes image+video refs (audio is a chat-only upload, so not in the
  // library picker); a recast/motion model takes a source video + an image;
  // everything else takes images only.
  const pickerKinds = computed(() => {
    const info = settings.activeInfo.value
    if (mode.value !== 'video' || !info) return ['image']
    if (info.ref_mode) return (info.ref_mode.types || ['image', 'video']).filter(t => t !== 'audio')
    if (info.video_input) return ['image', 'video']
    return ['image']
  })
  // Per-kind caps for the picker = what's left after the current attachments
  const pickerLimits = computed(() => {
    const info = settings.activeInfo.value
    if (mode.value !== 'video' || !info?.ref_mode?.limits) return null
    const counts = { image: 0, video: 0, audio: 0 }
    for (const a of attachments.value) counts[a.audio ? 'audio' : a.video ? 'video' : 'image']++
    const rem = {}
    for (const [k, cap] of Object.entries(info.ref_mode.limits)) rem[k] = Math.max(cap - counts[k], 0)
    return rem
  })
  const pickerTitle = computed(() => (pickerKinds.value.length > 1 ? 'Add references' : 'Attach images'))
  return { pickerOpen, pickerKinds, pickerLimits, pickerTitle }
}
