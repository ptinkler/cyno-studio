// Which reference images the next image will be sent with, and which won't
// fit the image model (mirrors plan_refs in web/chat/generation.py). The priority:
// `lead` (attachments), the ones switched on, each character's main image,
// the other chat images (pins), then the characters' other images.

export const charRef = (id: number, file: string): string => `char:${String(id)}/${file}`

/** The part of a character the plan needs. */
export interface RefCharacter {
  id: number
  images?: readonly string[] | null
}

const dedupe = <T>(list: readonly T[]): T[] => [...new Set(list)]

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
  /** Cap on chat images (null = all). */
  imageLimit?: number | null
  /** The model's maximum number of refs (null = unknown). */
  maxRefs?: number | null
  /** The composer's switches: refs turned on or off. */
  choices?: { on?: readonly string[]; off?: readonly string[] }
}

export interface RefPlan {
  /** In send order. */
  sent: string[]
  dropped: string[]
  off: string[]
}

export function planRefs({
  lead = [],
  chat = [],
  characters = [],
  imageLimit = null,
  maxRefs = null,
  choices: { on = [], off: offList = [] } = {},
}: RefPlanInput): RefPlan {
  const off = new Set(offList)
  const offChat = dedupe([...lead, ...chat]).filter(r => off.has(r))
  const kept = dedupe([...lead, ...chat]).filter(r => !off.has(r))
  const chatRefs = take(kept, imageLimit)
  const split = Math.min(dedupe(lead).filter(r => !off.has(r)).length, chatRefs.length)
  const every = characterRefs(characters, off)
  const mains = characterRefs(characters, off, 1)
  const candidates = new Set([...kept, ...every]) // a switched-on chat image goes even over the slider
  const ordered = dedupe([
    ...chatRefs.slice(0, split),
    ...on.filter(r => candidates.has(r)),
    ...mains,
    ...chatRefs.slice(split),
    ...every,
  ])
  const offChars = switchedOffCharacterRefs(characters, off)
  const sent = take(ordered, maxRefs)
  return { sent, dropped: ordered.slice(sent.length), off: [...offChat, ...offChars] }
}
