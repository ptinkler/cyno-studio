// The chat API in one place. Everything is implemented in the typed modules below (each owns one area and
// takes its types from the backend); this file only gathers them, so composables import from one path and
// tests have one seam to mock.

// Status, balances, defaults, instructions and spaces
export {
  fetchChatStatus,
  fetchOpenRouterCredits,
  fetchVeniceBalance,
  fetchInstructions,
  createInstruction,
  updateInstruction,
  deleteInstruction,
  createInstructionGroup,
  updateInstructionGroup,
  deleteInstructionGroup,
  fetchSpaces,
  createSpace,
  updateSpace,
  deleteSpace,
  fetchSettings,
  updateSettings,
  setTitleModel,
} from './chatSettingsApi'

// Conversations and their messages are typed in chatConversationsApi.ts
export {
  fetchConversations,
  fetchConversationSpend,
  fetchSpendBreakdown,
  fetchConversation,
  fetchConversationThumbs,
  createConversation,
  patchConversation,
  deleteConversation,
  fetchChatMessage,
  switchChatBranch,
  forkConversation,
  deleteChatExchange,
  fetchDeleteInfo,
  fetchConversationDeleteInfo,
} from './chatConversationsApi'

// Media-card actions: pin, favourite, regenerate, versions
export {
  regenerateChatMedia,
  showChatTextVersion,
  showChatMediaVersion,
  pinChatMedia,
  favouriteChatMedia,
} from './chatMediaApi'

// The model catalogue is typed in chatModelsApi.ts
export { fetchChatModels } from './chatModelsApi'

// A chat's files, library, generation queue and request log are typed in chatFilesApi.ts
export {
  uploadChatAttachment,
  uploadChatVideoAttachment,
  uploadChatAudioAttachment,
  discardChatAttachment,
  chatMediaUrl,
  chatMediaPreviewUrl,
  fetchActiveGenerations,
  fetchChatLibrary,
} from './chatFilesApi'

// Importing and exporting chats are typed in chatTransferApi.ts
export {
  fetchChatGptImport,
  startChatGptImport,
  startChatGptUpload,
  sendChatGptUploadChunk,
  cancelChatGptUpload,
  chatExportUrl,
  fetchExportableChats,
} from './chatTransferApi'

// Composer helpers: estimate, enhance, voices, cancel
export { fetchAudioVoices, estimateChatCost, enhanceChatPrompt, cancelChatMessage } from './chatToolsApi'

// The streamed turns (send, retry, edit, reword) and their event types are in chatStreamApi.ts
export { readSSE, sendChatMessage, retryChatMessage, editChatMessage, rewordChatMessage } from './chatStreamApi'
