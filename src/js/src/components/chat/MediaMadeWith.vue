<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { MediaCard } from '../../composables/chatConversationsApi'
import { refUrl, refsLabel, refsTitle } from '../../utils/cardSpecs'
import type { CardParams } from '../../utils/cardSpecs'
import { shortModel } from '../../utils/format'
import { isMissing, markMissing, probeRef } from '../../utils/refAvailability'

// What made a card's picture: the model, its settings, the cost, and what it was based on.
const props = defineProps<{
  item: MediaCard
  convId: string
  params: CardParams
  specs: readonly string[]
}>()

const KIND_ICON: Readonly<Record<string, string>> = { image: '#s-image', video: '#s-film', audio: '#s-audio' }

// Hovering "🔗 4 refs" shows the reference images. Teleported and fixed so
// the caption's overflow clipping doesn't cut it off.
// Character images that aren't served here (see utils/refAvailability) are left out of the count and shown as gaps
const refMissing = (r: string): boolean => isMissing(refUrl(props.convId, r))
const missingRefs = computed(() => props.params.refs.filter(refMissing).length)
watch(
  () => props.params.refs,
  refs => {
    for (const r of refs) if (r.startsWith('char:')) probeRef(refUrl(props.convId, r))
  },
  { immediate: true },
)

const refsPeek = ref<{ params: CardParams; x: number; y: number } | null>(null)
function showRefs(event: MouseEvent, shown: CardParams): void {
  if (!(event.currentTarget instanceof HTMLElement)) return
  const rect = event.currentTarget.getBoundingClientRect()
  refsPeek.value = { params: shown, x: rect.left, y: rect.top }
}
</script>

<template>
  <div class="foot-info" :title="[item.model, ...specs].join(' · ')">
    <span class="foot-model">
      <svg class="ic sm"><use :href="KIND_ICON[item.kind] || '#s-film'" /></svg>{{ shortModel(item.model) }}
    </span>
    <span v-if="specs.length" class="foot-specs">{{ specs.join(' · ') }}</span>
    <span v-if="item.credits" class="chip" title="Billed to your Pollo account"
      >{{ item.credits }} credit{{ item.credits === 1 ? '' : 's' }}</span
    >
    <span v-if="params.context" class="chip" title="Sent with chat context">
      <svg class="ic sm"><use href="#s-chat" /></svg>context
    </span>
    <span
      v-if="params.refs.length"
      class="chip caption-refs"
      @mouseenter="showRefs($event, params)"
      @mouseleave="refsPeek = null"
    >
      <svg class="ic sm"><use href="#s-link" /></svg>{{ refsLabel(params, missingRefs) }}
    </span>
    <span v-if="params.upload_notice" class="chip caption-warn" :title="params.upload_notice">
      <svg class="ic sm"><use href="#s-warn" /></svg>backup upload host
    </span>
  </div>
  <Teleport to="body">
    <div v-if="refsPeek" class="refs-peek" :style="{ left: `${refsPeek.x}px`, top: `${refsPeek.y}px` }">
      <div class="refs-peek-title">
        {{ refsTitle(refsPeek.params, refsPeek.params.refs.filter(refMissing).length) }}
      </div>
      <div class="refs-peek-grid">
        <template v-for="(r, i) in refsPeek.params.refs" :key="r">
          <div v-if="refMissing(r)" class="ref-gone" title="Image unavailable">
            <svg class="ic"><use href="#s-image" /></svg>
          </div>
          <img
            v-else
            :src="refUrl(convId, r)"
            :alt="r"
            :class="{ unused: refsPeek.params.refs_used != null && i >= refsPeek.params.refs_used }"
            @error="markMissing(refUrl(convId, r))"
          />
        </template>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.foot-info {
  display: flex;
  flex: 1 1 14rem;
  flex-wrap: wrap;
  align-items: center;
  align-content: center;
  gap: 0.2667rem 0.5333rem;
  min-width: 0;
  min-height: 2rem; /* level with the buttons beside it */
}
.foot-model {
  display: inline-flex;
  align-items: center;
  gap: 0.3333rem;
  min-width: 0;
  color: var(--sfg);
  font-size: 0.8667rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.foot-specs {
  color: var(--smuted);
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.2667rem;
  padding: 1px 0.4667rem;
  border: 1px solid var(--sborder);
  border-radius: 0.4rem;
  background: var(--shover);
  color: var(--smuted);
  font-size: 0.8rem;
  white-space: nowrap;
}
.chip.caption-warn {
  color: var(--swarn);
  border-color: color-mix(in srgb, var(--swarn) 45%, transparent);
  cursor: help;
}
.chip.caption-refs {
  cursor: default;
}
.refs-peek {
  position: fixed;
  z-index: var(--z-modal);
  transform: translateY(calc(-100% - 6px));
  max-width: 22.6667rem;
  padding: 0.5333rem;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  box-shadow: var(--shadow-pop);
  font-size: 0.8rem;
  color: var(--text2);
  pointer-events: none;
}
.refs-peek-title {
  margin-bottom: 0.4rem;
}
.refs-peek-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.refs-peek-grid img {
  width: 4.8rem;
  height: 4.8rem;
  object-fit: cover;
  border-radius: 0.2667rem;
  background: var(--surface2);
}
/* A reference image that isn't served here: a gap instead of a broken picture */
.ref-gone {
  display: grid;
  place-items: center;
  width: 4.8rem;
  height: 4.8rem;
  border: 1px dashed var(--sborder);
  border-radius: 0.2667rem;
  color: var(--sfaint);
}
.refs-peek-grid img.unused {
  opacity: 0.35;
}
</style>
