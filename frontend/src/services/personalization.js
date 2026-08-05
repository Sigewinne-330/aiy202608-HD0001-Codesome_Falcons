import { api, authFetch } from '@/stores/auth'

export const CONSENT_POLICY_VERSION = 'scheduling-personalization-consent.v1'

export function createIdempotencyKey(prefix = 'ui') {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${random}`.slice(0, 128)
}

export function normalizedConsentPayload(settings) {
  const operational = Boolean(settings.operational_personalization_enabled)
  return {
    operational_personalization_enabled: operational,
    work_session_capture_enabled: operational && Boolean(settings.work_session_capture_enabled),
    llm_memory_enabled: operational && Boolean(settings.llm_memory_enabled),
    cross_user_learning_enabled: operational && Boolean(settings.cross_user_learning_enabled),
    near_tie_exploration_enabled: operational && Boolean(settings.near_tie_exploration_enabled),
    raw_event_retention_days: Number(settings.raw_event_retention_days || 365),
    rebuild_after_reset_enabled: Boolean(settings.rebuild_after_reset_enabled),
    expected_version: settings.version || settings.expected_version || null,
    policy_version: settings.policy_version || CONSENT_POLICY_VERSION,
  }
}

export function nextWorkControlState(current, action) {
  const allowed = {
    idle: { start: 'active' },
    active: { pause: 'paused', stop: 'idle' },
    paused: { resume: 'active', stop: 'idle', discard: 'idle' },
  }
  return allowed[current]?.[action] || current
}

export function parseServerTimestamp(value) {
  if (!value) return NaN
  const raw = String(value)
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw}Z`
  return new Date(normalized).getTime()
}

export const personalizationApi = {
  settings: () => api('/api/scheduling/personalization/settings'),
  saveSettings: (value) => api('/api/scheduling/personalization/settings', {
    method: 'PUT', body: JSON.stringify(normalizedConsentPayload(value)),
  }),
  dashboard: () => api('/api/scheduling/personalization/dashboard'),
  memories: (params = {}) => {
    const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value != null))
    return api(`/api/scheduling/memory?${query}`)
  },
  memoryDetail: (id) => api(`/api/scheduling/memory/${id}`),
  editMemory: (id, value) => api(`/api/scheduling/memory/${id}`, {
    method: 'PUT', body: JSON.stringify(value),
  }),
  deleteMemory: (id) => api(`/api/scheduling/memory/${id}`, { method: 'DELETE' }),
  exportMemory: async () => {
    const response = await authFetch('/api/scheduling/memory/export')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response.json()
  },
  reset: (settings, rebuild) => api('/api/scheduling/personalization/reset', {
    method: 'POST',
    body: JSON.stringify({
      idempotency_key: createIdempotencyKey('reset'),
      rebuild_from_retained_evidence: rebuild,
      expected_settings_version: settings.version,
    }),
  }),
  deletionStatus: () => api('/api/scheduling/personalization/deletion-status'),
  activeSessions: () => api('/api/scheduling/work-sessions/active'),
  startSession: (source) => api('/api/scheduling/work-sessions/start', {
    method: 'POST',
    body: JSON.stringify({ source, idempotency_key: createIdempotencyKey('start'), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai' }),
  }),
  transitionSession: (id, action) => api(`/api/scheduling/work-sessions/${id}/${action}`, {
    method: 'POST', body: JSON.stringify({ idempotency_key: createIdempotencyKey(action) }),
  }),
  outcome: (source, value) => api('/api/scheduling/outcomes', {
    method: 'POST',
    body: JSON.stringify({ source, idempotency_key: createIdempotencyKey('outcome'), provenance: 'direct_user', confidence: 'high', ...value }),
  }),
}
