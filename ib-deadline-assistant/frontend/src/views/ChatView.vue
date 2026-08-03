<template>
  <div class="d-flex" style="height: calc(100vh - 48px);">
    <!-- 对话列表侧栏 -->
    <v-navigation-drawer permanent width="260" class="conversation-drawer">
      <div class="pa-3">
        <v-btn color="primary" block prepend-icon="mdi-plus" @click="newConversation" :disabled="loading">
          {{ $t('chat.newConversation') }}
        </v-btn>
      </div>

      <div class="px-2 pb-2 conversation-list">
        <v-list nav density="comfortable">
          <v-list-item
            v-for="conv in conversations"
            :key="conv.id"
            :active="conv.id === activeConversationId"
            class="conversation-item"
            rounded="lg"
            @click="switchConversation(conv.id)"
          >
            <template v-slot:prepend>
              <v-icon size="16" color="primary" class="mr-2">mdi-message-outline</v-icon>
            </template>
            <v-list-item-title class="text-caption conversation-title">
              {{ conv.title || $t('chat.newConversationTip') }}
            </v-list-item-title>
            <v-list-item-subtitle class="text-caption text-grey">
              {{ formatConvTime(conv.update_time) }}
            </v-list-item-subtitle>
            <template v-slot:append>
              <v-btn
                icon="mdi-close"
                size="x-small"
                variant="text"
                class="conversation-delete"
                @click.stop="deleteConversation(conv.id)"
              />
            </template>
          </v-list-item>
        </v-list>
        <div v-if="conversations.length === 0" class="text-center text-caption text-grey py-6">
          {{ $t('chat.noConversation') }}
        </div>
      </div>
    </v-navigation-drawer>

    <!-- 聊天主区域 -->
    <div class="d-flex flex-column flex-grow-1" style="min-width: 0;">
      <!-- 顶部 -->
      <div class="d-flex align-center mb-4">
        <v-icon size="28" color="primary" class="mr-2">mdi-robot-outline</v-icon>
        <div>
          <div class="text-h6 font-weight-bold">{{ $t('chat.title') }}</div>
          <div class="text-caption text-grey">{{ $t('chat.subtitle') }}</div>
        </div>
        <v-spacer />
        <v-btn variant="tonal" color="grey" size="small" prepend-icon="mdi-delete-outline" @click="clearHistory" :disabled="!activeConversationId">
          {{ $t('chat.clear') }}
        </v-btn>
      </div>

      <!-- 消息区域 -->
      <v-sheet class="flex-grow-1 scroll-container pa-4 mb-4" rounded="lg" elevation="0" border style="min-height: 0; overflow-y: auto;">
        <div v-if="messages.length === 0" class="d-flex flex-column align-center justify-center" style="height: 100%;">
          <v-icon size="80" color="grey-lighten-1" class="mb-4">mdi-robot-outline</v-icon>
          <div class="text-h6 text-grey-darken-1 mb-2">{{ $t('chat.hello') }}</div>
          <div class="text-body-2 text-grey text-center" style="max-width: 400px;">
            {{ $t('chat.intro') }}
          </div>
          <div class="mt-4 d-flex gap-2 flex-wrap justify-center">
            <v-chip v-for="s in suggestions" :key="s" size="small" color="primary" variant="outlined"
              class="cursor-pointer" @click="sendSuggestion(s)">
              {{ $t(s) }}
            </v-chip>
          </div>
        </div>

        <div v-else>
          <div v-for="(msg, i) in messages" :key="i" class="mb-3">
            <!-- 用户消息 -->
            <div v-if="msg.role === 'user'" class="d-flex justify-end mb-2">
              <div class="user-message pa-3">
                <div class="text-body-2" v-text="msg.content" />
              </div>
            </div>
            <!-- AI 消息 -->
            <div v-else class="d-flex align-start gap-2">
              <v-avatar size="32" color="primary" class="mt-1">
                <v-icon size="18" color="white">mdi-robot</v-icon>
              </v-avatar>
              <div class="assistant-message-wrapper" style="max-width: 92%;">
                <div class="assistant-message pa-3">
                  <!-- 流式传输中：空内容 loading -->
                  <div v-if="msg.streaming && !msg.content" class="d-flex align-center">
                    <v-progress-circular indeterminate size="16" width="2" color="primary" />
                    <span class="text-caption text-grey ml-2">{{ $t('chat.thinking') }}</span>
                  </div>
                  <!-- 有内容时始终用 Markdown 渲染 -->
                  <div v-else class="text-body-2 message-content"
                    :key="'md-' + i + '-' + (msg.streaming ? 1 : 0)"
                    v-html="renderMarkdown(msg.content)" />
                </div>
                <!-- 每条 AI 回复的 token 统计：流式中实时估算增长，结束后显示 API 真实值 -->
                <div v-if="msg.role === 'assistant' && msg.token" class="d-flex align-center justify-end pa-2 text-caption text-grey" style="border-top: 1px solid #E0E0E0;">
                  <v-icon size="13" class="mr-1">mdi-lightning-bolt-outline</v-icon>
                  {{ tokenLabel(msg) }} tokens
                </div>
                <!-- 提取到任务 JSON 时显示操作按钮 -->
                <div v-if="!msg.streaming && msg.taskData" class="d-flex align-center pa-2" style="border-top: 1px solid #E0E0E0;">
                  <v-icon size="18" color="primary" class="mr-1">mdi-clipboard-list-outline</v-icon>
                  <span class="text-caption mr-2">
                    {{ $t('chat.subtaskCount', { n: msg.taskData.subtasks?.length || 0 }) }}
                  </span>
                  <v-spacer />
                  <v-btn
                    v-if="!msg.taskSaved"
                    size="x-small"
                    color="primary"
                    variant="tonal"
                    prepend-icon="mdi-plus"
                    :loading="msg.saving"
                    @click="saveTaskFromChat(i)"
                  >
                    {{ $t('chat.addToTasks') }}
                  </v-btn>
                  <v-chip v-else size="x-small" color="success" variant="tonal" prepend-icon="mdi-check">
                    {{ $t('chat.added') }}
                  </v-chip>
                </div>
              </div>
            </div>
          </div>
        </div>
      </v-sheet>

      <!-- 输入区域 -->
      <v-card flat rounded="lg" border style="flex-shrink: 0;">
        <v-card-text class="pa-4">
          <div class="d-flex align-end gap-3">
            <v-textarea
              v-model="input"
              :placeholder="$t('chat.placeholder')"
              rows="3"
              auto-grow
              hide-details
              variant="solo"
              class="flex-grow-1"
              @keydown.enter.exact.prevent="sendMessage"
              :disabled="loading"
            />
            <v-btn
              :icon="loading ? 'mdi-stop' : 'mdi-send'"
              :color="loading ? 'grey' : 'primary'"
              size="40"
              variant="flat"
              @click="loading ? stopGeneration() : sendMessage()"
              :disabled="!input.trim() && !loading"
            />
          </div>
        </v-card-text>
      </v-card>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import MarkdownIt from 'markdown-it'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { authFetch } from '@/stores/auth'

const { t } = useI18n()

// 开启 html，允许 KaTeX 生成的 HTML 直接嵌入
const md = new MarkdownIt({ html: true, breaks: true, linkify: true })

/** 将 LaTeX 公式渲染为 KaTeX HTML */
function renderMath(text) {
  // 块级公式 $$...$$
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (m, tex) => {
    try {
      return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false })
    } catch {
      return m
    }
  })
  // 块级公式 \[...\]
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (m, tex) => {
    try {
      return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false })
    } catch {
      return m
    }
  })
  // 行内公式 \(...\)
  text = text.replace(/\\\(([\s\S]+?)\\\)/g, (m, tex) => {
    try {
      return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false })
    } catch {
      return m
    }
  })
  // 行内公式 $...$（单个 $，避免误伤）
  text = text.replace(/(?<!\\)\$([^$\n]+?)\$/g, (m, tex) => {
    try {
      return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false })
    } catch {
      return m
    }
  })
  return text
}

const messages = ref([])
const input = ref('')
const loading = ref(false)
let abortController = null

// ---- 对话窗口管理 ----
const conversations = ref([])
const activeConversationId = ref(null)

const suggestions = [
  'chat.suggestion1',
  'chat.suggestion2',
  'chat.suggestion3',
  'chat.suggestion4',
]

const API_BASE = '/api'

function formatConvTime(value) {
  if (!value) return ''
  const d = new Date(value)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return `${t('chat.todayPrefix')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  return t('common.monthDay', { month: d.getMonth() + 1, day: d.getDate() })
}

async function loadConversations() {
  try {
    const res = await authFetch(`${API_BASE}/chat/conversations`)
    if (!res.ok) return
    const data = await res.json()
    conversations.value = data.conversations || []
  } catch { /* ignore */ }
}

/** 新建对话：清空消息区，下次发送时后端自动创建 conversation */
function newConversation() {
  if (loading.value) return
  activeConversationId.value = null
  messages.value = []
}

/** 切换对话：加载该对话的历史消息 */
async function switchConversation(convId) {
  if (loading.value) return
  activeConversationId.value = convId
  messages.value = []
  await loadHistory(convId)
}

/** 删除对话 */
async function deleteConversation(convId) {
  try {
    await authFetch(`${API_BASE}/chat/conversations/${convId}`, { method: 'DELETE' })
    conversations.value = conversations.value.filter(c => c.id !== convId)
    if (activeConversationId.value === convId) {
      activeConversationId.value = null
      messages.value = []
    }
  } catch { /* ignore */ }
}

// ---- Markdown / JSON 处理 ----

function renderMarkdown(text) {
  try {
    // 去掉末尾的 JSON 代码块
    const clean = text.replace(/```json[\s\S]*?```\s*$/, '').trim()
    // 先渲染 LaTeX 公式，再交给 markdown-it
    return md.render(renderMath(clean || text))
  } catch {
    return text
  }
}

/** 从 AI 回复中提取任务 JSON */
function extractTaskJson(content) {
  try {
    const match = content.match(/```json\s*([\s\S]*?)\s*```\s*$/)
    if (!match) return null
    const data = JSON.parse(match[1])
    // 验证必要字段
    if (!data.title || !Array.isArray(data.subtasks)) return null
    return data
  } catch {
    return null
  }
}

/** 流式中实时估算 token：中文 1 字 ≈ 1 token，其他字符 ≈ 4 字/token（结束时会用 API 真实值替换） */
function estimateTokens(text) {
  if (!text) return 0
  let cjk = 0
  let other = 0
  for (const ch of text) {
    if (/[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/.test(ch)) cjk++
    else other++
  }
  return Math.max(1, Math.round(cjk + other / 4))
}

/** 渲染 token 标签：流式中显示估算值（≈ 前缀），结束后显示 API 真实值 */
function tokenLabel(message) {
  if (!message || !message.token) return ''
  return (message.tokenIsEstimate ? '≈ ' : '') + message.token.toLocaleString()
}

// ---- 消息发送 / 流式 ----

async function sendMessage() {
  const content = input.value.trim()
  if (!content || loading.value) return

  messages.value.push({ role: 'user', content })
  input.value = ''
  loading.value = true

  // 插入一个空的 AI 消息占位，标记正在流式
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  const aiIndex = messages.value.length - 1

  scrollToBottom()

  // 滚动节流：最多 60fps
  let scrollPending = false
  function scheduleScroll() {
    if (!scrollPending) {
      scrollPending = true
      requestAnimationFrame(() => {
        scrollToBottom()
        scrollPending = false
      })
    }
  }

  try {
    abortController = new AbortController()
    const res = await authFetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, conversation_id: activeConversationId.value }),
      signal: abortController.signal,
    })

    // 余额不足：给出明确提示（特殊错误码，catch 里不覆盖该文案）
    if (res.status === 402) {
      messages.value[aiIndex].content = t('billing.insufficient')
      throw new Error('INSUFFICIENT_BALANCE')
    }

    if (!res.ok || !res.body) {
      const errText = await res.text()
      let detail = errText
      try { detail = JSON.parse(errText).detail || errText } catch { /* ignore */ }
      throw new Error(typeof detail === 'string' ? detail : t('chat.requestFailed'))
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const data = line.slice(6)
        if (data === '[DONE]') continue
        // 新格式：JSON 编码（chunk 内换行被转义，SSE 帧不再被破坏）
        try {
          const parsed = JSON.parse(data)
          if (parsed && typeof parsed === 'object' && parsed.done) {
            // 流式结束事件：API 真实值替换估算值
            if (parsed.tokens) {
              messages.value[aiIndex].token = parsed.tokens
              messages.value[aiIndex].tokenIsEstimate = false
            }
            continue
          }
          if (typeof parsed === 'string') {
            messages.value[aiIndex].content += parsed
          } else if (parsed && parsed.error) {
            messages.value[aiIndex].content = t('chat.errorPrefix') + parsed.error
          }
          // 实时估算 token，让数字随生成过程增长（结束时用 API 真实值替换）
          messages.value[aiIndex].token = estimateTokens(messages.value[aiIndex].content)
          messages.value[aiIndex].tokenIsEstimate = true
        } catch {
          // 兼容旧格式：[ERROR] 前缀或裸文本
          if (data.startsWith('[ERROR]')) {
            messages.value[aiIndex].content = t('chat.errorPrefix') + data.slice(8)
          } else {
            messages.value[aiIndex].content += data
          }
          messages.value[aiIndex].token = estimateTokens(messages.value[aiIndex].content)
          messages.value[aiIndex].tokenIsEstimate = true
        }
        scheduleScroll()
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError' && e.message !== 'INSUFFICIENT_BALANCE') {
      messages.value[aiIndex].content = t('chat.networkError') + (e.message || t('chat.saveFailedBackend'))
    }
  } finally {
    // 用新对象替换，强制 Vue 重新渲染 v-html
    const old = messages.value[aiIndex]
    messages.value[aiIndex] = { ...old, streaming: false }
    loading.value = false
    abortController = null

    // 尝试提取任务 JSON
    const taskData = extractTaskJson(messages.value[aiIndex].content)
    if (taskData) {
      messages.value[aiIndex].taskData = taskData
      messages.value[aiIndex].taskSaved = false
    }

    // 刷新对话列表（新对话会出现在列表里，并自动选中它）
    const wasNew = !activeConversationId.value
    await loadConversations()
    if (wasNew && conversations.value.length > 0) {
      activeConversationId.value = conversations.value[0].id
    }

    scrollToBottom()
  }
}

// ---- 保存任务到 MySQL ----

async function saveTaskFromChat(index) {
  const msg = messages.value[index]
  if (!msg.taskData || msg.saving) return

  msg.saving = true
  try {
    const res = await authFetch(`${API_BASE}/chat/save-tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(msg.taskData),
    })
    const result = await res.json()
    if (result.ok) {
      msg.taskSaved = true
      msg.savedInfo = result
    } else {
      alert(t('chat.saveFailed'))
    }
  } catch {
    alert(t('chat.saveFailedBackend'))
  } finally {
    msg.saving = false
  }
}

// ---- 其他操作 ----

function sendSuggestion(text) {
  input.value = t(text)
  sendMessage()
}

function stopGeneration() {
  if (abortController) {
    abortController.abort()
    loading.value = false
    // 将最后一个 streaming 消息标记为完成，触发 markdown 渲染
    const last = messages.value[messages.value.length - 1]
    if (last && last.streaming) {
      last.streaming = false
    }
  }
}

async function loadHistory(convId) {
  if (!convId) return
  try {
    const res = await authFetch(`${API_BASE}/chat/history?conversation_id=${convId}`)
    if (!res.ok) return
    const data = await res.json()
    messages.value = (data.messages || []).map(m => ({ role: m.role, content: m.content, token: m.token || 0 }))
    scrollToBottom()
  } catch {
    // 忽略加载失败
  }
}

async function clearHistory() {
  if (!activeConversationId.value) return
  try {
    await authFetch(`${API_BASE}/chat/history?conversation_id=${activeConversationId.value}`, { method: 'DELETE' })
  } catch { /* ignore */ }
  messages.value = []
}

async function scrollToBottom() {
  await nextTick()
  const container = document.querySelector('.scroll-container')
  if (container) {
    container.scrollTop = container.scrollHeight
  }
}

onMounted(async () => {
  await loadConversations()
  // 默认选中最近一个对话；没有对话则保持空（发消息时自动新建）
  if (conversations.value.length > 0) {
    activeConversationId.value = conversations.value[0].id
    await loadHistory(activeConversationId.value)
  }
})
</script>

<style scoped>
.conversation-drawer {
  background: #FAFBFF;
  border-right: 1px solid #EDF0F6;
}
.conversation-list {
  overflow-y: auto;
  height: calc(100% - 76px);
}
.conversation-item {
  margin-bottom: 2px;
}
.conversation-item:hover .conversation-delete {
  opacity: 1;
}
.conversation-delete {
  opacity: 0;
  transition: opacity .15s;
}
.conversation-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-message {
  background: #1565C0;
  color: white;
  border-radius: 16px 16px 4px 16px;
  max-width: 85%;
  word-break: break-word;
}

.assistant-message {
  background: #F3F4F6;
  border-radius: 4px 16px 16px 16px;
  word-break: break-word;
}

.message-content :deep(p) {
  margin-bottom: 4px;
}
.message-content :deep(p:last-child) {
  margin-bottom: 0;
}
.message-content :deep(code) {
  background: #E8E8E8;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.85em;
}
.message-content :deep(pre) {
  background: #2D2D2D;
  color: #E0E0E0;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
}
.message-content :deep(pre code) {
  background: transparent;
  color: inherit;
}

.gap-2 { gap: 8px; }
.gap-3 { gap: 12px; }
.cursor-pointer { cursor: pointer; }
</style>
