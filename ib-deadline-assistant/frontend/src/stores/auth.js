import { ref, computed } from 'vue'

const TOKEN_KEY = 'ib_auth_token'
const USER_KEY = 'ib_auth_user'

export const API_ERROR_KIND = Object.freeze({
  TRANSPORT: 'transport',
  HTTP: 'http',
  PROTOCOL: 'protocol',
})

export class ApiError extends Error {
  constructor(message, { kind, status = null, cause } = {}) {
    super(message, cause ? { cause } : undefined)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
  }
}

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

export async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  let res
  try {
    res = await authFetch(path, { ...options, headers })
  } catch (cause) {
    throw new ApiError('无法连接服务器，请确认后端服务已启动后重试', {
      kind: API_ERROR_KIND.TRANSPORT,
      cause,
    })
  }

  // 先拿文本，再尝试解析 JSON，避免空响应 / 非 JSON 响应直接抛错
  const text = await res.text()
  let data
  try {
    data = JSON.parse(text)
  } catch {
    // 响应体不是有效 JSON（比如后端挂了返回空白或 HTML）
    throw new ApiError(text || `服务器响应异常 (HTTP ${res.status})`, {
      kind: API_ERROR_KIND.PROTOCOL,
      status: res.status,
    })
  }

  if (!res.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg || '输入信息有误').join('；')
      : data.detail
    throw new ApiError(detail || `请求失败 (HTTP ${res.status})`, {
      kind: API_ERROR_KIND.HTTP,
      status: res.status,
    })
  }
  return data
}

// ---- 认证方法 ----
export function useAuth() {
  /** 请求注册验证码 */
  async function requestVerificationCode(email) {
    return api('/api/auth/verification-codes', {
      method: 'POST',
      body: JSON.stringify({ email }),
    })
  }

  async function verifyEmailCode(email, code) {
    return api('/api/auth/verification-codes/verify', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    })
  }

  /** 注册 */
  async function register(username, email, password, verificationToken) {
    const data = await api('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        username,
        email,
        password,
        verification_token: verificationToken,
      }),
    })
    saveSession(data)
    return data
  }

  /** 登录：支持用户名或邮箱 */
  async function login(username, password) {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
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
    requestVerificationCode,
    verifyEmailCode,
    register,
    login,
    logout,
    restoreSession,
  }
}
