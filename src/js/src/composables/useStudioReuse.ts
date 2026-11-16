import type { Ref } from 'vue'
import { partialAudioOpts, partialImageOpts, partialVideoOpts } from './composerPrefs'
import type { Mode } from './composerPrefs'
import type { ComposerSettings } from './useComposerSettings'
import type { GenerationItem } from './studioTypes'
import { asRecord, asStrings } from '../utils/storage'

// "Use settings" (gallery): fill the composer from a past generation so the
// user can tweak and press Generate. Fills only — never fires (unlike retry).

type MediaKind = 'image' | 'video' | 'audio'

/** How an attachment is put back, as the composer's attachment layer offers it. */
export interface AttachmentRestore {
  clearAttachments: () => void
  addChatMedia: (file: string, kind: string, fromConv: string) => boolean
  addChatImage: (file: string, fromConv: string) => boolean
}

type ReuseSettings = Pick<ComposerSettings, 'selected' | 'mode' | 'imageOpts' | 'videoOpts' | 'audioOpts'>

// A generation's stored params back into the composer's options for its kind
function applyVideoOptions(settings: ReuseSettings, params: Record<string, unknown>): void {
  const { generate_audio: audio, duration } = partialVideoOpts(params)
  if (typeof audio === 'boolean') settings.videoOpts.generate_audio = audio
  // A generation made on Auto goes back to Auto ('') — its stored duration is
  // what Auto worked out to (the clip's length), not a length that was chosen.
  settings.videoOpts.duration = params['duration_auto'] === true ? '' : (duration ?? settings.videoOpts.duration)
}

function applyOptions(settings: ReuseSettings, kind: MediaKind, params: Record<string, unknown>): void {
  if (kind === 'audio') {
    Object.assign(settings.audioOpts, partialAudioOpts(params))
    return
  }
  const opts = kind === 'video' ? settings.videoOpts : settings.imageOpts
  const { aspect_ratio: ratio, resolution } = partialImageOpts(params)
  if (ratio) opts.aspect_ratio = ratio
  if (resolution) opts.resolution = resolution
  if (kind === 'video') applyVideoOptions(settings, params)
}

const isChatRef = (ref: string): boolean => ref.startsWith('char:')

/** A reference-to-video generation's named refs: [{ file, type }], in order. */
function namedRefs(params: Record<string, unknown>): { file: string; type: string }[] {
  const items = Array.isArray(params['ref_items']) ? (params['ref_items'] as unknown[]) : []
  return items.flatMap(item => {
    const { file, type } = asRecord(item)
    return typeof file === 'string' && typeof type === 'string' ? [{ file, type }] : []
  })
}

// Put a generation's reference images back as attachments (character refs
// come back with the characters, not as files)
function restoreRefs(item: GenerationItem, attachments: AttachmentRestore): void {
  attachments.clearAttachments()
  const params = asRecord(item.params)
  // Reference-to-video: re-attach each named ref with its kind, in order, so
  // the [@name] pills resolve again (image1, video1…).
  const named = namedRefs(params)
  if (named.length) {
    for (const ref of named) {
      if (!isChatRef(ref.file)) attachments.addChatMedia(ref.file, ref.type, item.conversation_id)
    }
    return
  }
  const frames = [params['first_frame'], params['last_frame']].filter((f): f is string => typeof f === 'string')
  const files = [...asStrings(params['refs']), ...frames].filter(f => f && !isChatRef(f))
  for (const file of new Set(files)) attachments.addChatImage(file, item.conversation_id)
}

export function useStudioReuse({
  draft,
  settings,
  attachments,
}: {
  draft: Ref<string>
  settings: ReuseSettings
  attachments: AttachmentRestore
}) {
  const { selected, mode } = settings

  function applyGenerationSettings(item: GenerationItem): void {
    const kind: MediaKind = item.kind === 'video' || item.kind === 'audio' ? item.kind : 'image'
    const text = item.original_prompt ?? item.prompt
    if (text) draft.value = text
    const params = asRecord(item.params)
    const model = item.model ?? (typeof params['model'] === 'string' ? params['model'] : null)
    if (model) selected[kind] = model
    mode.value = kind satisfies Mode
    applyOptions(settings, kind, params)
    restoreRefs(item, attachments)
  }

  return { applyGenerationSettings }
}
