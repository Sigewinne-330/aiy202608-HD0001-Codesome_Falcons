import { ref, computed } from 'vue'

const TOKEN_KEY = 'ib_auth_token'
const USER_KEY = 'ib_auth_user'

// ---- 全局响应式状态（非 Pinia，纯 Composition API） ----
const token = ref(localStorage.getItem(TOKEN_KEY) || '')
const user = ref(loadUser())

function loadUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

const isAuthenticated = computed(() => !!token.value)

// ---- API 请求封装 ----
export async function authFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (token.value) headers.Authorization = `Bearer ${token.value}`
  return fetch(path, { ...options, headers })
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  const res = await authFetch(path, { ...options, headers })

  // 先拿文本，再尝试解析 JSON，避免空响应 / 非 JSON 响应直接抛错
  const text = await res.text()
  let data
  try {
    data = JSON.parse(text)
  } catch {
    // 响应体不是有效 JSON（比如后端挂了返回空白或 HTML）
    throw new Error(text || `服务器异常 (HTTP ${res.status})，请检查后端是否已启动`)
  }

  if (!res.ok) throw new Error(data.detail || `请求失败 (HTTP ${res.status})`)
  return data
}

// ---- 认证方法 ----
export function useAuth() {
  /** 注册 */
  async function register(username, email, password) {
    const data = await api('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password }),
    })
    saveSession(data)
    return data
  }

  /** 登录 */
  async function login(email, password) {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    saveSession(data)
    return data
  }

  /** 退出登录 */
  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  /** 应用启动时恢复会话 */
  async function restoreSession() {
    if (!token.value) return false
    try {
      const u = await api('/api/auth/me')
      user.value = u
      localStorage.setItem(USER_KEY, JSON.stringify(u))
      return true
    } catch {
      logout()
      return false
    }
  }

  // ---- 内部 ----
  function saveSession(data) {
    token.value = data.access_token
    user.value = data.user
    localStorage.setItem(TOKEN_KEY, data.access_token)
    localStorage.setItem(USER_KEY, JSON.stringify(data.user))
  }

  return {
    token,
    user,
    isAuthenticated,
    register,
    login,
    logout,
    restoreSession,
  }
}
