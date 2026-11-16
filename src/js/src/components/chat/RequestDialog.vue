<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { RouterLink } from 'vue-router'
import { useCopy } from '../../composables/useClipboard'

// What an image/video card sent to its provider and what came back, as
// JSON. Images in them are cut down to their type and size by the server.
const props = withDefaults(defineProps<{ request: unknown; response: unknown; error?: string | undefined }>(), {
  error: '',
})
const emit = defineEmits<{ close: [] }>()
const { copiedKey, copy } = useCopy()

const fmt = (value: unknown): string => (typeof value === 'string' ? value : JSON.stringify(value, null, 2))
const requestJson = computed(() => fmt(props.request))
const responseJson = computed(() => (props.response == null ? '' : fmt(props.response)))
const both = computed(() => JSON.stringify({ request: props.request, response: props.response }, null, 2))

const onKey = (event: KeyboardEvent): void => {
  if (event.key === 'Escape') emit('close')
}
onMounted(() => {
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <div class="req-backdrop" @click.self="emit('close')">
      <div class="req-dialog" role="dialog" aria-modal="true" aria-label="Request and response">
        <div class="req-head">
          <h3>Request and response</h3>
          <button class="btn btn-sm" @click="copy(both, 'req')">
            {{ copiedKey === 'req' ? '✓ Copied' : '⧉ Copy JSON' }}
          </button>
          <RouterLink class="btn btn-sm" :to="{ name: 'studio-requests' }" @click="emit('close')"
            >All requests</RouterLink
          >
          <button class="iconbtn x" title="Close" @click="emit('close')">✕</button>
        </div>
        <p v-if="error" class="req-error">{{ error }}</p>
        <div class="req-body">
          <h4>Sent</h4>
          <pre class="req-json">{{ requestJson }}</pre>
          <h4>Response</h4>
          <pre v-if="responseJson" class="req-json">{{ responseJson }}</pre>
          <p v-else class="req-none">
            Nothing recorded (the connection failed, or this was made before responses were logged).
          </p>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.req-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1300;
  display: grid;
  place-items: center;
  padding: 1.0667rem;
  background: rgba(0, 0, 0, 0.6);
}

.req-dialog {
  width: min(50.6667rem, 100%);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  background: var(--sbg);
  border: 1px solid var(--sborder);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-modal);
  padding: 0.9333rem 1.2rem 1.0667rem;
}

.req-head {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.req-head h3 {
  flex: 1;
  font-size: 1rem;
  font-weight: 600;
}

.x {
  width: 1.8667rem;
  height: 1.8667rem;
  margin-right: -6px;
  font-size: 0.8667rem;
}

.req-body {
  overflow: auto;
  min-height: 0;
}

.req-body h4 {
  margin-top: 0.8rem;
  font-size: 0.8rem;
  font-weight: 650;
  color: var(--sfaint);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.req-none {
  margin-top: 0.4rem;
  font-size: 0.8333rem;
  color: var(--smuted);
}

.req-error {
  margin-top: 0.6667rem;
  font-size: 0.8333rem;
  color: var(--sdanger);
}

.req-json {
  margin-top: 0.4rem;
  padding: 0.6667rem 0.8rem;
  border-radius: var(--r);
  background: var(--sbg2);
  font-size: 0.8rem;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
