<!-- One row of the picker's list: a model's name, provider, badges (folded into dots when there are many),
     the favourite star and its id; or, with `none`, the "no model" choice. -->
<script setup>
import { computed } from 'vue'
import ModelBadge from './ModelBadge.vue'
import { ALL_PROVIDERS, providerOf } from '../../composables/modelTags'
import { MAX_INLINE_BADGES, modelBadges } from '../../utils/modelBadges'

const props = defineProps({
  model: { type: Object, default: null }, // null with `none`
  none: { type: Boolean, default: false },
  kind: { type: String, default: 'text' },
  selected: { type: Boolean, default: false },
  favourite: { type: Boolean, default: false },
  showProvider: { type: Boolean, default: false },
})
const emit = defineEmits(['pick', 'toggle-favourite'])

const badges = computed(() => (props.model ? modelBadges(props.model, props.kind) : []))
const provider = computed(() => providerOf(props.model?.id))
</script>

<template>
  <div
    role="button"
    tabindex="0"
    class="picker-item"
    :class="{ selected }"
    @click="emit('pick')"
    @keydown.enter.prevent="emit('pick')"
  >
    <span class="item-row">
      <span class="item-name">{{ none ? 'None' : model.name }}</span>
      <span
        v-if="showProvider && !none"
        class="row-provider"
        :class="provider"
        :title="ALL_PROVIDERS[provider].title"
        >{{ ALL_PROVIDERS[provider].label }}</span
      >
      <span v-if="!none" class="item-badges" :class="{ collapsed: badges.length > MAX_INLINE_BADGES }">
        <!-- Long lists fold into coloured dots; hovering unfolds the labels -->
        <span v-if="badges.length > MAX_INLINE_BADGES" class="badge-dots" aria-hidden="true">
          <ModelBadge v-for="b in badges" :key="b.t" :badge="b" dot />
          <span class="dots-n">{{ badges.length }}</span>
        </span>
        <span class="badge-list">
          <ModelBadge v-for="b in badges" :key="b.t" :badge="b" />
        </span>
      </span>
      <button
        v-if="!none"
        type="button"
        class="star"
        :class="{ on: favourite }"
        :title="favourite ? 'Remove from favourites' : 'Add to favourites'"
        :aria-pressed="favourite"
        @click.stop="emit('toggle-favourite')"
        @keydown.enter.stop
      >
        {{ favourite ? '★' : '☆' }}
      </button>
    </span>
    <span class="item-id">{{ none ? `Disable ${kind} generation` : model.id }}</span>
  </div>
</template>

<style scoped>
.picker-item {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  background: none;
  border: none;
  border-radius: 8px;
  padding: 7px 10px;
  color: var(--text);
  cursor: pointer;
  text-align: left;
}
.picker-item:hover {
  background: var(--shover);
}
.picker-item.selected {
  background: var(--saccent-soft);
}
.item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.item-name {
  font-size: 0.87rem;
}
.item-id {
  font-size: 0.72rem;
  color: var(--text2);
  font-family: monospace;
}

.row-provider {
  flex-shrink: 0;
  font-size: 0.62rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  color: var(--text2);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 0 5px;
  line-height: 1.5;
}
.row-provider.pollo {
  color: var(--p-pollo);
  border-color: color-mix(in srgb, var(--p-pollo) 45%, transparent);
}
.row-provider.venice {
  color: var(--p-venice);
  border-color: color-mix(in srgb, var(--p-venice) 45%, transparent);
}
.row-provider.openrouter {
  color: var(--p-openrouter);
  border-color: color-mix(in srgb, var(--p-openrouter) 45%, transparent);
}

.item-badges {
  position: relative;
  flex-shrink: 0;
  margin-left: auto;
}
.badge-list {
  display: flex;
  gap: 4px;
}
/* Folded: just coloured dots (one per badge) + a count; the labels open on hover */
.item-badges.collapsed .badge-list {
  display: none;
  position: absolute;
  top: 100%;
  right: 0;
  z-index: 5;
  flex-wrap: wrap;
  justify-content: flex-end;
  width: max-content;
  max-width: 300px;
  margin-top: 2px;
  padding: 6px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
}
.item-badges.collapsed:hover .badge-list,
.item-badges.collapsed:focus-within .badge-list {
  display: flex;
}
.badge-dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--surface2);
  cursor: default;
}
.item-badges.collapsed:hover .badge-dots {
  outline: 1px solid var(--border);
}
.dots-n {
  margin-left: 2px;
  font-size: 0.65rem;
  color: var(--text2);
}

.star {
  flex-shrink: 0;
  background: none;
  border: none;
  color: var(--text2);
  font-size: 1rem;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 6px;
  cursor: pointer;
  opacity: 0.45;
  transition:
    opacity 0.15s,
    color 0.15s;
}
.picker-item:hover .star,
.star:focus-visible {
  opacity: 1;
}
.star:hover {
  color: var(--yellow);
}
.star.on {
  color: var(--yellow);
  opacity: 1;
}
</style>
