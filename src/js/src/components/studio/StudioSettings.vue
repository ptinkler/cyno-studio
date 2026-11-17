<script setup lang="ts">
import { ref } from 'vue'
import type { ThemeChoice } from '../../composables/useStudioTheme'
import { TEXT_SIZES, useTextSize } from '../../composables/useTextSize'
import StudioAccount from './StudioAccount.vue'
import StudioTitleModel from './StudioTitleModel.vue'
import StudioKeys from './StudioKeys.vue'
import StudioUploads from './StudioUploads.vue'
import StudioVpnCard from './StudioVpnCard.vue'

withDefaults(defineProps<{ theme?: ThemeChoice | undefined }>(), { theme: 'system' })
defineEmits<{ 'set-theme': [theme: ThemeChoice]; close: []; 'sign-out': [] }>()

const { textSize, setTextSize } = useTextSize()

// VPN controls are admin-only; StudioAccount reports the signed-in user
const isAdmin = ref(false)
function onUser(user: { is_admin?: boolean } | null): void {
  isAdmin.value = !!user?.is_admin
}

const THEMES: readonly { id: ThemeChoice; label: string }[] = [
  { id: 'system', label: 'System' },
  { id: 'light', label: 'Light' },
  { id: 'dark', label: 'Dark' },
]
</script>

<template>
  <div class="page">
    <div class="pwrap narrow">
      <div class="phead">
        <h1>Settings</h1>
        <div class="hactions">
          <button class="btn" @click="$emit('close')">
            <svg class="ic"><use href="#s-chevL" /></svg> Back
          </button>
        </div>
      </div>

      <section class="scard">
        <div class="ctitle">Appearance</div>
        <div class="crow">
          <div class="clabel">Theme</div>
          <div class="seg" role="group" aria-label="Theme">
            <button v-for="t in THEMES" :key="t.id" :class="{ on: theme === t.id }" @click="$emit('set-theme', t.id)">
              {{ t.label }}
            </button>
          </div>
        </div>
        <div class="crow">
          <div class="clabel">Text size</div>
          <div class="seg" role="group" aria-label="Text size">
            <button
              v-for="size in TEXT_SIZES"
              :key="size.id"
              :class="{ on: textSize === size.id }"
              :title="`${size.label}: ${size.hint} base text`"
              @click="setTextSize(size.id)"
            >
              {{ size.label }}
            </button>
          </div>
        </div>
      </section>

      <StudioTitleModel />

      <StudioAccount @user="onUser" @sign-out="$emit('sign-out')" />

      <StudioKeys />

      <StudioUploads />

      <StudioVpnCard v-if="isAdmin" />
    </div>
  </div>
</template>
