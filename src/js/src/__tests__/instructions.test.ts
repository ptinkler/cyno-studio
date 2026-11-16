import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import InstructionEditor from '../components/chat/InstructionEditor.vue'
import InstructionPicker from '../components/chat/InstructionPicker.vue'
import StudioInstructionsPage from '../components/studio/StudioInstructionsPage.vue'
import { useChatDefaults } from '../composables/useChatDefaults'
import { asRecord } from '../utils/storage'
import { all, one } from './dom'
import { fakeServer } from './fakeServer'
import type { Call } from './fakeServer'
import { instruction, instructionGroup, space } from './models'

const snippets = [
  instruction({ id: 1, name: 'Terse tone', content: 'Be brief.' }),
  instruction({ id: 2, name: 'British spelling', content: 'Use British spelling.' }),
  instruction({ id: 3, name: 'No emoji', content: 'Never use emoji.' }),
]
const groups = [instructionGroup({ id: 7, name: 'House style', snippet_ids: [1] })]
const EMPTY = { default_character_ids: [], default_instruction_ids: [], default_instruction_group_ids: [] }
const spaces = [space({ id: 4, name: 'Novel' })]

let calls: Call[]
beforeEach(() => {
  calls = fakeServer(({ method, url, body }) => {
    if (url.includes('/settings')) return method === 'PUT' ? body : { ...EMPTY }
    if (url.includes('/spaces/')) return { id: 4, ...asRecord(body) }
    if (url.includes('/spaces')) return { spaces }
    if (url.endsWith('/instructions')) return { instructions: snippets, groups }
    if (method === 'PUT') return { id: Number(url.split('/').pop()), ...asRecord(body) }
    if (method === 'POST') return { id: 99, ...asRecord(body) }
    return {}
  })
})

describe('InstructionEditor', () => {
  let w: VueWrapper | undefined
  afterEach(() => {
    w?.unmount()
  })

  async function open(target: { kind: 'snippet' | 'group'; id: number }) {
    const mounted = mount(InstructionEditor, {
      props: { target: null, instructions: snippets, groups },
      attachTo: document.body,
    })
    w = mounted
    await mounted.setProps({ target })
    await flushPromises()
    return one('.dialog[role="dialog"]')
  }

  it("adds snippets to a group by searching, saves the group's snippets and closes", async () => {
    const dialog = await open({ kind: 'group', id: 7 })
    expect(one(HTMLInputElement, 'input[aria-label="Name"]', dialog).value).toBe('House style')
    const adder = one(HTMLInputElement, 'input[aria-label="Add a snippet"]', dialog)
    adder.value = 'emoji'
    adder.dispatchEvent(new Event('input'))
    await flushPromises()
    const options = all('.adder-menu .item', dialog)
    expect(options.map(o => o.textContent.trim())).toEqual(['No emoji']) // members aren't offered again
    options[0]?.click()
    await flushPromises()
    one('.btn-primary', dialog).click()
    await flushPromises()
    const put = calls.find(c => c.method === 'PUT' && c.url.endsWith('/instruction-groups/7'))
    expect(put?.body).toEqual({ name: 'House style', snippet_ids: [1, 3] })
    expect(w?.emitted('close')).toHaveLength(1)
  })

  it('saves "Default for" picks with the Save button, for any space', async () => {
    useChatDefaults().setCurrentSpace(null)
    await useChatDefaults().loadDefaults()
    const dialog = await open({ kind: 'snippet', id: 1 })
    const save = one(HTMLButtonElement, '.btn-primary', dialog)
    expect(save.disabled).toBe(true) // nothing changed yet
    one('.def-toggles .add', dialog).click()
    await flushPromises()
    const option = (name: string) => all('.option', dialog).find(o => o.textContent.includes(name))
    option('All chats')?.click()
    option('Novel')?.click()
    await flushPromises()
    expect(all('.def-toggles .pill-name', dialog).map(p => p.textContent.trim())).toEqual(['🌐 All chats', '🗂 Novel'])
    expect(save.disabled).toBe(false) // picks alone are a change to save
    expect(calls.some(c => c.method === 'PUT')).toBe(false) // nothing written before Save
    save.click()
    await flushPromises()
    const saved = (match: (call: Call) => boolean): unknown => calls.find(match)?.body
    expect(saved(c => c.method === 'PUT' && c.url.includes('/settings'))).toMatchObject({
      default_instruction_ids: [1],
    })
    expect(saved(c => c.method === 'PUT' && c.url.endsWith('/spaces/4'))).toMatchObject({
      default_instruction_ids: [1],
    })
  })
})

describe('StudioInstructionsPage', () => {
  it('lists groups and snippets and opens one in the editor', async () => {
    const w = mount(StudioInstructionsPage, { attachTo: document.body })
    await flushPromises()
    expect(w.findAll('.card h3').map(h => h.text())).toEqual([
      '📦 House style',
      'Terse tone',
      'British spelling',
      'No emoji',
    ])
    await w.find('.search').setValue('brit')
    expect(w.findAll('.card h3').map(h => h.text())).toEqual(['British spelling'])
    await w.find('.card').trigger('click')
    await flushPromises()
    expect(one(HTMLInputElement, '.dialog input[aria-label="Name"]').value).toBe('British spelling')
    w.unmount()
  })
})

// The picker's dialog is teleported to <body>: query the document
const pickCards = () => all('.dialog .card')
const pickNames = () => pickCards().map(c => one('.name-text', c).textContent.trim())
const actionButton = (text: string) => all('.dialog .actions button').find(b => b.textContent.includes(text))

describe('InstructionPicker', () => {
  it('opens the editor for a new snippet or group from the dialog', async () => {
    const w = mount(InstructionPicker, {
      props: { instructions: [], groups: [], snippetIds: [], groupIds: [] },
      attachTo: document.body,
    })
    await w.find('.add').trigger('click')
    actionButton('New snippet')?.click()
    await flushPromises()
    expect(w.emitted('edit')?.[0]).toEqual([{ kind: 'snippet', id: null }])
    await w.find('.add').trigger('click')
    actionButton('New group')?.click()
    await flushPromises()
    expect(w.emitted('edit')?.[1]).toEqual([{ kind: 'group', id: null }])
    w.unmount()
  })

  it('opens an attached snippet or group when its chip is clicked', async () => {
    const w = mount(InstructionPicker, {
      props: { instructions: snippets, groups, snippetIds: [2], groupIds: [7] },
    })
    const chips = w.findAll('.chip-main')
    await chips[0]?.trigger('click')
    await chips[1]?.trigger('click')
    expect(w.emitted('edit')).toEqual([[{ kind: 'group', id: 7 }], [{ kind: 'snippet', id: 2 }]])
  })

  it('shows what the defaults attach, which can be hidden in this chat and brought back', async () => {
    const w = mount(InstructionPicker, {
      props: {
        instructions: snippets,
        groups,
        snippetIds: [2],
        groupIds: [],
        inheritedSnippets: [{ id: 1, from: 'Novel' }],
        inheritedGroups: [{ id: 7, from: 'All chats' }],
        hiddenSnippets: [{ id: 3, from: 'All chats' }],
      },
      attachTo: document.body,
    })
    const inherited = w.findAll('.chip.inherited')
    expect(inherited.map(c => c.find('.chip-name').text())).toEqual(['📦 House style', 'Terse tone'])
    expect(inherited[1]?.attributes('title')).toContain('From the Novel defaults')
    await inherited[1]?.find('.chip-x').trigger('click')
    expect(w.emitted('hide')).toEqual([[{ kind: 'snippet', id: 1 }]])
    // The hidden one is offered to switch back on, not to attach as the chat's own
    await w.find('.add').trigger('click')
    const hidden = pickCards().find(c => one('.name-text', c).textContent.trim() === 'No emoji')
    expect(hidden?.classList).toContain('default')
    expect(hidden?.getAttribute('aria-pressed')).toBe('false')
    hidden?.click()
    await flushPromises()
    expect(w.emitted('unhide')).toEqual([[{ kind: 'snippet', id: 3 }]])
    expect(w.emitted('update:snippetIds')).toBeUndefined()
    w.unmount()
  })

  it('pauses and resumes an attached snippet or group, keeping it attached', async () => {
    const w = mount(InstructionPicker, {
      props: { instructions: snippets, groups, snippetIds: [2], groupIds: [7], pausedSnippets: [2] },
    })
    const chipNamed = (name: string) => w.findAll('.chip').find(c => c.find('.chip-name').text() === name)
    // The paused snippet is dimmed and its control offers to resume
    const snippetChip = chipNamed('British spelling')
    expect(snippetChip?.classes()).toContain('paused')
    expect(snippetChip?.find('.chip-pause').text()).toBe('▶')
    await snippetChip?.find('.chip-pause').trigger('click')
    expect(w.emitted('resume')).toEqual([[{ kind: 'snippet', id: 2 }]])
    // The group isn't paused → its control pauses it, and it stays attached (no detach)
    const groupChip = chipNamed('📦 House style')
    expect(groupChip?.classes()).not.toContain('paused')
    await groupChip?.find('.chip-pause').trigger('click')
    expect(w.emitted('pause')).toEqual([[{ kind: 'group', id: 7 }]])
    expect(w.emitted('update:groupIds')).toBeUndefined()
    w.unmount()
  })

  it('searches names and text, and attaches with a tap', async () => {
    const many = Array.from({ length: 10 }, (_, i) =>
      instruction({ id: 100 + i, name: `Snippet ${String(i)}`, content: `body ${String(i)}` }),
    )
    const w = mount(InstructionPicker, {
      props: { instructions: many, groups: [], snippetIds: [], groupIds: [] },
      attachTo: document.body,
    })
    await w.find('.add').trigger('click')
    const search = one(HTMLInputElement, '.dialog .search')
    search.value = 'body 7'
    search.dispatchEvent(new Event('input'))
    await flushPromises()
    expect(pickNames()).toEqual(['Snippet 7'])
    pickCards()[0]?.click()
    await flushPromises()
    expect(w.emitted('update:snippetIds')).toEqual([[[107]]])
    w.unmount()
  })
})
