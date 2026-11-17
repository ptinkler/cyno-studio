<script setup lang="ts">
import type { ProviderFacet, TagFacet } from '../../composables/useModelList'
import type { Provider } from '../../composables/modelTags'

const props = withDefaults(
  defineProps<{
    providers?: readonly ProviderFacet[] | undefined
    tags?: readonly TagFacet[] | undefined
    selProviders?: readonly Provider[] | undefined
    selTags?: readonly string[] | undefined
    uncensoredCount?: number | undefined
    hiddenCount?: number | undefined
    anyFilter?: boolean | undefined
  }>(),
  {
    providers: () => [],
    tags: () => [],
    selProviders: () => [],
    selTags: () => [],
    uncensoredCount: 0,
    hiddenCount: 0,
    anyFilter: false,
  },
)
defineEmits<{ 'toggle-provider': [id: Provider]; 'toggle-tag': [slug: string]; clear: [] }>()
const uncensoredOnly = defineModel<boolean>('uncensoredOnly', { default: false })
const showHidden = defineModel<boolean>('showHidden', { default: false })
</script>

<template>
  <div class="fpanel" role="group" aria-label="Filters" @mousedown.stop>
    <template v-if="props.providers.length">
      <div class="fhead">Provider</div>
      <label v-for="p in props.providers" :key="p.id" class="frow provider" :title="p.title">
        <input type="checkbox" :checked="props.selProviders.includes(p.id)" @change="$emit('toggle-provider', p.id)" />
        <span class="flabel"
          ><span class="fpill" :style="{ '--b': p.color }">{{ p.label }}</span></span
        >
        <span class="fn">{{ p.n }}</span>
      </label>
    </template>

    <template v-if="props.tags.length">
      <div v-if="props.providers.length" class="fsep"></div>
      <div class="fhead">Capability</div>
      <label v-for="t in props.tags" :key="t.slug" class="frow tag">
        <input type="checkbox" :checked="props.selTags.includes(t.slug)" @change="$emit('toggle-tag', t.slug)" />
        <span class="flabel"
          ><span class="fpill" :style="{ '--b': t.color }">{{ t.label }}</span></span
        >
        <span class="fn">{{ t.n }}</span>
      </label>
    </template>

    <template v-if="uncensoredCount || hiddenCount">
      <div class="fsep"></div>
      <label v-if="uncensoredCount" class="frow uncensored-only" title="Uncensored only">
        <input v-model="uncensoredOnly" type="checkbox" />
        <span class="flabel">Uncensored only</span>
        <span class="fn">{{ uncensoredCount }}</span>
      </label>
      <label v-if="hiddenCount" class="frow show-hidden" title="Not enabled for this key, or retired">
        <input v-model="showHidden" type="checkbox" />
        <span class="flabel">Show hidden models</span>
        <span class="fn">{{ hiddenCount }}</span>
      </label>
    </template>

    <button v-if="anyFilter" type="button" class="fclear" @click="$emit('clear')">Clear all filters</button>
  </div>
</template>

<style scoped>
.fpanel {
  position: absolute;
  top: 3.0667rem;
  right: 0.5333rem;
  z-index: 2;
  width: min(17.3333rem, calc(100% - 1.0667rem));
  max-height: calc(100% - 3.6rem);
  overflow-y: auto;
  padding: 0.5333rem;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 0.8rem;
  box-shadow: var(--shadow-pop);
}
.fhead {
  padding: 0.2667rem 0.5333rem;
  font-size: 0.8rem;
  color: var(--text2);
}
.fsep {
  height: 1px;
  margin: 0.4rem 0.2667rem;
  background: var(--border);
}
.frow {
  display: flex;
  align-items: center;
  gap: 0.6667rem;
  padding: 0.4rem 0.5333rem;
  border-radius: var(--r);
  font-size: 0.8667rem;
  font-weight: 400;
  text-transform: none;
  letter-spacing: normal;
  color: var(--sfg);
  cursor: pointer;
  user-select: none;
}
.frow:hover {
  background: var(--surface);
}
.frow input {
  margin: 0;
  accent-color: var(--accent);
}
.flabel {
  flex: 1;
}
/* The same pill the row badges use, in the tag's own colour */
.fpill {
  --b: var(--text2);
  display: inline-block;
  padding: 1px 0.4667rem;
  border-radius: 0.4rem;
  font-size: 0.8rem;
  font-weight: 600;
  line-height: 1.5;
  color: var(--b);
  background: color-mix(in srgb, var(--b) 16%, transparent);
}
.fn {
  font-size: 0.8rem;
  color: var(--text2);
}
.fclear {
  display: block;
  width: 100%;
  margin-top: 0.4rem;
  padding: 0.4667rem 0.5333rem;
  background: none;
  border: none;
  border-top: 1px solid var(--border);
  color: var(--text2);
  font-size: 0.8rem;
  text-align: left;
  cursor: pointer;
}
.fclear:hover {
  color: var(--text);
}
</style>
