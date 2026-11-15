<!-- One model badge as a pill (or, folded, as a coloured dot). Every badge is the same
     shape: its hue comes from --b alone (text colour, tinted fill, and the dot), so
     they stay consistent whatever they say. `badge` is { t, title, cls, color? }. -->
<script setup>
defineProps({
  badge: { type: Object, required: true },
  dot: { type: Boolean, default: false },
  picked: { type: Boolean, default: false }, // beside the picked model in the closed picker
})
</script>

<template>
  <span
    :class="[dot ? 'dot' : 'item-badge', badge.cls, { picked }]"
    :style="badge.color ? { '--b': badge.color } : null"
    :title="dot ? null : badge.title"
    :aria-hidden="dot ? 'true' : null"
    >{{ dot ? '' : badge.t }}</span
  >
</template>

<style scoped>
.item-badge {
  --b: var(--text2);
  font-size: 0.65rem;
  font-weight: 600;
  line-height: 1.5;
  padding: 1px 7px;
  border-radius: 6px;
  white-space: nowrap;
  color: var(--b);
  background: color-mix(in srgb, var(--b) 16%, transparent);
}
.dot {
  width: 7px;
  height: 7px;
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
  margin-left: 6px;
  vertical-align: middle;
}
</style>
