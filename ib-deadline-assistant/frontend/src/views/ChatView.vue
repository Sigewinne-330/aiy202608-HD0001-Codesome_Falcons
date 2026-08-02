<template>
  <div class="d-flex flex-column" style="height: calc(100vh - 48px);">
    <!-- 顶部 -->
    <div class="d-flex align-center mb-4">
      <v-icon size="28" color="primary" class="mr-2">mdi-robot-outline</v-icon>
      <div>
        <div class="text-h6 font-weight-bold">AI 助手</div>
        <div class="text-caption text-grey">随时帮你规划长期任务、拆解目标、管理进度</div>
      </div>
      <v-spacer />
      <v-btn variant="tonal" color="grey" size="small" prepend-icon="mdi-delete-outline" @click="clearHistory">
        清空对话
      </v-btn>
    </div>

    <!-- 消息区域 -->
    <v-sheet class="flex-grow-1 scroll-container pa-4 mb-4" rounded="lg" elevation="0" border style="min-height: 0; overflow-y: auto;">
      <div v-if="messages.length === 0" class="d-flex flex-column align-center justify-center" style="height: 100%;">
        <v-icon size="80" color="grey-lighten-1" class="mb-4">mdi-robot-outline</v-icon>
        <div class="text-h6 text-grey-darken-1 mb-2">你好！有什么可以帮你的？</div>
        <div class="text-body-2 text-grey text-center" style="max-width: 400px;">
          我是你的长期任务规划助手，可以帮你规划时间线、
          拆解大型任务、管理截止日期，或者给你执行建议
        </div>
        <div class="mt-4 d-flex gap-2 flex-wrap justify-center">
          <v-chip v-for="s in suggestions" :key="s" size="small" color="primary" variant="outlined"
            class="cursor-pointer" @click="sendSuggestion(s)">
            {{ s }}
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
            <div class="assistant-message pa-3">
              <div class="text-body-2 message-content" v-html="renderMarkdown(msg.content)" />
            </div>
          </div>
        </div>
        <!-- 加载动画 -->
        <div v-if="loading" class="d-flex align-start gap-2 mb-2">
          <v-avatar size="32" color="primary">
            <v-icon size="18" color="white">mdi-robot</v-icon>
          </v-avatar>
          <div class="assistant-message pa-3">
            <v-progress-circular indeterminate size="16" width="2" color="primary" />
            <span class="text-caption text-grey ml-2">思考中...</span>
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
            placeholder="输入你的问题，比如：帮我规划一个三个月的学习计划..."
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
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { marked } from 'marked'

const messages = ref([])
const input = ref('')
const loading = ref(false)
let abortController = null

const suggestions = [
  '帮我规划一个长期任务的时间线',
  '我这周有哪些 Deadline？',
  '如何高效拆解一个大型任务？',
  '任务执行各阶段应该注意什么？',
]

const API_BASE = '/api'

function renderMarkdown(text) {
  try {
    return marked.parse(text)
  } catch {
    return text
  }
}

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
    const res = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
      signal: abortController.signal,
    })

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
        if (data.startsWith('[ERROR]')) {
          messages.value[aiIndex].content = '出错了：' + data.slice(8)
          continue
        }
        messages.value[aiIndex].content += data
        scheduleScroll()
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') {
      messages.value[aiIndex].content = '网络请求失败，请检查后端是否启动。'
    }
  } finally {
    // 流式结束，切换到 markdown 渲染
    messages.value[aiIndex].streaming = false
    loading.value = false
    abortController = null
    scrollToBottom()
  }
}

function sendSuggestion(text) {
  input.value = text
  sendMessage()
}

function stopGeneration() {
  if (abortController) {
    abortController.abort()
    loading.value = false
  }
}

async function loadHistory() {
  try {
    const res = await fetch(`${API_BASE}/chat/history`)
    const data = await res.json()
    if (data.messages) {
      messages.value = data.messages.map(m => ({ role: m.role, content: m.content }))
    }
  } catch {
    // 忽略加载失败
  }
}

async function clearHistory() {
  try {
    await fetch(`${API_BASE}/chat/history`, { method: 'DELETE' })
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

onMounted(() => {
  loadHistory()
})
</script>

<style scoped>
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
  max-width: 92%;
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
