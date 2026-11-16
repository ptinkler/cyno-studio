<script setup lang="ts">
import { computed } from 'vue'
import type { UiMessage } from '../../composables/studioTypes'
import ForkList from './ForkList.vue'
import VersionStepper from './VersionStepper.vue'

// What applies to the reply as a whole (not just its words or one picture):
// other versions of the turn, Stop / Retry, branching a new chat from here.
const props = withDefaults(
  defineProps<{
    message: UiMessage
    streaming: boolean
    canRetry?: boolean | undefined
    canSwitch?: boolean | undefined
    canBranch?: boolean | undefined
  }>(),
  { canRetry: false, canSwitch: false, canBranch: false },
)
const emit = defineEmits<{
  stop: []
  retry: []
  fork: []
  branch: [id: number]
  'open-chat': [id: string]
}>()

const siblings = computed(() => props.message.siblings)
const branchIndex = computed(() => siblings.value.indexOf(Number(props.message.id)))
function goBranch(by: number): void {
  const id = siblings.value[branchIndex.value + by]
  if (id !== undefined) emit('branch', id)
}
</script>

<template>
  <div class="reply-controls">
    <VersionStepper
      v-if="siblings.length > 1"
      class="branch-nav"
      :shown="branchIndex"
      :count="siblings.length"
      :enabled="canSwitch"
      prev-title="Previous version"
      next-title="Next version"
      @step="goBranch"
    />
    <button v-if="streaming" class="btn btn-sm" title="Stop generating" @click="emit('stop')">
      <svg class="ic sm"><use href="#s-stop" /></svg> Stop
    </button>
    <template v-else>
      <button
        v-if="canRetry"
        class="iconbtn boxed"
        title="Retry: a fresh version of this whole reply, pictures included, kept beside this one — use ‹ › to compare."
        @click="emit('retry')"
      >
        <svg class="ic"><use href="#s-refresh" /></svg>
      </button>
      <button
        v-if="canBranch"
        class="iconbtn boxed"
        title="Start a new chat from here: everything up to this reply, nothing after"
        @click="emit('fork')"
      >
        <svg class="ic"><use href="#s-branch" /></svg>
      </button>
    </template>
    <ForkList v-if="message.forks?.length" :forks="message.forks" @open="id => emit('open-chat', id)" />
  </div>
</template>

<style scoped>
.reply-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
</style>
