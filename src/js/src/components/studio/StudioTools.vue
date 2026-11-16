<script setup lang="ts">
defineEmits<{ close: []; navigate: [route: string]; defaults: []; import: [] }>()

// `path` so each row is a real link (right-click, new tab); `route` is what the
// click emits for in-app navigation. They must agree — see STUDIO_PANE_PATH.
const TOOLS: readonly { route: string; path: string; label: string; note: string }[] = [
  {
    route: 'characters',
    path: '/characters',
    label: 'Characters',
    note: 'Reusable characters for chats and generations',
  },
  {
    route: 'instructions',
    path: '/instructions',
    label: 'Instructions',
    note: 'Snippets and groups sent to the chat model',
  },
  { route: 'presets', path: '/presets', label: 'Presets', note: 'Saved model and option sets' },
  { route: 'usage', path: '/usage', label: 'Credit usage', note: 'Balances for every provider' },
  { route: 'request-log', path: '/requests', label: 'Request log', note: 'What was sent to each provider' },
]
</script>

<template>
  <div class="page">
    <div class="pwrap narrow">
      <div class="phead">
        <h1>Tools &amp; library</h1>
        <div class="hactions">
          <button class="btn" @click="$emit('close')">
            <svg class="ic"><use href="#s-chevL" /></svg> Back
          </button>
        </div>
      </div>

      <div class="links">
        <button class="link" @click="$emit('defaults')">
          <span class="lmain"
            ><span class="llabel">Default instructions &amp; characters</span
            ><span class="lnote">Attached to every chat, or to every chat in a space</span></span
          >
          <svg class="ic"><use href="#s-chev" /></svg>
        </button>
        <a v-for="t in TOOLS" :key="t.route" class="link" :href="t.path" @click.prevent="$emit('navigate', t.route)">
          <span class="lmain"
            ><span class="llabel">{{ t.label }}</span
            ><span class="lnote">{{ t.note }}</span></span
          >
          <svg class="ic"><use href="#s-chev" /></svg>
        </a>
        <button class="link" @click="$emit('import')">
          <span class="lmain"
            ><span class="llabel">Import / Export</span
            ><span class="lnote">Move chats between instances, or bring in a ChatGPT export</span></span
          >
          <svg class="ic"><use href="#s-chev" /></svg>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.links {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--sborder);
  background: var(--sbg);
  border-radius: var(--r-lg);
  padding: 0.4rem;
}
.link {
  text-decoration: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
  padding: 0.6667rem 0.8rem;
  border: none;
  border-radius: var(--r);
  background: none;
  color: var(--sfg);
  cursor: pointer;
  text-align: left;
}
.link:hover {
  background: var(--shover);
}
.lmain {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.llabel {
  font-size: 0.9rem;
  font-weight: 500;
}
.lnote {
  font-size: 0.8rem;
  color: var(--smuted);
}
.link .ic {
  color: var(--sfaint);
  flex-shrink: 0;
}
</style>
