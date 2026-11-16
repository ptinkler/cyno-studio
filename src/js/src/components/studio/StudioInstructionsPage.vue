<script setup lang="ts">
import { ref, computed, onMounted, inject } from 'vue'
import { showToastKey, noToast } from '../../injection'
import InstructionEditor from '../chat/InstructionEditor.vue'
import type { Instruction, InstructionGroup } from '../../composables/chatSettingsApi'
import { fetchInstructions } from '../../composables/useChat'
import { useChatDefaults } from '../../composables/useChatDefaults'
import type { DefaultKind } from '../../composables/useChatDefaults'
import { instructionColor } from '../../utils/format'
import { ALL_CHATS, defaultIcon } from '../../utils/defaults'
import { messageOf } from '../../utils/errors'

const emit = defineEmits<{ close: [] }>()
const showToast = inject(showToastKey, noToast)
const { globalSettings, spaces, loadDefaults, setCurrentSpace } = useChatDefaults()

const snippets = ref<Instruction[]>([])
const groups = ref<InstructionGroup[]>([])
const loading = ref(true)
const query = ref('')
const editing = ref<{ kind: 'snippet' | 'group'; id: number | null } | null>(null)

const matches = (item: { name: string }): boolean => item.name.toLowerCase().includes(query.value.trim().toLowerCase())
const shownGroups = computed(() => groups.value.filter(matches))
const shownSnippets = computed(() => snippets.value.filter(matches))
const snippetById = computed(() => new Map(snippets.value.map(s => [s.id, s])))

const membersOf = (group: InstructionGroup): Instruction[] =>
  group.snippet_ids.flatMap(id => snippetById.value.get(id) ?? [])

function defaultFor(kind: Extract<DefaultKind, 'instruction' | 'instruction_group'>, id: number): string[] {
  const field = `default_${kind}_ids` as const
  return [
    ...(globalSettings.value[field].includes(id) ? [ALL_CHATS] : []),
    ...spaces.value.filter(s => s[field].includes(id)).map(s => s.name),
  ]
}
async function load(): Promise<void> {
  try {
    const data = await fetchInstructions()
    snippets.value = data.instructions
    groups.value = data.groups
  } catch (e) {
    showToast(`Couldn't load instructions: ${messageOf(e)}`, 'error')
  } finally {
    loading.value = false
  }
}
function onChanged(): void {
  void load()
  void loadDefaults()
}
onMounted(() => {
  setCurrentSpace(null)
  onChanged()
})
</script>

<template>
  <div class="page">
    <div class="pwrap">
      <div class="phead">
        <div>
          <h1>Instructions</h1>
          <p class="sub">Sent to the chat model word for word. A group bundles snippets that go together.</p>
        </div>
        <div class="hactions">
          <button class="btn" @click="editing = { kind: 'group', id: null }">
            <svg class="ic"><use href="#s-plus" /></svg> Group
          </button>
          <button class="btn btn-primary" @click="editing = { kind: 'snippet', id: null }">
            <svg class="ic"><use href="#s-plus" /></svg> Snippet
          </button>
          <button class="btn" @click="emit('close')">
            <svg class="ic"><use href="#s-chevL" /></svg> Back
          </button>
        </div>
      </div>

      <input
        v-if="snippets.length || groups.length"
        v-model="query"
        type="search"
        class="search"
        placeholder="Search instructions"
      />

      <div v-if="loading" class="muted">Loading…</div>
      <template v-else>
        <div v-if="!snippets.length && !groups.length" class="empty">
          No instructions yet. Make a snippet for a tone, a format or a rule.
        </div>

        <section v-if="shownGroups.length">
          <h2 class="sect">Groups</h2>
          <div class="grid">
            <button
              v-for="g in shownGroups"
              :key="g.id"
              class="gcard card"
              @click="editing = { kind: 'group', id: g.id }"
            >
              <h3>📦 {{ g.name }}</h3>
              <div class="members">
                <span v-for="s in membersOf(g)" :key="s.id" class="member">
                  <span class="dot" :style="{ background: instructionColor(s.name) }"></span>{{ s.name }}
                </span>
                <span v-if="!g.snippet_ids.length" class="muted">No snippets</span>
              </div>
              <div v-if="defaultFor('instruction_group', g.id).length" class="badges">
                <span v-for="b in defaultFor('instruction_group', g.id)" :key="b" class="badge">
                  {{ defaultIcon(b) }} {{ b }}
                </span>
              </div>
            </button>
          </div>
        </section>

        <section v-if="shownSnippets.length">
          <h2 class="sect">Snippets</h2>
          <div class="grid">
            <button
              v-for="s in shownSnippets"
              :key="s.id"
              class="gcard card"
              @click="editing = { kind: 'snippet', id: s.id }"
            >
              <h3><span class="dot" :style="{ background: instructionColor(s.name) }"></span>{{ s.name }}</h3>
              <p class="preview">{{ s.content || 'Empty' }}</p>
              <div v-if="defaultFor('instruction', s.id).length" class="badges">
                <span v-for="b in defaultFor('instruction', s.id)" :key="b" class="badge">
                  {{ defaultIcon(b) }} {{ b }}
                </span>
              </div>
            </button>
          </div>
        </section>

        <p v-if="query && !shownGroups.length && !shownSnippets.length" class="muted">Nothing matches</p>
      </template>
    </div>

    <InstructionEditor
      :target="editing"
      :instructions="snippets"
      :groups="groups"
      @close="editing = null"
      @changed="onChanged"
    />
  </div>
</template>

<style scoped>
.search {
  width: 100%;
  margin-bottom: 0.5333rem;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--tile-m), 1fr));
  gap: 0.6667rem;
}
.card {
  padding: 0.6667rem 0.8rem;
}
.card h3 {
  display: flex;
  align-items: center;
  gap: 0.4667rem;
  font-size: 0.9rem;
  font-weight: 600;
}
.dot {
  width: 0.5333rem;
  height: 0.5333rem;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.preview {
  margin-top: 0.2667rem;
  font-size: 0.8rem;
  color: var(--smuted);
  line-height: 1.45;
  max-height: 3.2em;
  overflow: hidden;
}
.members {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.4rem;
}
.member {
  display: inline-flex;
  align-items: center;
  gap: 0.3333rem;
  font-size: 0.8rem;
  color: var(--smuted);
}
.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3333rem;
  margin-top: 0.5333rem;
}
.badge {
  background: var(--saccent-soft);
  color: var(--saccent);
  border-radius: 66.6rem;
  padding: 1px 0.4667rem;
}
</style>
