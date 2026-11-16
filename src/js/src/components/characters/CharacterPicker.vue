<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Character } from '../../composables/charactersApi'
import type { InheritedDefault } from '../../composables/useChatDefaults'
import { characterAvatar } from '../../composables/useCharacters'
import { defaultIcon, defaultTitle as fromTitle } from '../../utils/defaults'
import PickDialog from '../PickDialog.vue'
import type { PickItem } from '../PickDialog.vue'

// Attached characters as chips, plus a dialog to pick more (a grid of
// pictures: names aren't unique, so a chat's own "Linh" and a library "Linh"
// are told apart by face and badge). Editing and creating happen in
// CharacterEditor; this only emits 'edit' / 'create'.
const props = withDefaults(
  defineProps<{
    /** The attached character ids. */
    modelValue?: readonly number[] | undefined
    /** What can be attached. */
    characters?: readonly Character[] | undefined
    allowCreate?: boolean | undefined
    createLabel?: string | undefined
    /** Attached by the chat's defaults: shown, but changed in the defaults, not here. */
    inherited?: readonly InheritedDefault[] | undefined
    /** Defaults switched off in this chat: offered in the menu to switch back on. */
    hidden?: readonly InheritedDefault[] | undefined
  }>(),
  {
    modelValue: () => [],
    characters: () => [],
    allowCreate: true,
    createLabel: '＋ New character',
    inherited: () => [],
    hidden: () => [],
  },
)
// 'hide' / 'unhide': a default character's id, switched off / on in this chat only
const emit = defineEmits<{
  'update:modelValue': [ids: number[]]
  edit: [character: Character]
  create: []
  hide: [id: number]
  unhide: [id: number]
}>()

/** A character that comes from a default, and which one. */
type FromDefault = Character & { from: string }

/** One card in the pick dialog. */
interface CharacterCard extends PickItem {
  id: number
  kind: 'default' | 'own'
}

const open = ref(false)
const close = (): void => {
  open.value = false
}
const toggle = (): void => {
  open.value = !open.value
}

const byId = computed(() => new Map(props.characters.map(c => [c.id, c])))
const inheritedIds = computed(() => [...props.inherited, ...props.hidden].map(x => x.id))

const withSource = (entries: readonly InheritedDefault[]): FromDefault[] =>
  entries.flatMap(entry => {
    const character = byId.value.get(entry.id)
    return character ? [{ ...character, from: entry.from }] : []
  })
const hiddenItems = computed(() => withSource(props.hidden))
const fromDefaults = computed(() => withSource(props.inherited))
const attached = computed(() =>
  props.modelValue.filter(id => !inheritedIds.value.includes(id)).flatMap(id => byId.value.get(id) ?? []),
)
const available = computed(() =>
  props.characters.filter(c => !props.modelValue.includes(c.id) && !inheritedIds.value.includes(c.id)),
)

const attach = (c: Character): void => {
  emit('update:modelValue', [...props.modelValue, c.id])
}
const detach = (c: Character): void => {
  emit(
    'update:modelValue',
    props.modelValue.filter(id => id !== c.id),
  )
}

function create(): void {
  close()
  emit('create')
}

// Every character as a card: in use (own, or from the defaults) or not
const card = (c: Character, on: boolean, from?: string): CharacterCard => ({
  key: `${from ? 'd' : ''}${String(c.id)}`,
  id: c.id,
  name: c.name,
  sub: c.description,
  img: characterAvatar(c),
  badge: c.adhoc ? 'This chat' : 'Library',
  ...(from ? { from: `${defaultIcon(from)} ${fromTitle(from)}` } : {}),
  on,
  kind: from ? 'default' : 'own',
})
const cards = computed<CharacterCard[]>(() => [
  ...attached.value.map(c => card(c, true)),
  ...fromDefaults.value.map(c => card(c, true, c.from)),
  ...hiddenItems.value.map(c => card(c, false, c.from)),
  ...available.value.map(c => card(c, false)),
])

function onToggle(item: CharacterCard): void {
  const character = byId.value.get(item.id)
  if (!character) return
  if (item.kind === 'default') {
    if (item.on) emit('hide', character.id)
    else emit('unhide', character.id)
  } else if (item.on) {
    detach(character)
  } else {
    attach(character)
  }
}
</script>

<template>
  <div class="char-picker">
    <div class="chips">
      <span
        v-for="c in fromDefaults"
        :key="`d${c.id}`"
        class="chip inherited"
        :title="`${c.name} · ${fromTitle(c.from)}`"
      >
        <button class="chip-main" @click="emit('edit', c)">
          <img v-if="characterAvatar(c)" :src="characterAvatar(c) ?? undefined" alt="" />
          <span v-else class="avatar-blank">👤</span>
          {{ c.name }}
        </button>
        <span class="chip-src">{{ defaultIcon(c.from) }}</span>
        <button class="chip-x" :title="`Hide ${c.name} in this chat`" @click="emit('hide', c.id)">✕</button>
      </span>
      <span
        v-for="c in attached"
        :key="c.id"
        class="chip"
        :class="{ adhoc: c.adhoc }"
        :title="(c.adhoc ? 'This chat only — ' : '') + (c.description || c.name)"
      >
        <button class="chip-main" @click="emit('edit', c)">
          <img v-if="characterAvatar(c)" :src="characterAvatar(c) ?? undefined" alt="" />
          <span v-else class="avatar-blank">👤</span>
          {{ c.name }}
        </button>
        <button class="chip-x" :title="`Detach ${c.name}`" @click="detach(c)">✕</button>
      </span>
      <button class="add" @click="toggle">
        {{ attached.length || fromDefaults.length ? '＋' : '＋ Add character' }}
      </button>
    </div>

    <PickDialog
      :open="open"
      title="Characters"
      :items="cards"
      empty="No characters yet"
      search-placeholder="Search characters"
      @toggle="onToggle"
      @close="close"
    >
      <template v-if="allowCreate" #actions>
        <button type="button" class="btn btn-secondary" @click="create">{{ createLabel }}</button>
      </template>
    </PickDialog>
  </div>
</template>

<style scoped>
.char-picker {
  position: relative;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface2);
  font-size: 0.8rem;
  overflow: hidden;
}

.chip.adhoc {
  border-style: dashed;
}

/* Attached by the chat's defaults: no ✕ — the icon says where from */
.chip.inherited {
  background: transparent;
}

.chip-src {
  flex-shrink: 0;
  padding: 0 0 0 2px;
  font-size: 0.7rem;
  opacity: 0.75;
}

.chip-main {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 4px 3px 3px;
  background: none;
  border: none;
  color: var(--text);
  cursor: pointer;
  font: inherit;
}

.chip img,
.avatar-blank {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  display: inline-grid;
  place-items: center;
  font-size: 0.7rem;
  background: var(--surface);
}

.chip-x {
  background: none;
  border: none;
  color: var(--text2);
  cursor: pointer;
  padding: 0 8px 0 2px;
  font-size: 0.7rem;
}

.chip-x:hover {
  color: var(--text);
}

.add {
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px dashed var(--border);
  background: none;
  color: var(--text2);
  cursor: pointer;
  font-size: 0.8rem;
}

.add:hover {
  color: var(--text);
  border-color: var(--accent);
}
</style>
