<script setup lang="ts">
import { computed } from 'vue'
import { useInspectorSections } from '../../composables/useInspectorSections'

// One inspector section: a header that folds it away (remembered per browser) and its body.
const props = defineProps<{ title: string }>()
const { isCollapsed, toggle } = useInspectorSections()
const collapsed = computed(() => isCollapsed(props.title))
</script>

<template>
  <div class="isection" :class="{ folded: collapsed }">
    <button class="ilabel ihead" type="button" :aria-expanded="!collapsed" @click="toggle(title)">
      <span>{{ title }}</span>
      <svg class="ic"><use href="#s-chev" /></svg>
    </button>
    <div v-show="!collapsed"><slot /></div>
  </div>
</template>

<style scoped>
.ihead {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  background: none;
  border: 0;
  padding: 0;
  cursor: pointer;
  font: inherit;
  font-size: 0.8rem;
}
.ihead:hover {
  color: var(--sfg);
}
.ihead .ic {
  transition: transform 0.15s;
}
.folded .ihead {
  margin-bottom: 0;
}
.folded .ihead .ic {
  transform: rotate(-90deg);
}
</style>
