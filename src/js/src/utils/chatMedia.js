// Small rules about the media on a chat message, shared by its attachments and its generated cards.

// Only saved images (not a reply still streaming) can be pinned as references
export const canPinMedia = (item, message) => item.kind === 'image' && !!item.file && typeof message.id === 'number'
