import { describe, it, expect, vi, beforeEach } from 'vitest'

// useAuth checks the session as soon as it is imported, so each test sets up fetch first and imports afresh.
async function loadAuth(status: Record<string, unknown>) {
  vi.resetModules()
  const reload = vi.fn()
  vi.stubGlobal('location', { reload })
  const calls: [string, string][] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, opts?: { method?: string }) => {
      calls.push([url, opts?.method ?? 'GET'])
      const body = url === '/api/auth/status' ? status : url === '/api/auth/login' ? { id: 7, email: 'a@b.c' } : {}
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
    }),
  )
  const { useAuth } = await import('../composables/useAuth')
  await vi.waitFor(() => {
    expect(calls.length).toBeGreaterThan(0)
  }) // the initial status check
  return { auth: useAuth(), reload, calls }
}

describe('useAuth restarts the app when the signed-in user changes', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it("reloads after signing in, so the first (refused) load is replaced by the user's data", async () => {
    const { auth, reload } = await loadAuth({ authenticated: false, user: null })
    await vi.waitFor(() => {
      expect(auth.showLogin.value).toBe(true)
    })
    await auth.login('a@b.c', 'pw')
    expect(auth.isAuthenticated.value).toBe(true)
    expect(auth.showLogin.value).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it("reloads after signing out, so the previous user's data is not left on screen", async () => {
    const { auth, reload } = await loadAuth({ authenticated: true, user: { id: 7 } })
    await auth.logout()
    expect(auth.isAuthenticated.value).toBe(false)
    expect(auth.showLogin.value).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('does not reload just because the page loaded already signed in', async () => {
    const { reload } = await loadAuth({ authenticated: true, user: { id: 7 } })
    expect(reload).not.toHaveBeenCalled()
  })
})
