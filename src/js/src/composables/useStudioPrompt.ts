import { ref, watch } from 'vue'
import type { Ref } from 'vue'
import type { components } from '../api/schema'
import type { Mode } from './composerPrefs'
import type { TurnSettingsBody } from './useComposerSettings'
import { enhanceChatPrompt, estimateChatCost } from './useChat'
import type { ShowToast } from './useToast'
import { messageOf } from '../utils/errors'

type Schemas = components['schemas']
type MediaKind = 'image' | 'video' | 'audio'

const ESTIMATE_DELAY_MS = 400

const MEDIA_MODES: readonly Mode[] = ['image', 'video', 'audio']
const isMediaMode = (mode: Mode): mode is MediaKind => MEDIA_MODES.includes(mode)

interface EstimateHooks {
  mode: Ref<Mode>
  selected: Record<'image' | 'video' | 'audio', string>
  turnSettings: () => TurnSettingsBody
  attachments: Ref<readonly { video: boolean; audio: boolean }[]>
  draft: Ref<string>
}

/** The inputs that price a generation of `kind`: its own options, and for speech the text. */
function priceInputs(kind: MediaKind, settings: TurnSettingsBody, draft: string): Partial<Schemas['EstimateRequest']> {
  switch (kind) {
    case 'video':
      return { ...settings.video_options }
    case 'image':
      return { ...settings.image_options }
    case 'audio':
      return { prompt: draft.trim(), audio_options: settings.audio_options }
  }
}

// Pollo's own price for what's set up in the composer (Pollo models only), refreshed shortly after each change
export function useStudioEstimate({ mode, selected, turnSettings, attachments, draft }: EstimateHooks) {
  const estimate = ref<Schemas['CreditEstimate'] | null>(null)
  let timer: ReturnType<typeof setTimeout> | undefined
  let seq = 0

  async function refresh(): Promise<void> {
    const kind = mode.value
    const mine = ++seq
    const model = isMediaMode(kind) ? selected[kind] : ''
    if (!isMediaMode(kind) || !model.startsWith('pollo/')) {
      estimate.value = null
      return
    }
    try {
      const result = await estimateChatCost({
        model,
        kind,
        ...priceInputs(kind, turnSettings(), draft.value),
        n_images: attachments.value.filter(a => !a.video && !a.audio).length,
      })
      if (mine === seq) estimate.value = result.estimate
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
      timer = setTimeout(() => void refresh(), ESTIMATE_DELAY_MS)
    },
    { immediate: true },
  )
  return estimate
}

interface EnhanceHooks {
  mode: Ref<Mode>
  selected: { text: string }
  draft: Ref<string>
  showToast: ShowToast
}

// Enhance button: rewrite the draft with the text model. Only on request —
// sending never alters the prompt.
export function useStudioEnhance({ mode, selected, draft, showToast }: EnhanceHooks) {
  const enhancing = ref(false)

  async function enhanceDraft(): Promise<void> {
    const prompt = draft.value.trim()
    if (!prompt || enhancing.value) return
    if (!selected.text) {
      showToast('Pick a text model to enhance prompts', 'error')
      return
    }
    enhancing.value = true
    try {
      const result = await enhanceChatPrompt({
        prompt,
        model: selected.text,
        kind: mode.value === 'video' ? 'video' : 'image',
      })
      draft.value = result.prompt
    } catch (e) {
      showToast(messageOf(e), 'error')
    } finally {
      enhancing.value = false
    }
  }

  return { enhancing, enhanceDraft }
}
