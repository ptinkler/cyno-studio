// Small shared helpers for the chat defaults (global and per space)

// Where an inherited default comes from ('All chats' or a space's name): its icon and tooltip
export const ALL_CHATS = 'All chats'
export const defaultIcon = (from: string): string => (from === ALL_CHATS ? '🌐' : '🗂')
export const defaultTitle = (from: string): string =>
  from === ALL_CHATS ? 'From the defaults for all chats' : `From the ${from} defaults`

// The same ids, in any order
export const sameIds = <T>(a: readonly T[], b: readonly T[]): boolean =>
  a.length === b.length && a.every(item => b.includes(item))
