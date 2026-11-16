<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { chatModelsKey, injectRequired } from '../../injection'
import ModelPicker from '../chat/ModelPicker.vue'
import { fetchSettings, setTitleModel } from '../../composables/useChat'

const models = injectRequired(chatModelsKey)
const current = ref('')
const loaded = ref(false)

const titleModels = computed(() => models.text)

onMounted(async () => {
  try {
    current.value = (await fetchSettings()).title_model ?? ''
  } catch {
    current.value = ''
  } finally {
    loaded.value = true
  }
})

async function pick(id: string): Promise<void> {
  current.value = id
  try {
    await setTitleModel(id)
  } catch {
    /* keep the choice shown; it retries on next change */
  }
}
</script>

<template>
  <section class="scard">
    <div class="ctitle">Chat naming</div>
    <div class="crow">
      <div class="clabel">
        <div>Title model</div>
        <p class="hint">Names new chats from the first message. Leave empty to use the chat's own model.</p>
      </div>
      <ModelPicker
        v-if="loaded"
        :model-value="current"
        :models="titleModels"
        label="Title model"
        kind="text"
        @update:model-value="pick"
      />
    </div>
  </section>
</template>

<style scoped>
.clabel {
  flex: 1;
  min-width: 0;
}
.hint {
  margin-top: 2px;
  font-size: 12px;
  color: var(--smuted);
  line-height: 1.45;
  max-width: 360px;
}
.crow :deep(.model-picker) {
  flex: 0 1 240px;
  min-width: 190px;
}
</style>
