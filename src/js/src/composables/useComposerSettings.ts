import { ref, reactive, computed, watch, nextTick } from 'vue'
import type { components } from '../api/schema'
import type { Conversation } from './chatConversationsApi'
import type { AudioModel, ImageModel, ModelCatalogue, ModelKind, VideoModel } from './chatModelsApi'
import { isTextModel } from './chatModelsApi'
import { audioSettings, dropUnsupported, ratiosOf, videoSettings } from './composerOptions'
import {
  DEFAULT_IMAGES,
  DEFAULT_MEMORY,
  IMAGE_STEPS,
  MEMORY_STEPS,
  MODES,
  PREFS_KEY,
  audioOptsFrom,
  imageOptsFrom,
  isMode,
  loadPrefs,
  stepFor,
  stepIndex,
  videoOptsFrom,
} from './composerPrefs'
import type { Mode, PickKind } from './composerPrefs'
import { readPresets, snapshotKey, storePresets } from './composerPresets'
import type { Snapshot, StoredPreset } from './composerPresets'
import { writeStored } from '../utils/storage'

// The chat composer's settings: models, mode, the memory and image sliders and the media options. Remembered
// per browser (the last ones used) and per chat (restored when it's opened).
//
// The pieces live beside it: composerPrefs (what is remembered, and the option shapes), composerOptions (ratios,
// and how options become a turn's settings) and composerPresets.

export { IMAGE_STEPS, MEMORY_STEPS, MODES } from './composerPrefs'

type Schemas = components['schemas']

/** The catalogues the pickers choose from. */
export type Catalogues = Pick<ModelCatalogue, ModelKind>

/** The settings a turn is sent with: the body of a send / retry / edit, without what is particular to each. */
export type TurnSettingsBody = Omit<Schemas['SendMessage'], 'content' | 'attachments' | 'lane'>

// First id containing one of these wins when nothing is remembered yet
const PREFERRED: Record<PickKind, readonly string[]> = {
  text: ['anthropic/claude-sonnet', 'google/gemini', 'openai/gpt'],
  image: ['gemini', 'seedream', 'flux', 'gpt-image'],
  video: ['veo', 'seedance', 'wan', 'sora'],
  audio: ['eleven', 'suno', 'minimax'],
}

const MEDIA_KINDS = ['image', 'video', 'audio'] as const

export function useComposerSettings(models: Catalogues) {
  const prefs = loadPrefs()
  const selected = reactive<Record<PickKind, string>>({
    text: prefs.models.text ?? '',
    image: prefs.models.image ?? '',
    video: prefs.models.video ?? '',
    audio: prefs.models.audio ?? '',
  })
  const mode = ref<Mode>(prefs.mode)
  const memoryIndex = ref(stepIndex(MEMORY_STEPS, prefs.memory, DEFAULT_MEMORY))
  const imageIndex = ref(stepIndex(IMAGE_STEPS, prefs.images, DEFAULT_IMAGES))
  const historyLimit = computed(() => MEMORY_STEPS[memoryIndex.value] ?? null)
  const imageLimit = computed(() => IMAGE_STEPS[imageIndex.value] ?? null)
  // Settings for generated media, used in every mode (Auto too).
  // '' = let the chat model choose (Auto), else the media model's default.
  const imageOpts = reactive(prefs.imageOpts)
  const videoOpts = reactive(prefs.videoOpts)
  // Length of the attached source clip, snapped to what the model allows (set by useStudio)
  const clipDuration = ref<number | null>(null)
  // Speech / music settings; '' / null = the model's own default
  const audioOpts = reactive(prefs.audioOpts)
  // Reference images switched on (sent first) or off (never sent) in the
  // composer: chat filenames or "char:<id>/<file>". Per chat, not per browser.
  const refChoices = reactive<{ on: string[]; off: string[] }>({ on: [], off: [] })

  watch(
    [
      () => ({ ...selected }),
      mode,
      memoryIndex,
      imageIndex,
      () => ({ ...imageOpts }),
      () => ({ ...videoOpts }),
      () => ({ ...audioOpts }),
    ],
    () => {
      writeStored(PREFS_KEY, {
        ...selected,
        mode: mode.value,
        memory: historyLimit.value,
        images: imageLimit.value,
        imageOpts: { ...imageOpts },
        videoOpts: { ...videoOpts },
        audioOpts: { ...audioOpts },
      })
    },
    { deep: true },
  )

  const textInfo = computed(() => models.text.find(m => m.id === selected.text))
  const imageInfo = computed<ImageModel | undefined>(() => models.image.find(m => m.id === selected.image))
  const videoInfo = computed<VideoModel | undefined>(() => models.video.find(m => m.id === selected.video))
  const audioInfo = computed<AudioModel | undefined>(() => models.audio.find(m => m.id === selected.audio))
  const imageRatioOptions = computed(() => ratiosOf(imageInfo.value))
  const imageResOptions = computed(() => imageInfo.value?.resolutions ?? [])
  const videoRatioOptions = computed(() => ratiosOf(videoInfo.value))
  const videoResOptions = computed(() => videoInfo.value?.resolutions ?? [])
  const durationOptions = computed(() => videoInfo.value?.durations ?? [])
  // Source-file tools (upscale, face swap…) carry no ratio / duration of their own
  const imageShowsRatio = computed(() => !imageInfo.value?.tool)
  const videoShowsRatio = computed(() => !(videoInfo.value?.type && !videoInfo.value.aspect_ratios))
  const videoShowsDuration = computed(() => !(videoInfo.value?.type && !videoInfo.value.durations))
  const showImageOpts = computed(() => !!selected.image && (mode.value === 'auto' || mode.value === 'image'))
  const showVideoOpts = computed(() => !!selected.video && (mode.value === 'auto' || mode.value === 'video'))
  const showAudioOpts = computed(() => !!selected.audio && mode.value === 'audio')
  const currentMode = computed(() => MODES.find(m => m.id === mode.value) ?? MODES[0])

  watch(imageInfo, info => {
    if (info) dropUnsupported(imageOpts, imageRatioOptions.value, imageResOptions.value)
  })
  watch(videoInfo, (info, prev) => {
    if (!info) return
    dropUnsupported(videoOpts, videoRatioOptions.value, videoResOptions.value, durationOptions.value)
    // Audio starts on for every model that offers it, so a choice made on one
    // model never silently carries over (e.g. an "off" left from another). Only
    // when the model really changes — not when the catalogue first loads on a
    // page refresh, which would undo the remembered choice (and a loaded preset).
    if (info.generate_audio && prev && prev.id !== info.id) videoOpts.generate_audio = true
  })

  function cycleMode(): void {
    const i = MODES.findIndex(m => m.id === mode.value)
    const next = MODES[(i + 1) % MODES.length]
    if (next) mode.value = next.id
  }

  function pickDefault(kind: PickKind): string {
    const list = models[kind]
    if (!list.length) return ''
    const preferred = PREFERRED[kind]
      .map(needle => list.find(m => m.id.includes(needle) && (!isTextModel(m) || kind !== 'text' || m.supports_tools)))
      .find(m => m !== undefined)
    return (preferred ?? list[0])?.id ?? ''
  }

  // A model this browser remembered (or a thread recorded) can have been
  // renamed or retired since. `known` only answers once that catalogue has
  // loaded, so a provider outage never discards the user's pick.
  const known = (kind: PickKind, id: string): boolean => !models[kind].length || models[kind].some(m => m.id === id)

  // Once the catalogues are in: models for anything not picked yet, and a
  // fresh default for anything whose remembered model is gone. An empty
  // image/video pick is a deliberate "None" once the user has made one.
  function applyDefaults(): void {
    if (!selected.text || !known('text', selected.text)) selected.text = pickDefault('text')
    for (const kind of MEDIA_KINDS) {
      // an empty pick is the user's "None" — only a named-but-missing model is replaced
      const stale = !!selected[kind] && !known(kind, selected[kind])
      if (prefs.models[kind] === undefined || stale) selected[kind] = pickDefault(kind)
    }
  }

  // The models a chat recorded, skipping any the catalogue no longer has
  // (renamed or retired) so the composer never points at a dead model.
  function applyChatModels(conv: Pick<Conversation, 'text_model' | 'image_model' | 'video_model' | 'settings'>): void {
    const recorded: Record<'text' | 'image' | 'video', string | null> = {
      text: conv.text_model,
      image: conv.image_model,
      video: conv.video_model,
    }
    for (const kind of ['text', 'image', 'video'] as const) {
      const id = recorded[kind]
      if (id && known(kind, id)) selected[kind] = id
    }
    const audio = conv.settings?.audio_model
    if (audio && known('audio', audio)) selected.audio = audio
  }

  function setRefChoices(choices: { on?: readonly string[]; off?: readonly string[] } | null | undefined): void {
    refChoices.on = [...(choices?.on ?? [])]
    refChoices.off = [...(choices?.off ?? [])]
  }

  // A chat's own models and settings, restored when it's opened
  function applyChat(conv: Pick<Conversation, 'text_model' | 'image_model' | 'video_model' | 'settings'>): void {
    applyChatModels(conv)
    const settings = conv.settings
    setRefChoices(settings?.ref_choices)
    if (!settings) return
    if (isMode(settings.mode)) mode.value = settings.mode
    const memory = stepFor(MEMORY_STEPS, settings.history_limit)
    if (memory !== undefined) memoryIndex.value = memory
    const images = stepFor(IMAGE_STEPS, settings.image_limit)
    if (images !== undefined) imageIndex.value = images
    Object.assign(imageOpts, imageOptsFrom(settings.image_options))
    const video = videoOptsFrom(settings.video_options)
    // null = the chat's video model never offered audio: keep what the composer has
    if (typeof settings.video_options.generate_audio !== 'boolean') video.generate_audio = videoOpts.generate_audio
    Object.assign(videoOpts, video)
    Object.assign(audioOpts, audioOptsFrom(settings.audio_options))
  }

  // --- Presets -----------------------------------------------------------------------------------------------
  const presets = ref<StoredPreset[]>(readPresets())
  const snapshot = (): Snapshot => ({
    mode: mode.value,
    models: { ...selected },
    imageOpts: { ...imageOpts },
    videoOpts: { ...videoOpts },
    audioOpts: { ...audioOpts },
  })
  // The saved preset the setup currently matches (so the picker can show it),
  // or '' once anything has been changed away from it
  const activePresetId = computed(() => {
    const now = snapshotKey(snapshot())
    return presets.value.find(p => snapshotKey(p) === now)?.id ?? ''
  })
  function savePreset(name: string, snap: Snapshot = snapshot()): void {
    const preset: StoredPreset = { id: Date.now().toString(36), name, ...snap }
    // Same name replaces, so re-saving updates a preset
    presets.value = [...presets.value.filter(p => p.name !== name), preset]
    storePresets(presets.value)
  }
  // Change a preset: its name and/or its settings (a snapshot)
  function updatePreset(id: string, patch: Partial<Omit<StoredPreset, 'id'>>): void {
    presets.value = presets.value.map(p => (p.id === id ? { ...p, ...patch } : p))
    storePresets(presets.value)
  }
  function deletePreset(id: string): void {
    presets.value = presets.value.filter(p => p.id !== id)
    storePresets(presets.value)
  }
  async function loadPreset(preset: Snapshot): Promise<void> {
    Object.assign(selected, preset.models)
    mode.value = preset.mode
    // Let the model-change watchers (drop unsupported options, reset audio) run
    // first, then put the preset's own options back on top.
    await nextTick()
    Object.assign(imageOpts, preset.imageOpts)
    Object.assign(videoOpts, preset.videoOpts)
    Object.assign(audioOpts, preset.audioOpts)
  }

  // The settings a turn is sent with (retries and edits too: they run in the mode selected now)
  function turnSettings(): TurnSettingsBody {
    return {
      mode: mode.value,
      history_limit: historyLimit.value,
      image_limit: imageLimit.value,
      text_model: selected.text || null,
      image_model: selected.image || null,
      video_model: selected.video || null,
      audio_model: selected.audio || null,
      image_options: { aspect_ratio: imageOpts.aspect_ratio || null, resolution: imageOpts.resolution || null },
      video_options: videoSettings(videoInfo.value, videoOpts, clipDuration.value),
      audio_options: audioSettings(audioInfo.value, audioOpts),
      ref_choices: { on: [...refChoices.on], off: [...refChoices.off] },
    }
  }

  // The picked model's catalogue entry for the current mode (null in Chat / Auto)
  const activeInfo = computed<ImageModel | VideoModel | AudioModel | null>(() => {
    switch (mode.value) {
      case 'image':
        return imageInfo.value ?? null
      case 'video':
        return videoInfo.value ?? null
      case 'audio':
        return audioInfo.value ?? null
      default:
        return null
    }
  })

  return {
    selected,
    mode,
    memoryIndex,
    imageIndex,
    historyLimit,
    imageLimit,
    imageOpts,
    videoOpts,
    audioOpts,
    refChoices,
    setRefChoices,
    textInfo,
    imageInfo,
    videoInfo,
    audioInfo,
    imageRatioOptions,
    imageResOptions,
    videoRatioOptions,
    videoResOptions,
    durationOptions,
    imageShowsRatio,
    videoShowsRatio,
    videoShowsDuration,
    activeInfo,
    showImageOpts,
    showVideoOpts,
    showAudioOpts,
    currentMode,
    cycleMode,
    presets,
    snapshot,
    savePreset,
    activePresetId,
    updatePreset,
    deletePreset,
    loadPreset,
    applyDefaults,
    applyChat,
    turnSettings,
    clipDuration,
  }
}
