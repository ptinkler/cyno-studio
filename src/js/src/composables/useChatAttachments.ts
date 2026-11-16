import { computed, reactive, ref } from 'vue'
import type { Ref } from 'vue'
import { chatMediaUrl, chatMediaPreviewUrl } from './chatFilesApi'
import {
  discardChatAttachment,
  uploadChatAttachment,
  uploadChatAudioAttachment,
  uploadChatVideoAttachment,
} from './chatFilesApi'
import { importMediaToChat } from './mediaApi'
import type { ShowToast } from './useToast'
import { messageOf } from '../utils/errors'

export const MAX_ATTACHMENTS = 8

/** One thing attached to the next message: on the server (`file`) or still uploading. */
export interface Attachment {
  key: string
  file: string | null // set once it is on the server
  preview: string
  video: boolean
  audio: boolean
  uploading: boolean
}

/** Something from the media library (or a stand-in for a chat file) that can be attached. */
export interface LibrarySource {
  id: string
  kind?: string | null
  url?: string | null
  thumb_url?: string | null
}

interface AttachmentHooks {
  convId: Ref<string | null>
  /** The chat to attach into (made first when there isn't one yet). */
  ensureConversation: () => Promise<string>
  showToast: ShowToast
  /** How many images the selected model takes. */
  limit?: () => number
  videoLimit?: () => number
  audioLimit?: () => number
}

const VIDEO_FILE = /\.(mp4|webm|mov)$/i

// Images attached to the next message: uploaded from the device, copied in
// from the media library, or already in the chat.
export function useChatAttachments({
  convId,
  ensureConversation,
  showToast,
  limit = () => MAX_ATTACHMENTS,
  videoLimit = () => 1,
  audioLimit = () => 1,
}: AttachmentHooks) {
  const attachments = ref<Attachment[]>([])
  const images = (): number => attachments.value.filter(a => !a.video && !a.audio).length
  const videos = (): number => attachments.value.filter(a => a.video).length
  const audios = (): number => attachments.value.filter(a => a.audio).length
  const room = (): number => Math.min(MAX_ATTACHMENTS - attachments.value.length, limit() - images())
  const files = computed(() => attachments.value.flatMap(a => a.file ?? []))
  const uploading = computed(() => attachments.value.some(a => a.uploading))

  // Why nothing more can be added: the model's own image limit, else the general cap
  const fullMessage = (): string =>
    limit() < MAX_ATTACHMENTS && images() >= limit()
      ? `This model takes ${String(limit())} image${limit() === 1 ? '' : 's'} — pick a reference-image (“Ref”) model for more`
      : `Up to ${String(MAX_ATTACHMENTS)} attachments per message`

  function add(preview: string, file: string | null = null, video = false, audio = false): Attachment {
    const attachment = reactive<Attachment>({
      key: Math.random().toString(36).slice(2),
      file,
      preview,
      video,
      audio,
      uploading: !file,
    })
    attachments.value.push(attachment)
    return attachment
  }

  function remove(attachment: Attachment): void {
    if (attachment.preview.startsWith('blob:')) URL.revokeObjectURL(attachment.preview)
    attachments.value = attachments.value.filter(a => a !== attachment)
    // Removed before sending: don't leave the upload behind (no-op if still in use)
    if (attachment.file && convId.value) discardChatAttachment(convId.value, attachment.file).catch(() => undefined)
  }

  function clear(): void {
    attachments.value = []
  }

  // Each source becomes an attachment at once; `send(source, chatId)` puts it on the server
  async function attachEach<S>(
    sources: readonly S[],
    preview: (source: S) => string,
    send: (source: S, chatId: string) => Promise<{ file: string }>,
    video = false,
    audio = false,
  ): Promise<void> {
    const single = video || audio // a video / audio rides singly, outside the image-count cap
    let id: string
    try {
      id = await ensureConversation()
    } catch (e) {
      showToast(messageOf(e), 'error')
      return
    }
    if (!single && sources.length > room()) showToast(fullMessage(), 'error')
    for (const source of single ? sources : sources.slice(0, Math.max(room(), 0))) {
      const attachment = add(preview(source), null, video, audio)
      send(source, id)
        .then(result => {
          attachment.file = result.file
        })
        .catch((e: unknown) => {
          showToast(messageOf(e), 'error')
          remove(attachment)
        })
        .finally(() => {
          attachment.uploading = false
        })
    }
  }

  // Files from the device (picked, pasted or dropped): images, source videos
  // and audio tracks. Most models take a single video + single audio; a
  // reference-to-video model takes several of each (up to its ref_mode caps,
  // via videoLimit / audioLimit).
  function addFiles(list: Iterable<File>): void {
    const picked = [...list]
    const vids = picked.filter(f => f.type === 'video/mp4').slice(0, Math.max(videoLimit() - videos(), 0))
    if (vids.length) {
      void attachEach(
        vids,
        f => URL.createObjectURL(f),
        (f, id) => uploadChatVideoAttachment(id, f),
        true,
      )
    }
    const auds = picked.filter(f => f.type.startsWith('audio/')).slice(0, Math.max(audioLimit() - audios(), 0))
    if (auds.length) {
      void attachEach(
        auds,
        () => '',
        (f, id) => uploadChatAudioAttachment(id, f),
        false,
        true,
      )
    }
    const pictures = picked.filter(f => f.type.startsWith('image/'))
    if (pictures.length) {
      void attachEach(
        pictures,
        f => URL.createObjectURL(f),
        (f, id) => uploadChatAttachment(id, f),
      )
    }
  }

  // Items from the media library, copied into the chat — each with its kind, so
  // a picked video imports as a video reference, not an image.
  function addFromLibrary(items: readonly LibrarySource[]): void {
    for (const item of items) {
      // A video needs a playable URL for the <video> thumbnail; an image uses its thumb.
      const preview = item.kind === 'video' ? (item.url ?? item.thumb_url) : (item.thumb_url ?? item.url)
      void attachEach(
        [item],
        () => preview ?? '',
        (it, id) => importMediaToChat(it.id, id),
        item.kind === 'video',
        item.kind === 'audio',
      )
    }
  }

  // Re-attach an existing media file by kind (image/video/audio) — used to put
  // a past generation's references back when you "use settings". Same thread:
  // reference it directly; another thread: import a copy with the right kind.
  function addChatMedia(file: string, kind = 'image', fromConv: string | null = null): boolean {
    const video = kind === 'video'
    const audio = kind === 'audio'
    if (fromConv && fromConv !== convId.value) {
      void attachEach(
        [{ id: `chat:${fromConv}:${file}`, thumb: chatMediaPreviewUrl(fromConv, file) }],
        source => source.thumb,
        (source, id) => importMediaToChat(source.id, id),
        video,
        audio,
      )
      return true
    }
    if (attachments.value.some(a => a.file === file)) return true
    if (convId.value === null) return false // not in a chat yet: there is no such file to point at
    add(audio ? '' : chatMediaUrl(convId.value, file), file, video, audio)
    return true
  }

  // An image already in this chat; false if there's no room for it
  // (`fromConv`: it lives in another thread, so copy it into this one)
  function addChatImage(file: string, fromConv: string | null = null): boolean {
    if (VIDEO_FILE.test(file)) return false // a video isn't an image reference
    if (fromConv && fromConv !== convId.value) {
      if (room() < 1) {
        showToast(fullMessage(), 'error')
        return false
      }
      addFromLibrary([{ id: `chat:${fromConv}:${file}`, thumb_url: chatMediaPreviewUrl(fromConv, file) }])
      return true
    }
    if (attachments.value.some(a => a.file === file)) return true
    if (convId.value === null) return false
    if (room() < 1) {
      showToast(fullMessage(), 'error')
      return false
    }
    add(chatMediaUrl(convId.value, file), file)
    return true
  }

  return { attachments, files, uploading, room, addFiles, addFromLibrary, addChatImage, addChatMedia, remove, clear }
}
