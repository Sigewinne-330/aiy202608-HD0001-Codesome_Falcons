import { api, ApiError } from '@/stores/auth'

export { ApiError }

const BASE = '/api/integrations/managebac'

export function createDisconnectedManageBacState(syncIntervalMinutes = 10) {
  return {
    connected: false,
    enabled: false,
    status: null,
    sync_interval_minutes: syncIntervalMinutes,
  }
}

export function normalizeManageBacConnection(value, fallbackInterval = 10) {
  const fallback = createDisconnectedManageBacState(fallbackInterval)
  if (!value || value.connected !== true) {
    return { ...fallback, ...(value || {}), connected: false, enabled: false }
  }
  return {
    ...fallback,
    ...value,
    connected: true,
    enabled: Boolean(value.enabled),
  }
}

export function isManageBacFeedCandidate(value) {
  return /^(webcal|https):\/\//i.test(String(value || '').trim())
}

export const managebacApi = {
  status: () => api(`${BASE}/status`),
  validate: (feedUrl) => api(`${BASE}/validate`, {
    method: 'POST',
    body: JSON.stringify({ feed_url: feedUrl }),
  }),
  connect: (feedUrl) => api(`${BASE}/connect`, {
    method: 'POST',
    body: JSON.stringify({ feed_url: feedUrl }),
  }),
  sync: () => api(`${BASE}/sync`, { method: 'POST' }),
  setEnabled: (enabled) => api(`${BASE}/settings`, {
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  }),
  runs: (limit = 10) => api(`${BASE}/runs?limit=${limit}`),
  disconnect: (deleteImportedTasks = false) => api(
    `${BASE}/disconnect?delete_imported_tasks=${deleteImportedTasks ? 'true' : 'false'}`,
    { method: 'DELETE' },
  ),
}
