import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { computed, ref } from 'vue'
import type { Mode } from '../composables/composerPrefs'
import CharacterPicker from '../components/characters/CharacterPicker.vue'
import CharacterEditor from '../components/characters/CharacterEditor.vue'
import { all, one } from './dom'
import { fakeServer } from './fakeServer'
import type { Call } from './fakeServer'
import { character, imageModel } from './models'

const linh = character({ id: 1, name: 'Linh', description: 'red scarf', images: ['a.png'] })
const bao = character({ id: 2, name: 'Bao', adhoc: true })

// The picker's dialog is teleported to <body>: query the document, unmount after
const cards = () => all('.dialog .card')
const cardNames = () => cards().map(c => one('.name-text', c).textContent.trim())
const click = async (el: HTMLElement | undefined) => {
  el?.click()
  await flushPromises()
}

describe('CharacterPicker', () => {
  it('shows attached characters and attaches / detaches', async () => {
    const w = mount(CharacterPicker, { props: { modelValue: [1], characters: [linh, bao] }, attachTo: document.body })
    expect(w.findAll('.chip').map(c => c.text())).toEqual([expect.stringContaining('Linh')])
    expect(w.find('.chip img').attributes('src')).toBe('/api/characters/1/images/a.png')

    await w.find('.add').trigger('click')
    // Every character is a card; the attached one is on
    expect(cardNames()).toEqual(['Linh', 'Bao'])
    expect(cards().map(c => c.getAttribute('aria-pressed'))).toEqual(['true', 'false'])
    await click(cards()[1])
    expect(w.emitted('update:modelValue')?.[0]).toEqual([[1, 2]])
    await click(cards()[0]) // tapping an attached one detaches it
    expect(w.emitted('update:modelValue')?.[1]).toEqual([[]])

    await w.find('.chip-x').trigger('click')
    expect(w.emitted('update:modelValue')?.[2]).toEqual([[]])
    w.unmount()
  })

  it('tells same-named characters apart by where they live', async () => {
    const ownLinh = character({ id: 3, name: 'Linh', description: 'short, blue coat', adhoc: true })
    const w = mount(CharacterPicker, {
      props: { modelValue: [], characters: [linh, ownLinh] },
      attachTo: document.body,
    })
    await w.find('.add').trigger('click')
    expect(cards().map(c => one('.badge', c).textContent.trim())).toEqual(['Library', 'This chat'])
    expect(one('.sub', cards()[1] ?? document.body).textContent).toContain('blue coat')
    w.unmount()
  })

  it('emits edit and create', async () => {
    const w = mount(CharacterPicker, { props: { modelValue: [1], characters: [linh] }, attachTo: document.body })
    await w.find('.chip-main').trigger('click')
    expect(w.emitted('edit')?.[0]).toEqual([linh])
    await w.find('.add').trigger('click')
    const create = all('.dialog .actions button').find(b => b.textContent.includes('New character'))
    await click(create)
    expect(w.emitted('create')).toHaveLength(1)
    expect(cards()).toHaveLength(0) // the dialog closed for the editor
    w.unmount()
  })
})

describe('CharacterEditor', () => {
  let requests: Call[]
  beforeEach(() => {
    requests = fakeServer(({ url }) => ({
      id: 7,
      name: 'Linh',
      description: 'red scarf',
      images: url.endsWith('/from-chat') ? ['img_x.png'] : [],
      adhoc: true,
      conversation_id: 'c1',
    }))
  })

  it('creates an ad-hoc character and copies the seed image from the chat', async () => {
    const w = mount(CharacterEditor, {
      props: {
        open: false,
        conversationId: 'c1',
        seed: [{ kind: 'chat', conversationId: 'c1', file: 'g.png', preview: '/p' }],
      },
      attachTo: document.body,
    })
    await w.setProps({ open: true })
    const dialog = one('.dialog')
    expect(all('.img.pending', dialog)).toHaveLength(1)

    const name = one(HTMLInputElement, '#char-name', dialog)
    name.value = 'Linh'
    name.dispatchEvent(new Event('input'))
    const desc = one(HTMLTextAreaElement, '#char-desc', dialog)
    desc.value = 'red scarf'
    desc.dispatchEvent(new Event('input'))
    await flushPromises()
    one('.btn-primary', dialog).click()
    await flushPromises()

    // The editor's "add to defaults" toggles fetch settings/spaces on open, so
    // assert on the character-creation POSTs specifically.
    const posts = requests.filter(call => call.method === 'POST')
    expect(posts[0]).toEqual({
      method: 'POST',
      url: '/api/characters',
      body: { name: 'Linh', description: 'red scarf', conversation_id: 'c1' },
    })
    expect(posts[1]).toEqual({
      method: 'POST',
      url: '/api/characters/7/images/from-chat',
      body: { conversation_id: 'c1', file: 'g.png' },
    })
    expect(w.emitted('saved')?.[0]).toEqual([expect.objectContaining({ images: ['img_x.png'] })])
    w.unmount()
  })
})

describe('which models can use characters', () => {
  it('chat image models: reference images or conversational', async () => {
    const { chatImageModelTakesCharacters: ok } = await import('../composables/useCharacters')
    expect(ok(imageModel({ id: 'a', input_modalities: ['text', 'image'] }))).toBe(true)
    expect(ok(imageModel({ id: 'b', input_modalities: ['text'], conversational: true }))).toBe(true)
    expect(ok(imageModel({ id: 'c', input_modalities: ['text'] }))).toBe(false)
    expect(ok(null)).toBe(false)
  })

  it('the chat model picker badges image models that can', async () => {
    const { nextTick } = await import('vue')
    const ModelPicker = (await import('../components/chat/ModelPicker.vue')).default
    const w = mount(ModelPicker, {
      props: {
        kind: 'image',
        label: 'Image',
        modelValue: '',
        models: [
          imageModel({ id: 'a/refs', name: 'Refs', input_modalities: ['text', 'image'] }),
          imageModel({ id: 'b/prompt', name: 'Prompt only', input_modalities: ['text'] }),
        ],
      },
      attachTo: document.body,
    })
    await w.find('.picker-btn').trigger('click')
    await nextTick()
    const badged = w.findAll('.picker-item').filter(i => i.findAll('.item-badge').some(b => b.text() === 'characters'))
    expect(badged.map(i => i.find('.item-name').text())).toEqual(['Refs'])
    w.unmount()
  })
})

describe('useChatCharacters reloads for the open chat', () => {
  it("asks for a chat's own characters once the chat is known (a refresh opens it after the first load)", async () => {
    vi.resetModules()
    const fetchCharacters = vi.fn(({ conversationId }: { conversationId?: string }) =>
      Promise.resolve(conversationId ? [character({ id: 1, name: 'Ad hoc', conversation_id: conversationId })] : []),
    )
    vi.doMock('../composables/useCharacters', () => ({ chatImageModelTakesCharacters: () => true, fetchCharacters }))
    const { nextTick } = await import('vue')
    const { useChatCharacters } = await import('../composables/useChatCharacters')
    const convId = ref<string | null>(null)
    const c = useChatCharacters({
      convId,
      settings: {
        mode: ref<Mode>('auto'),
        selected: { text: '', image: '', video: '', audio: '' },
        textInfo: computed(() => undefined),
        imageInfo: computed(() => undefined),
        videoInfo: computed(() => undefined),
      },
      ensureConversation: vi.fn(),
      showToast: vi.fn(),
    })
    await c.loadCharacters()
    expect(c.characters.value).toEqual([])
    convId.value = 'abc'
    await nextTick()
    await vi.waitFor(() => {
      expect(c.characters.value.map(x => x.name)).toEqual(['Ad hoc'])
    })
    expect(fetchCharacters).toHaveBeenLastCalledWith({ conversationId: 'abc' })
    vi.doUnmock('../composables/useCharacters')
  })
})
