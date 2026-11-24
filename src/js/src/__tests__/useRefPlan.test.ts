import { describe, it, expect } from 'vitest'
import { reactive, ref } from 'vue'
import { useRefPlan } from '../composables/useRefPlan'
import type { Character } from '../composables/charactersApi'

const media = (file: string, pinned = false) => ({ kind: 'image', status: 'done', file, pinned })
const chars = (...list: { id: number; images: string[] }[]) => ref(list as unknown as Character[])

function plan(mode: string, limit: number | null, characters = chars()) {
  const settings = {
    mode: ref(mode),
    imageInfo: ref({ input_modalities: ['image'], max_refs: null }),
    imageLimit: ref(limit),
    refChoices: reactive<{ on: string[]; off: string[] }>({ on: [], off: [] }),
  }
  const messages = ref([{ media: [media('old.png'), media('pin.png', true)] }, { media: [media('new.png')] }])
  const rp = useRefPlan({
    convId: ref('c1'),
    messages,
    characters,
    attached: ref([]),
    settings: settings as never,
  })
  return { ...rp, settings }
}

describe('useRefPlan', () => {
  it('shows nothing in chat mode', () => {
    expect(plan('text', 6).planned.value).toEqual([])
  })

  it('Image mode offers pins only; Auto adds recent chat images', () => {
    expect(plan('image', 6).planned.value.map(r => r.ref)).toEqual(['pin.png'])
    expect(
      plan('auto', 6)
        .planned.value.map(r => r.ref)
        .sort(),
    ).toEqual(['new.png', 'old.png', 'pin.png'])
  })

  it('marks what the slider cuts, over several characters', () => {
    const two = chars({ id: 1, images: ['a0', 'a1'] }, { id: 2, images: ['b0', 'b1'] })
    const states = Object.fromEntries(plan('image', 3, two).planned.value.map(r => [r.ref, r.state]))
    expect(states).toEqual({
      'char:1/a0': 'sent',
      'char:2/b0': 'sent',
      'pin.png': 'sent',
      'char:1/a1': 'capped',
      'char:2/b1': 'capped',
    })
  })

  it('toggle switches a reference off and back on, freeing its slot', () => {
    const two = chars({ id: 1, images: ['a0', 'a1'] })
    const p = plan('image', 2, two)
    p.toggle('char:1/a0')
    const states = Object.fromEntries(p.planned.value.map(r => [r.ref, r.state]))
    expect(states['char:1/a0']).toBe('off')
    expect(states['pin.png']).toBe('sent')
    p.toggle('char:1/a0')
    expect(p.settings.refChoices.off).toEqual([])
  })
})
