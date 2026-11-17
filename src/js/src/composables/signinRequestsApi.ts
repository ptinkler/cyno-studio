import { api } from './useApi'

const enc = encodeURIComponent

// Sign-ins the allow-lists refused, for the admin to approve or deny (see web/auth/signin_requests.py).
export const fetchSigninRequests = () => api.get('/api/signin-requests')
export const approveSignin = (identity: string) => api.post(`/api/signin-requests/approve?identity=${enc(identity)}`)
export const denySignin = (identity: string) => api.delete(`/api/signin-requests?identity=${enc(identity)}`)
