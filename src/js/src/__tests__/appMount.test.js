/**
 * The whole app, mounted: App + the real router + StudioView, with the network stubbed. Unit tests mount
 * pieces in isolation and can't see a mistake in how StudioView wires its composables together (a use-before-
 * define in setup() once broke every page while all of them passed), so this walks every pane and fails on
 * any error or Vue warning.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createApp, nextTick } from 'vue'
import { audioModel, imageModel, textModel, videoModel } from './models'

const MODELS = {
  text: [textModel({ id: 'openai/gpt-5', name: 'GPT-5', supports_tools: true, tags: ['vision', 'functions'] })],
  image: [imageModel({ id: 'pollo/seedream', name: 'Pollo: Seedream', tags: ['text2img'], aspect_ratios: ['1:1'] })],
  video: [
    videoModel({ id: 'pollo/seedance20fast', name: 'Pollo: Seedance', tags: ['img2vid', 'audio'], durations: [5, 10] }),
  ],
  audio: [audioModel({ id: 'pollo/elevenv3', name: 'Pollo: ElevenLabs', type: 'speech', options: ['voice'] })],
}

// What each endpoint the Studio calls on load answers; anything else gets an empty object
const ANSWERS = [
  [/\/api\/chat\/models/, MODELS],
  [/\/api\/chat\/status/, { openrouter: true, venice: false }],
  [/\/api\/chat\/conversations$/, { conversations: [] }],
  [/\/api\/chat\/spaces/, { spaces: [] }],
  [/\/api\/chat\/instructions/, { instructions: [], groups: [] }],
  [
    /\/api\/chat\/settings/,
    { default_character_ids: [], default_instruction_ids: [], default_instruction_group_ids: [], title_model: null },
  ],
  [/\/api\/chat\/spend\/breakdown/, { days: 0, total_usd: 0, rows: [] }],
  [/\/api\/chat\/pollo-balance/, { availableCredits: 0, totalCredits: 0 }],
  [/\/api\/chat\/(library|favourites)/, { items: [] }],
  [/\/api\/chat\/request-log/, { entries: [] }],
  [/\/api\/characters/, { characters: [] }],
  [/\/api\/media/, { items: [], total: 0 }],
  [/\/api\/keys/, { keys: {} }],
  [/\/api\/settings\/uploads/, { prefs: {}, hosts: [], expiry_options: [] }],
]
const answer = url => ANSWERS.find(([re]) => re.test(url))?.[1] ?? {}

let problems
beforeEach(() => {
  problems = []
  vi.spyOn(console, 'error').mockImplementation((...a) => problems.push(a.map(String).join(' ')))
  vi.spyOn(console, 'warn').mockImplementation((...a) => problems.push(a.map(String).join(' ')))
  vi.stubGlobal(
    'fetch',
    vi.fn(async url => ({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => answer(String(url)),
      text: async () => '',
    })),
  )
  window.matchMedia ??= () => ({ matches: true, addEventListener() {} })
})
afterEach(() => vi.restoreAllMocks())

describe('the whole app', () => {
  it('opens every pane and the composer without an error or a warning', async () => {
    const router = (await import('../router')).default
    const App = (await import('../App.vue')).default
    const el = document.createElement('div')
    document.body.appendChild(el)
    const app = createApp(App)
    app.config.errorHandler = (e, _instance, info) => problems.push(`${info}: ${e.stack || e}`)
    app.use(router)
    app.mount(el)

    const panes = ['/', '/settings', '/tools', '/media', '/favourites', '/usage', '/characters']
    for (const path of [
      ...panes,
      '/instructions',
      '/presets',
      '/requests',
      '/space/1',
      '/abc123',
      '/abc123/gallery',
      '/',
    ]) {
      await router.push(path)
      await flushPromises()
      await nextTick()
    }
    expect(document.querySelector('.compose')).not.toBeNull()
    expect(problems).toEqual([])
    app.unmount()
  })
})
