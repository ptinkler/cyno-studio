import { describe, it, expect } from 'vitest'
import { reactive, ref } from 'vue'
import { useRefPlan } from '../composables/useRefPlan'
import type { Character } from '../composables/charactersApi'

const media = (file: string) => ({ kind: 'image', status: 'done', file })
const chars = (...list: { id: number; images: string[] }[]) => ref(list as unknown as Character[])

function plan(mode: string, limit: number | null, characters = chars(), keys: Record<string, string> = {}) {
  const settings = {
    mode: ref(mode),
    imageInfo: ref({ input_modalities: ['image'], max_refs: null }),
    imageLimit: ref(limit),
    refChoices: reactive<{ on: string[]; off: string[] }>({ on: [], off: [] }),
  }
  // old.png is the oldest image in the thread, new.png the newest
  const messages = ref([{ media: [media('old.png'), media('mid.png')] }, { media: [media('new.png')] }])
  const rp = useRefPlan({
    convId: ref('c1'),
    messages,
    characters,
    attached: ref([]),
    settings: settings as never,
    keysFor: () => Promise.resolve(keys),
  })
  return { ...rp, settings }
}

const states = (p: ReturnType<typeof plan>) => Object.fromEntries(p.planned.value.map(r => [r.ref, r.state]))

describe('useRefPlan', () => {
  it('shows nothing in chat mode', () => {
    expect(plan('text', 6).planned.value).toEqual([])
  })

  it('Image mode offers the chat images unpicked; Auto sends the recent ones', () => {
    expect(states(plan('image', 6))).toEqual({ 'new.png': 'idle', 'mid.png': 'idle', 'old.png': 'idle' })
    expect(states(plan('auto', 6))).toEqual({ 'new.png': 'sent', 'mid.png': 'sent', 'old.png': 'sent' })
  })

  it('a click on an unpicked image sends it; a second click takes it back out', () => {
    const p = plan('image', 6)
    p.toggle('mid.png')
    expect(states(p)['mid.png']).toBe('sent')
    expect(p.settings.refChoices.on).toEqual(['mid.png'])
    p.toggle('mid.png')
    expect(states(p)['mid.png']).toBe('idle')
    p.toggle('mid.png')
    expect(states(p)['mid.png']).toBe('sent')
    expect(p.settings.refChoices.off).toEqual([])
    // In Auto an image goes by itself: a click leaves it out, another sends it again
    const auto = plan('auto', 6)
    auto.toggle('mid.png')
    expect(states(auto)['mid.png']).toBe('off')
    auto.toggle('mid.png')
    expect(states(auto)['mid.png']).toBe('sent')
  })

  it('marks what the slider cuts, over several characters', () => {
    const two = chars({ id: 1, images: ['a0', 'a1'] }, { id: 2, images: ['b0', 'b1'] })
    const p = plan('image', 3, two)
    p.toggle('mid.png')
    expect(states(p)).toMatchObject({
      'char:1/a0': 'sent',
      'char:2/b0': 'sent',
      'mid.png': 'sent',
      'char:1/a1': 'capped',
      'char:2/b1': 'capped',
    })
  })

  it('switching a reference off frees its slot', () => {
    const two = chars({ id: 1, images: ['a0', 'a1'] })
    const p = plan('auto', 2, two)
    p.toggle('char:1/a0')
    expect(states(p)['char:1/a0']).toBe('off')
    expect(states(p)['new.png']).toBe('sent')
  })

  it('keeps every reference in place when some are switched off', () => {
    const two = chars({ id: 1, images: ['a0', 'a1'] }, { id: 2, images: ['b0'] })
    const p = plan('auto', 6, two)
    const before = p.planned.value.map(r => r.ref)
    p.toggle('char:1/a0')
    p.toggle('mid.png')
    expect(p.planned.value.map(r => r.ref)).toEqual(before)
  })

  it('a picture kept under two names shows once, and switching it off switches off both', async () => {
    const two = chars({ id: 1, images: ['a0'] })
    const p = plan('auto', 6, two, { 'char:1/a0': 'same', 'mid.png': 'same' })
    await Promise.resolve()
    await Promise.resolve()
    const shown = p.planned.value.map(r => r.ref)
    expect(shown.filter(r => r === 'mid.png' || r === 'char:1/a0')).toHaveLength(1)
    const dup = shown.find(r => r === 'mid.png' || r === 'char:1/a0') ?? ''
    p.toggle(dup)
    expect(p.planned.value.filter(r => r.state === 'off')).toHaveLength(1)
    expect(p.planned.value.filter(r => r.state === 'sent').map(r => r.ref)).toEqual(['new.png', 'old.png'])
  })

  it('the bar can be folded away, and stays so', () => {
    const p = plan('auto', 6)
    expect(p.hidden.value).toBe(false)
    p.hidden.value = true
    return Promise.resolve().then(() => {
      expect(localStorage.getItem('cyno.refsBarHidden')).toBe('1')
      p.hidden.value = false
    })
  })
})
