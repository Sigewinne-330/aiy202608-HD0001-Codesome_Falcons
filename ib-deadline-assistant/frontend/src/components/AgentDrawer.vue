<template>
  <div class="agent-panel">
    <div class="agent-panel__header">
      <div class="d-flex align-center">
        <v-avatar color="primary" size="42" class="mr-3 agent-avatar">
          <v-icon icon="mdi-creation-outline" color="white" />
        </v-avatar>
        <div>
          <div class="text-subtitle-1 font-weight-bold">{{ $t('agent.title') }}</div>
          <div class="agent-status-line">
            <span class="agent-status"><span /> {{ $t('agent.status') }}</span>
            <span
              class="balance-pill"
              :class="{ 'balance-pill--low': balance < 1000 }"
              :title="$t('billing.balance')"
              @click="goBilling"
            >
              <v-icon icon="mdi-lightning-bolt" size="11" />
              {{ balance.toLocaleString() }} {{ $t('billing.creditsUnit') }}
            </span>
          </div>
        </div>
      </div>
      <div class="d-flex align-center">
        <!-- 对话列表菜单 -->
        <v-menu location="bottom end">
          <template v-slot:activator="{ props }">
            <v-btn
              icon="mdi-message-text-outline"
              variant="text"
              size="small"
              :aria-label="$t('agent.history')"
              :disabled="loading"
              v-bind="props"
            />
          </template>
          <v-list dense style="max-height: 320px; overflow-y: auto; min-width: 220px;">
            <v-list-subheader>{{ $t('agent.history') }}</v-list-subheader>
            <v-list-item
              v-for="conv in conversations"
              :key="conv.id"
              :active="conv.id === activeConversationId"
              density="compact"
              @click="switchConversation(conv.id)"
            >
              <template v-slot:prepend>
                <v-icon size="14" class="mr-2">mdi-message-outline</v-icon>
              </template>
              <v-list-item-title class="text-caption" style="max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                {{ conv.title || $t('agent.newConversation') }}
              </v-list-item-title>
              <template v-slot:append>
                <v-btn
                  icon="mdi-close"
                  size="x-small"
                  variant="text"
                  @click.stop="deleteConversation(conv.id)"
                />
              </template>
            </v-list-item>
            <div v-if="conversations.length === 0" class="text-center text-caption text-grey py-3">
              {{ $t('agent.noHistory') }}
            </div>
          </v-list>
        </v-menu>
        <!-- 新建对话 -->
        <v-btn
          icon="mdi-plus"
          variant="text"
          size="small"
          :aria-label="$t('agent.newConversation')"
          :disabled="loading"
          @click="newConversation"
        />
        <v-btn icon="mdi-close" variant="text" size="small" :aria-label="$t('agent.close')" @click="$emit('close')" />
      </div>
    </div>

    <div ref="messageContainer" class="agent-panel__messages scroll-container">
      <div v-if="messages.length === 0" class="agent-welcome">
        <div class="agent-welcome__icon"><v-icon icon="mdi-message-processing-outline" size="30" /></div>
        <div class="text-subtitle-1 font-weight-bold mt-4">{{ $t('agent.welcomeTitle') }}</div>
        <div class="text-caption text-medium-emphasis text-center mt-1">{{ $t('agent.welcomeSub') }}</div>
        <button v-for="suggestion in suggestions" :key="suggestion" type="button" @click="useSuggestion(suggestion)">
          {{ $t(suggestion) }}
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
      <!-- 已选图片预览 -->
      <div v-if="selectedImages.length" class="image-preview-row">
        <div v-for="(img, idx) in selectedImages" :key="idx" class="image-preview-thumb">
          <img :src="img.dataUrl" alt="preview" />
          <button type="button" class="image-remove-btn" @click="removeImage(idx)" aria-label="移除图片">
            <v-icon icon="mdi-close" size="12" />
          </button>
        </div>
      </div>
      <div class="composer-row">
        <input
          ref="imageInput"
          type="file"
          accept="image/*"
          multiple
          style="display:none"
          @change="onImagesSelected"
        />
        <v-btn
          icon="mdi-image-outline"
          variant="text"
          size="small"
          :disabled="loading || selectedImages.length >= 5"
          :color="selectedImages.length ? 'deep-purple' : undefined"
          @click="$refs.imageInput.click()"
        />
        <v-textarea
          v-model="input"
          :placeholder="$t('agent.placeholder')"
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
    </div>
    <div class="agent-panel__note">{{ $t('agent.note') }}</div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuth } from '@/stores/auth'
import { notifyTasksChanged } from '@/services/taskSync'
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

const { t } = useI18n()
const { token } = useAuth()
const router = useRouter()
const messages = ref([])
const input = ref('')
const loading = ref(false)
const messageContainer = ref(null)
const activeConversationId = ref(null)
const conversations = ref([])
const selectedImages = ref([])  // [{ dataUrl, file }]
const imageInput = ref(null)
const balance = ref(0)
let controller = null

const suggestions = [
  'agent.suggestion1',
  'agent.suggestion2',
  'agent.suggestion3',
]

function headers(extra = {}) {
  return {
    ...extra,
    ...(token.value ? { Authorization: `Bearer ${token.value}` } : {}),
  }
}

/** 加载积分余额（头部显示） */
async function loadBalance() {
  try {
    const res = await fetch('/api/billing/summary', { headers: headers() })
    if (res.ok) {
      const data = await res.json()
      balance.value = data.balance || 0
    }
  } catch {
    /* ignore */
  }
}

/** 点击余额 → 跳转充值页 */
function goBilling() {
  router.push('/billing')
}

async function scrollToBottom() {
  await nextTick()
  if (messageContainer.value) messageContainer.value.scrollTop = messageContainer.value.scrollHeight
}

function useSuggestion(value) {
  input.value = t(value)
  sendMessage()
}

// ---- 对话窗口管理 ----

async function loadConversations() {
  try {
    const convRes = await fetch('/api/chat/conversations', { headers: headers() })
    if (convRes.ok) {
      const convData = await convRes.json()
      conversations.value = convData.conversations || []
    }
  } catch {
    conversations.value = []
  }
}

/** 新建对话：清空消息区，下次发送时自动创建 conversation */
function newConversation() {
  if (loading.value) return
  activeConversationId.value = null
  messages.value = []
  selectedImages.value = []
}

// ---- 图片上传 ----

function onImagesSelected(e) {
  const files = Array.from(e.target.files || [])
  const remaining = 5 - selectedImages.value.length
  if (remaining <= 0) return
  const toAdd = files.slice(0, remaining)
  toAdd.forEach(file => {
    const reader = new FileReader()
    reader.onload = (ev) => {
      selectedImages.value.push({ dataUrl: ev.target.result, file })
    }
    reader.readAsDataURL(file)
  })
  // 重置 input 以便重复选择同一文件
  if (imageInput.value) imageInput.value.value = ''
}

function removeImage(idx) {
  selectedImages.value.splice(idx, 1)
}

/** 切换对话：加载该对话的历史消息 */
async function switchConversation(convId) {
  if (loading.value) return
  activeConversationId.value = convId
  messages.value = []
  try {
    const response = await fetch(`/api/chat/history?conversation_id=${convId}`, { headers: headers() })
    if (response.ok) {
      const data = await response.json()
      messages.value = (data.messages || []).map((item) => ({ role: item.role, content: item.content }))
      await scrollToBottom()
    }
  } catch {
    messages.value = []
  }
}

/** 删除对话 */
async function deleteConversation(convId) {
  try {
    await fetch(`/api/chat/conversations/${convId}`, { method: 'DELETE', headers: headers() })
    conversations.value = conversations.value.filter(c => c.id !== convId)
    if (activeConversationId.value === convId) {
      activeConversationId.value = null
      messages.value = []
    }
  } catch { /* ignore */ }
}

async function sendMessage() {
  const content = input.value.trim()
  if (!content || loading.value) return

  messages.value.push({ role: 'user', content })
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  const responseIndex = messages.value.length - 1
  const images = selectedImages.value.map(img => img.dataUrl)
  input.value = ''
  selectedImages.value = []
  loading.value = true
  let taskMutationSucceeded = false
  await scrollToBottom()

  try {
    // 没有对话时先创建一个（避免每次发送都新建窗口）
    if (!activeConversationId.value) {
      const convRes = await fetch('/api/chat/conversations', {
        method: 'POST',
        headers: headers({ 'Content-Type': 'application/json' }),
      })
      if (convRes.ok) {
        const convData = await convRes.json()
        activeConversationId.value = convData.id
      }
    }
    controller = new AbortController()
    const body = { content, conversation_id: activeConversationId.value }
    if (images.length) body.images = images
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    // 余额不足：给出明确提示（特殊错误码，catch 里不覆盖该文案）
    if (response.status === 402) {
      messages.value[responseIndex].content = t('billing.insufficient')
      throw new Error('INSUFFICIENT_BALANCE')
    }
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
          const chunk = typeof parsed === 'string' ? parsed : (parsed.error || '')
          messages.value[responseIndex].content += chunk
          if (chunk.includes('✓ 操作成功')) taskMutationSucceeded = true
        } catch {
          messages.value[responseIndex].content += payload
          if (payload.includes('✓ 操作成功')) taskMutationSucceeded = true
        }
      }
      await scrollToBottom()
    }
  } catch (error) {
    if (error.name !== 'AbortError' && error.message !== 'INSUFFICIENT_BALANCE') {
      messages.value[responseIndex].content = t('agent.connectError')
    }
  } finally {
    // 用新对象替换，强制 Vue 重新渲染 v-html（修复流式结束后 markdown 不重渲染）
    const old = messages.value[responseIndex]
    messages.value[responseIndex] = { ...old, streaming: false }
    loading.value = false
    controller = null
    if (taskMutationSucceeded) notifyTasksChanged()
    // 刷新对话列表，让新对话出现在历史里
    await loadConversations()
    await loadBalance()  // 扣费后刷新余额
    await scrollToBottom()
  }
}

function stopGeneration() {
  controller?.abort()
  loading.value = false
}

async function loadHistory() {
  await loadConversations()
  // 自动选中最近一个对话；没有对话则保持空（发消息时自动新建）
  if (conversations.value.length > 0) {
    await switchConversation(conversations.value[0].id)
  } else {
    messages.value = []
  }
}

onMounted(() => {
  loadHistory()
  loadBalance()
})
</script>

<style scoped>
.agent-panel { height: 100%; display: flex; flex-direction: column; background: #fff; }
.agent-panel__header { display: flex; align-items: center; justify-content: space-between; padding: 20px; border-bottom: 1px solid #edf0f6; }
.agent-avatar { box-shadow: 0 8px 18px rgba(50, 101, 245, .25); }
.agent-status { display: flex; align-items: center; gap: 5px; margin-top: 2px; color: #8b95a8; font-size: 11px; }
.agent-status span { width: 6px; height: 6px; border-radius: 50%; background: #2bb978; box-shadow: 0 0 0 3px rgba(43,185,120,.12); }
.agent-status-line { display: flex; align-items: center; gap: 8px; }
.balance-pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-top: 2px;
  padding: 2px 8px;
  border-radius: 999px;
  color: #4169e8;
  background: #eef2ff;
  font-size: 10.5px;
  font-weight: 650;
  cursor: pointer;
  transition: background .15s;
}
.balance-pill:hover { background: #e2e9ff; }
.balance-pill--low { color: #d4552e; background: #fff0ea; }
.balance-pill--low:hover { background: #ffe6dc; }
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
.agent-panel__composer { display: flex; flex-direction: column; gap: 0; margin: 12px 14px 6px; padding: 8px; border: 1px solid #dfe4ee; border-radius: 18px; background: #f8f9fc; }
.image-preview-row { display: flex; gap: 8px; padding: 0 4px 8px 4px; overflow-x: auto; }
.image-preview-thumb { position: relative; width: 56px; height: 56px; flex: 0 0 auto; border-radius: 10px; overflow: hidden; border: 1px solid #dfe4ee; }
.image-preview-thumb img { width: 100%; height: 100%; object-fit: cover; }
.image-remove-btn { position: absolute; top: 2px; right: 2px; width: 18px; height: 18px; display: grid; place-items: center; border: 0; border-radius: 50%; background: rgba(0,0,0,.45); color: #fff; cursor: pointer; padding: 0; }
.composer-row { display: flex; align-items: flex-end; gap: 10px; }
.agent-panel__note { padding: 0 20px 12px; color: #a0a7b5; text-align: center; font-size: 10px; }
.typing-dots { display: flex; gap: 4px; padding: 4px 2px; }
.typing-dots i { width: 6px; height: 6px; border-radius: 50%; background: #8590a6; animation: dotPulse 1s infinite alternate; }
.typing-dots i:nth-child(2) { animation-delay: .2s; }
.typing-dots i:nth-child(3) { animation-delay: .4s; }
@keyframes dotPulse { to { opacity: .25; transform: translateY(-2px); } }
</style>
