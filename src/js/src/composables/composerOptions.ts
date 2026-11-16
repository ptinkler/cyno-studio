import type { components } from '../api/schema'
import type { AudioModel, VideoModel } from './chatModelsApi'
import type { AudioOpts, VideoOpts } from './composerPrefs'

// Pure rules for the composer's media options: which ratios and lengths to offer, and how the options become
// the settings a turn is sent with.

type Schemas = components['schemas']

const DEFAULT_RATIOS: readonly string[] = ['1:1', '16:9', '9:16', '4:3', '3:4', '3:2', '2:3', '21:9']

// "auto"/"adaptive" are dropped from the list: the "Ratio: auto" placeholder
// already stands for them (the backend sends the model's own auto value when
// the ratio is left unset), so showing them again is a confusing duplicate.
const AUTO_RATIOS: readonly string[] = ['auto', 'adaptive']

/** The aspect ratios to offer for a model: its own, else a standard set, without the "auto" ones. */
export function ratiosOf(info: { aspect_ratios?: readonly string[] | null } | undefined): string[] {
  const ratios = info?.aspect_ratios?.length ? info.aspect_ratios : DEFAULT_RATIOS
  return ratios.filter(r => !AUTO_RATIOS.includes(r))
}

interface PickedOptions {
  aspect_ratio: string
  resolution: string
  duration?: string | number
}

/** A newly picked model may not offer the old picks — fall back to auto/default. */
export function dropUnsupported(
  opts: PickedOptions,
  ratios: readonly string[],
  resolutions: readonly string[],
  durations: readonly number[] | null = null,
): void {
  if (opts.aspect_ratio && !ratios.includes(opts.aspect_ratio)) opts.aspect_ratio = ''
  if (opts.resolution && !resolutions.includes(opts.resolution)) opts.resolution = ''
  if (durations && opts.duration && !durations.includes(Number(opts.duration))) opts.duration = ''
}

// --- Audio ---------------------------------------------------------------------------------------------------

type AudioSettings = Schemas['AudioOptions']

const toNumber = (value: number | string | null): number | null =>
  value === null || value === '' ? null : Number(value)
const toText = (value: string): string | null => value.trim() || null

/** Each audio option's value as the server wants it: '' and blanks become null. */
function cleaned(opts: AudioOpts) {
  return {
    voice: opts.voice || null,
    speed: toNumber(opts.speed),
    volume: toNumber(opts.volume),
    pitch: toNumber(opts.pitch),
    instrumental: opts.instrumental,
    vocal_gender: opts.instrumental ? null : opts.vocal_gender || null,
    style: toText(opts.style),
    title: toText(opts.title),
    negative_prompt: toText(opts.negative_prompt),
    duration: toNumber(opts.duration),
  } satisfies Record<keyof AudioOpts, unknown>
}

// Which of the model's own options offers each field
const OFFERED_BY: Record<keyof AudioOpts, string> = {
  voice: 'voice',
  speed: 'tuning',
  volume: 'tuning',
  pitch: 'tuning',
  instrumental: 'instrumental',
  vocal_gender: 'instrumental',
  style: 'lyrics',
  title: 'lyrics',
  negative_prompt: 'instrumental',
  duration: 'duration',
}

/** Only what the picked audio model takes goes out (the rest stays the model's default). */
export function audioSettings(info: Pick<AudioModel, 'options'> | undefined, opts: AudioOpts): AudioSettings {
  const clean = cleaned(opts)
  const keep = <K extends keyof AudioOpts>(field: K): ReturnType<typeof cleaned>[K] | null =>
    info?.options.includes(OFFERED_BY[field]) ? clean[field] : null
  return {
    voice: keep('voice'),
    speed: keep('speed'),
    volume: keep('volume'),
    pitch: keep('pitch'),
    instrumental: keep('instrumental'),
    vocal_gender: keep('vocal_gender'),
    style: keep('style'),
    title: keep('title'),
    negative_prompt: keep('negative_prompt'),
    duration: keep('duration'),
  }
}

// --- Video ---------------------------------------------------------------------------------------------------

/**
 * `duration` '' = Auto: the attached clip's length (reference-to-video), else the model's default. The flag
 * rides along so reusing this generation's settings later lands back on Auto, not on the number Auto resolved to.
 */
export function videoSettings(
  info: Pick<VideoModel, 'generate_audio'> | undefined,
  opts: VideoOpts,
  clipDuration: number | null,
): Schemas['VideoTurnOptions'] {
  return {
    aspect_ratio: opts.aspect_ratio || null,
    resolution: opts.resolution || null,
    duration: opts.duration ? Number(opts.duration) : clipDuration,
    duration_auto: !opts.duration,
    generate_audio: info?.generate_audio ? opts.generate_audio : null,
  }
}
