<script lang="ts">
/** One card in a pick dialog. */
export interface PickItem {
  key: string | number
  name: string
  /** A line under the name (a preview of the text). */
  sub?: string
  img?: string | null
  dot?: string
  icon?: string
  /** Where it lives ("Library", "This chat"), shown on the card. */
  badge?: string
  /** The heading it is listed under (Groups / Snippets…). */
  section?: string
  /** Currently in use here. */
  on: boolean
  /** Set for defaults: where they come from. Turning one off hides it in this chat rather than detaching it. */
  from?: string
}
</script>

<script setup lang="ts" generic="T extends PickItem">
import { computed, nextTick, ref, watch } from 'vue'
import BaseDialog from './BaseDialog.vue'

// Pick what a chat (or a space's defaults) uses: a searchable grid of cards,
// each switched on or off with a tap. Shared by the character and the
// instruction pickers. Names needn't be unique, so a card also shows its
// picture or a preview of its text and where it lives (`badge`).
// Emits `toggle` with the item; the parent decides what that means.
const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    items: readonly T[]
    empty?: string | undefined
    searchPlaceholder?: string | undefined
  }>(),
  { empty: 'Nothing saved yet', searchPlaceholder: 'Search' },
)
const emit = defineEmits<{ close: []; toggle: [item: T] }>()

const query = ref('')
const search = ref<HTMLInputElement | null>(null)
watch(
  () => props.open,
  async open => {
    if (!open) return
    query.value = ''
    await nextTick()
    search.value?.focus()
  },
)

const matches = (item: PickItem): boolean => {
  const q = query.value.trim().toLowerCase()
  return !q || `${item.name} ${item.sub ?? ''} ${item.badge ?? ''}`.toLowerCase().includes(q)
}
// In use first, then the rest; each in its section (Groups / Snippets…)
const sections = computed(() => {
  const out = new Map<string, T[]>()
  for (const item of props.items.filter(matches)) {
    const name = item.section ?? ''
    const list = out.get(name) ?? []
    list.push(item)
    out.set(name, list)
  }
  for (const list of out.values()) list.sort((a, b) => Number(b.on) - Number(a.on))
  return [...out.entries()]
})
const onCount = computed(() => props.items.filter(i => i.on).length)
</script>

<template>
  <BaseDialog :open="open" :title="title" width="48rem" @close="emit('close')">
    <template #head>
      <span class="count">{{ onCount }} on</span>
    </template>
    <input
      ref="search"
      v-model="query"
      type="search"
      class="search"
      :placeholder="searchPlaceholder"
      :aria-label="searchPlaceholder"
    />
    <p v-if="!items.length" class="note">{{ empty }}</p>
    <p v-else-if="!sections.length" class="note">Nothing matches</p>
    <template v-for="[section, list] in sections" :key="section">
      <p v-if="section" class="section">{{ section }}</p>
      <div class="grid">
        <button
          v-for="item in list"
          :key="item.key"
          type="button"
          class="card"
          :class="{ on: item.on, default: !!item.from }"
          :aria-pressed="item.on"
          :title="
            item.from
              ? `${item.name} — ${item.from}. ${item.on ? 'Click to hide it in this chat' : 'Click to use it here again'}`
              : `${item.name}${item.sub ? `\n${item.sub}` : ''}`
          "
          @click="emit('toggle', item)"
        >
          <span v-if="'img' in item" class="thumb">
            <img v-if="item.img" :src="item.img" alt="" loading="lazy" />
            <span v-else class="blank">{{ item.icon || '👤' }}</span>
            <span class="tick" aria-hidden="true">{{ item.on ? '✓' : '' }}</span>
          </span>
          <span class="name">
            <span v-if="!('img' in item)" class="tick inline" aria-hidden="true">{{ item.on ? '✓' : '' }}</span>
            <span v-if="item.dot" class="dot" :style="{ background: item.dot }"></span>
            <span v-else-if="item.icon && !('img' in item)">{{ item.icon }}</span>
            <span class="name-text">{{ item.name }}</span>
          </span>
          <span v-if="item.sub" class="sub">{{ item.sub }}</span>
          <span v-if="item.badge || item.from" class="badge">{{ item.from || item.badge }}</span>
        </button>
      </div>
    </template>
    <template #actions>
      <slot name="actions" />
      <span class="spacer"></span>
      <button type="button" class="btn btn-primary" @click="emit('close')">Done</button>
    </template>
  </BaseDialog>
</template>

<style scoped>
.count {
  font-size: 0.8rem;
  color: var(--text2);
}

.search {
  width: 100%;
  padding: 0.4667rem 0.6667rem;
  border: 1px solid var(--border);
  border-radius: 0.5333rem;
  background: var(--surface);
  color: inherit;
  font: inherit;
}

.note {
  color: var(--text2);
  font-size: 0.8667rem;
}

.section {
  margin-top: 0.2667rem;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text2);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(8.2667rem, 1fr));
  gap: 0.5333rem;
}

.card {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
  padding: 0.4rem;
  border: 1px solid var(--border);
  border-radius: 0.6667rem;
  background: var(--surface2);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.card:hover {
  border-color: var(--text2);
}

.card.on {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent) inset;
}

.card.default:not(.on) {
  opacity: 0.6;
}

.thumb {
  position: relative;
  display: grid;
  place-items: center;
  aspect-ratio: 1;
  border-radius: 0.4667rem;
  background: var(--surface);
  overflow: hidden;
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumb .blank {
  font-size: 1.8667rem;
  opacity: 0.6;
}

.dot {
  flex-shrink: 0;
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
}

.tick {
  position: absolute;
  top: 0.3333rem;
  right: 0.3333rem;
  width: 1.3333rem;
  height: 1.3333rem;
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-size: 0.8rem;
  color: #fff;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.5);
}

.tick.inline {
  position: static;
  flex-shrink: 0;
  width: 1.0667rem;
  height: 1.0667rem;
  font-size: 0.7333rem;
  border-color: var(--border);
  background: transparent;
}

.card.on .tick {
  background: var(--accent);
  border-color: var(--accent);
}

.name {
  display: flex;
  align-items: center;
  gap: 0.3333rem;
  min-width: 0;
  font-size: 0.8667rem;
  font-weight: 600;
}

.name-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sub {
  font-size: 0.8rem;
  color: var(--text2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.35;
}

.badge {
  align-self: flex-start;
  max-width: 100%;
  padding: 1px 0.4rem;
  border-radius: 66.6rem;
  font-size: 0.7333rem;
  color: var(--text2);
  border: 1px solid var(--border);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.spacer {
  flex: 1;
}
</style>
