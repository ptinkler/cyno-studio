import { api } from './useApi'

// The VPN tunnel (admin only; see web/vpn.py).
export const fetchVpnStatus = () => api.get('/api/vpn/status')
export const restartVpn = () => api.post('/api/vpn/restart')
