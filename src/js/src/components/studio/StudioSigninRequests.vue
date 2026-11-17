<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { approveSignin, denySignin, fetchSigninRequests } from '../../composables/signinRequestsApi'

type Rows = Awaited<ReturnType<typeof fetchSigninRequests>>['requests']

const rows = ref<Rows>([])
const error = ref('')

async function run(call: () => Promise<{ requests: Rows }>): Promise<void> {
  error.value = ''
  try {
    rows.value = (await call()).requests
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(() => run(fetchSigninRequests))
</script>

<template>
  <section class="scard">
    <div class="ctitle">Sign-in requests</div>
    <div v-if="error" class="cnote">{{ error }}</div>
    <div v-else-if="!rows.length" class="cnote">Nobody is waiting. A sign-in the allow-lists refuse shows up here.</div>
    <div v-for="r in rows" :key="r.identity" class="req">
      <div class="who">
        <span class="nm">{{ r.name || r.email || r.identity }}</span>
        <span class="id">{{ r.email || r.identity }}</span>
      </div>
      <span v-if="r.approved" class="st">Approved</span>
      <button v-else class="btn" @click="run(() => approveSignin(r.identity))">Approve</button>
      <button class="btn" @click="run(() => denySignin(r.identity))">{{ r.approved ? 'Revoke' : 'Deny' }}</button>
    </div>
  </section>
</template>

<style scoped>
.req {
  display: flex;
  align-items: center;
  gap: 0.5333rem;
  padding: 0.2667rem 0;
  font-size: 0.8667rem;
}
.who {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
.nm,
.id {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.id,
.st {
  color: var(--smuted);
}
</style>
