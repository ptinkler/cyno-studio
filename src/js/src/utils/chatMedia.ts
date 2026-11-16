// Small rules about the media on a chat message, shared by its attachments and its generated cards.

// Only saved images (not a reply still streaming) can be pinned as references
export const canPinMedia = (
  item: { kind?: string | null; file?: string | null },
  message: { id: number | string },
): boolean => item.kind === 'image' && !!item.file && typeof message.id === 'number'
