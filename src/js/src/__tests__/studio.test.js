import { describe, it, expect, vi, beforeEach } from 'vitest'
import { effectScope, reactive, nextTick } from 'vue'

// useChat is the Studio's whole network layer: replace the calls with spies
vi.mock('../composables/useChat', async importOriginal => ({
  ...(await importOriginal()),
  fetchConversations: vi.fn(async () => ({ conversations: [] })),
  fetchSpaces: vi.fn(async () => ({ spaces: [] })),
  fetchConversation: vi.fn(),
  fetchConversationSpend: vi.fn(async () => null),
  fetchChatStatus: vi.fn(async () => ({ openrouter: true })),
  fetchChatModels: vi.fn(async () => ({ text: [{ id: 't1' }], image: [{ id: 'pollo/seedream' }] })),
  createConversation: vi.fn(async body => ({ id: 'c1', kind: body.kind, title: 'New' })),
  sendChatMessage: vi.fn(),
  retryChatMessage: vi.fn(),
  editChatMessage: vi.fn(),
  estimateChatCost: vi.fn(async () => ({ estimate: null })),
  fetchDeleteInfo: vi.fn(),
  deleteChatExchange: vi.fn(),
  switchChatBranch: vi.fn(),
  forkConversation: vi.fn(),
}))
vi.mock('../composables/useDialog', async importOriginal => ({
  ...(await importOriginal()),
  confirmDialog: vi.fn(),
}))

import * as chat from '../composables/useChat'
import { confirmDialog } from '../composables/useDialog'
import { useComposerSettings } from '../composables/useComposerSettings'
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

const scope = effectScope()
function setup() {
  const models = reactive({ text: [], image: [], video: [], audio: [] })
  const settings = scope.run(() => useComposerSettings(models))
  const showToast = vi.fn()
  const studio = scope.run(() => useStudio({ models, settings, showToast }))
  return { models, settings, showToast, studio }
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  // useComposerSettings registers lifecycle hooks, which warn outside a component
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}), text: async () => '' })),
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
    expect(models.text).toEqual([{ id: 't1' }])
    expect(studio.modelsLoading.value).toBe(false)
    expect(studio.threads.value).toEqual([])
  })

  it('opens a thread, unwrapping the conversation and its messages', async () => {
    chat.fetchConversation.mockResolvedValue({
      conversation: { id: 'c9', kind: 'gallery', title: 'Old', instruction_ids: [3], character_ids: [4] },
      messages: [{ id: 'm1', role: 'user', content: 'hi' }],
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
    chat.fetchConversation.mockRejectedValue(new Error('nope'))
    const { studio } = setup()
    expect(await studio.openThread('gone')).toBe(false)
    expect(studio.active.value).toBe(null)
    expect(studio.messages.value).toEqual([])
  })

  it('picks the landing view of a new thread', () => {
    const { studio } = setup()
    studio.newThread('gallery')
    expect(studio.activeKind.value).toBe('gallery')
    studio.newThread('anything else')
    expect(studio.activeKind.value).toBe('chat')
  })

  it('does not send an empty draft', async () => {
    const { studio } = setup()
    await studio.send()
    expect(chat.createConversation).not.toHaveBeenCalled()
    expect(studio.canSend.value).toBe(false)
  })

  it('sends: creates the thread, streams the reply into the messages, then settles', async () => {
    chat.sendChatMessage.mockImplementation(async (id, body, onEvent) => {
      expect(id).toBe('c1')
      expect(body.content).toBe('draw a cat')
      onEvent({
        type: 'start',
        user_message: { id: 'u1', role: 'user', content: 'draw a cat' },
        assistant_message: { id: 'a1', role: 'assistant', content: '', status: 'streaming' },
      })
      onEvent({ type: 'delta', text: 'Sure' })
      onEvent({ type: 'delta', text: '!' })
      onEvent({ type: 'done', message: { id: 'a1', role: 'assistant', content: 'Sure!', status: 'done' } })
    })
    const { studio } = setup()
    studio.draft.value = 'draw a cat'
    expect(studio.canSend.value).toBe(true)
    await studio.send()
    await vi.waitFor(() => expect(studio.sending.value).toBe(false))
    expect(chat.createConversation).toHaveBeenCalledOnce()
    expect(studio.active.value).toBe('c1')
    expect(studio.draft.value).toBe('')
    expect(studio.messages.value.map(m => [m.id, m.content])).toEqual([
      ['u1', 'draw a cat'],
      ['a1', 'Sure!'],
    ])
    expect(studio.streamingId.value).toBe(null)
  })

  it('on a failed send, tells the user and drops the unsent prompt', async () => {
    chat.sendChatMessage.mockRejectedValue(new Error('boom'))
    const { studio, showToast } = setup()
    studio.draft.value = 'hello'
    await studio.send()
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('boom', 'error'))
    await nextTick()
    expect(studio.messages.value).toEqual([])
  })

  it('retries a reply by resending from its message', async () => {
    chat.fetchConversation.mockResolvedValue({
      conversation: { id: 'c9' },
      messages: [
        { id: 'u1', role: 'user', content: 'q' },
        { id: 'a1', role: 'assistant', content: 'a', parent_id: 'u1' },
      ],
    })
    chat.retryChatMessage.mockResolvedValue(undefined)
    const { studio } = setup()
    await studio.openThread('c9')
    await studio.retry(studio.messages.value[1])
    expect(chat.retryChatMessage).toHaveBeenCalledOnce()
    expect(chat.retryChatMessage.mock.calls[0][0]).toBe('c9')
    expect(chat.retryChatMessage.mock.calls[0][1].message_id).toBe('a1')
  })

  it('asks before deleting an exchange, naming what goes, and shows the result', async () => {
    chat.fetchConversation.mockResolvedValue({
      conversation: { id: 'c9' },
      messages: [{ id: 'u1', role: 'user', content: 'q' }],
    })
    chat.fetchDeleteInfo.mockResolvedValue({ other_versions: 2, other_messages: 0, media: { image: 2, video: 1 } })
    confirmDialog.mockResolvedValue({ checked: true })
    chat.deleteChatExchange.mockResolvedValue({ messages: [] })
    const { studio } = setup()
    await studio.openThread('c9')
    await studio.deleteExchange(studio.messages.value[0])
    const opts = confirmDialog.mock.calls[0][0]
    expect(opts.message).toContain('This also removes 2 other versions.')
    expect(opts.checkbox.label).toBe('Also delete the 2 images and 1 video it made')
    expect(chat.deleteChatExchange).toHaveBeenCalledWith('u1', { deleteMedia: true })
    expect(studio.messages.value).toEqual([])
  })

  it('leaves the exchange alone when the dialog is declined', async () => {
    chat.fetchConversation.mockResolvedValue({
      conversation: { id: 'c9' },
      messages: [{ id: 'u1', role: 'user', content: 'q' }],
    })
    chat.fetchDeleteInfo.mockResolvedValue({})
    confirmDialog.mockResolvedValue(null)
    const { studio } = setup()
    await studio.openThread('c9')
    await studio.deleteExchange(studio.messages.value[0])
    expect(chat.deleteChatExchange).not.toHaveBeenCalled()
  })

  it('fills the composer from a past generation without sending it', () => {
    const { studio, settings } = setup()
    studio.applyGenerationSettings({
      kind: 'video',
      prompt: 'waves',
      model: 'pollo/seedance20fast',
      params: { aspect_ratio: '16:9', resolution: '720p', duration: 5, generate_audio: true },
    })
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
