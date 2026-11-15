import { ref } from 'vue'
import type { components } from '../api/schema'
import type { RequestBody, ResponseOf } from '../api/paths'
import { errorMessage, readJson } from '../api/json'

type SessionUser = components['schemas']['SessionUser']

// Shared across all callers.
const isAuthenticated = ref(false)
const currentUser = ref<SessionUser | null>(null)
const showLogin = ref(false)

// Sign-in is the one place a 401 is an answer rather than a reason to prompt for sign-in, so these
// calls use `fetch` directly instead of the API client.
async function signIn<P extends '/api/auth/login' | '/api/auth/dev-login'>(
  url: P,
  body?: RequestBody<P, 'post'>,
): Promise<ResponseOf<P, 'post'>> {
  const res = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  if (!res.ok) throw new Error(await errorMessage(res, 'Request failed'))
  return readJson<ResponseOf<P, 'post'>>(res)
}

// Everything the app holds in memory (threads, instructions, characters, balances, preferences) belongs
// to whoever was signed in when the page loaded — and if nobody was, the first load was refused with a
// 401 and is still empty. So signing in or out starts the app over with a page reload, rather than
// patching each piece of state: you see your data straight away, and the next person to sign in on
// this browser never sees the last person's.
function restart(): void {
  location.reload()
}

function signedIn(user: SessionUser): void {
  isAuthenticated.value = true
  currentUser.value = user
  showLogin.value = false
  restart()
}

async function checkStatus(): Promise<void> {
  try {
    const res = await fetch('/api/auth/status', { credentials: 'same-origin' })
    const status = await readJson<ResponseOf<'/api/auth/status', 'get'>>(res)
    isAuthenticated.value = status.authenticated
    currentUser.value = status.user
    if (!status.authenticated) showLogin.value = true
  } catch {
    // Server unreachable — leave state as-is
  }
}

void checkStatus()

export function useAuth() {
  async function login(email: string, password: string): Promise<void> {
    signedIn(await signIn('/api/auth/login', { email, password }))
  }

  // One-click local dev account (only works when the server has DEV_LOGIN on).
  async function devLogin(): Promise<void> {
    signedIn(await signIn('/api/auth/dev-login'))
  }

  async function logout(): Promise<void> {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
    isAuthenticated.value = false
    currentUser.value = null
    showLogin.value = true
    restart()
  }

  function promptLogin(): void {
    showLogin.value = true
  }

  return { isAuthenticated, currentUser, showLogin, login, devLogin, logout, promptLogin }
}
