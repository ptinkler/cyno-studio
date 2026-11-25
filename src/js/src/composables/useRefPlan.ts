import { computed } from 'vue'
import type { Ref } from 'vue'
import { characterImageUrl } from './charactersApi'
import type { Character } from './charactersApi'
import { chatMediaUrl } from './chatFilesApi'
import type { ComposerSettings } from './useComposerSettings'
import { planRefs } from '../utils/refPlan'

export type RefState = 'sent' | 'capped' | 'dropped' | 'off'

/** One reference image the next generation may carry, and what will happen to it. */
export interface PlannedRef {
  ref: string
  url: string
  state: RefState
  /** Where it comes from: a pin, a recent chat image, or a character. */
  source: 'pin' | 'recent' | 'character'
}

/** The part of a media card the plan reads. */
interface MediaLike {
  kind: string
  status?: string | null
  file?: string | null
  pinned?: boolean | null
}

interface Hooks {
  convId: Ref<string | null>
  messages: Ref<readonly { media: readonly MediaLike[] }[]>
  characters: Ref<readonly Character[]>
  /** Files attached to the next message (they lead the list). */
  attached: Ref<readonly string[]>
  settings: Pick<ComposerSettings, 'mode' | 'imageInfo' | 'imageLimit' | 'refChoices'>
}

// Finished images in the thread, newest first
function doneImages(messages: readonly { media: readonly MediaLike[] }[]): { file: string; pinned: boolean }[] {
  return [...messages]
    .reverse()
    .flatMap(m => [...m.media].reverse())
    .flatMap(item =>
      item.kind === 'image' && item.status === 'done' && item.file ? [{ file: item.file, pinned: !!item.pinned }] : [],
    )
}

// The references the next image will go out with (mirrors Turn._image_refs / _direct_image): Image mode sends
// attachments + pins; Auto also sends the most recent chat images. Characters go in both.
export function useRefPlan({ convId, messages, characters, attached, settings }: Hooks) {
  const { mode, imageInfo, imageLimit, refChoices } = settings
  const active = computed(() => {
    const info = imageInfo.value
    return (mode.value === 'image' || mode.value === 'auto') && (!info || info.input_modalities.includes('image'))
  })

  const planned = computed<PlannedRef[]>(() => {
    const id = convId.value
    if (!active.value) return []
    const images = doneImages(messages.value)
    const pins = images.filter(i => i.pinned).map(i => i.file)
    const recent = mode.value === 'auto' ? images.slice(0, imageLimit.value ?? undefined).map(i => i.file) : []
    const chat = [...new Set([...pins, ...recent])].filter(f => !attached.value.includes(f))
    const plan = planRefs({
      lead: attached.value,
      chat,
      characters: characters.value,
      imageLimit: imageLimit.value,
      maxRefs: imageInfo.value?.max_refs ?? null,
      choices: refChoices,
    })
    const stateOf = (ref: string): RefState =>
      plan.sent.includes(ref)
        ? 'sent'
        : plan.dropped.includes(ref)
          ? 'dropped'
          : plan.off.includes(ref)
            ? 'off'
            : 'capped'
    const urlOf = (ref: string): string => {
      const char = /^char:(\d+)\/(.+)$/.exec(ref)
      return char?.[1] && char[2] ? characterImageUrl(Number(char[1]), char[2]) : chatMediaUrl(id ?? '', ref)
    }
    const sourceOf = (ref: string): PlannedRef['source'] =>
      ref.startsWith('char:') ? 'character' : pins.includes(ref) ? 'pin' : 'recent'
    const all = [...plan.sent, ...plan.dropped, ...plan.capped, ...plan.off]
    return all
      .filter(r => !attached.value.includes(r))
      .map(ref => ({ ref, url: urlOf(ref), state: stateOf(ref), source: sourceOf(ref) }))
  })

  /** Switch a reference off (never sent) or back on. */
  function toggle(ref: string): void {
    const off = new Set(refChoices.off)
    if (off.has(ref)) off.delete(ref)
    else off.add(ref)
    refChoices.off = [...off]
    refChoices.on = refChoices.on.filter(r => r !== ref)
  }

  return { planned, toggle }
}
