import type { components } from '../api/schema'

import { api } from './useApi'

type UploadPrefsUpdate = components['schemas']['UploadPrefsUpdate']

// Account + per-user keys (OAuth sign-in, admin, provider keys).
export const fetchMe = () => api.get('/api/auth/me')
export const fetchAuthProviders = () => api.get('/api/auth/providers')
// Ends every other device's login; this one stays signed in.
export const signOutOtherDevices = () => api.post('/api/auth/logout-others')
export const fetchUserKeys = () => api.get('/api/keys')
export const saveUserKeys = (keys: Record<string, string | null>) => api.put('/api/keys', { keys })

// Per-user source-media hosting (where uploads go for Pollo to fetch).
export const fetchUploadPrefs = () => api.get('/api/settings/uploads')
export const saveUploadPrefs = (prefs: UploadPrefsUpdate) => api.put('/api/settings/uploads', prefs)
export const testSelfhost = (selfhostBase: string | null) =>
  api.post('/api/settings/uploads/test-selfhost', { selfhost_base: selfhostBase })

export const UPLOAD_HOSTS = [
  { id: 'litterbox', label: 'Litterbox (temp host, up to ~1GB)' },
  { id: 'uguu', label: 'uguu.se (temp host, up to 128MB, 3 hours)' },
  { id: 'tmpfiles', label: 'tmpfiles.org (temp host)' },
  { id: 'selfhost', label: 'Self-host from this instance' },
] as const
export const EXPIRY_LABELS: Record<number, string> = {
  60: '1 hour',
  720: '12 hours',
  1440: '24 hours',
  4320: '72 hours',
}

// Provider sign-in is a full-page redirect so the OAuth cookies land correctly.
export const authLoginUrl = (provider: string) => `/api/auth/login/${provider}`

export const PROVIDER_LABELS: Record<string, string> = { google: 'Google', microsoft: 'Microsoft', x: 'X' }
export const KEY_PROVIDERS = [
  { id: 'pollo', label: 'Pollo' },
  { id: 'venice', label: 'Venice' },
  { id: 'openrouter', label: 'OpenRouter' },
] as const
