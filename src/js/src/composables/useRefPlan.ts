import { computed, reactive, ref, watch } from 'vue'
import type { Ref } from 'vue'
import { characterImageUrl } from './charactersApi'
import type { Character } from './charactersApi'
import { chatMediaUrl } from './chatFilesApi'
import { fetchRefKeys } from './chatMediaApi'
import type { ComposerSettings } from './useComposerSettings'
import { planRefs } from '../utils/refPlan'

/** What happens to a reference: it goes, or it is left out (by you, the slider, or the model's maximum), or just isn't picked. */
export type RefState = 'sent' | 'capped' | 'dropped' | 'off' | 'idle'

/** One reference image the next generation may carry, and what will happen to it. */
export interface PlannedRef {
  ref: string
  url: string
  state: RefState
  /** Where it comes from: an image in the chat, or a character. */
  source: 'chat' | 'character'
}

/** The part of a media card the plan reads. */
interface MediaLike {
  kind: string
  status?: string | null
  file?: string | null
}

type Messages = readonly { media: readonly MediaLike[] }[]

interface Hooks {
  convId: Ref<string | null>
  messages: Ref<Messages>
  characters: Ref<readonly Character[]>
  /** Files attached to the next message (they lead the list). */
  attached: Ref<readonly string[]>
  settings: Pick<ComposerSettings, 'mode' | 'imageInfo' | 'imageLimit' | 'refChoices'>
  /** Content keys for refs (the same picture has the same key); the server's by default. */
  keysFor?: (convId: string, refs: string[]) => Promise<Record<string, string>>
}

/** How many unpicked chat images the bar offers. */
const IDLE_SHOWN = 12
const HIDDEN_KEY = 'cyno.refsBarHidden'

// Finished images in the thread, newest first
function doneImages(messages: Messages): string[] {
  return [...messages]
    .reverse()
    .flatMap(m => [...m.media].reverse())
    .flatMap(item => (item.kind === 'image' && item.status === 'done' && item.file ? [item.file] : []))
}

function storedHidden(): boolean {
  try {
    return localStorage.getItem(HIDDEN_KEY) === '1'
  } catch {
    return false
  }
}

// The references the next image will go out with (mirrors Turn._image_refs / _direct_image): Image mode sends
// attachments + the chat images you switched on; Auto also sends the most recent chat images. Characters go in both.
// The same picture kept in two places (a character's image that is also in the chat) shows and goes once.
export function useRefPlan({
  convId,
  messages,
  characters,
  attached,
  settings,
  keysFor = (id, refs) => fetchRefKeys(id, refs).then(r => r.keys),
}: Hooks) {
  const { mode, imageInfo, imageLimit, refChoices } = settings
  const active = computed(() => {
    const info = imageInfo.value
    return (mode.value === 'image' || mode.value === 'auto') && (!info || info.input_modalities.includes('image'))
  })
  /** The bar's reference part is folded away (the plan still applies). */
  const hidden = ref(storedHidden())
  watch(hidden, value => {
    try {
      localStorage.setItem(HIDDEN_KEY, value ? '1' : '0')
    } catch {
      // storage is off: the choice lasts for this visit only
    }
  })

  const images = computed(() => doneImages(messages.value))
  const characterRefs = computed(() => characters.value.flatMap(c => c.images.map(f => `char:${String(c.id)}/${f}`)))
  /** Everything the plan might look at, to learn which are the same picture. */
  const candidates = computed(() => [...attached.value, ...images.value, ...characterRefs.value])

  const keys = reactive<Record<string, string | undefined>>({})
  let keysConv = convId.value
  watch(
    [convId, candidates],
    ([id, list]) => {
      if (id !== keysConv) {
        for (const k of Object.keys(keys)) Reflect.deleteProperty(keys, k)
        keysConv = id
      }
      const missing = list.filter(r => !(r in keys)).slice(0, 200)
      if (!id || !missing.length) return
      keysFor(id, missing)
        .then(found => {
          if (id === convId.value) Object.assign(keys, found)
        })
        .catch(() => undefined) // without keys, only identical names count as the same
    },
    { immediate: true },
  )
  const keyOf = (r: string): string => keys[r] ?? r

  const plan = computed(() => {
    const chosen = refChoices.on.filter(r => images.value.includes(r) && !attached.value.includes(r))
    const recent = mode.value === 'auto' ? images.value : []
    const chat = [...new Set([...chosen, ...recent])].filter(f => !attached.value.includes(f))
    const input = {
      lead: attached.value,
      chat,
      characters: characters.value,
      imageLimit: imageLimit.value,
      maxRefs: imageInfo.value?.max_refs ?? null,
    }
    return { input, plan: planRefs({ ...input, choices: refChoices, key: keyOf }) }
  })

  const planned = computed<PlannedRef[]>(() => {
    const id = convId.value
    if (!active.value) return []
    const { input, plan: result } = plan.value
    const stateOf = (r: string): RefState =>
      result.sent.includes(r)
        ? 'sent'
        : result.dropped.includes(r)
          ? 'dropped'
          : result.off.includes(r)
            ? 'off'
            : 'capped'
    const urlOf = (r: string): string => {
      const char = /^char:(\d+)\/(.+)$/.exec(r)
      return char?.[1] && char[2] ? characterImageUrl(Number(char[1]), char[2]) : chatMediaUrl(id ?? '', r)
    }
    const sourceOf = (r: string): PlannedRef['source'] => (r.startsWith('char:') ? 'character' : 'chat')
    // A fixed order, so switching one off or on never moves the others
    const order = planRefs({ ...input }).sent
    const rank = (r: string): number => order.indexOf(r)
    const all = [...result.sent, ...result.dropped, ...result.capped, ...result.off].sort((a, b) => rank(a) - rank(b))
    // Copies of one picture show once; copies of an attachment not at all
    const seen = new Set(attached.value.map(keyOf))
    const shown = all.filter(r => {
      const k = keyOf(r)
      if (seen.has(k) || attached.value.includes(r)) return false
      seen.add(k)
      return true
    })
    const known = new Set(all)
    const idle = images.value
      .filter(f => !known.has(f) && !attached.value.includes(f))
      .filter(f => {
        const k = keyOf(f)
        if (seen.has(k)) return false
        seen.add(k)
        return true
      })
      .slice(0, IDLE_SHOWN)
    return [
      ...shown.map(r => ({ ref: r, url: urlOf(r), state: stateOf(r), source: sourceOf(r) })),
      ...idle.map(r => ({ ref: r, url: urlOf(r), state: 'idle' as const, source: 'chat' as const })),
    ]
  })

  /** Leave a reference out, or send it (an unpicked chat image is switched on). */
  function toggle(r: string): void {
    const state = planned.value.find(p => p.ref === r)?.state
    const out = state === 'sent' || state === 'capped' || state === 'dropped'
    const off = new Set(refChoices.off)
    const on = new Set(refChoices.on)
    if (out) {
      off.add(r)
      on.delete(r)
    } else {
      off.delete(r)
      on.add(r)
    }
    refChoices.off = [...off]
    refChoices.on = [...on]
  }

  return { planned, toggle, hidden }
}
