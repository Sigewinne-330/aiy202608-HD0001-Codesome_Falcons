import { api, ApiError } from '@/stores/auth'

/**
 * 提醒中心 API 封装。
 * 只消费后端已有接口，不做任何路由操作；
 * 调用方负责捕获 ApiError（含 status === 401 的登录失效处理）。
 */
export { ApiError }

/** GET /api/reminders/preferences */
export function getPreferences() {
  return api('/api/reminders/preferences')
}

/** PUT /api/reminders/preferences —— 只传实际变化的字段 */
export function updatePreferences(patch) {
  return api('/api/reminders/preferences', {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
}

/** GET /api/reminder-role-cards */
export function listRoleCards() {
  return api('/api/reminder-role-cards')
}

/** GET /api/reminder-role-cards/{id} */
export function getRoleCard(id) {
  return api(`/api/reminder-role-cards/${id}`)
}

/** GET /api/reminders/history?limit=&offset= */
export function getHistory({ limit = 20, offset = 0 } = {}) {
  return api(`/api/reminders/history?limit=${limit}&offset=${offset}`)
}

/** POST /api/reminder-role-cards/import —— 当前用户私有角色卡导入 */
export function importRoleCard(card) {
  return api('/api/reminder-role-cards/import', {
    method: 'POST',
    body: JSON.stringify({ card }),
  })
}
