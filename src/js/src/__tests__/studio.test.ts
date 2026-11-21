import { describe, it, expect, vi, beforeEach } from 'vitest'
import { effectScope, reactive, nextTick } from 'vue'

// useChat is the Studio's whole network layer: replace the calls with spies
vi.mock('../composables/useChat', async importOriginal => ({
  ...(await importOriginal<typeof chat>()),
  fetchConversations: vi.fn(() => Promise.resolve({ conversations: [] })),
  fetchSpaces: vi.fn(() => Promise.resolve({ spaces: [] })),
  fetchConversation: vi.fn(),
  fetchConversationSpend: vi.fn(() => Promise.resolve(null)),
  fetchChatStatus: vi.fn(() => Promise.resolve({ openrouter: true })),
  fetchChatModels: vi.fn(() =>
    Promise.resolve({
      errors: {},
      text: [textModel({ id: 't1', name: 'T1' })],
      image: [imageModel({ id: 'pollo/seedream', name: 'Seedream' })],
      video: [],
      audio: [],
    }),
  ),
  createConversation: vi.fn((body: { kind?: ThreadKind }) =>
    Promise.resolve(conversation({ id: 'c1', kind: body.kind ?? 'chat', title: 'New' })),
  ),
  sendChatMessage: vi.fn(),
  retryChatMessage: vi.fn(),
  editChatMessage: vi.fn(),
  estimateChatCost: vi.fn(() => Promise.resolve({ estimate: null })),
  fetchDeleteInfo: vi.fn(),
  deleteChatExchange: vi.fn(),
  switchChatBranch: vi.fn(),
  forkConversation: vi.fn(),
}))
vi.mock('../composables/useDialog', async importOriginal => ({
  ...(await importOriginal<typeof dialog>()),
  confirmDialog: vi.fn(),
}))

import * as chat from '../composables/useChat'
import * as dialog from '../composables/useDialog'
import type { Catalogues } from '../composables/useComposerSettings'
import type { ThreadKind } from '../composables/studioTypes'
import { useComposerSettings } from '../composables/useComposerSettings'
import { defined } from './dom'
import {
  conversation,
  generationItem,
  openConversation,
  imageModel,
  serverMessage,
  shownMessage,
  textModel,
} from './models'
import { useStudio } from '../composables/useStudio'

// Every name the Studio view reads off useStudio(): a refactor must keep them all
const SURFACE = [
  'modelsLoading',
  'threads',
  'spaces',
  'active',
  'activeThread',
  'messages',
  'loading',
  'sending',
  'estimate',
  'unusedAttachments',
  'lane',
  'streamingId',
  'draft',
  'attachments',
  'uploading',
  'addFiles',
  'addFromLibrary',
  'enhancing',
  'enhanceDraft',
  'removeAttachment',
  'lastAssistantId',
  'canSend',
  'activeTitle',
  'activeKind',
  'newKind',
  'favourites',
  'loadFavourites',
  'favouriteMedia',
  'setThreadKind',
  'instructions',
  'instructionGroups',
  'instructionIds',
  'instructionGroupIds',
  'attachedInstructions',
  'attachedGroups',
  'instructionSummary',
  'loadInstructions',
  'setInstructions',
  'setGroups',
  'onInstructionsChanged',
  'editingInstruction',
  'inheritedDefaults',
  'hiddenInherited',
  'pausedInstructionIds',
  'setDefaultHidden',
  'setPaused',
  'loadDefaults',
  'globalSettings',
  'characters',
  'characterIds',
  'charEditor',
  'attachedCharacters',
  'characterNames',
  'characterSupport',
  'loadCharacters',
  'setCharacters',
  'editCharacter',
  'newCharacter',
  'onCharacterSaved',
  'onCharacterDeleted',
  'providers',
  'balances',
  'spend',
  'loadStatus',
  'loadModels',
  'loadLists',
  'openThread',
  'newThread',
  'send',
  'retry',
  'editMessage',
  'resendMessage',
  'switchBranch',
  'forkFrom',
  'regenerateMedia',
  'applyGenerationSettings',
  'pinMedia',
  'stop',
  'deleteExchange',
  'useImage',
  'reword',
  'showTextVersion',
  'showMediaVersion',
  'toggleFav',
  'renameThread',
  'removeThread',
  'moveThread',
  'addSpace',
  'renameSpace',
  'removeSpace',
]

// What the tests drive: the mocked network calls and the confirm dialog, typed as the real ones
const fetchConversation = vi.mocked(chat.fetchConversation)
const fetchDeleteInfo = vi.mocked(chat.fetchDeleteInfo)
const deleteChatExchange = vi.mocked(chat.deleteChatExchange)
const retryChatMessage = vi.mocked(chat.retryChatMessage)
const sendChatMessage = vi.mocked(chat.sendChatMessage)
const confirmDialog = vi.mocked(dialog.confirmDialog)

const scope = effectScope()
const inScope = <T>(build: () => T): T => defined(scope.run(build), 'the scope to run')
function setup() {
  const models = reactive<Catalogues>({ text: [], image: [], video: [], audio: [] })
  const settings = inScope(() => useComposerSettings(models))
  const showToast = vi.fn()
  const studio = inScope(() => useStudio({ models, settings, showToast }))
  return { models, settings, showToast, studio }
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  // useComposerSettings registers lifecycle hooks, which warn outside a component
  vi.spyOn(console, 'warn').mockReturnValue(undefined)
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}), text: () => Promise.resolve('') }),
    ),
  )
})

describe('useStudio', () => {
  it('exposes everything the Studio view uses', () => {
    const { studio } = setup()
    expect(Object.keys(studio).sort()).toEqual([...SURFACE].sort())
  })

  it('loads the catalogue and the thread lists', async () => {
    const { studio, models } = setup()
    await studio.loadModels()
    await studio.loadLists()
    expect(models.text.map(m => m.id)).toEqual(['t1'])
    expect(studio.modelsLoading.value).toBe(false)
    expect(studio.threads.value).toEqual([])
  })

  it('opens a thread, unwrapping the conversation and its messages', async () => {
    fetchConversation.mockResolvedValue({
      conversation: openConversation({
        id: 'c9',
        kind: 'gallery',
        title: 'Old',
        instruction_ids: [3],
        character_ids: [4],
      }),
      messages: [serverMessage({ id: 1, role: 'user', content: 'hi' })],
    })
    const { studio } = setup()
    expect(await studio.openThread('c9')).toBe(true)
    expect(studio.active.value).toBe('c9')
    expect(studio.activeKind.value).toBe('gallery')
    expect(studio.messages.value).toHaveLength(1)
    expect(studio.instructionIds.value).toEqual([3])
    expect(studio.characterIds.value).toEqual([4])
  })

  it('falls back to a clean new thread when the opened one is missing', async () => {
    fetchConversation.mockRejectedValue(new Error('nope'))
    const { studio } = setup()
    expect(await studio.openThread('gone')).toBe(false)
    expect(studio.active.value).toBe(null)
    expect(studio.messages.value).toEqual([])
  })

  it('picks the landing view of a new thread', () => {
    const { studio } = setup()
    studio.newThread('gallery')
    expect(studio.activeKind.value).toBe('gallery')
    studio.newThread('chat')
    expect(studio.activeKind.value).toBe('chat')
  })

  it('files added together on a new thread share one new thread', async () => {
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x' }))
    const { studio } = setup()
    const png = (name: string) => new File(['x'], name, { type: 'image/png' })
    studio.addFiles([png('a.png')])
    studio.addFiles([png('b.png')])
    await vi.waitFor(() => {
      expect(studio.active.value).toBe('c1')
    })
    expect(chat.createConversation).toHaveBeenCalledOnce()
  })

  it('does not send an empty draft', async () => {
    const { studio } = setup()
    await studio.send()
    expect(chat.createConversation).not.toHaveBeenCalled()
    expect(studio.canSend.value).toBe(false)
  })

  it('sends: creates the thread, streams the reply into the messages, then settles', async () => {
    sendChatMessage.mockImplementation((id, body, onEvent) => {
      expect(id).toBe('c1')
      expect(body.content).toBe('draw a cat')
      onEvent({
        type: 'start',
        user_message: shownMessage({ id: 11, role: 'user', content: 'draw a cat' }),
        assistant_message: shownMessage({ id: 12, status: 'streaming' }),
      })
      onEvent({ type: 'delta', text: 'Sure' })
      onEvent({ type: 'delta', text: '!' })
      onEvent({ type: 'done', message: shownMessage({ id: 12, content: 'Sure!' }) })
      return Promise.resolve()
    })
    const { studio } = setup()
    studio.draft.value = 'draw a cat'
    expect(studio.canSend.value).toBe(true)
    await studio.send()
    await vi.waitFor(() => {
      expect(studio.sending.value).toBe(false)
    })
    expect(chat.createConversation).toHaveBeenCalledOnce()
    expect(studio.active.value).toBe('c1')
    expect(studio.draft.value).toBe('')
    expect(studio.messages.value.map(m => [m.id, m.content])).toEqual([
      [11, 'draw a cat'],
      [12, 'Sure!'],
    ])
    expect(studio.streamingId.value).toBe(null)
  })

  it('on a failed send, tells the user and drops the unsent prompt', async () => {
    sendChatMessage.mockRejectedValue(new Error('boom'))
    const { studio, showToast } = setup()
    studio.draft.value = 'hello'
    await studio.send()
    await vi.waitFor(() => {
      expect(showToast).toHaveBeenCalledWith('boom', 'error')
    })
    await nextTick()
    expect(studio.messages.value).toEqual([])
  })

  it('retries a reply by resending from its message', async () => {
    fetchConversation.mockResolvedValue({
      conversation: openConversation({ id: 'c9' }),
      messages: [
        serverMessage({ id: 1, role: 'user', content: 'q' }),
        serverMessage({ id: 2, content: 'a', parent_id: 1 }),
      ],
    })
    retryChatMessage.mockResolvedValue(undefined)
    const { studio } = setup()
    await studio.openThread('c9')
    await studio.retry(defined(studio.messages.value[1]))
    expect(retryChatMessage).toHaveBeenCalledOnce()
    expect(retryChatMessage.mock.calls[0]?.[0]).toBe('c9')
    expect(retryChatMessage.mock.calls[0]?.[1].message_id).toBe(2)
  })

  it('asks before deleting an exchange, naming what goes, and shows the result', async () => {
    fetchConversation.mockResolvedValue({
      conversation: openConversation({ id: 'c9' }),
      messages: [serverMessage({ id: 1, role: 'user', content: 'q' })],
    })
    fetchDeleteInfo.mockResolvedValue({ other_versions: 2, other_messages: 0, media: { image: 2, video: 1 } })
    confirmDialog.mockResolvedValue({ checked: true })
    deleteChatExchange.mockResolvedValue({ conversation: openConversation({ id: 'c9' }), messages: [] })
    const { studio } = setup()
    await studio.openThread('c9')
    await studio.deleteExchange(defined(studio.messages.value[0]))
    const opts = defined(confirmDialog.mock.calls[0]?.[0])
    expect(opts.message).toContain('This also removes 2 other versions.')
    expect(opts.checkbox?.label).toBe('Also delete the 2 images and 1 video it made')
    expect(deleteChatExchange).toHaveBeenCalledWith(1, { deleteMedia: true })
    expect(studio.messages.value).toEqual([])
  })

  it('deletes by the message it is given: a reply from the gallery goes to the server as itself', async () => {
    fetchConversation.mockResolvedValue({
      conversation: openConversation({ id: 'c9' }),
      messages: [serverMessage({ id: 7, role: 'assistant', parent_id: null, content: '' })],
    })
    fetchDeleteInfo.mockResolvedValue({ other_versions: 0, other_messages: 0, media: {} })
    confirmDialog.mockResolvedValue({ checked: false })
    deleteChatExchange.mockResolvedValue({ conversation: openConversation({ id: 'c9' }), messages: [] })
    const { studio } = setup()
    await studio.openThread('c9')
    await studio.deleteExchange(defined(studio.messages.value[0]))
    expect(fetchDeleteInfo).toHaveBeenCalledWith(7)
    expect(deleteChatExchange).toHaveBeenCalledWith(7, { deleteMedia: false })
  })

  it('leaves the exchange alone when the dialog is declined', async () => {
    fetchConversation.mockResolvedValue({
      conversation: openConversation({ id: 'c9' }),
      messages: [serverMessage({ id: 1, role: 'user', content: 'q' })],
    })
    fetchDeleteInfo.mockResolvedValue({ other_versions: 0, other_messages: 0, media: {} })
    confirmDialog.mockResolvedValue(false)
    const { studio } = setup()
    await studio.openThread('c9')
    await studio.deleteExchange(defined(studio.messages.value[0]))
    expect(deleteChatExchange).not.toHaveBeenCalled()
  })

  it('fills the composer from a past generation without sending it', () => {
    const { studio, settings } = setup()
    studio.applyGenerationSettings(
      generationItem({
        kind: 'video',
        prompt: 'waves',
        model: 'pollo/seedance20fast',
        params: { aspect_ratio: '16:9', resolution: '720p', duration: 5, generate_audio: true },
      }),
    )
    expect(studio.draft.value).toBe('waves')
    expect(settings.selected.video).toBe('pollo/seedance20fast')
    expect(settings.mode.value).toBe('video')
    expect(settings.videoOpts.aspect_ratio).toBe('16:9')
    expect(settings.videoOpts.duration).toBe(5)
    expect(chat.sendChatMessage).not.toHaveBeenCalled()
  })

  it('switches a new thread between chat and gallery without a request', async () => {
    const { studio } = setup()
    await studio.setThreadKind('gallery')
    expect(studio.newKind.value).toBe('gallery')
  })
})
