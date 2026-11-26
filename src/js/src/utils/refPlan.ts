// Which reference images the next image will be sent with, and which won't
// fit the image model (mirrors plan_refs in web/chat/generation.py). The priority:
// `lead` (attachments), the ones switched on, each character's main image,
// the other chat images, then the characters' other images. The image slider
// caps the whole list; what it cuts is `capped`. The same picture kept under
// two names (a character's image that is also in the chat) goes once.

export const charRef = (id: number, file: string): string => `char:${String(id)}/${file}`

/** The part of a character the plan needs. */
export interface RefCharacter {
  id: number
  images?: readonly string[] | null
}

const dedupe = <T>(list: readonly T[]): T[] => [...new Set(list)]

// The first of each picture: refs with one `key` are the same image
function dedupeBy(list: readonly string[], key: (ref: string) => string): string[] {
  const seen = new Set<string>()
  return list.filter(ref => {
    const k = key(ref)
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

// Each character's images, up to `perCharacter` each, taken round-robin
function characterRefs(
  characters: readonly RefCharacter[],
  off: ReadonlySet<string>,
  perCharacter = Infinity,
): string[] {
  const files = characters.map(c => (c.images ?? []).map(f => charRef(c.id, f)).filter(r => !off.has(r)))
  const out: string[] = []
  const rounds = Math.min(perCharacter, Math.max(0, ...files.map(f => f.length)))
  for (let i = 0; i < rounds; i++) {
    for (const f of files) {
      const ref = f[i]
      if (ref !== undefined) out.push(ref)
    }
  }
  return out
}

// The first `n` of a list (all of it when `n` is null)
const take = <T>(list: readonly T[], n: number | null): T[] => (n === null ? [...list] : list.slice(0, n))

// Character image refs the user switched off
const switchedOffCharacterRefs = (characters: readonly RefCharacter[], off: ReadonlySet<string>): string[] =>
  characters.flatMap(c => (c.images ?? []).map(f => charRef(c.id, f))).filter(r => off.has(r))

export interface RefPlanInput {
  /** Chat image refs that lead (attachments). */
  lead?: readonly string[]
  /** The other chat image refs (pins). */
  chat?: readonly string[]
  characters?: readonly RefCharacter[]
  /** Cap on all references sent (null = all). */
  imageLimit?: number | null
  /** The model's maximum number of refs (null = unknown). */
  maxRefs?: number | null
  /** The composer's switches: refs turned on or off. */
  choices?: { on?: readonly string[]; off?: readonly string[] }
  /** A ref's content key: refs with the same key are one picture (default: its name). */
  key?: (ref: string) => string
}

export interface RefPlan {
  /** In send order. */
  sent: string[]
  /** Left out because the model takes fewer. */
  dropped: string[]
  /** Left out because of the image slider. */
  capped: string[]
  off: string[]
}

type Choices = NonNullable<RefPlanInput['choices']>

export function planRefs({
  lead = [],
  chat = [],
  characters = [],
  imageLimit = null,
  maxRefs = null,
  choices,
  key = ref => ref,
}: RefPlanInput): RefPlan {
  const { ordered: all, off } = orderRefs({ lead, chat, characters }, choices, key)
  const ordered = take(all, imageLimit)
  const sent = take(ordered, maxRefs)
  return { sent, dropped: ordered.slice(sent.length), capped: all.slice(ordered.length), off }
}

/** Every ref in send order (before the model's maximum cuts it), and the ones the user switched off. */
function orderRefs(
  { lead, chat, characters }: Required<Pick<RefPlanInput, 'lead' | 'chat' | 'characters'>>,
  { on = [], off: offList = [] }: Choices = {},
  key: (ref: string) => string = ref => ref,
): { ordered: string[]; off: string[] } {
  // Switching one off switches off every copy of the same picture
  const offKeys = new Set(offList.map(key))
  const everyRef = [...lead, ...chat, ...characterRefs(characters, new Set())]
  const off = new Set(everyRef.filter(r => offKeys.has(key(r))))
  const offChat = dedupe([...lead, ...chat]).filter(r => off.has(r))
  const kept = dedupe([...lead, ...chat]).filter(r => !off.has(r))
  const split = Math.min(dedupe(lead).filter(r => !off.has(r)).length, kept.length)
  const every = characterRefs(characters, off)
  const mains = characterRefs(characters, off, 1)
  const candidates = new Set([...kept, ...every])
  const ordered = dedupeBy(
    [...kept.slice(0, split), ...on.filter(r => candidates.has(r)), ...mains, ...kept.slice(split), ...every],
    key,
  )
  return { ordered, off: [...offChat, ...switchedOffCharacterRefs(characters, off)] }
}
