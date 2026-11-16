import { describe, it, expect, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import DefaultToggles from '../components/chat/DefaultToggles.vue'
import { useChatDefaults } from '../composables/useChatDefaults'
import type { Space } from '../composables/studioTypes'
import { asRecord } from '../utils/storage'
import { fakeServer } from './fakeServer'
import type { Call } from './fakeServer'
import { space } from './models'

const EMPTY = { default_character_ids: [], default_instruction_ids: [], default_instruction_group_ids: [] }

/** DefaultToggles exposes `commit` for the editor that holds it. Typed here: typed ESLint can't read .vue files. */
const commit = (wrapper: { vm: unknown }, id: number): Promise<void> =>
  (wrapper.vm as { commit: (id: number) => Promise<void> }).commit(id)

describe('DefaultToggles', () => {
  let calls: Call[]
  let spaces: Space[]
  beforeEach(async () => {
    spaces = [space({ id: 3, name: 'Novel' })]
    calls = fakeServer(({ method, url, body }) => {
      if (url.includes('/settings')) return method === 'PUT' ? body : { ...EMPTY }
      if (url.includes('/spaces/')) return { id: Number(url.split('/').pop()), ...asRecord(body) }
      if (url.includes('/spaces')) return { spaces }
      return {}
    })
    await useChatDefaults().loadDefaults()
  })

  const option = (w: Pick<VueWrapper, 'findAll'>, name: string) =>
    w.findAll('.option').find(o => o.text().includes(name))

  it('picks from all chats and every space, saved only when the editor commits', async () => {
    useChatDefaults().setCurrentSpace(null) // every space is offered, not just the chat's
    const w = mount(DefaultToggles, { props: { kind: 'instruction', itemId: 5 } })
    await flushPromises()
    expect(w.findAll('.pill')).toHaveLength(0)
    await w.find('.add').trigger('click')
    expect(w.find('.search').exists()).toBe(true) // always searchable
    expect(w.findAll('.option').map(o => o.find('.name').text())).toEqual(['All chats', 'Novel'])
    await option(w, 'Novel')?.trigger('click')
    await option(w, 'All chats')?.trigger('click')
    expect(option(w, 'Novel')?.attributes('aria-selected')).toBe('true')
    expect(w.findAll('.pill .pill-name').map(p => p.text())).toEqual(['🌐 All chats', '🗂 Novel'])
    expect(w.emitted('update:dirty')?.at(-1)).toEqual([true]) // the editor's Save lights up
    expect(calls.some(c => c.method === 'PUT')).toBe(false) // nothing written yet

    await commit(w, 5)
    await flushPromises()
    const saved = (match: (call: Call) => boolean): unknown => calls.find(match)?.body
    expect(saved(c => c.url.includes('/settings') && c.method === 'PUT')).toMatchObject({
      default_instruction_ids: [5],
    })
    expect(saved(c => c.url.endsWith('/spaces/3'))).toMatchObject({ default_instruction_ids: [5] })
    expect(w.emitted('update:dirty')?.at(-1)).toEqual([false])
  })

  it('clicking a ticked one unticks it', async () => {
    const w = mount(DefaultToggles, { props: { kind: 'character', itemId: 9 } })
    await flushPromises()
    await w.find('.add').trigger('click')
    await option(w, 'Novel')?.trigger('click')
    await option(w, 'Novel')?.trigger('click')
    expect(option(w, 'Novel')?.attributes('aria-selected')).toBe('false')
    expect(w.emitted('update:dirty')?.at(-1)).toEqual([false])
  })

  it('a pill’s ✕ takes it off', async () => {
    const w = mount(DefaultToggles, { props: { kind: 'instruction', itemId: 5 } })
    await flushPromises()
    await w.find('.add').trigger('click')
    await option(w, 'Novel')?.trigger('click')
    await w.find('.pill .pill-x').trigger('click')
    expect(w.findAll('.pill')).toHaveLength(0)
    expect(w.emitted('update:dirty')?.at(-1)).toEqual([false])
  })

  it('searches the list', async () => {
    spaces = Array.from({ length: 8 }, (_, i) => space({ id: 10 + i, name: `Space ${String(i)}` }))
    await useChatDefaults().loadDefaults()
    const w = mount(DefaultToggles, { props: { kind: 'instruction', itemId: 5 } })
    await flushPromises()
    await w.find('.add').trigger('click')
    await w.find('.search').setValue('5')
    expect(w.findAll('.option').map(o => o.find('.name').text())).toEqual(['Space 5'])
  })

  it('works for an item that is saved for the first time', async () => {
    const w = mount(DefaultToggles, { props: { kind: 'instruction_group', itemId: null } })
    await flushPromises()
    await w.find('.add').trigger('click')
    await option(w, 'All chats')?.trigger('click')
    await commit(w, 42) // the id it was created under
    await flushPromises()
    const put = calls.findLast(c => c.method === 'PUT' && c.url.includes('/settings'))
    expect(asRecord(put?.body)['default_instruction_group_ids']).toContain(42)
  })
})
