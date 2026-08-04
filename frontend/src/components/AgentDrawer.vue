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
          <!-- 汇总提醒消息标识：metadata.source === 'reminder' -->
          <div v-if="message.metadata?.source === 'reminder'" class="reminder-banner">
            <v-icon size="14" color="primary">mdi-bell-ring-outline</v-icon>
            <v-chip size="x-small" color="primary" variant="tonal">{{ $t('reminders.chatChip') }}</v-chip>
            <v-spacer />
            <v-btn
              size="x-small"
              variant="text"
              color="primary"
              @click="goReminderDetail(message.metadata)"
            >
              {{ $t('reminders.viewDetail') }}
            </v-btn>
          </div>
          <!-- 任务级提醒消息标识：metadata.source === 'task_relative_reminder' -->
          <div v-else-if="message.metadata?.source === 'task_relative_reminder'" class="reminder-banner">
            <v-icon size="14" color="deep-purple">mdi-bell-outline</v-icon>
            <v-chip size="x-small" color="deep-purple" variant="tonal">{{ $t('reminders.taskChatChip') }}</v-chip>
            <v-spacer />
            <v-btn
              v-if="message.metadata?.task_id"
              size="x-small"
              variant="text"
              color="deep-purple"
              @click="goTaskReminderDetail(message.metadata)"
            >
              {{ $t('reminders.viewDetail') }}
            </v-btn>
          </div>
          <!-- 流式中且无内容：打字动画 -->
          <div v-if="message.streaming && !message.content" class="typing-dots"><i /><i /><i /></div>
          <!-- 用户消息：图片 + 文本 -->
          <div v-else-if="message.role === 'user'">
            <div v-if="message.images && message.images.length" class="agent-images">
              <img
                v-for="(img, i) in message.images"
                :key="i"
                :src="img"
                class="agent-img"
                :alt="`image-${i + 1}`"
                @click="previewImage(img)"
              />
            </div>
            <div v-if="message.content" class="agent-text">{{ message.content }}</div>
          </div>
          <!-- 提醒正文：纯文本原样展示（汇总提醒与任务级提醒均已含完整文本） -->
          <div v-else-if="message.metadata?.source === 'reminder' || message.metadata?.source === 'task_relative_reminder'" class="agent-text reminder-plain-text" v-text="message.content" />
          <!-- AI 消息：Markdown + LaTeX 实时渲染（key 切换强制结束重渲染） -->
          <div v-else class="agent-md"
            :key="'md-' + index + '-' + (message.streaming ? 1 : 0)"
            v-html="renderMarkdown(message.content)" />
          <!-- 每条 AI 回复的积分消耗：流式中实时估算增长，结束后显示后端换算的权威值 -->
          <div v-if="message.role === 'assistant' && message.credits" class="agent-token-meta">
            <v-icon icon="mdi-lightning-bolt" size="11" />
            {{ creditLabel(message) }} {{ $t('chat.creditsUnit') }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="contextLabel" class="agent-context">
      <v-icon icon="mdi-chart-timeline-variant" size="14" />
      <span>{{ contextLabel }}</span>
    </div>

    <div
      class="agent-panel__composer"
      :class="{ 'agent-panel__composer--drag': dragActive }"
      @dragover.prevent="onDragOver"
      @dragenter.prevent="dragActive = true"
      @dragleave="onDragLeave"
      @drop.prevent="onDrop"
    >
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
          @paste="onPaste"
        />
        <v-btn
          :icon="loading ? 'mdi-stop' : 'mdi-arrow-up'"
          :color="loading ? 'grey' : 'primary'"
          variant="flat"
          :disabled="!loading && !input.trim() && !selectedImages.length"
          @click="loading ? stopGeneration() : sendMessage()"
        />
      </div>
    </div>
    <div class="agent-panel__note">{{ $t('agent.note') }}</div>

    <!-- 图片大图预览 -->
    <v-dialog v-model="previewOpen" max-width="85vw" @click:outside="previewOpen = false">
      <v-img :src="previewUrl" contain max-height="80vh" style="border-radius: 12px;" />
    </v-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuth } from '@/stores/auth'
import { notifyTasksChanged } from '@/services/taskSync'
import { compressImageFile } from '@/services/imageCompress'
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

/** token → 积分：1000 token = 1 积分，向上取整、最少 1（与后端 billing.credits_for_tokens 一致） */
function tokensToCredits(tokens) {
  if (!tokens || tokens <= 0) return 0
  return Math.max(1, Math.ceil(tokens / 1000))
}

/** 渲染积分标签：流式中显示估算值（≈ 前缀），结束后显示后端下发的权威值 */
function creditLabel(message) {
  if (!message || !message.credits) return ''
  return (message.creditsIsEstimate ? '≈ ' : '') + message.credits.toLocaleString()
}

const props = defineProps({
  context: { type: Object, default: null },
})

const emit = defineEmits(['close'])

const { t } = useI18n()
const { token } = useAuth()
const router = useRouter()

/** 提醒消息 → 跳转提醒中心精确定位并关闭抽屉（只用 digest_id，不读 metadata 内的 URL/任务 ID） */
function goReminderDetail(metadata) {
  if (!metadata?.digest_id) return
  emit('close')
  router.push({ path: '/reminders', query: { tab: 'history', digest: metadata.digest_id } })
}

/** 任务级提醒消息（task_relative_reminder）→ 跳转任务页高亮对应任务并关闭抽屉 */
function goTaskReminderDetail(metadata) {
  if (!metadata?.task_id) return
  emit('close')
  router.push({ path: '/tasks', query: { focus: metadata.task_id } })
}
const messages = ref([])
const input = ref('')
const loading = ref(false)
const messageContainer = ref(null)
const activeConversationId = ref(null)
const conversations = ref([])
const selectedImages = ref([])  // [{ dataUrl, file }]
const imageInput = ref(null)
const dragActive = ref(false)   // 拖拽高亮状态
const balance = ref(0)
const previewUrl = ref('')   // 图片大图预览
const previewOpen = ref(false)
let controller = null

const suggestions = [
  'agent.suggestion1',
  'agent.suggestion2',
  'agent.suggestion3',
]

const contextLabel = computed(() => {
  if (!props.context) return ''
  return [props.context.category, props.context.subject || props.context.title]
    .filter(Boolean)
    .join(' · ')
})

function contextualize(content) {
  if (!props.context) return content
  const context = {
    category: props.context.category || null,
    task_id: props.context.taskId || props.context.task_id || null,
    subject: props.context.subject || null,
    title: props.context.title || null,
  }
  return `[PROGRESS_CONTEXT]${JSON.stringify(context)}[/PROGRESS_CONTEXT]\n` +
    `Use this exact timeline context. Only manage milestones, dates, priorities, and completion states; do not provide academic-content advice.\n\n${content}`
}

function stripContext(content) {
  return String(content || '').replace(/^\[PROGRESS_CONTEXT\][\s\S]*?\[\/PROGRESS_CONTEXT\]\n[^\n]*\n\n/, '')
}

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

// ---- 图片上传（选图 / 拖拽 / 粘贴统一入口） ----

/** 只接受图片文件 */
function isImageFile(file) {
  return file && file.type && file.type.startsWith('image/')
}

/** 将文件压缩后转 base64 加入待发送列表（最多 5 张） */
async function addFiles(files) {
  const imgFiles = Array.from(files || []).filter(isImageFile)
  const remaining = 5 - selectedImages.value.length
  if (remaining <= 0) return
  const batch = imgFiles.slice(0, remaining)
  // 逐张异步压缩（不阻塞 UI），压缩完成后依次加入
  for (const file of batch) {
    try {
      const dataUrl = await compressImageFile(file)
      // 并行压缩期间用户可能已移除/添加，这里按剩余容量兜底
      if (selectedImages.value.length >= 5) break
      selectedImages.value.push({ dataUrl, file })
    } catch {
      // 单张压缩失败静默跳过，不影响其他图片
    }
  }
}

function onImagesSelected(e) {
  addFiles(e.target.files || [])
  // 重置 input 以便重复选择同一文件
  if (imageInput.value) imageInput.value.value = ''
}

/** 拖拽悬停：保持高亮 */
function onDragOver() {
  dragActive.value = true
}

/** 拖拽离开：真正离开整个输入区才取消高亮（避免子元素间闪烁） */
function onDragLeave(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) dragActive.value = false
}

/** 松开拖拽：将图片加入待发送列表 */
function onDrop(e) {
  dragActive.value = false
  if (loading.value) return
  if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files)
}

/** 粘贴图片（如截图）：仅在有图片时拦截，纯文本粘贴不受影响 */
function onPaste(e) {
  const files = e.clipboardData?.files
  if (!files || !files.length) return
  if (Array.from(files).some(isImageFile)) {
    e.preventDefault()
    addFiles(files)
  }
}

function removeImage(idx) {
  selectedImages.value.splice(idx, 1)
}

/** 点击历史/发送的图片 → 大图预览 */
function previewImage(url) {
  previewUrl.value = url
  previewOpen.value = true
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
      messages.value = (data.messages || []).map((item) => ({
        role: item.role,
        content: item.role === 'user' ? stripContext(item.content) : item.content,
        credits: tokensToCredits(item.token),
        creditsIsEstimate: false,
        images: item.images || null,
        metadata: item.metadata || null,
      }))
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
  const hasImages = selectedImages.value.length > 0
  if ((!content && !hasImages) || loading.value) return

  // 先取出待发送图片（挂到用户消息上，气泡里永久显示）
  const images = selectedImages.value.map(img => img.dataUrl)
  messages.value.push({ role: 'user', content, images: images.length ? [...images] : null })
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  const responseIndex = messages.value.length - 1
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
    const body = { content: contextualize(content), conversation_id: activeConversationId.value }
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
          // 流式结束事件：携带本轮真实 token 与后端换算的积分（权威值替换估算值）
          if (parsed && typeof parsed === 'object' && parsed.done) {
            if (parsed.credits || parsed.tokens) {
              messages.value[responseIndex].credits = parsed.credits || tokensToCredits(parsed.tokens)
              messages.value[responseIndex].creditsIsEstimate = false
            }
            continue
          }
          const chunk = typeof parsed === 'string' ? parsed : (parsed.error || '')
          messages.value[responseIndex].content += chunk
          // 实时估算积分，让数字随生成过程增长（结束时用后端权威值替换）
          messages.value[responseIndex].credits = tokensToCredits(estimateTokens(messages.value[responseIndex].content))
          messages.value[responseIndex].creditsIsEstimate = true
          if (chunk.includes('✓ 操作成功')) taskMutationSucceeded = true
        } catch {
          messages.value[responseIndex].content += payload
          messages.value[responseIndex].credits = tokensToCredits(estimateTokens(messages.value[responseIndex].content))
          messages.value[responseIndex].creditsIsEstimate = true
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
    // A read-only refresh is cheap and guarantees timeline pages reflect tool mutations,
    // including update_task/update_subtask status messages from different providers.
    notifyTasksChanged()
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
.reminder-banner { display: flex; align-items: center; gap: 6px; padding-bottom: 8px; }
.reminder-plain-text { white-space: pre-wrap; line-height: 1.7; }
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
.agent-context { display: flex; align-items: center; gap: 7px; margin: 8px 14px 0; padding: 8px 11px; border-radius: 11px; color: #4662bd; background: #eef2ff; font-size: 11px; font-weight: 700; }
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
.agent-images { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.agent-img { width: 116px; height: 116px; object-fit: cover; border-radius: 10px; cursor: zoom-in; border: 1px solid rgba(0,0,0,.08); }
.agent-img:hover { opacity: .92; }
.agent-md { padding: 11px 13px; border-radius: 5px 15px 15px 15px; background: #f0f2f7; color: #28334b; word-break: break-word; font-size: 13px; line-height: 1.55; }
.agent-token-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 3px;
  padding: 4px 13px 0;
  color: #9aa3b5;
  font-size: 10.5px;
  font-weight: 500;
}
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
.agent-panel__composer { display: flex; flex-direction: column; gap: 0; margin: 12px 14px 6px; padding: 8px; border: 1px solid #dfe4ee; border-radius: 18px; background: #f8f9fc; transition: border-color .15s, background .15s, box-shadow .15s; }
.agent-panel__composer--drag { border-color: #315fdf; background: #f2f6ff; box-shadow: 0 0 0 3px rgba(49,95,223,.14); }
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
