<script setup lang="ts">
import type { Badge } from '../../utils/modelBadges'

withDefaults(
  defineProps<{
    badge: Badge
    dot?: boolean | undefined
    /** Beside the picked model in the closed picker. */
    picked?: boolean | undefined
  }>(),
  { dot: false, picked: false },
)
</script>

<template>
  <span
    :class="[dot ? 'dot' : 'item-badge', badge.cls, { picked }]"
    :style="badge.color ? { '--b': badge.color } : undefined"
    :title="dot ? undefined : badge.title"
    :aria-hidden="dot ? 'true' : undefined"
    >{{ dot ? '' : badge.t }}</span
  >
</template>

<style scoped>
.item-badge {
  --b: var(--text2);
  font-size: 0.7333rem;
  font-weight: 600;
  line-height: 1.5;
  padding: 1px 0.4667rem;
  border-radius: 0.4rem;
  white-space: nowrap;
  color: var(--b);
  background: color-mix(in srgb, var(--b) 16%, transparent);
}
.dot {
  width: 0.4667rem;
  height: 0.4667rem;
  border-radius: 50%;
  background: var(--b, var(--text2));
}
:is(.item-badge, .dot).uncensored {
  --b: #ff8a6e;
}
:is(.item-badge, .dot).private {
  --b: #4fd1a5;
}
:is(.item-badge, .dot).anonymized {
  --b: var(--text2);
}
:is(.item-badge, .dot).characters {
  --b: #e68fd0; /* pastel magenta */
}
:is(.item-badge, .dot).context {
  --b: #5fb0f0; /* pastel sky blue */
}
:is(.item-badge, .dot).duration {
  --b: #3fcabf; /* pastel teal */
}
:is(.item-badge, .dot).price {
  --b: #e8a33d;
}
:is(.item-badge, .dot).hidden {
  --b: #c9a227;
}
.item-badge.picked {
  margin-left: 0.4rem;
  vertical-align: middle;
}
</style>
