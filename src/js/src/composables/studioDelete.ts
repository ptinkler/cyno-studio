import type { components } from '../api/schema'
import type { DialogOptions } from './useDialog'

// What the "delete this prompt and its reply?" dialog says, from the server's count of what goes with it.

type DeleteInfo = components['schemas']['DeleteInfo']

const plural = (n: number, word: string): string => `${String(n)} ${word}${n === 1 ? '' : 's'}`

function deleteDetail({ other_versions: versions, other_messages: after }: DeleteInfo): string {
  const removes = [versions && plural(versions, 'other version'), after && plural(after, 'message')].filter(Boolean)
  const where = versions ? ' that followed them' : ' on other branches'
  return removes.length ? `This also removes ${removes.join(' and ')}${after ? where : ''}.` : ''
}

// The files the "also delete" box decides on, named so it's clear what goes:
// only what this turn generated (uploads stay), and nothing at all when the
// generation failed — then there's no box to tick.
const MEDIA_WORDS: Readonly<Record<string, string>> = { image: 'image', video: 'video', audio: 'audio clip' }

export function deleteMediaLabel(media: Readonly<Record<string, number>> | null | undefined): string {
  const parts = Object.entries(media ?? {})
    .filter(([, n]) => n > 0)
    .map(([kind, n]) => plural(n, MEDIA_WORDS[kind] ?? 'file'))
  const [first] = parts
  if (first === undefined) return ''
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1) ?? ''}` : first
  return `Also delete the ${list} it made`
}

// The confirmDialog() options for a delete-info reply ({ other_versions, other_messages, media })
export function deleteDialogOptions(info: DeleteInfo): DialogOptions {
  const mediaLabel = deleteMediaLabel(info.media)
  return {
    title: 'Delete this prompt and its reply?',
    message: [deleteDetail(info), mediaLabel && 'Unticked, those files stay in your Media library.']
      .filter(Boolean)
      .join(' '),
    confirmLabel: 'Delete',
    danger: true,
    ...(mediaLabel ? { checkbox: { label: mediaLabel, checked: true } } : {}),
  }
}
