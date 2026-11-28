<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { vTip } from '../../directives/tip'
import FilterRow from './FilterRow.vue'
import type { LengthFilter } from '../../composables/studioTypes'

const props = withDefaults(
  defineProps<{
    /** Names of the models the shown items were made with. */
    models?: readonly string[] | undefined
    /** Some video has a known length, so Length is offered. */
    lengths?: boolean | undefined
    /** The Favourites page is favourites-only already. */
    favFilter?: boolean | undefined
    /** Filters the page adds itself (in the slot) that are switched on. */
    extraActive?: number | undefined
  }>(),
  { models: () => [], lengths: false, favFilter: true, extraActive: 0 },
)
const emit = defineEmits<{ clear: [] }>()
const kind = defineModel<string>('kind', { default: 'all' })
const favOnly = defineModel<boolean>('favOnly', { default: false })
const model = defineModel<string>('model', { default: '' })
const length = defineModel<LengthFilter>('length', { default: 'any' })

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const active = computed(
  () =>
    (kind.value !== 'all' ? 1 : 0) +
    (favOnly.value ? 1 : 0) +
    (model.value ? 1 : 0) +
    (length.value !== 'any' ? 1 : 0) +
    props.extraActive,
)

const KINDS = [
  { id: 'all', label: 'All' },
  { id: 'image', label: 'Images' },
  { id: 'video', label: 'Videos' },
]
const LENGTHS: readonly { id: LengthFilter; label: string }[] = [
  { id: 'any', label: 'Any' },
  { id: 'short', label: 'Up to 5 s' },
  { id: 'medium', label: '5 to 10 s' },
  { id: 'long', label: 'Over 10 s' },
]

function clear(): void {
  kind.value = 'all'
  favOnly.value = false
  model.value = ''
  length.value = 'any'
  emit('clear')
}
function onOutside(event: PointerEvent): void {
  if (open.value && !root.value?.contains(event.target as Node)) open.value = false
}
function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') open.value = false
}
onMounted(() => {
  document.addEventListener('pointerdown', onOutside)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onOutside)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="gfilters">
    <button
      v-tip="'Filter'"
      class="iconbtn boxed"
      :class="{ active: active > 0 || open }"
      aria-label="Filter"
      aria-haspopup="dialog"
      :aria-expanded="open"
      @click="open = !open"
    >
      <svg class="ic"><use href="#s-filter" /></svg>
      <span v-if="active" class="gbadge">{{ active }}</span>
    </button>
    <div v-if="open" class="gpop" role="dialog" aria-label="Filters">
      <FilterRow label="Type">
        <span class="seg" role="group" aria-label="Type">
          <button
            v-for="k in KINDS"
            :key="k.id"
            :class="{ on: kind === k.id }"
            :aria-label="k.label"
            :aria-pressed="kind === k.id"
            @click.prevent="kind = k.id"
          >
            {{ k.label }}
          </button>
        </span>
      </FilterRow>
      <FilterRow v-if="favFilter" label="Favourites only">
        <input v-model="favOnly" type="checkbox" class="gcheck" />
      </FilterRow>
      <FilterRow v-if="models.length > 1" label="Model">
        <select v-model="model">
          <option value="">Any</option>
          <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
        </select>
      </FilterRow>
      <FilterRow v-if="lengths" label="Length">
        <select v-model="length">
          <option v-for="l in LENGTHS" :key="l.id" :value="l.id">{{ l.label }}</option>
        </select>
      </FilterRow>
      <slot></slot>
      <button v-if="active" class="gclear" @click="clear">Clear filters</button>
    </div>
  </div>
</template>

<style scoped>
.gfilters {
  position: relative;
}
.gfilters .iconbtn {
  position: relative;
}
.gfilters .iconbtn.active {
  color: var(--saccent);
  border-color: var(--saccent);
}
.gbadge {
  position: absolute;
  top: -0.3rem;
  right: -0.3rem;
  min-width: 1rem;
  height: 1rem;
  padding: 0 0.25rem;
  display: grid;
  place-items: center;
  border-radius: 66.6rem;
  background: var(--saccent-fill);
  color: #fff;
  font-size: 0.65rem;
  font-weight: 600;
  line-height: 1;
}
.gpop {
  position: absolute;
  top: calc(100% + 0.4rem);
  right: 0;
  z-index: var(--z-popover);
  min-width: 18rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.6rem 0.8rem;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-pop);
}
.gcheck {
  width: 1rem;
  height: 1rem;
  accent-color: var(--saccent);
}
.gclear {
  align-self: flex-end;
  margin-top: 0.2rem;
  border: none;
  background: none;
  color: var(--smuted);
  font: inherit;
  font-size: 0.8rem;
  cursor: pointer;
}
.gclear:hover {
  color: var(--sfg);
}
</style>
