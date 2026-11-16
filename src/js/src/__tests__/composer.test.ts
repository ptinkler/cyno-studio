/** The composer's pure pieces: what it reads back from storage, and how its options become a turn's settings. */
import { beforeEach, describe, expect, it } from 'vitest'
import { audioSettings, dropUnsupported, ratiosOf, videoSettings } from '../composables/composerOptions'
import { presetFrom, snapshotKey } from '../composables/composerPresets'
import {
  IMAGE_STEPS,
  MEMORY_STEPS,
  PREFS_KEY,
  defaultAudioOpts,
  defaultVideoOpts,
  loadPrefs,
  stepFor,
  stepIndex,
} from '../composables/composerPrefs'

beforeEach(() => {
  localStorage.clear()
})

describe('loadPrefs', () => {
  it('is all defaults when nothing is stored', () => {
    const prefs = loadPrefs()
    expect(prefs.models).toEqual({})
    expect(prefs.mode).toBe('auto')
    expect(prefs.memory).toBeUndefined()
    expect(prefs.videoOpts).toEqual(defaultVideoOpts())
  })

  it('keeps what is well-formed and drops what is not', () => {
    localStorage.setItem(
      PREFS_KEY,
      JSON.stringify({
        text: 5,
        image: 'pollo/seedream',
        mode: 'telepathy',
        memory: 'lots',
        imageOpts: { aspect_ratio: 7, resolution: '2K' },
        videoOpts: { duration: 8, generate_audio: 'yes', extra: true },
      }),
    )
    const prefs = loadPrefs()
    expect(prefs.models).toEqual({ image: 'pollo/seedream' })
    expect(prefs.mode).toBe('auto')
    expect(prefs.memory).toBeUndefined()
    expect(prefs.imageOpts).toEqual({ aspect_ratio: '', resolution: '2K' })
    expect(prefs.videoOpts).toEqual({ ...defaultVideoOpts(), duration: 8 })
  })

  it('tells "all" (null) from "never set"', () => {
    localStorage.setItem(PREFS_KEY, JSON.stringify({ memory: null }))
    expect(loadPrefs().memory).toBeNull()
  })

  it('survives storage that is not JSON', () => {
    localStorage.setItem(PREFS_KEY, '{nope')
    expect(loadPrefs().mode).toBe('auto')
  })
})

describe('slider stops', () => {
  it('finds the stop for a remembered value, else the default', () => {
    expect(MEMORY_STEPS[stepIndex(MEMORY_STEPS, 40, 20)]).toBe(40)
    expect(MEMORY_STEPS[stepIndex(MEMORY_STEPS, 41, 20)]).toBe(20)
    expect(MEMORY_STEPS[stepIndex(MEMORY_STEPS, null, 20)]).toBeNull()
    expect(MEMORY_STEPS[stepIndex(MEMORY_STEPS, undefined, 20)]).toBe(20)
  })

  it('maps a saved value to its stop, null to "All", and an odd one to nothing', () => {
    expect(stepFor(IMAGE_STEPS, 6)).toBe(IMAGE_STEPS.indexOf(6))
    expect(stepFor(IMAGE_STEPS, null)).toBe(IMAGE_STEPS.length - 1)
    expect(stepFor(IMAGE_STEPS, 7)).toBeUndefined()
  })
})

describe('audioSettings', () => {
  const opts = {
    ...defaultAudioOpts(),
    voice: 'v1',
    speed: 1.2,
    style: '  jazz ',
    instrumental: true,
    vocal_gender: 'f',
  }

  it('sends only the options the model offers', () => {
    const got = audioSettings({ options: ['voice'] }, opts)
    expect(got.voice).toBe('v1')
    expect(got.speed).toBeNull()
    expect(got.style).toBeNull()
  })

  it('cleans blanks to null and trims text', () => {
    const got = audioSettings({ options: ['voice', 'tuning', 'lyrics', 'instrumental', 'duration'] }, opts)
    expect(got.speed).toBe(1.2)
    expect(got.volume).toBeNull()
    expect(got.style).toBe('jazz')
    expect(got.title).toBeNull()
    expect(got.duration).toBeNull()
  })

  it('drops the vocal gender of an instrumental track', () => {
    expect(audioSettings({ options: ['instrumental'] }, opts).vocal_gender).toBeNull()
    expect(audioSettings({ options: ['instrumental'] }, { ...opts, instrumental: false }).vocal_gender).toBe('f')
  })

  it('sends nothing for an unknown model', () => {
    expect(Object.values(audioSettings(undefined, opts)).every(v => v === null)).toBe(true)
  })
})

describe('videoSettings', () => {
  it('uses the attached clip and says Auto while the length is left unset', () => {
    const got = videoSettings({ generate_audio: true }, { ...defaultVideoOpts(), generate_audio: false }, 7)
    expect(got).toMatchObject({ duration: 7, duration_auto: true, generate_audio: false })
  })

  it('uses a picked length and does not call it Auto', () => {
    const got = videoSettings({ generate_audio: null }, { ...defaultVideoOpts(), duration: '5' }, 7)
    expect(got).toMatchObject({ duration: 5, duration_auto: false, generate_audio: null })
  })
})

describe('options a model does not offer', () => {
  it('fall back to auto when a new model lacks the old pick', () => {
    const opts = { aspect_ratio: '4:3', resolution: '1080p', duration: 10 as string | number }
    dropUnsupported(opts, ['1:1'], ['720p'], [5])
    expect(opts).toEqual({ aspect_ratio: '', resolution: '', duration: '' })
  })

  it('leave an unset option alone, and offer standard ratios without the "auto" ones', () => {
    const opts = { aspect_ratio: '', resolution: '' }
    dropUnsupported(opts, [], [])
    expect(opts).toEqual({ aspect_ratio: '', resolution: '' })
    expect(ratiosOf({ aspect_ratios: ['auto', '16:9'] })).toEqual(['16:9'])
    expect(ratiosOf(undefined)).toContain('1:1')
  })
})

describe('presets', () => {
  it('need an id, a name and a mode; the rest is filled in', () => {
    expect(presetFrom({ name: 'x', mode: 'image' })).toBeNull()
    expect(presetFrom({ id: 'a', name: 'x', mode: 'warp' })).toBeNull()
    const preset = presetFrom({ id: 'a', name: 'x', mode: 'image', models: { image: 'm', video: 3 } })
    expect(preset?.models).toEqual({ text: '', image: 'm', video: '', audio: '' })
    expect(preset?.videoOpts).toEqual(defaultVideoOpts())
  })

  it('compare equal whatever order their options were written in', () => {
    const a = presetFrom({ id: '1', name: 'a', mode: 'video', videoOpts: { resolution: '720p', aspect_ratio: '16:9' } })
    const b = presetFrom({ id: '2', name: 'b', mode: 'video', videoOpts: { aspect_ratio: '16:9', resolution: '720p' } })
    expect(a && b && snapshotKey(a) === snapshotKey(b)).toBe(true)
  })
})
