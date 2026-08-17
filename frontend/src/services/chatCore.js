export function extractTaskPayload(content) {
  try {
    const match = String(content || '').match(/```json\s*([\s\S]*?)\s*```\s*$/)
    if (!match) return null
    const data = JSON.parse(match[1])
    return data?.title && Array.isArray(data.subtasks) ? data : null
  } catch {
    return null
  }
}

export function estimateTokens(text) {
  if (!text) return 0
  let cjk = 0
  let other = 0
  for (const character of text) {
    if (/[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/.test(character)) cjk += 1
    else other += 1
  }
  return Math.max(1, Math.round(cjk + other / 4))
}

export function tokensToCredits(tokens) {
  if (!tokens || tokens <= 0) return 0
  return Math.max(1, Math.ceil(tokens / 1000))
}

export function creditLabel(message) {
  if (!message?.credits) return ''
  return `${message.creditsIsEstimate ? '≈ ' : ''}${message.credits.toLocaleString()}`
}

export async function responseErrorMessage(response, fallback) {
  const text = await response.text().catch(() => '')
  if (!text) return fallback || `HTTP ${response.status}`
  try {
    const payload = JSON.parse(text)
    if (typeof payload?.detail === 'string') return payload.detail
    if (Array.isArray(payload?.detail)) {
      return payload.detail.map((item) => item?.msg).filter(Boolean).join('; ') || fallback
    }
  } catch {
    // A text response is still useful to the caller.
  }
  return text || fallback || `HTTP ${response.status}`
}

export async function consumeChatStream(response, handlers = {}) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const handleData = (payload) => {
    if (!payload || payload === '[DONE]') return
    try {
      const parsed = JSON.parse(payload)
      if (parsed && typeof parsed === 'object' && parsed.done) {
        handlers.onUsage?.(parsed)
      } else if (typeof parsed === 'string') {
        handlers.onChunk?.(parsed)
      } else if (parsed?.error) {
        handlers.onError?.(String(parsed.error))
      }
    } catch {
      if (payload.startsWith('[ERROR]')) handlers.onError?.(payload.slice(7).trim())
      else handlers.onChunk?.(payload)
    }
  }

  const flushLines = (final = false) => {
    const lines = buffer.split(/\r?\n/)
    const tail = lines.pop() || ''
    buffer = final ? '' : tail
    for (const line of lines) {
      if (line.startsWith('data:')) handleData(line.slice(5).trimStart())
    }
    if (final && tail.startsWith('data:')) handleData(tail.slice(5).trimStart())
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    flushLines()
  }
  buffer += decoder.decode()
  flushLines(true)
}
