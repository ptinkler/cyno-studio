<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { GenerationItem, ImagePick } from '../../composables/studioTypes'
import { shortModel, fmtCost, creditsToUsd } from '../../utils/format'
import RequestDialog from '../chat/RequestDialog.vue'

const props = withDefaults(
  defineProps<{
    item?: GenerationItem | null | undefined
    canManage?: boolean | undefined
    /** Studio theme ('dark' | 'light'), so the body-teleported modal keeps the --s* vars. */
    theme?: string | undefined
  }>(),
  { item: null, canManage: false, theme: '' },
)
const emit = defineEmits<{
  close: []
  favourite: [item: GenerationItem]
  'use-image': [pick: ImagePick]
  'use-settings': [item: GenerationItem]
  regenerate: [item: GenerationItem]
  delete: [item: GenerationItem]
  'open-thread': [id: string]
  'make-character': [item: GenerationItem]
}>()

const isVideo = computed(() => props.item?.kind === 'video')
const isError = computed(() => props.item?.status === 'error')
const requestOpen = ref(false) // the "exactly what was sent" dialog
// Pollo bills in credits, everything else in dollars
const costLabel = computed(() => {
  const { credits, cost } = props.item ?? {}
  if (credits) return `${fmtCost(creditsToUsd(credits))} (${String(credits)} cr)`
  return fmtCost(cost)
})
const loop = ref(false) // videos don't autoplay; the user opts into looping
const when = computed(() => {
  const created = props.item?.created_at
  if (!created) return ''
  const date = new Date(created)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
})

function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape' && props.item) emit('close')
}
onMounted(() => {
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <!-- Teleport to body (not .studio): .studio is an ancestor of this modal, so it
       isn't in the DOM yet when the Teleport first mounts — resolving .studio then
       fails and the modal never opens. The `studio` class + data-theme re-supply the
       --s* theme vars that would otherwise only cascade from the .studio ancestor. -->
  <Teleport to="body">
    <div v-if="item" class="gm-back studio" :data-theme="theme || undefined" @click="emit('close')">
      <div class="gm-card" role="dialog" aria-modal="true" aria-label="Generation" @click.stop>
        <button class="gm-x" title="Close" aria-label="Close" @click="emit('close')">×</button>

        <div class="gm-media" :class="{ 'is-error': isError }">
          <div v-if="isError" class="gm-err">
            <div class="gm-err-title">{{ item.moderated ? 'Blocked by moderation' : 'Generation failed' }}</div>
            <div class="gm-err-msg">{{ item.error || 'Unknown error' }}</div>
          </div>
          <template v-else-if="isVideo">
            <video :src="item.url" controls :loop="loop" playsinline></video>
            <label class="gm-loop"><input v-model="loop" type="checkbox" /> Loop</label>
          </template>
          <img v-else :src="item.url" alt="" />
        </div>

        <div class="gm-side">
          <div class="gm-scroll">
            <div class="gm-prompt">{{ item.original_prompt || item.prompt || 'No prompt' }}</div>
            <details v-if="item.original_prompt && item.prompt && item.prompt !== item.original_prompt" class="gm-sent">
              <summary>Prompt sent to the model</summary>
              <div class="gm-prompt">{{ item.prompt }}</div>
            </details>
            <dl class="gm-meta">
              <template v-if="item.model">
                <dt>Model</dt>
                <dd>{{ shortModel(item.model) }}</dd>
              </template>
              <template v-if="costLabel">
                <dt>Cost</dt>
                <dd>{{ costLabel }}</dd>
              </template>
              <template v-if="when">
                <dt>Created</dt>
                <dd>{{ when }}</dd>
              </template>
              <template v-if="item.conversation_title">
                <dt>Thread</dt>
                <dd>{{ item.conversation_title }}</dd>
              </template>
            </dl>
          </div>

          <div class="gm-actions">
            <div class="gm-icons">
              <button
                v-if="!isError"
                class="gm-btn icon"
                :class="{ on: item.favourite }"
                :title="item.favourite ? 'Unfavourite' : 'Favourite'"
                @click="emit('favourite', item)"
              >
                <svg class="ic"><use href="#s-star" /></svg>
              </button>
              <a v-if="!isError" class="gm-btn icon" title="Download" :href="item.url" :download="item.file">
                <svg class="ic"><use href="#s-download" /></svg>
              </a>
              <button
                v-if="canManage"
                class="gm-btn icon danger"
                title="Delete"
                aria-label="Delete"
                @click="emit('delete', item)"
              >
                <svg class="ic"><use href="#s-trash" /></svg>
              </button>
              <button v-if="item.request" class="gm-btn icon req" title="View request" @click="requestOpen = true">
                { }
              </button>
            </div>
            <div class="gm-grid">
              <!-- Only a picture can start another picture, a video or a character -->
              <template v-if="!isError && item.kind === 'image'">
                <button
                  class="gm-btn"
                  title="Use in Image mode"
                  @click="emit('use-image', { file: item.file, mode: 'image', conversation_id: item.conversation_id })"
                >
                  <svg class="ic"><use href="#s-image" /></svg>Edit
                </button>
                <button
                  class="gm-btn"
                  title="Use in Video mode"
                  @click="emit('use-image', { file: item.file, mode: 'video', conversation_id: item.conversation_id })"
                >
                  <svg class="ic"><use href="#s-film" /></svg>Animate
                </button>
                <button class="gm-btn" title="Make character" @click="emit('make-character', item)">
                  <svg class="ic"><use href="#s-user" /></svg>Character
                </button>
              </template>
              <button v-if="canManage" class="gm-btn" title="Reuse settings" @click="emit('use-settings', item)">
                <svg class="ic"><use href="#s-cog" /></svg>Settings
              </button>
              <button v-if="canManage" class="gm-btn" :class="{ primary: isError }" @click="emit('regenerate', item)">
                <svg class="ic"><use href="#s-refresh" /></svg>{{ isError ? 'Retry' : 'Regenerate' }}
              </button>
              <a
                v-if="!canManage && item.conversation_id"
                class="gm-btn"
                :href="`/${item.conversation_id}`"
                @click.prevent="emit('open-thread', item.conversation_id)"
              >
                <svg class="ic"><use href="#s-chat" /></svg>Open thread
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
  <!-- Its own Teleport, so it must NOT be nested inside the modal's Teleport
       (nested teleports to <body> crash on teardown — emitsOptions null). -->
  <RequestDialog
    v-if="requestOpen && item"
    :request="item.request"
    :response="item.response"
    :error="isError ? (item.error ?? '') : ''"
    @close="requestOpen = false"
  />
</template>

<style scoped>
a.gm-btn {
  text-decoration: none;
}
.gm-btn.icon.req {
  font-family: monospace;
  font-weight: 700;
  font-size: 0.8667rem;
}
.gm-sent {
  margin-top: 0.6667rem;
  font-size: 0.8333rem;
  color: var(--smuted, inherit);
}
.gm-sent summary {
  cursor: pointer;
}
.gm-back {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  background: rgba(0, 0, 0, 0.82);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.6rem;
}
.gm-card {
  position: relative;
  display: flex;
  gap: 0;
  width: min(73.3333rem, 100% - 1.5rem);
  max-height: 90dvh;
  background: var(--sbg);
  border: 1px solid var(--sborder);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-modal);
  overflow: hidden;
}
.gm-x {
  position: absolute;
  top: 0.6667rem;
  right: 0.8rem;
  z-index: 2;
  width: 2rem;
  height: 2rem;
  border: none;
  border-radius: 0.5333rem;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  font-size: 1.3333rem;
  line-height: 1;
  cursor: pointer;
}
.gm-media {
  position: relative;
  flex: 1 1 auto;
  min-width: 0;
  display: grid;
  place-items: center;
  background: #000;
  padding: 0.6667rem;
}
.gm-media img,
.gm-media video {
  max-width: 100%;
  max-height: calc(90dvh - 1.3333rem);
  object-fit: contain;
  border-radius: 0.5333rem;
}
.gm-media.is-error {
  background: var(--sbg2);
}
.gm-err {
  display: flex;
  flex-direction: column;
  gap: 0.6667rem;
  align-items: center;
  text-align: center;
  padding: 2.1333rem;
  max-width: 29.3333rem;
}
.gm-err-title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--sdanger);
}
.gm-err-msg {
  font-size: 0.8667rem;
  line-height: 1.5;
  color: var(--smuted);
  white-space: pre-wrap;
  word-break: break-word;
}
.gm-btn.primary {
  background: var(--saccent-fill);
  border-color: var(--saccent-fill);
  color: #fff;
}
.gm-btn.primary:hover {
  filter: brightness(1.08);
  background: var(--saccent);
}
.gm-loop {
  position: absolute;
  left: 1.0667rem;
  bottom: 0.9333rem;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  font-weight: 500;
  text-transform: none;
  letter-spacing: normal;
  color: #fff;
  background: rgba(0, 0, 0, 0.5);
  padding: 0.2667rem 0.6rem;
  border-radius: var(--r);
  cursor: pointer;
}
.gm-side {
  flex: 0 0 20rem;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--sborder);
  background: var(--spanel2);
}
.gm-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 2.9333rem 1.0667rem 0.8rem;
}
.gm-prompt {
  font-size: 0.8667rem;
  line-height: 1.5;
  color: var(--sfg);
  white-space: pre-wrap;
  margin-bottom: 0.9333rem;
}
.gm-meta {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.2667rem 0.8rem;
  margin: 0;
  font-size: 0.8rem;
}
.gm-meta dt {
  color: var(--sfaint);
}
.gm-meta dd {
  margin: 0;
  color: var(--smuted);
  word-break: break-word;
}
.gm-actions {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.8rem;
  border-top: 1px solid var(--sborder);
}
.gm-btn {
  display: flex;
  align-items: center;
  gap: 0.5333rem;
  min-height: 2rem;
  padding: 0.3333rem 0.8rem;
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  background: var(--sbg);
  color: var(--sfg);
  font: inherit;
  font-size: 0.8667rem;
  cursor: pointer;
  text-decoration: none;
}
.gm-btn:hover {
  background: var(--shover);
}
.gm-btn .ic {
  width: 1.0667rem;
  height: 1.0667rem;
}
.gm-icons {
  display: flex;
  gap: 0.4rem;
}
/* Every text action is a cell, so the column stays even however many show */
.gm-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.4rem;
}
.gm-grid .gm-btn {
  justify-content: center;
}
.gm-grid .gm-btn:last-child:nth-child(odd) {
  grid-column: 1 / -1;
}
.gm-btn.icon {
  flex: 1;
  justify-content: center;
}
.gm-btn.on {
  color: var(--saccent);
  border-color: var(--saccent);
}
.gm-btn.danger:hover {
  color: var(--sdanger);
  border-color: var(--sdanger);
}
@media (max-width: 760px) {
  .gm-card {
    flex-direction: column;
    max-height: 92dvh;
  }
  .gm-side {
    flex: 1 1 auto;
    border-left: none;
    border-top: 1px solid var(--sborder);
  }
  .gm-scroll {
    padding-top: 0.8rem;
  }
  .gm-media video,
  .gm-media img {
    max-height: 50dvh;
  }
}
</style>
