<script setup lang="ts">
import { ref, watch } from 'vue'
import type { ConversationSummary } from '../../composables/chatConversationsApi'
import { fetchConversationThumbs, chatMediaPreviewUrl } from '../../composables/useChat'
import type { Space } from '../../composables/studioTypes'

const props = withDefaults(defineProps<{ space: Space; threads?: readonly ConversationSummary[] | undefined }>(), {
  threads: () => [],
})
defineEmits<{ open: [id: string]; close: []; new: [] }>()

// Cover thumbnail per thread (newest image), loaded lazily; threads without a
// generated image fall back to the placeholder icon.
const thumbs = ref<Record<string, string>>({})
watch(
  () => props.threads.map(t => t.id).join(','),
  async ids => {
    if (!ids) return
    try {
      const found = await fetchConversationThumbs(props.threads.map(t => t.id))
      thumbs.value = Object.fromEntries(
        Object.entries(found.thumbs).map(([id, file]) => [id, chatMediaPreviewUrl(id, file)]),
      )
    } catch {
      /* placeholders shown */
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="page">
    <div class="pwrap full">
      <div class="phead">
        <h1>
          <svg class="ic lg"><use href="#s-folder" /></svg> {{ space.name }}
        </h1>
        <div class="hactions">
          <button class="btn btn-primary" @click="$emit('new')">
            <svg class="ic"><use href="#s-plus" /></svg> New thread
          </button>
          <button class="btn" @click="$emit('close')">
            <svg class="ic"><use href="#s-chevL" /></svg> Back
          </button>
        </div>
      </div>
      <div v-if="!props.threads.length" class="empty">No threads in this space yet.</div>
      <div v-else class="grid">
        <button v-for="t in threads" :key="t.id" class="gcard card" @click="$emit('open', t.id)">
          <div class="cthumb">
            <img v-if="thumbs[t.id]" :src="thumbs[t.id]" alt="" loading="lazy" />
            <div v-else class="cph">
              <svg class="ic lg"><use :href="t.kind === 'gallery' ? '#s-image' : '#s-chat'" /></svg>
            </div>
          </div>
          <span class="ct">{{ t.title || 'Untitled' }}</span>
          <span v-if="t.pinned" class="cfav"
            ><svg class="ic sm"><use href="#s-star" /></svg
          ></span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--tile-s), 1fr));
  gap: 0.6667rem;
}
.card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.5333rem;
  align-items: stretch;
  padding: 0.5333rem;
}
.cthumb {
  aspect-ratio: 4 / 3;
  border-radius: var(--r);
  overflow: hidden;
  background: var(--sbg2);
}
.cthumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.cph {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  color: var(--sfaint);
  background: var(--saccent-soft);
}
.cph .ic {
  width: 1.7333rem;
  height: 1.7333rem;
  color: var(--saccent);
}
.ct {
  font-size: 0.8667rem;
  font-weight: 500;
  line-height: 1.4;
  padding: 0 0.2667rem 2px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.cfav {
  position: absolute;
  top: 0.8rem;
  right: 0.8rem;
  color: var(--sstar);
  background: rgba(0, 0, 0, 0.45);
  border-radius: var(--r-sm);
  padding: 0.2rem;
  display: grid;
}
</style>
