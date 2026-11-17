<script setup lang="ts">
withDefaults(defineProps<{ modelValue?: boolean; label: string; id: string }>(), { modelValue: false })

const emit = defineEmits<{ 'update:modelValue': [checked: boolean] }>()

function onChange(event: Event): void {
  if (event.target instanceof HTMLInputElement) emit('update:modelValue', event.target.checked)
}
</script>

<template>
  <div class="toggle-row">
    <label class="toggle">
      <input :id="id" type="checkbox" :checked="modelValue" @change="onChange" />
      <span class="track">
        <span class="thumb"></span>
      </span>
    </label>
    <label :for="id" class="toggle-label">{{ label }}</label>
  </div>
</template>

<style scoped>
.toggle-row {
  display: flex;
  align-items: center;
  gap: 0.5333rem;
}

.toggle {
  position: relative;
  width: 2.6667rem;
  height: 1.4667rem;
  cursor: pointer;
}

.toggle input {
  display: none;
}

.track {
  position: absolute;
  inset: 0;
  background: linear-gradient(145deg, rgba(40, 40, 48, 0.9), rgba(30, 30, 36, 0.95));
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 0.7333rem;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.3);
}

.thumb {
  position: absolute;
  width: 1.0667rem;
  height: 1.0667rem;
  background: linear-gradient(145deg, #888, #666);
  border-radius: 50%;
  left: 0.2rem;
  top: 2px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}

.toggle input:checked + .track {
  background: linear-gradient(145deg, var(--accent), #5a4bd1);
  border-color: rgba(108, 92, 231, 0.3);
  box-shadow:
    inset 0 1px 3px rgba(0, 0, 0, 0.2),
    0 0 12px rgba(108, 92, 231, 0.3);
}

.toggle input:checked + .track .thumb {
  left: 1.4rem;
  background: linear-gradient(145deg, #fff, #e8e8e8);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
}

.toggle-label {
  cursor: pointer;
  text-transform: none;
  font-size: 0.8rem;
  font-weight: 500;
  margin: 0;
  color: var(--text2);
  transition: color 0.2s;
  letter-spacing: 0.02em;
}

.toggle:hover + .toggle-label {
  color: var(--text);
}
</style>
