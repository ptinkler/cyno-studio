<script setup lang="ts">
import { ref, inject, onMounted } from 'vue'
import { showToastKey, noToast } from '../../injection'
import { fetchAuthProviders, authLoginUrl, signOutOtherDevices, PROVIDER_LABELS } from '../../composables/useAccount'
import { messageOf } from '../../utils/errors'

type Providers = Awaited<ReturnType<typeof fetchAuthProviders>>

const emit = defineEmits<{ user: [user: Providers['user']]; 'sign-out': [] }>()

const showToast = inject(showToastKey, noToast)
const user = ref<Providers['user']>(null)
const providers = ref<string[]>([])

async function load(): Promise<void> {
  try {
    const found = await fetchAuthProviders()
    user.value = found.user
    providers.value = found.providers
    emit('user', found.user)
  } catch {
    user.value = null
  }
}

// Anyone signed in as this account on another device (or a stolen cookie) is signed out; this device isn't
async function signOutOthers(): Promise<void> {
  try {
    await signOutOtherDevices()
    showToast('Signed out of your other devices', 'success')
  } catch (e) {
    showToast(messageOf(e), 'error')
  }
}

onMounted(load)
</script>

<template>
  <section class="scard">
    <div class="ctitle">Account</div>
    <div v-if="user" class="who">
      <img v-if="user.avatar_url" :src="user.avatar_url" class="av" alt="" />
      <div v-else class="av ph">{{ (user.name || user.email || '?').charAt(0).toUpperCase() }}</div>
      <div class="meta">
        <div class="nm">{{ user.name || user.email }} <span v-if="user.is_admin" class="badge admin">Admin</span></div>
        <div class="em">{{ user.email }} · {{ PROVIDER_LABELS[user.provider] || user.provider }}</div>
      </div>
      <button class="btn" @click="$emit('sign-out')">Sign out</button>
    </div>
    <div v-if="user" class="crow">
      <span class="cnote">Signed in somewhere else, or lost a device?</span>
      <button class="btn btn-sm" @click="signOutOthers">Sign out other devices</button>
    </div>
    <template v-else>
      <div class="providers">
        <a v-for="p in providers" :key="p" class="btn" :href="authLoginUrl(p)"
          >Continue with {{ PROVIDER_LABELS[p] || p }}</a
        >
      </div>
      <p v-if="!providers.length" class="cnote">No sign-in providers configured.</p>
    </template>
  </section>
</template>

<style scoped>
.who {
  display: flex;
  align-items: center;
  gap: 12px;
}
.av {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  object-fit: cover;
  flex: 0 0 auto;
}
.av.ph {
  display: grid;
  place-items: center;
  background: var(--saccent-soft);
  color: var(--saccent);
  font-weight: 650;
}
.meta {
  flex: 1;
  min-width: 0;
}
.nm {
  color: var(--sfg);
  font-weight: 550;
  font-size: 13.5px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.badge.admin {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--saccent-soft);
  color: var(--saccent);
  font-weight: 650;
}
.em {
  color: var(--smuted);
  font-size: 12.5px;
  margin-top: 1px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.providers {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.providers .btn {
  justify-content: center;
}
</style>
