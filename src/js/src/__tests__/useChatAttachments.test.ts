import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'

vi.mock('../composables/chatFilesApi', () => ({
  uploadChatAttachment: vi.fn(() => Promise.resolve({ file: 'up_same.png' })),
  uploadChatVideoAttachment: vi.fn(),
  uploadChatAudioAttachment: vi.fn(),
  discardChatAttachment: vi.fn(() => Promise.resolve()),
  chatMediaUrl: (c: string, f: string) => `/m/${c}/${f}`,
  chatMediaPreviewUrl: (c: string, f: string) => `/m/${c}/${f}/preview`,
}))
vi.mock('../composables/mediaApi', () => ({ importMediaToChat: vi.fn() }))

const { useChatAttachments } = await import('../composables/useChatAttachments')

describe('useChatAttachments', () => {
  it('attaching the same picture twice keeps one', async () => {
    URL.createObjectURL = () => 'blob:x'
    const a = useChatAttachments({
      convId: ref('c1'),
      ensureConversation: () => Promise.resolve('c1'),
      showToast: vi.fn(),
    })
    const png = new File(['x'], 'a.png', { type: 'image/png' })
    a.addFiles([png])
    a.addFiles([png])
    await vi.waitFor(() => {
      expect(a.attachments.value.every(x => !x.uploading)).toBe(true)
      expect(a.attachments.value).toHaveLength(1)
    })
    expect(a.files.value).toEqual(['up_same.png'])
  })
})
