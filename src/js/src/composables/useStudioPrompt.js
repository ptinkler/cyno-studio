import { ref, watch } from 'vue'
import { enhanceChatPrompt, estimateChatCost } from './useChat'

const ESTIMATE_DELAY_MS = 400

// Pollo's own price for what's set up in the composer (Pollo models only), refreshed shortly after each change
export function useStudioEstimate({ mode, selected, turnSettings, attachments, draft }) {
  const estimate = ref(null)
  let timer = null
  let seq = 0
  async function refresh() {
    const kind = mode.value
    const model = ['image', 'video', 'audio'].includes(kind) ? selected[kind] : null
    const mine = ++seq
    if (!model?.startsWith('pollo/')) {
      estimate.value = null
      return
    }
    const t = turnSettings()
    const o = { video: t.video_options, audio: {}, image: t.image_options }[kind]
    const audio = kind === 'audio' ? { prompt: draft.value.trim(), audio_options: t.audio_options } : {}
    try {
      const r = await estimateChatCost({
        model,
        kind,
        ...o,
        ...audio,
        n_images: attachments.value.filter(a => !a.video && !a.audio).length,
      })
      if (mine === seq) estimate.value = r.estimate
    } catch {
      if (mine === seq) estimate.value = null
    }
  }
  watch(
    () =>
      JSON.stringify([
        mode.value,
        selected.image,
        selected.video,
        selected.audio,
        turnSettings(),
        attachments.value.length,
        mode.value === 'audio' ? draft.value : '',
      ]),
    () => {
      clearTimeout(timer)
      timer = setTimeout(refresh, ESTIMATE_DELAY_MS)
    },
    { immediate: true },
  )
  return estimate
}

// Enhance button: rewrite the draft with the text model. Only on request —
// sending never alters the prompt.
export function useStudioEnhance({ mode, selected, draft, showToast }) {
  const enhancing = ref(false)
  async function enhanceDraft() {
    const prompt = draft.value.trim()
    if (!prompt || enhancing.value) return
    if (!selected.text) return showToast('Pick a text model to enhance prompts', 'error')
    enhancing.value = true
    try {
      const r = await enhanceChatPrompt({
        prompt,
        model: selected.text,
        kind: mode.value === 'video' ? 'video' : 'image',
      })
      draft.value = r.prompt
    } catch (e) {
      showToast(e.message, 'error')
    } finally {
      enhancing.value = false
    }
  }
  return { enhancing, enhanceDraft }
}
