<template>
  <div class="agent-panel">
    <div class="agent-panel__header">
      <div class="d-flex align-center">
        <v-avatar color="primary" size="42" class="mr-3 agent-avatar">
          <v-icon icon="mdi-creation-outline" color="white" />
        </v-avatar>
        <div>
          <div class="text-subtitle-1 font-weight-bold">IBuddy Agent</div>
          <div class="agent-status"><span /> 随时协助你的任务规划</div>
        </div>
      </div>
      <v-btn icon="mdi-close" variant="text" size="small" aria-label="关闭 Agent" @click="$emit('close')" />
    </div>

    <div ref="messageContainer" class="agent-panel__messages scroll-container">
      <div v-if="messages.length === 0" class="agent-welcome">
        <div class="agent-welcome__icon"><v-icon icon="mdi-message-processing-outline" size="30" /></div>
        <div class="text-subtitle-1 font-weight-bold mt-4">需要我帮你安排什么？</div>
        <div class="text-caption text-medium-emphasis text-center mt-1">拆解任务、检查截止日期，或一起规划今天。</div>
        <button v-for="suggestion in suggestions" :key="suggestion" type="button" @click="useSuggestion(suggestion)">
          {{ suggestion }}
        </button>
      </div>

      <div v-for="(message, index) in messages" :key="index" class="agent-message" :class="`agent-message--${message.role}`">
        <v-avatar v-if="message.role === 'assistant'" color="primary" size="28">
          <v-icon icon="mdi-creation-outline" color="white" size="15" />
        </v-avatar>
        <div class="agent-bubble" :class="{ 'agent-bubble--md': message.role === 'assistant' }">
          <!-- 流式中且无内容：打字动画 -->
          <div v-if="message.streaming && !message.content" class="typing-dots"><i /><i /><i /></div>
          <!-- 用户消息：纯文本 -->
          <div v-else-if="message.role === 'user'" class="agent-text">{{ message.content }}</div>
          <!-- AI 消息：Markdown + LaTeX 实时渲染（key 切换强制结束重渲染） -->
          <div v-else class="agent-md"
            :key="'md-' + index + '-' + (message.streaming ? 1 : 0)"
            v-html="renderMarkdown(message.content)" />
        </div>
      </div>
    </div>

    <div class="agent-panel__composer">
      <v-textarea
        v-model="input"
        placeholder="输入问题或任务…"
        rows="1"
        auto-grow
        max-rows="5"
        variant="solo-filled"
        flat
        hide-details
        :disabled="loading"
        @keydown.enter.exact.prevent="sendMessage"
      />
      <v-btn
        :icon="loading ? 'mdi-stop' : 'mdi-arrow-up'"
        :color="loading ? 'grey' : 'primary'"
        variant="flat"
        :disabled="!loading && !input.trim()"
        @click="loading ? stopGeneration() : sendMessage()"
      />
    </div>
    <div class="agent-panel__note">Agent 可能会出错，请核对重要日期与内容。</div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { useAuth } from '@/stores/auth'
import MarkdownIt from 'markdown-it'
import katex from 'katex'
import 'katex/dist/katex.min.css'

// 开启 html 允许 KaTeX 生成的 HTML 嵌入
const md = new MarkdownIt({ html: true, breaks: true, linkify: true })

/** 将 LaTeX 公式渲染为 KaTeX HTML */
function renderMath(text) {
  // 块级 $$...$$
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (m, tex) => {
    try { return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }) } catch { return m }
  })
  // 块级 \[...\]
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (m, tex) => {
    try { return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }) } catch { return m }
  })
  // 行内 \(...\)
  text = text.replace(/\\\(([\s\S]+?)\\\)/g, (m, tex) => {
    try { return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }) } catch { return m }
  })
  // 行内 $...$
  text = text.replace(/(?<!\\)\$([^$\n]+?)\$/g, (m, tex) => {
    try { return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }) } catch { return m }
  })
  return text
}

/** Markdown + LaTeX 渲染（剥离末尾 JSON 任务块） */
function renderMarkdown(text) {
  try {
    const clean = text.replace(/```json[\s\S]*?```\s*$/, '').trim()
    return md.render(renderMath(clean || text))
  } catch {
    return text
  }
}

defineEmits(['close'])

const { token } = useAuth()
const messages = ref([])
const input = ref('')
const loading = ref(false)
const messageContainer = ref(null)
let controller = null

const suggestions = [
  '帮我看看本周最紧急的任务',
  '把我的 IA 拆成今天能做的步骤',
  '帮我安排一个两小时的专注时段',
]

function headers(extra = {}) {
  return {
    ...extra,
    ...(token.value ? { Authorization: `Bearer ${token.value}` } : {}),
  }
}

async function scrollToBottom() {
  await nextTick()
  if (messageContainer.value) messageContainer.value.scrollTop = messageContainer.value.scrollHeight
}

function useSuggestion(value) {
  input.value = value
  sendMessage()
}

async function sendMessage() {
  const content = input.value.trim()
  if (!content || loading.value) return

  messages.value.push({ role: 'user', content })
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  const responseIndex = messages.value.length - 1
  input.value = ''
  loading.value = true
  await scrollToBottom()

  try {
    controller = new AbortController()
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ content }),
      signal: controller.signal,
    })
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6)
        if (!payload || payload === '[DONE]') continue
        try {
          const parsed = JSON.parse(payload)
          messages.value[responseIndex].content += typeof parsed === 'string' ? parsed : (parsed.error || '')
        } catch {
          messages.value[responseIndex].content += payload
        }
      }
      await scrollToBottom()
    }
  } catch (error) {
    if (error.name !== 'AbortError') messages.value[responseIndex].content = '暂时无法连接 Agent，请稍后再试。'
  } finally {
    // 用新对象替换，强制 Vue 重新渲染 v-html（修复流式结束后 markdown 不重渲染）
    const old = messages.value[responseIndex]
    messages.value[responseIndex] = { ...old, streaming: false }
    loading.value = false
    controller = null
    await scrollToBottom()
  }
}

function stopGeneration() {
  controller?.abort()
  loading.value = false
}

async function loadHistory() {
  try {
    const response = await fetch('/api/chat/history', { headers: headers() })
    if (!response.ok) return
    const data = await response.json()
    messages.value = (data.messages || []).map((item) => ({ role: item.role, content: item.content }))
    await scrollToBottom()
  } catch {
    messages.value = []
  }
}

onMounted(loadHistory)
</script>

<style scoped>
.agent-panel { height: 100%; display: flex; flex-direction: column; background: #fff; }
.agent-panel__header { display: flex; align-items: center; justify-content: space-between; padding: 20px; border-bottom: 1px solid #edf0f6; }
.agent-avatar { box-shadow: 0 8px 18px rgba(50, 101, 245, .25); }
.agent-status { display: flex; align-items: center; gap: 5px; margin-top: 2px; color: #8b95a8; font-size: 11px; }
.agent-status span { width: 6px; height: 6px; border-radius: 50%; background: #2bb978; box-shadow: 0 0 0 3px rgba(43,185,120,.12); }
.agent-panel__messages { flex: 1; min-height: 0; overflow-y: auto; padding: 22px 18px; background: linear-gradient(180deg, #fafbfe 0, #fff 35%); }
.agent-welcome { min-height: 360px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.agent-welcome__icon { width: 62px; height: 62px; display: grid; place-items: center; border-radius: 20px; background: #eef2ff; color: #4169e8; }
.agent-welcome button { width: 100%; margin-top: 10px; padding: 11px 13px; border: 1px solid #e5e9f2; border-radius: 12px; color: #46516a; background: white; text-align: left; cursor: pointer; font-size: 12px; transition: border .15s, background .15s; }
.agent-welcome button:first-of-type { margin-top: 22px; }
.agent-welcome button:hover { border-color: #aab9f4; background: #f7f8ff; }
.agent-message { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 16px; }
.agent-message--user { justify-content: flex-end; }
.agent-bubble { max-width: 84%; padding: 11px 13px; border-radius: 5px 15px 15px 15px; background: #f0f2f7; color: #28334b; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.55; }
.agent-message--user .agent-bubble { border-radius: 15px 15px 5px 15px; color: #fff; background: #315fdf; }
.agent-bubble--md { max-width: 92%; background: transparent; padding: 0; }
.agent-text { white-space: pre-wrap; word-break: break-word; }
.agent-md { padding: 11px 13px; border-radius: 5px 15px 15px 15px; background: #f0f2f7; color: #28334b; word-break: break-word; font-size: 13px; line-height: 1.55; }
.agent-md :deep(p) { margin-bottom: 6px; }
.agent-md :deep(p:last-child) { margin-bottom: 0; }
.agent-md :deep(h1), .agent-md :deep(h2), .agent-md :deep(h3), .agent-md :deep(h4) { margin: 10px 0 6px; font-weight: 700; }
.agent-md :deep(h1) { font-size: 17px; } .agent-md :deep(h2) { font-size: 15px; } .agent-md :deep(h3) { font-size: 14px; }
.agent-md :deep(ul), .agent-md :deep(ol) { padding-left: 18px; margin: 4px 0; }
.agent-md :deep(li) { margin: 2px 0; }
.agent-md :deep(code) { background: #e8eaf2; padding: 1px 5px; border-radius: 4px; font-size: .88em; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.agent-md :deep(pre) { background: #1e2430; color: #e6e9f0; padding: 10px 12px; border-radius: 8px; overflow-x: auto; margin: 6px 0; }
.agent-md :deep(pre code) { background: transparent; color: inherit; padding: 0; }
.agent-md :deep(blockquote) { border-left: 3px solid #b9c4e8; margin: 6px 0; padding: 2px 10px; color: #5a6480; background: #f7f8fc; }
.agent-md :deep(table) { border-collapse: collapse; margin: 6px 0; width: 100%; font-size: 12px; }
.agent-md :deep(th), .agent-md :deep(td) { border: 1px solid #d8dde8; padding: 5px 8px; text-align: left; }
.agent-md :deep(th) { background: #eef1f8; font-weight: 600; }
.agent-md :deep(tr:nth-child(even) td) { background: #f8f9fc; }
.agent-md :deep(a) { color: #315fdf; }
.agent-md :deep(.katex) { font-size: 1.05em; }
.agent-panel__composer { display: flex; align-items: flex-end; gap: 10px; margin: 12px 14px 6px; padding: 8px; border: 1px solid #dfe4ee; border-radius: 18px; background: #f8f9fc; }
.agent-panel__note { padding: 0 20px 12px; color: #a0a7b5; text-align: center; font-size: 10px; }
.typing-dots { display: flex; gap: 4px; padding: 4px 2px; }
.typing-dots i { width: 6px; height: 6px; border-radius: 50%; background: #8590a6; animation: dotPulse 1s infinite alternate; }
.typing-dots i:nth-child(2) { animation-delay: .2s; }
.typing-dots i:nth-child(3) { animation-delay: .4s; }
@keyframes dotPulse { to { opacity: .25; transform: translateY(-2px); } }
</style>
