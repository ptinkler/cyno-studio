<script setup lang="ts">
import { vTip } from '../../directives/tip'
import { ref, reactive, onMounted } from 'vue'
import { fetchUserKeys, saveUserKeys, KEY_PROVIDERS } from '../../composables/useAccount'

const emit = defineEmits<{ saved: [] }>()

type KeyStatus = Awaited<ReturnType<typeof fetchUserKeys>>['keys']

const keys = ref<KeyStatus>({}) // provider -> { set, hint }
const drafts = reactive<Record<string, string>>({}) // provider -> new value typed (or '' to clear)
const saving = ref(false)
const message = ref('')

async function load(): Promise<void> {
  try {
    keys.value = (await fetchUserKeys()).keys
  } catch {
    keys.value = {}
  }
}

function onType(provider: string, event: Event): void {
  if (event.target instanceof HTMLInputElement) drafts[provider] = event.target.value
}

async function save(): Promise<void> {
  saving.value = true
  message.value = ''
  const payload: Record<string, string | null> = {}
  for (const p of KEY_PROVIDERS) {
    const draft = drafts[p.id]
    if (draft !== undefined) payload[p.id] = draft // only what changed
  }
  try {
    keys.value = (await saveUserKeys(payload)).keys
    for (const k of Object.keys(drafts)) Reflect.deleteProperty(drafts, k)
    message.value = 'Saved'
    emit('saved')
  } catch (e) {
    message.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="scard">
    <div class="ctitle">Provider keys</div>
    <p class="cnote">Enter your Pollo, Venice and OpenRouter keys.</p>
    <div class="rows">
      <div v-for="p in KEY_PROVIDERS" :key="p.id" class="krow">
        <div class="kl">
          {{ p.label }}
          <span v-if="keys[p.id]?.set" class="kset">{{ keys[p.id]?.hint }}</span>
        </div>
        <input
          :value="drafts[p.id] ?? ''"
          type="password"
          autocomplete="off"
          :placeholder="keys[p.id]?.set ? 'Enter a new key to replace' : 'Paste key'"
          @input="onType(p.id, $event)"
        />
        <button v-if="keys[p.id]?.set" v-tip="'Clear this key'" class="btn btn-sm" @click="drafts[p.id] = ''">
          Clear
        </button>
      </div>
    </div>
    <div class="cactions">
      <button class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? 'Saving…' : 'Save keys' }}</button>
      <span v-if="message" class="cmsg">{{ message }}</span>
    </div>
  </section>
</template>

<style scoped>
.rows {
  display: flex;
  flex-direction: column;
  gap: 0.5333rem;
}
.krow {
  display: grid;
  grid-template-columns: 7.3333rem 1fr auto;
  align-items: center;
  gap: 0.6667rem;
}
.kl {
  color: var(--sfg);
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 0.5333rem;
}
.kset {
  font-size: 0.8rem;
  color: var(--saccent);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
</style>
