import { beforeEach, describe, it, expect, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ChatMessage from '../components/chat/ChatMessage.vue'
import type { MediaCard } from '../composables/chatConversationsApi'
import type { UiMessage } from '../composables/studioTypes'
import { one } from './dom'
import { fakeServer } from './fakeServer'
import { mediaCard, uiMessage } from './models'

const image = mediaCard({ id: 'm1', file: 'img_a.png', prompt: 'a fox' })
const video = mediaCard({ id: 'm2', kind: 'video', file: 'vid_a.mp4' })

describe('ChatMessage "make a video from this image"', () => {
  it('is offered on generated images, not videos', async () => {
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 1,
          role: 'assistant',
          content: '',
          status: 'done',
          media: [image, video],
        }),
      },
    })
    const buttons = w.findAll('button[data-tip="Use in Video mode"]')
    expect(buttons).toHaveLength(1)
    await buttons[0]?.trigger('click')
    expect(w.emitted('use-image')).toEqual([[{ file: 'img_a.png', mode: 'video' }]])
  })

  it("is offered on the user's own attachments", async () => {
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 2,
          role: 'user',
          content: 'look',
          status: 'done',
          media: [{ id: 'u1', kind: 'image', source: 'upload', status: 'done', file: 'up_b.png' }],
        }),
      },
    })
    await w.find('button[data-tip="Use in Video mode"]').trigger('click')
    expect(w.emitted('use-image')).toEqual([[{ file: 'up_b.png', mode: 'video' }]])
  })

  it('passes the file to the image viewer so it can offer it too', async () => {
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 3,
          role: 'assistant',
          content: '',
          status: 'done',
          media: [image],
        }),
      },
    })
    await w.find('.media-item img').trigger('click')
    expect(w.emitted('open-media')?.[0]?.[0]).toMatchObject({ kind: 'image', file: 'img_a.png' })
  })
})

describe('ChatMessage media settings', () => {
  it('shows the settings a video was made with, while rendering and when done', async () => {
    const params = {
      duration: 5,
      resolution: '480p',
      aspect_ratio: null,
      first_frame: 'img_a.png',
      generate_audio: true,
    }
    const pending = mediaCard({ id: 'v1', kind: 'video', status: 'pending', file: null, prompt: 'waves', params })
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 4,
          role: 'assistant',
          content: '',
          status: 'done',
          created_at: new Date().toISOString(),
          media: [pending],
        }),
      },
    })
    expect(w.find('.pending-specs').text()).toBe('from image · 5s · 480p · audio')
    await w.setProps({
      message: uiMessage({
        id: 4,
        role: 'assistant',
        content: '',
        status: 'done',
        media: [{ ...pending, status: 'done', file: 'vid.mp4' }],
      }),
    })
    expect(w.find('.foot-specs').text()).toBe('from image · 5s · 480p · audio')
  })

  it('shows ratio and resolution for images', () => {
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 5,
          role: 'assistant',
          content: '',
          status: 'done',
          media: [{ ...image, model: 'pollo/seedream', params: { aspect_ratio: '16:9', resolution: '2K', refs: [] } }],
        }),
      },
    })
    expect(w.find('.foot-specs').text()).toBe('2K · 16:9')
  })
})

describe('ChatMessage mode tag', () => {
  const user = (mode: UiMessage['mode']) =>
    mount(ChatMessage, {
      props: {
        convId: 'c1',
        canEdit: true,
        message: uiMessage({ id: 6, role: 'user', content: 'waves', status: 'done', mode }),
      },
    })

  it('marks prompts sent outside Auto mode', () => {
    expect(user('video').find('.mode-tag').text()).toBe('🎬 Video')
    expect(user('image').find('.mode-tag').text()).toBe('🖼 Image')
  })

  it('stays quiet for Auto and older messages', () => {
    expect(user('auto').find('.mode-tag').exists()).toBe(false)
    expect(user(null).find('.mode-tag').exists()).toBe(false)
  })
})

describe('ChatMessage "make a picture" and text-to-media', () => {
  it('offers a picture-from-image button beside the video one', async () => {
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 7,
          role: 'assistant',
          content: '',
          status: 'done',
          media: [image],
        }),
      },
    })
    await w.find('button[data-tip="Use in Image mode"]').trigger('click')
    expect(w.emitted('use-image')).toEqual([[{ file: 'img_a.png', mode: 'image' }]])
  })

  it('no longer offers the reply-text-to-prompt buttons', () => {
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({ id: 9, role: 'assistant', content: 'Some words.', status: 'done', media: [] }),
      },
    })
    expect(w.find('button[data-tip$="as an Image-mode prompt"]').exists()).toBe(false)
    expect(w.find('button[data-tip$="as a Video-mode prompt"]').exists()).toBe(false)
  })
})

describe('ChatMessage delete', () => {
  it('is offered on saved prompts, not replies', async () => {
    const user = mount(ChatMessage, {
      props: {
        convId: 'c1',
        canEdit: true,
        message: uiMessage({
          id: 7,
          role: 'user',
          content: 'draw a cat',
          status: 'done',
          media: [],
        }),
      },
    })
    await user.find('button[data-tip^="Delete prompt"]').trigger('click')
    expect(user.emitted('delete')).toHaveLength(1)
    const reply = mount(ChatMessage, {
      props: {
        convId: 'c1',
        canEdit: false,
        message: uiMessage({
          id: 8,
          role: 'assistant',
          content: 'Meow',
          status: 'done',
          media: [],
        }),
      },
    })
    expect(reply.find('button[data-tip^="Delete prompt"]').exists()).toBe(false)
  })
})

describe('ChatMessage branch to a new chat', () => {
  it('is offered on saved prompts, not replies', async () => {
    const user = mount(ChatMessage, {
      props: {
        convId: 'c1',
        canEdit: true,
        message: uiMessage({
          id: 7,
          role: 'user',
          content: 'draw a cat',
          status: 'done',
          media: [],
        }),
      },
    })
    await user.find('button[data-tip^="Branch from here"]').trigger('click')
    expect(user.emitted('fork')).toHaveLength(1)
    const reply = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 8,
          role: 'assistant',
          content: 'Meow',
          status: 'done',
          media: [],
        }),
      },
    })
    expect(reply.find('button[data-tip^="Branch from here"]').exists()).toBe(false)
  })
})

describe('ChatMessage branches', () => {
  it('offers Branch on replies too', async () => {
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        canBranch: true,
        message: uiMessage({
          id: 9,
          role: 'assistant',
          content: 'Meow',
          status: 'done',
          media: [],
        }),
      },
    })
    await w.find('button[data-tip^="Branch from here"]').trigger('click')
    expect(w.emitted('fork')).toHaveLength(1)
  })

  it('lists the chats branched off a message and opens one', async () => {
    const forks = [
      { id: 'b1', title: 'Fox (branch)' },
      { id: 'b2', title: 'Other' },
    ]
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 7,
          role: 'user',
          content: 'draw a fox',
          status: 'done',
          media: [],
          forks,
        }),
      },
    })
    expect(w.find('.fork-toggle').text()).toBe('⑂ 2 branches')
    await w.find('.fork-toggle').trigger('click')
    const items = w.findAll('.fork-item')
    expect(items.map(i => i.text())).toEqual(['Fox (branch)', 'Other'])
    await items[1]?.trigger('click')
    expect(w.emitted('open-chat')).toEqual([['b2']])
    expect(w.find('.fork-menu').exists()).toBe(false)
  })
})

describe('ChatMessage refs sent', () => {
  it('says when a model took fewer reference images than were picked', () => {
    const item = { ...image, params: { refs: ['a.png', 'b.png', 'c.png'], refs_used: 1 } }
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 9,
          role: 'assistant',
          content: '',
          status: 'done',
          media: [item],
        }),
      },
    })
    expect(w.find('.media-caption').text()).toContain('1 of 3 refs')
    const all = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 10,
          role: 'assistant',
          content: '',
          status: 'done',
          media: [{ ...image, params: { refs: ['a.png', 'b.png'] } }],
        }),
      },
    })
    expect(all.find('.media-caption').text()).toContain('2 refs')
  })

  describe('when a character image is not on this server', () => {
    // Character images stay behind when a chat is exported, so the card points at one that isn't here
    const withGone = { ...image, params: { refs: ['a.png', 'char:7/gone.png', 'char:7/here.png'] } }
    const asks: string[] = []

    beforeEach(() => {
      asks.length = 0
      vi.stubGlobal(
        'Image',
        class {
          onload: (() => void) | null = null
          onerror: (() => void) | null = null
          set src(url: string) {
            asks.push(url)
            queueMicrotask(() => (url.includes('gone') ? this.onerror : this.onload)?.())
          }
        },
      )
    })

    const mountIt = () =>
      mount(ChatMessage, {
        attachTo: document.body,
        props: {
          convId: 'c1',
          message: uiMessage({ id: 12, role: 'assistant', content: '', status: 'done', media: [withGone] }),
        },
      })

    it("asks about only the character's images, and leaves the missing one out of the count", async () => {
      const w = mountIt()
      await flushPromises()
      expect(asks).toEqual(['/api/characters/7/images/gone.png', '/api/characters/7/images/here.png'])
      expect(w.find('.media-caption').text()).toContain('2 refs')
      expect(w.find('.media-caption').text()).not.toContain('3 refs')
      w.unmount()
    })

    it('shows a gap, not a broken picture, in the hover preview', async () => {
      const w = mountIt()
      await flushPromises()
      await w.find('.caption-refs').trigger('mouseenter')
      expect(document.querySelectorAll('.refs-peek .ref-gone')).toHaveLength(1)
      expect([...document.querySelectorAll('.refs-peek img')].map(i => i.getAttribute('src'))).toEqual([
        '/api/chat/media/c1/a.png',
        '/api/characters/7/images/here.png',
      ])
      expect(document.querySelector('.refs-peek-title')?.textContent).toContain('1 no longer available')
      w.unmount()
    })
  })

  it('shows thumbnails of the refs on hover, dimming the ones not sent', async () => {
    const item = { ...image, params: { refs: ['a.png', 'char:7/b.png'], refs_used: 1 } }
    const w = mount(ChatMessage, {
      attachTo: document.body,
      props: {
        convId: 'c1',
        message: uiMessage({ id: 11, role: 'assistant', content: '', status: 'done', media: [item] }),
      },
    })
    await w.find('.caption-refs').trigger('mouseenter')
    const imgs = document.querySelectorAll('.refs-peek img')
    expect([...imgs].map(i => i.getAttribute('src'))).toEqual([
      '/api/chat/media/c1/a.png',
      '/api/characters/7/images/b.png',
    ])
    expect([...imgs].map(i => i.classList.contains('unused'))).toEqual([false, true])
    await w.find('.caption-refs').trigger('mouseleave')
    expect(document.querySelector('.refs-peek')).toBeNull()
    w.unmount()
  })
})

describe('ChatMessage request view', () => {
  it('shows what a card sent to the provider', async () => {
    const request = { model: 'seedream-v5-pro-edit', prompt: 'a fox', images: ['data:image/png;base64,… (90 KB)'] }
    const w = mount(ChatMessage, {
      attachTo: document.body,
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 3,
          role: 'assistant',
          content: '',
          status: 'done',
          media: [
            {
              id: 'm',
              kind: 'image',
              source: 'generated',
              status: 'error',
              error: 'Venice: blocked',
              prompt: 'a fox',
              model: 'venice/seedream-v5-pro',
              request,
              response: { error: 'Your prompt violates the content policy' },
            },
          ],
        }),
      },
    })
    await w.find('button[data-tip="View request"]').trigger('click')
    const dialog = one('.req-dialog')
    expect(dialog.textContent).toContain('"model": "seedream-v5-pro-edit"')
    expect(dialog.textContent).toContain('Venice: blocked')
    expect(dialog.textContent).toContain('"error": "Your prompt violates the content policy"')
    w.unmount()
  })

  it('has no request button for media without one', () => {
    const w = mount(ChatMessage, {
      props: {
        convId: 'c1',
        message: uiMessage({
          id: 4,
          role: 'assistant',
          content: '',
          status: 'done',
          media: [
            { id: 'n', kind: 'image', source: 'generated', status: 'done', file: 'x.png', prompt: 'p', model: 'a/b' },
          ],
        }),
      },
    })
    expect(w.find('button[data-tip="View request"]').exists()).toBe(false)
  })
})

const reply = (media: MediaCard[], extra: Partial<UiMessage> = {}) => ({
  props: {
    convId: 'c1',
    message: uiMessage({ id: 42, role: 'assistant', content: 'Here you go.', status: 'done', media, ...extra }),
  },
})

describe('ChatMessage edit and redo a picture in place', () => {
  it('offers Edit only on a picture, Redo on anything it can make again', () => {
    const img = mount(ChatMessage, reply([image]))
    expect(img.find('button[data-tip^="Edit picture"]').exists()).toBe(true)
    expect(img.find('button[data-tip^="Redo picture"]').exists()).toBe(true)
    const vid = mount(ChatMessage, reply([{ ...video, prompt: 'waves' }]))
    expect(vid.find('button[data-tip^="Edit picture"]').exists()).toBe(false)
    expect(vid.find('button[data-tip^="Redo picture"]').exists()).toBe(true)
  })

  it('Edit opens an empty box and asks to edit this picture', async () => {
    const w = mount(ChatMessage, reply([image]))
    await w.find('button[data-tip^="Edit picture"]').trigger('click')
    const box = w.find<HTMLTextAreaElement>('.prompt-box textarea')
    expect(box.element.value).toBe('')
    expect(box.attributes('placeholder')).toBe('Describe the change…')
    await box.setValue('give it a hat')
    await w.find('.prompt-box .edit-send').trigger('click')
    expect(w.emitted('regenerate')?.[0]?.[0]).toEqual({
      mediaId: 'm1',
      model: null,
      prompt: 'give it a hat',
      edit: true,
      replace: true,
    })
  })

  it('Redo pre-fills the prompt it was made with and does not edit', async () => {
    const w = mount(ChatMessage, reply([image]))
    await w.find('button[data-tip^="Redo picture"]').trigger('click')
    expect(w.find<HTMLTextAreaElement>('.prompt-box textarea').element.value).toBe('a fox')
    await w.find('.prompt-box .edit-send').trigger('click')
    expect(w.emitted('regenerate')?.[0]?.[0]).toMatchObject({ prompt: 'a fox', edit: false, replace: true })
  })

  it('will not send an empty prompt', async () => {
    const w = mount(ChatMessage, reply([image]))
    await w.find('button[data-tip^="Edit picture"]').trigger('click')
    expect(w.find('.prompt-box .edit-send').attributes('disabled')).toBeDefined()
    await w.find('.prompt-box .edit-send').trigger('click')
    expect(w.emitted('regenerate')).toBeUndefined()
  })

  it('Cancel closes the box without regenerating', async () => {
    const w = mount(ChatMessage, reply([image]))
    await w.find('button[data-tip^="Redo picture"]').trigger('click')
    await w.find('.prompt-box .meta-btn').trigger('click')
    expect(w.find('.prompt-box').exists()).toBe(false)
    expect(w.emitted('regenerate')).toBeUndefined()
  })

  it('neither is offered while the reply is still streaming', () => {
    const w = mount(ChatMessage, reply([image], { status: 'streaming' }))
    expect(w.find('button[data-tip^="Edit picture"]').exists()).toBe(false)
    expect(w.find('button[data-tip^="Redo picture"]').exists()).toBe(false)
  })
})

describe('ChatMessage links', () => {
  const link = (content: string) => mount(ChatMessage, reply([], { content })).find('.markdown a')

  it('open in a new tab with no handle back to the chat', () => {
    const a = link('See [the docs](https://example.com/x).')
    expect(a.attributes('href')).toBe('https://example.com/x')
    expect(a.attributes('target')).toBe('_blank')
    expect(a.attributes('rel')).toBe('noopener noreferrer')
  })

  it('still strip a script address', () => {
    const a = link('[click](javascript:alert(1))')
    expect(a.attributes('href') ?? '').not.toContain('javascript')
  })
})

describe('ChatMessage cost', () => {
  const priced = { ...image, model: 'venice/seedream-v5-pro', cost: 0.06 }
  interface Hoverable {
    find: (selector: string) => { trigger: (event: string) => Promise<void> }
    findAll: (selector: string) => { element: Element }[]
  }
  const hover = async (w: Hoverable) => {
    await w.find('.msg-meta .cost').trigger('mouseenter')
    return w.findAll('.pop-row').map(r => [...r.element.children].map(c => c.textContent).join(' '))
  }

  it('shows one cost, the total, and nothing of the breakdown until asked', () => {
    const w = mount(ChatMessage, reply([priced], { cost: 0.07 }))
    expect(w.find('.msg-meta .cost').text()).toBe('$0.07')
    expect(w.find('.pop').exists()).toBe(false)
  })

  it('opens what the cost is made of on hover, and closes it again', async () => {
    const w = mount(ChatMessage, reply([priced], { cost: 0.07 }))
    expect(await hover(w)).toEqual(['Text $0.01', 'seedream-v5-pro $0.06', 'Total $0.07'])
    await w.find('.msg-meta .cost').trigger('mouseleave')
    expect(w.find('.pop').exists()).toBe(false)
  })

  it('opens on a tap or keyboard focus too', async () => {
    const w = mount(ChatMessage, reply([priced], { cost: 0.07 }))
    await w.find('.msg-meta .chip-btn').trigger('click')
    expect(w.find('.pop').exists()).toBe(true)
  })

  it("doesn't repeat the picture's cost on its own card", () => {
    const w = mount(ChatMessage, reply([priced], { cost: 0.07 }))
    expect(w.find('.media-caption').text()).not.toContain('$0.06')
  })

  it('has no cost when the reply cost nothing', () => {
    expect(
      mount(ChatMessage, reply([image]))
        .find('.cost')
        .exists(),
    ).toBe(false)
  })

  it('sits in the text bar when there are no pictures', () => {
    const w = mount(ChatMessage, reply([], { cost: 0.002 }))
    expect(w.find('.text-bar .cost').text()).toBe('$0.0020')
  })
})

describe('ChatMessage references on an Edit or Redo', () => {
  const withRefs: MediaCard = { ...image, params: { refs: ['up_1.png', 'char:3/c.png', 'up_2.png'] } }
  beforeEach(() => {
    // jsdom has no object URLs: a pasted picture's thumbnail needs one
    URL.createObjectURL = vi.fn(() => 'blob:preview')
    URL.revokeObjectURL = vi.fn()
  })
  const thumbs = (w: { findAll: (selector: string) => { attributes: (name: string) => string | undefined }[] }) =>
    w.findAll('.prompt-box .att-media img').map(i => i.attributes('src'))

  it('Redo starts with the pictures the card was made from, without the characters', async () => {
    const w = mount(ChatMessage, reply([withRefs]))
    await w.find('button[data-tip^="Redo picture"]').trigger('click')
    expect(thumbs(w)).toEqual(['/api/chat/media/c1/up_1.png', '/api/chat/media/c1/up_2.png'])
  })

  it('Edit starts with none: the picture itself is the reference', async () => {
    const w = mount(ChatMessage, reply([withRefs]))
    await w.find('button[data-tip^="Edit picture"]').trigger('click')
    expect(thumbs(w)).toEqual([])
    expect(w.find('.prompt-box .addtile').exists()).toBe(true)
  })

  it('sends no references when they are left as they were', async () => {
    const w = mount(ChatMessage, reply([withRefs]))
    await w.find('button[data-tip^="Redo picture"]').trigger('click')
    await w.find('.prompt-box .edit-send').trigger('click')
    expect(w.emitted('regenerate')?.[0]?.[0]).not.toHaveProperty('refs')
  })

  it('sends the pictures that are left once one is taken away', async () => {
    fakeServer(() => ({ deleted: false }))
    const w = mount(ChatMessage, reply([withRefs]))
    await w.find('button[data-tip^="Redo picture"]').trigger('click')
    await w.find('.prompt-box .attx').trigger('click')
    await w.find('.prompt-box .edit-send').trigger('click')
    expect(w.emitted('regenerate')?.[0]?.[0]).toMatchObject({ refs: ['up_2.png'], edit: false })
  })

  it('an edit sends what was added', async () => {
    const w = mount(ChatMessage, reply([image]))
    await w.find('button[data-tip^="Edit picture"]').trigger('click')
    // Pasting a picture uploads it to the chat first, then it is a reference
    fakeServer(() => ({ file: 'up_new.png' }))
    const png = new File(['x'], 'p.png', { type: 'image/png' })
    await w.find('.prompt-box textarea').trigger('paste', { clipboardData: { files: [png] } })
    await flushPromises()
    await w.find('.prompt-box textarea').setValue('as a cat')
    await w.find('.prompt-box .edit-send').trigger('click')
    expect(w.emitted('regenerate')?.[0]?.[0]).toMatchObject({ edit: true, prompt: 'as a cat', refs: ['up_new.png'] })
  })

  it('waits for an upload to finish before sending', async () => {
    const w = mount(ChatMessage, reply([image]))
    await w.find('button[data-tip^="Edit picture"]').trigger('click')
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => undefined)),
    )
    const png = new File(['x'], 'p.png', { type: 'image/png' })
    await w.find('.prompt-box textarea').trigger('paste', { clipboardData: { files: [png] } })
    await flushPromises()
    await w.find('.prompt-box textarea').setValue('as a cat')
    expect(w.find('.prompt-box .edit-send').attributes('disabled')).toBeDefined()
  })

  it('cancelling throws away what was uploaded for it', async () => {
    const calls = fakeServer(() => ({ file: 'up_new.png', deleted: true }))
    const w = mount(ChatMessage, reply([image]))
    await w.find('button[data-tip^="Edit picture"]').trigger('click')
    const png = new File(['x'], 'p.png', { type: 'image/png' })
    await w.find('.prompt-box textarea').trigger('paste', { clipboardData: { files: [png] } })
    await flushPromises()
    await w.find('.prompt-box .meta-btn').trigger('click')
    await flushPromises()
    expect(calls.some(c => c.method === 'DELETE' && c.url.endsWith('/attachments/up_new.png'))).toBe(true)
  })
})

describe('ChatMessage earlier versions of a picture', () => {
  const versioned: MediaCard = {
    ...image,
    file: 'img_new.png',
    prompt: 'a fox in a hat',
    versions: [{ file: 'img_a.png', prompt: 'a fox' }],
  }

  it('shows no arrows until a picture has been replaced', () => {
    expect(
      mount(ChatMessage, reply([image]))
        .find('.ver-nav')
        .exists(),
    ).toBe(false)
  })

  it('counts the live picture as the last version', () => {
    const w = mount(ChatMessage, reply([versioned]))
    expect(w.find('.ver-nav span').text()).toBe('2/2')
  })

  it('asks for the picture it replaced to become the real one', async () => {
    const w = mount(ChatMessage, { props: { ...reply([versioned]).props, canSwitch: true } })
    const [back, forward] = w.findAll('.ver-nav button')
    expect(forward?.attributes('disabled')).toBeDefined() // already on the newest
    await back?.trigger('click')
    expect(w.emitted('media-version')).toEqual([[{ mediaId: versioned.id, index: 0 }]])
  })

  it('shows where the live picture sits once an earlier one was chosen', () => {
    const chosen: MediaCard = { ...versioned, file: 'img_a.png', versions: [{ file: 'img_new.png' }], version_shown: 0 }
    const w = mount(ChatMessage, { props: { ...reply([chosen]).props, canSwitch: true } })
    expect(w.find('.ver-nav span').text()).toBe('1/2')
    expect(w.find('.media-item img').attributes('src')).toContain('img_a.png')
    const [back, forward] = w.findAll('.ver-nav button')
    expect(back?.attributes('disabled')).toBeDefined()
    expect(forward?.attributes('disabled')).toBeUndefined()
  })

  it('cannot switch mid-reply', () => {
    const w = mount(ChatMessage, reply([versioned]))
    for (const b of w.findAll('.ver-nav button')) expect(b.attributes('disabled')).toBeDefined()
  })

  it('offers the previous picture back after a failed redo', async () => {
    const failed: MediaCard = { ...versioned, status: 'error', file: null, error: 'nope' }
    const w = mount(ChatMessage, { props: { ...reply([failed]).props, canSwitch: true } })
    await w.find('button[data-tip^="Keep previous picture"]').trigger('click')
    expect(w.emitted('media-version')).toEqual([[{ mediaId: failed.id, index: 0 }]])
  })
})

describe('ChatMessage edit and redo the text in place', () => {
  // Offered on any finished reply (the feed passes canReword); the pictures stay
  const rewordable = (media: MediaCard[], extra: Partial<UiMessage> = {}) => {
    const r = reply(media, extra)
    return { props: { ...r.props, canReword: true, canSwitch: true } }
  }

  it('Redo text is offered on a reply that made media, and emits reword with no instruction', async () => {
    const w = mount(ChatMessage, rewordable([image]))
    await w.find('button[data-tip^="Redo text"]').trigger('click')
    expect(w.emitted('reword')).toEqual([['']])
  })

  it('a picture-only reply keeps Redo text under the picture, not in a bar above it', async () => {
    const w = mount(ChatMessage, rewordable([image], { content: '' }))
    expect(w.find('.text-bar').exists()).toBe(false)
    await w.find('.msg-meta button[data-tip^="Redo text"]').trigger('click')
    expect(w.emitted('reword')).toEqual([['']])
  })

  it('Redo text is not offered on a reply with no media to keep (Retry covers it)', () => {
    expect(mount(ChatMessage, rewordable([])).find('button[data-tip^="Redo text"]').exists()).toBe(false)
  })

  it('Edit text sends the instruction', async () => {
    const w = mount(ChatMessage, rewordable([image]))
    await w.find('button[data-tip^="Edit text"]').trigger('click')
    await w.find('.text-box textarea').setValue('make it shorter')
    await w.find('.text-box .edit-send').trigger('click')
    expect(w.emitted('reword')).toEqual([['make it shorter']])
    expect(w.find('.text-box').exists()).toBe(false)
  })

  it('is not offered while the reply cannot be reworded', () => {
    const w = mount(ChatMessage, reply([image]))
    expect(w.find('button[data-tip^="Redo text"]').exists()).toBe(false)
    expect(w.find('button[data-tip^="Edit text"]').exists()).toBe(false)
  })

  it('is not offered while a picture is still being made', () => {
    const w = mount(ChatMessage, rewordable([{ ...image, status: 'pending', file: null }]))
    expect(w.find('button[data-tip^="Redo text"]').exists()).toBe(false)
  })
})

describe('ChatMessage earlier wordings of the text', () => {
  const worded = (extra: { canSwitch?: boolean } = {}) => ({
    props: { ...reply([image]).props, canSwitch: true, ...extra },
  })
  const withVersions = (shown: number, extra: { canSwitch?: boolean } = {}) => {
    const base = reply([image], { text_versions: 3, text_shown: shown })
    return { props: { ...base.props, canSwitch: true, ...extra } }
  }

  it('has no text arrows until the text has been rewritten', () => {
    expect(mount(ChatMessage, worded()).find('.text-ver').exists()).toBe(false)
  })

  it('shows which wording is up, apart from the picture versions', () => {
    const w = mount(ChatMessage, withVersions(1))
    expect(w.find('.text-ver span').text()).toBe('text 2/3')
    expect(w.find('.ver-nav').exists()).toBe(false) // the picture has no versions of its own
  })

  it('asks for the neighbouring wording', async () => {
    const w = mount(ChatMessage, withVersions(1))
    const [back, forward] = w.findAll('.text-ver button')
    await back?.trigger('click')
    await forward?.trigger('click')
    expect(w.emitted('text-version')).toEqual([[0], [2]])
  })

  it('cannot switch mid-reply', () => {
    const w = mount(ChatMessage, withVersions(1, { canSwitch: false }))
    for (const b of w.findAll('.text-ver button')) expect(b.attributes('disabled')).toBeDefined()
  })
})

describe('ChatMessage renders one element per media kind', () => {
  // Regression: the version arrows were inserted between the <img v-if> and
  // its <video v-else>, which breaks Vue's conditional chain — the <video>
  // then rendered for images too, putting a play control on a picture.
  const media = (extra: Partial<MediaCard>) => ({
    props: {
      convId: 'c1',
      message: uiMessage({
        id: 50,
        role: 'assistant',
        content: '',
        status: 'done',
        media: [mediaCard({ id: 'm1', prompt: 'a fox', ...extra })],
      }),
    },
  })

  it('an image is an <img> and nothing else', () => {
    const w = mount(ChatMessage, media({ kind: 'image', file: 'a.png' }))
    expect(w.findAll('.media-item img')).toHaveLength(1)
    expect(w.find('video').exists()).toBe(false)
    expect(w.find('audio').exists()).toBe(false)
  })

  it('an image with earlier versions is still only an <img>', () => {
    const w = mount(ChatMessage, media({ kind: 'image', file: 'b.png', versions: [{ file: 'a.png' }] }))
    expect(w.find('.ver-nav').exists()).toBe(true)
    expect(w.find('video').exists()).toBe(false)
  })

  it('a video is a <video> and not an <img>', () => {
    const w = mount(ChatMessage, media({ kind: 'video', file: 'a.mp4' }))
    expect(w.findAll('video')).toHaveLength(1)
    expect(w.find('.media-item img').exists()).toBe(false)
  })

  it('audio is an <audio> and not a <video>', () => {
    const w = mount(ChatMessage, media({ kind: 'audio', file: 'a.mp3' }))
    expect(w.findAll('audio')).toHaveLength(1)
    expect(w.find('video').exists()).toBe(false)
  })
})

describe('ChatMessage a failed picture can be changed and retried', () => {
  const failed = {
    props: {
      convId: 'c1',
      message: uiMessage({
        id: 60,
        role: 'assistant',
        content: '',
        status: 'done',
        media: [
          {
            id: 'm1',
            kind: 'image',
            source: 'generated',
            status: 'error',
            error: 'flagged',
            prompt: 'a fox',
            model: 'i/model',
          },
        ],
      }),
    },
  }

  it('offers Change prompt beside Retry', async () => {
    const w = mount(ChatMessage, failed)
    expect(w.find('button[data-tip^="Retry on selected model"]').exists()).toBe(true)
    await w.find('button[data-tip="Retry with a new prompt"]').trigger('click')
    const box = w.find<HTMLTextAreaElement>('.prompt-box textarea')
    expect(box.element.value).toBe('a fox') // pre-filled with what failed
    await box.setValue('a fox, softer lighting')
    await w.find('.prompt-box .edit-send').trigger('click')
    expect(w.emitted('regenerate')?.[0]?.[0]).toMatchObject({
      mediaId: 'm1',
      prompt: 'a fox, softer lighting',
      edit: false,
      replace: true,
    })
  })
})
