<!--
  Unified Studio shell (overhaul). Thin orchestrator: it owns the shared
  catalogue + composer settings, wires useStudio()'s state/behaviour to the
  presentational panes (sidebar / feed+composer / inspector), and holds the
  icon sprite. All logic lives in useStudio; all markup in the child
  components. Route: /studio — runs alongside the existing app during the build.
-->
<script setup lang="ts">
import { ref, reactive, computed, provide, inject, onMounted, onUnmounted } from 'vue'
import { showToastKey, noToast, composerSettingsKey, chatModelsKey } from '../injection'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { useNarrowScreen } from '../composables/useNarrowScreen'
import { isVideoModel } from '../composables/chatModelsApi'
import type { Catalogues } from '../composables/useComposerSettings'
import { useComposerSettings } from '../composables/useComposerSettings'
import { useStudio } from '../composables/useStudio'
import { useStudioTheme } from '../composables/useStudioTheme'
import { useThreadView } from '../composables/useThreadView'
import { useAttachmentPicker } from '../composables/useAttachmentPicker'
import { useGalleryModal } from '../composables/useGalleryModal'
import type { Space } from '../composables/studioTypes'
import { useStudioRoutes } from '../composables/useStudioRoutes'
import StudioSidebar from '../components/studio/StudioSidebar.vue'
import StudioInspector from '../components/studio/StudioInspector.vue'
import StudioComposer from '../components/studio/StudioComposer.vue'
import StudioFeed from '../components/studio/StudioFeed.vue'
import StudioGenerations from '../components/studio/StudioGenerations.vue'
import GenerationGrid from '../components/studio/GenerationGrid.vue'
import GenerationModal from '../components/studio/GenerationModal.vue'
import GenerationQueueDock from '../components/studio/GenerationQueueDock.vue'
import { useGenQueue } from '../composables/useGenQueue'
import type { Generation } from '../composables/chatFilesApi'
import StudioSpace from '../components/studio/StudioSpace.vue'
import StudioMedia from '../components/studio/StudioMedia.vue'
import StudioUsage from '../components/studio/StudioUsage.vue'
import StudioCharactersPage from '../components/studio/StudioCharactersPage.vue'
import StudioPresetsPage from '../components/studio/StudioPresetsPage.vue'
import StudioInstructionsPage from '../components/studio/StudioInstructionsPage.vue'
import StudioRequestLog from '../components/studio/StudioRequestLog.vue'
import StudioSettings from '../components/studio/StudioSettings.vue'
import StudioTools from '../components/studio/StudioTools.vue'
import StudioIconSprite from '../components/studio/StudioIconSprite.vue'
import StudioBalances from '../components/studio/StudioBalances.vue'
import MediaPicker from '../components/media/MediaPicker.vue'
import CharacterEditor from '../components/characters/CharacterEditor.vue'
import InstructionEditor from '../components/chat/InstructionEditor.vue'
import SpaceSettingsDialog from '../components/chat/SpaceSettingsDialog.vue'
import ImportChatsModal from '../components/chat/ImportChatsModal.vue'
import '../components/studio/studio.css'

const router = useRouter()
const route = useRoute()
const { logout } = useAuth()

async function onSignOut(): Promise<void> {
  try {
    await logout()
  } catch {
    /* ignore */
  }
  window.location.href = '/'
}

const showToast = inject(showToastKey, noToast)

const models = reactive<Catalogues>({ text: [], image: [], video: [], audio: [] })
provide(chatModelsKey, models) // ChatMessage's "Try another model"
const settings = useComposerSettings(models)
provide(composerSettingsKey, settings) // read by the inspector's model/options sections
const { mode } = settings
// The picked video model, when the mode is Video: what its inputs allow shapes the composer
const activeVideo = computed(() => {
  const info = settings.activeInfo.value
  return info && isVideoModel(info) ? info : undefined
})

const studio = useStudio({ models, settings, showToast })
const {
  modelsLoading,
  threads,
  spaces,
  active,
  activeTitle,
  messages,
  sending,
  draft,
  lane,
  estimate,
  unusedAttachments,
  activeKind,
  attachments,
  uploading,
  addFiles,
  removeAttachment,
  lastAssistantId,
  canSend,
  loadModels,
  loadLists,
  openThread,
  loadStatus,
  send,
  retry,
  editMessage,
  resendMessage,
  switchBranch,
  forkFrom,
  regenerateMedia,
  pinMedia,
  stop,
  deleteExchange,
  addFromLibrary,
  enhancing,
  enhanceDraft,
  useImage,
  reword,
  showTextVersion,
  showMediaVersion,
  toggleFav,
  renameThread,
  removeThread,
  moveThread,
  addSpace,
  renameSpace,
  // instructions
  instructions,
  instructionGroups,
  instructionIds,
  instructionGroupIds,
  instructionSummary,
  setInstructions,
  setGroups,
  onInstructionsChanged,
  editingInstruction,
  loadInstructions,
  inheritedDefaults,
  hiddenInherited,
  pausedInstructionIds,
  setDefaultHidden,
  setPaused,
  loadDefaults,
  globalSettings,
  // characters
  characters,
  characterIds,
  charEditor,
  characterNames,
  characterSupport,
  loadCharacters,
  setCharacters,
  editCharacter,
  newCharacter,
  onCharacterSaved,
  onCharacterDeleted,
  spend,
  balances,
} = studio

const { theme, dataTheme, setTheme } = useStudioTheme()
const { threadView, chatMessages, composerModes } = useThreadView({ route, activeKind, draft, lane, messages, mode })
const { pickerOpen, pickerKinds, pickerLimits, pickerTitle } = useAttachmentPicker({ settings, attachments })

// Always-visible generation queue (polls across all threads; survives navigation).
const genQueue = useGenQueue()
const { entries: queueItems, pending: queuePending, done: queueDone } = genQueue
onMounted(() => {
  genQueue.start()
})
onUnmounted(() => {
  genQueue.stop()
})
// Generate from the composer, then refresh the queue so the new tile shows at once.
function onGenerate(): void {
  void send()
  void genQueue.refresh()
}
// Clicking a queued item jumps to that thread's gallery (where its tile lives).
function openQueueItem(entry: Generation): void {
  void router.push(`/${entry.conversation_id}/gallery`)
}
const leftCollapsed = ref(false)
const rightCollapsed = ref(false)
function collapsePanels(): void {
  leftCollapsed.value = true
  rightCollapsed.value = true
}
if (useNarrowScreen(collapsePanels).value) collapsePanels()
const search = ref('')
const spaceSettings = ref<Space | 'new' | 'global' | null>(null) // a space | 'new' | 'global' | null (closed)
const importOpen = ref(false)
function onSpacesChanged(): void {
  void loadDefaults()
  void loadLists()
}
const onImported = onSpacesChanged

const {
  centerView,
  sidebarFilter,
  onFilter,
  activeSpace,
  spaceThreads,
  composerRef,
  openSpace,
  deleteSpaceView,
  goThread,
  goSettings,
  goTools,
  goMedia,
  goInstructions,
  openThreadView,
  newThreadView,
  setThreadView,
  onSettingsNavigate,
  syncFromRoute,
} = useStudioRoutes({ router, route, studio, threadView })

// After the routes: the modal's actions navigate with openThreadView
const {
  galleryItem,
  galleryManage,
  favItems,
  openGeneration,
  onGalleryFavourite,
  onFavUnstar,
  openFavourite,
  regenerateFromModal,
  useSettingsFromModal,
  useImageFromModal,
  deleteFromModal,
  openThreadFromModal,
  makeCharacterFromModal,
} = useGalleryModal({ studio, genQueue, openThreadView })

onMounted(() => {
  void loadLists()
  void loadModels()
  void loadStatus() // which providers are configured + refresh their balances (Pollo/OpenRouter/Venice)
  void loadInstructions()
  void loadCharacters()
  void loadDefaults()
  void syncFromRoute()
})
</script>

<template>
  <div class="studio" :data-theme="dataTheme">
    <StudioSidebar
      v-model:collapsed="leftCollapsed"
      v-model:search="search"
      :filter="sidebarFilter"
      :threads="threads"
      :spaces="spaces"
      :active="centerView === 'thread' ? active : null"
      @update:filter="onFilter"
      @open="openThreadView"
      @new="newThreadView"
      @pin="toggleFav"
      @rename="renameThread"
      @delete="removeThread"
      @settings="goSettings"
      @open-space="openSpace"
      @add-space="addSpace"
      @rename-space="renameSpace"
      @delete-space="deleteSpaceView"
      @move="moveThread"
      @media="goMedia"
      @tools="goTools"
      @space-settings="spaceSettings = $event"
    />

    <main class="center">
      <StudioSettings
        v-if="centerView === 'settings'"
        :theme="theme"
        @set-theme="setTheme"
        @close="goThread"
        @navigate="onSettingsNavigate"
        @sign-out="onSignOut"
      />

      <StudioTools
        v-else-if="centerView === 'tools'"
        @close="goThread"
        @navigate="onSettingsNavigate"
        @defaults="spaceSettings = 'global'"
        @import="importOpen = true"
      />

      <StudioSpace
        v-else-if="centerView === 'space' && activeSpace"
        :space="activeSpace"
        :threads="spaceThreads"
        @open="openThreadView"
        @new="newThreadView"
        @close="goThread"
      />

      <StudioMedia v-else-if="centerView === 'media'" @close="goThread" />

      <StudioUsage
        v-else-if="centerView === 'usage'"
        :balances="balances"
        @close="goThread"
        @refresh="loadStatus"
        @manage-keys="goSettings"
      />

      <StudioCharactersPage v-else-if="centerView === 'characters'" @close="goThread" />
      <StudioPresetsPage v-else-if="centerView === 'presets'" @close="goThread" />

      <StudioInstructionsPage v-else-if="centerView === 'instructions'" @close="goThread" />

      <StudioRequestLog v-else-if="centerView === 'requests'" @close="goThread" />

      <template v-else-if="centerView === 'favourites'">
        <div class="top">
          <div class="ttitle">Favourites</div>
          <div class="spacer"></div>
          <span class="gcount">{{ favItems.length }} starred</span>
        </div>
        <GenerationGrid
          :items="favItems"
          :fav-filter="false"
          empty="No favourites yet — star a generation to add it here."
          @open="openFavourite"
          @favourite="onFavUnstar"
        />
      </template>

      <template v-else>
        <div class="top">
          <div class="seg" role="group" aria-label="Thread view">
            <button
              :class="{ on: threadView === 'chat' }"
              title="Open threads in Chat"
              aria-label="Open threads in Chat"
              @click="setThreadView('chat')"
            >
              <svg class="ic"><use href="#s-chat" /></svg>
            </button>
            <button
              :class="{ on: threadView === 'gallery' }"
              title="Open threads in Gallery"
              aria-label="Open threads in Gallery"
              @click="setThreadView('gallery')"
            >
              <svg class="ic"><use href="#s-image" /></svg>
            </button>
          </div>
          <div class="ttitle">{{ activeTitle }}</div>
          <div class="spacer"></div>
          <StudioBalances :balances="balances" :spend="spend" :messages="messages" @usage="router.push('/usage')" />
        </div>

        <StudioFeed
          v-if="threadView === 'chat'"
          :messages="chatMessages"
          :active="active"
          :sending="sending"
          :last-assistant-id="lastAssistantId"
          @retry="retry"
          @edit="editMessage"
          @resend="resendMessage"
          @branch="switchBranch"
          @use-image="useImage"
          @reword="reword"
          @text-version="showTextVersion"
          @media-version="showMediaVersion"
          @regenerate="regenerateMedia"
          @pin="pinMedia"
          @delete="deleteExchange"
          @fork="forkFrom"
          @open-chat="openThreadView"
          @stop="stop"
          @open-media="openGeneration"
        />
        <StudioGenerations
          v-else
          :messages="messages"
          :conv-id="active ?? undefined"
          @open="openGeneration"
          @favourite="onGalleryFavourite"
          @deleted="active && openThread(active)"
        />

        <StudioComposer
          ref="composerRef"
          v-model:draft="draft"
          v-model:mode="mode"
          :modes="composerModes"
          :sending="sending"
          :can-send="canSend"
          :attachments="attachments"
          :uploading="uploading"
          :enhancing="enhancing"
          :estimate="estimate"
          :unused="unusedAttachments"
          :video-input="!!activeVideo?.video_input"
          :audio-input="!!activeVideo?.audio_input"
          :ref-mode="activeVideo?.ref_mode ?? null"
          @send="onGenerate"
          @files="addFiles"
          @remove="removeAttachment"
          @clear="[...attachments].forEach(removeAttachment)"
          @library="pickerOpen = true"
          @enhance="enhanceDraft"
        />
      </template>
    </main>

    <StudioInspector
      v-model:collapsed="rightCollapsed"
      :models="models"
      :models-loading="modelsLoading"
      :instructions="{
        list: instructions,
        groups: instructionGroups,
        snippetIds: instructionIds,
        groupIds: instructionGroupIds,
        summary: instructionSummary,
        inheritedSnippets: inheritedDefaults.instruction,
        inheritedGroups: inheritedDefaults.instruction_group,
        hiddenSnippets: hiddenInherited.instruction,
        hiddenGroups: hiddenInherited.instruction_group,
        pausedSnippets: pausedInstructionIds.snippets,
        pausedGroups: pausedInstructionIds.groups,
      }"
      :characters="{
        list: characters,
        ids: characterIds,
        names: characterNames,
        support: characterSupport,
        inherited: inheritedDefaults.character,
        hidden: hiddenInherited.character,
      }"
      @update:snippet-ids="setInstructions"
      @update:group-ids="setGroups"
      @manage="goInstructions"
      @edit-instruction="editingInstruction = $event"
      @instr-hide="setDefaultHidden($event, true)"
      @instr-unhide="setDefaultHidden($event, false)"
      @instr-pause="setPaused($event, true)"
      @instr-resume="setPaused($event, false)"
      @update:character-ids="setCharacters"
      @edit-character="editCharacter"
      @create-character="newCharacter()"
      @char-hide="setDefaultHidden({ kind: 'character', id: $event }, true)"
      @char-unhide="setDefaultHidden({ kind: 'character', id: $event }, false)"
    />

    <MediaPicker
      :open="pickerOpen"
      :title="pickerTitle"
      :kinds="pickerKinds"
      :limits="pickerLimits"
      source="upload"
      @pick="addFromLibrary"
      @close="pickerOpen = false"
    />

    <GenerationModal
      :item="galleryItem"
      :can-manage="galleryManage"
      :theme="dataTheme"
      @close="galleryItem = null"
      @favourite="galleryManage ? onGalleryFavourite($event) : onFavUnstar($event)"
      @use-image="useImageFromModal"
      @use-settings="useSettingsFromModal"
      @regenerate="regenerateFromModal"
      @delete="deleteFromModal"
      @open-thread="openThreadFromModal"
      @make-character="makeCharacterFromModal"
    />

    <GenerationQueueDock
      :entries="queueItems"
      :pending="queuePending"
      :done="queueDone"
      @open="openQueueItem"
      @clear="genQueue.clearDone"
      @clear-one="genQueue.clearOne"
    />

    <CharacterEditor
      :open="charEditor.open"
      :character="charEditor.character"
      :conversation-id="charEditor.conversationId"
      :seed="charEditor.seed"
      show-defaults
      @close="charEditor.open = false"
      @saved="onCharacterSaved"
      @deleted="onCharacterDeleted"
    />

    <InstructionEditor
      :target="editingInstruction"
      :instructions="instructions"
      :groups="instructionGroups"
      @close="editingInstruction = null"
      @changed="onInstructionsChanged"
    />

    <SpaceSettingsDialog
      :target="spaceSettings"
      :global-settings="globalSettings"
      :characters="characters"
      :instructions="instructions"
      :groups="instructionGroups"
      @close="spaceSettings = null"
      @changed="onSpacesChanged"
    />

    <ImportChatsModal :visible="importOpen" @close="importOpen = false" @imported="onImported" />
  </div>

  <StudioIconSprite />
</template>

<style scoped src="./StudioView.css"></style>
