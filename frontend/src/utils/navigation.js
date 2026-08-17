export function safeInternalRedirect(value, fallback = '/calendar') {
  const target = Array.isArray(value) ? value[0] : value
  if (typeof target !== 'string') return fallback
  if (!target.startsWith('/') || target.startsWith('//') || target.startsWith('/login')) return fallback
  return target
}
