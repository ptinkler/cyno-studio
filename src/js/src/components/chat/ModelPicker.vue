<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Model, ModelKind } from '../../composables/chatModelsApi'
import { useDropdown } from '../../composables/useDropdown'
import { useModelList } from '../../composables/useModelList'
import { usePopPlacement } from '../../composables/usePopPlacement'
import { ALL_PROVIDERS, providerOf } from '../../composables/modelTags'
import { PRIVACY, UNCENSORED } from '../../utils/modelBadges'
import ModelBadge from './ModelBadge.vue'
import ModelFilterPanel from './ModelFilterPanel.vue'
import ModelRow from './ModelRow.vue'

const props = withDefaults(
  defineProps<{
    modelValue?: string | undefined
    models?: readonly Model[] | undefined
    label: string
    icon?: string | undefined
    kind?: ModelKind | undefined
    loading?: boolean | undefined
    /** Render the trigger as a small text button (e.g. "Try another model…") instead of the labelled picker box, for one-off picks. */
    triggerText?: string | undefined
    allowNone?: boolean | undefined
  }>(),
  { modelValue: '', models: () => [], icon: '', kind: 'text', loading: false, triggerText: '', allowNone: true },
)
const emit = defineEmits<{ 'update:modelValue': [id: string] }>()

const query = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
// The filter menu (providers, capabilities, uncensored, show-hidden) sits in
// the pop-up behind the Filters button; the active picks also show as chips
const filtersOpen = ref(false)

const current = computed(() => props.models.find(m => m.id === props.modelValue))
const list = useModelList(props, query)
const {
  showHidden,
  uncensoredOnly,
  visibleModels,
  hiddenCount,
  uncensoredCount,
  showProviders,
  providerFacet,
  tagsPresent,
  selProviders,
  selTags,
  anyFilter,
  hasFacets,
  filterCount,
  activeChips,
  filtered,
  sections,
  isFavourite,
  toggleFavourite,
  toggleProvider,
  toggleTag,
} = list

function clearAll(): void {
  list.clearAll()
  searchInput.value?.focus()
}

const colorVar = (badge: { color?: string | undefined }): Record<string, string> | undefined =>
  badge.color ? { '--b': badge.color } : undefined

const { open, root, toggle, close } = useDropdown({
  focus: searchInput,
  onOpen() {
    query.value = ''
    placement.track()
  },
  onClose() {
    filtersOpen.value = false
    placement.untrack()
  },
})
const placement = usePopPlacement(root)
const { popStyle } = placement

// A click anywhere in the pop-up but the filter menu / its button closes the menu
function closeFiltersOutside(event: MouseEvent): void {
  if (filtersOpen.value && event.target instanceof Element && !event.target.closest('.fpanel, .filters-btn')) {
    filtersOpen.value = false
  }
}

// A model, or null for none
function pick(model: Model | null): void {
  emit('update:modelValue', model?.id ?? '')
  close()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    if (filtersOpen.value) filtersOpen.value = false
    else close()
  }
  const [first] = filtered.value
  if (event.key === 'Enter' && first) pick(first)
}
</script>

<template>
  <div ref="root" class="model-picker">
    <button v-if="triggerText" type="button" class="picker-trigger" :class="{ active: open }" @click="toggle">
      {{ triggerText }}
    </button>
    <button
      v-else
      type="button"
      class="picker-btn"
      :class="{ active: open }"
      :title="modelValue || 'None selected'"
      @click="toggle"
    >
      <span class="picker-icon">{{ icon }}</span>
      <span class="picker-text">
        <span class="picker-label"
          >{{ label
          }}<span
            v-if="showProviders && modelValue"
            class="provider-tag"
            :class="providerOf(modelValue)"
            :title="ALL_PROVIDERS[providerOf(modelValue)].title"
          >
            · {{ ALL_PROVIDERS[providerOf(modelValue)].label }}</span
          ></span
        >
        <span class="picker-value">
          <template v-if="loading">Loading…</template>
          <template v-else>{{ current?.name || 'None' }}</template>
          <ModelBadge v-if="!loading && current?.uncensored" :badge="UNCENSORED" picked />
          <ModelBadge v-if="!loading && current?.privacy" :badge="PRIVACY[current.privacy]" picked />
        </span>
      </span>
      <span class="chev">▾</span>
    </button>

    <div
      v-if="open"
      class="picker-pop"
      :class="{ 'filters-open': filtersOpen }"
      :style="popStyle"
      @mousedown="closeFiltersOutside"
    >
      <div class="picker-searchrow">
        <input
          ref="searchInput"
          v-model="query"
          class="picker-search"
          :placeholder="`Search ${visibleModels.length} ${label.toLowerCase()} models…`"
          @keydown="onKeydown"
        />
        <button
          v-if="hasFacets"
          type="button"
          class="filters-btn"
          :class="{ on: filtersOpen || anyFilter }"
          title="Filters"
          aria-haspopup="true"
          :aria-expanded="filtersOpen"
          @click="filtersOpen = !filtersOpen"
        >
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
          >
            <path d="M4 7h16M7 12h10M10 17h4" />
          </svg>
          <span v-if="filterCount" class="filters-n">{{ filterCount }}</span>
        </button>
      </div>
      <ModelFilterPanel
        v-if="filtersOpen && hasFacets"
        v-model:uncensored-only="uncensoredOnly"
        v-model:show-hidden="showHidden"
        :providers="providerFacet"
        :tags="tagsPresent"
        :sel-providers="selProviders"
        :sel-tags="selTags"
        :uncensored-count="uncensoredCount"
        :hidden-count="hiddenCount"
        :any-filter="anyFilter"
        @toggle-provider="id => toggleProvider(props.kind, id)"
        @toggle-tag="slug => toggleTag(props.kind, slug)"
        @clear="clearAll"
      />
      <div v-if="activeChips.length" class="picker-active">
        <button
          v-for="c in activeChips"
          :key="c.key"
          type="button"
          class="achip"
          :style="colorVar(c)"
          :title="`Remove ${c.label}`"
          @click="c.off()"
        >
          {{ c.label }} ✕
        </button>
      </div>
      <div class="picker-list">
        <template v-for="section in sections" :key="section.id">
          <div v-if="section.label" class="picker-section">{{ section.label }}</div>
          <ModelRow
            v-if="section.id === 'all' && kind !== 'text' && allowNone && !query"
            none
            :kind="props.kind"
            :selected="!modelValue"
            @pick="pick(null)"
          />
          <ModelRow
            v-for="m in section.models"
            :key="m.id"
            :model="m"
            :kind="props.kind"
            :selected="m.id === modelValue"
            :favourite="isFavourite(props.kind, m.id)"
            :show-provider="showProviders"
            @pick="pick(m)"
            @toggle-favourite="toggleFavourite(props.kind, m.id)"
          />
        </template>
        <div v-if="!filtered.length" class="picker-empty">
          <template v-if="query">No models match “{{ query }}”</template>
          <template v-else-if="anyFilter">No models match the current filters</template>
          <template v-else>No models available</template>
          <button v-if="anyFilter" type="button" class="tab-hint" @click="clearAll">Clear filters →</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.model-picker {
  position: relative;
  min-width: 0;
}

.picker-btn {
  display: flex;
  align-items: center;
  gap: 0.5333rem;
  width: 100%;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  padding: 0.3333rem 0.6667rem;
  color: var(--sfg);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.12s;
}

.picker-trigger {
  background: none;
  border: 1px solid var(--border);
  border-radius: 0.5333rem;
  padding: 0.2667rem 0.6667rem;
  color: var(--text);
  font-size: 0.8rem;
  cursor: pointer;
}

.picker-trigger:hover,
.picker-trigger.active {
  border-color: var(--accent);
}

.picker-btn:hover,
.picker-btn.active {
  border-color: var(--accent);
}

.picker-icon {
  font-size: 1rem;
}

.picker-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.picker-label {
  font-size: 0.8rem;
  color: var(--text2);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.picker-value {
  font-size: 0.85rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chev {
  color: var(--text2);
  font-size: 0.8rem;
}

.picker-pop {
  position: fixed;
  z-index: var(--z-picker);
  width: min(28rem, 92vw);
  display: flex;
  flex-direction: column;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-pop);
  overflow: hidden;
}

.picker-search {
  flex-shrink: 0;
}

.picker-search {
  width: 100%;
  border: none;
  border-bottom: 1px solid var(--sborder);
  border-radius: 0;
  padding: 0.6rem 0.8rem;
  background: transparent;
  box-shadow: none;
}

/* Borderless field inside the pop-up: the global focus ring would box it in */
.picker-pop .picker-search.picker-search:focus-visible {
  box-shadow: none;
}

.provider-tag {
  text-transform: none;
  letter-spacing: 0;
  font-weight: 600;
}

.provider-tag.pollo {
  color: var(--p-pollo);
}

.provider-tag.venice {
  color: var(--p-venice);
}

.provider-tag.openrouter {
  color: var(--p-openrouter);
}

.tab-hint {
  display: block;
  margin: 0.5333rem auto 0;
  background: none;
  border: none;
  color: var(--accent2);
  font-size: 0.8rem;
  cursor: pointer;
}

/* Search + Filters button on one row; the menu itself is ModelFilterPanel */
.picker-searchrow {
  display: flex;
  align-items: stretch;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}
.picker-searchrow .picker-search {
  flex: 1;
  min-width: 0;
  border-bottom: none;
}
.filters-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.2667rem;
  margin: 0.4rem 0.5333rem 0.4rem 0;
  padding: 0 0.6667rem;
  background: none;
  border: 1px solid var(--border);
  border-radius: 66.6rem;
  color: var(--text2);
  cursor: pointer;
}
.filters-btn:hover,
.filters-btn.on {
  color: var(--text);
  border-color: var(--accent);
}
.filters-n {
  font-size: 0.7333rem;
  font-weight: 700;
  color: var(--accent);
}
/* Room for the menu even when only a few models are listed */
.picker-pop.filters-open {
  min-height: 22rem;
}
/* The active picks, as removable chips */
.picker-active {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0.4rem 0.6667rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.achip {
  --b: var(--accent);
  padding: 2px 0.6rem;
  border: 1px solid color-mix(in srgb, var(--b) 55%, transparent);
  border-radius: 66.6rem;
  background: color-mix(in srgb, var(--b) 16%, transparent);
  color: var(--b);
  font-weight: 600;
  font-size: 0.8rem;
  cursor: pointer;
}
.achip:hover {
  background: color-mix(in srgb, var(--b) 28%, transparent);
}

.picker-list {
  max-height: 24rem;
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 0.2667rem;
}

.picker-section {
  padding: 0.5333rem 0.6667rem 0.2667rem;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--text2);
}

.picker-section:not(:first-child) {
  margin-top: 0.2667rem;
  border-top: 1px solid var(--border);
  padding-top: 0.6667rem;
}

.picker-empty {
  padding: 1.0667rem;
  text-align: center;
  color: var(--text2);
  font-size: 0.85rem;
}
</style>
