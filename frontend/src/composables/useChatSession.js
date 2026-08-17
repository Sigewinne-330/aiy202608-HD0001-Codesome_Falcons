import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, authFetch } from '@/stores/auth'
import { compressImageFile } from '@/services/imageCompress'
import { notify } from '@/services/feedback'
import { getPreferences } from '@/services/reminders'
import { onRoleCardChanged } from '@/services/roleCardVisuals'
import {
  consumeChatStream,
  creditLabel,
  estimateTokens,
  extractTaskPayload,
  renderChatMarkdown,
  responseErrorMessage,
  tokensToCredits,
} from '@/services/chat'

const MAX_IMAGES = 5

export function useChatSession(options = {}) {
  const { t } = useI18n()
  const messages = ref([])
  const input = ref('')
  const loading = ref(false)
  const historyLoading = ref(false)
  const historyError = ref('')
  const conversations = ref([])
  const activeConversationId = ref(null)
  const selectedImages = ref([])
  const imageInput = ref(null)
  const dragActive = ref(false)
  const previewUrl = ref('')
  const previewOpen = ref(false)
  const activeRoleCard = ref(null)
  const messageContainer = ref(null)
  let controller = null
  let stopRoleCardListener = null
  let scrollFrame = null

  const prepareContent = options.prepareContent || ((content) => content)
  const sanitizeHistoryContent = options.sanitizeHistoryContent || ((content) => content)

  function report(message, type = 'error') {
    notify(message, { type })
  }

  function reportHistory(message) {
    historyError.value = message
    notify(message, { type: 'error' })
  }

  async function scrollToBottom() {
    await nextTick()
    const container = messageContainer.value
    if (container) container.scrollTop = container.scrollHeight
  }

  function scheduleScroll() {
    if (scrollFrame != null) return
    scrollFrame = window.requestAnimationFrame(() => {
      scrollFrame = null
      scrollToBottom()
    })
  }

  async function loadActiveRoleCard() {
    try {
      const preferences = await getPreferences()
      activeRoleCard.value = preferences?.role_card || null
    } catch {
      activeRoleCard.value = null
    }
  }

  async function loadConversations({ silent = false } = {}) {
    try {
      const data = await api('/api/chat/conversations')
      conversations.value = data?.conversations || []
      historyError.value = ''
      return conversations.value
    } catch (error) {
      conversations.value = []
      if (!silent) reportHistory(error?.message || t('chat.historyLoadFailed'))
      return []
    }
  }

  function normalizeHistoryMessage(item) {
    return {
      role: item.role,
      content: item.role === 'user' ? sanitizeHistoryContent(item.content) : item.content,
      credits: tokensToCredits(item.token),
      creditsIsEstimate: false,
      images: item.images || null,
      metadata: item.metadata || null,
    }
  }

  async function loadHistory(conversationId, { silent = false } = {}) {
    if (!conversationId) return
    historyLoading.value = true
    try {
      const data = await api(`/api/chat/history?conversation_id=${encodeURIComponent(conversationId)}`)
      messages.value = (data?.messages || []).map(normalizeHistoryMessage)
      historyError.value = ''
      await scrollToBottom()
    } catch (error) {
      messages.value = []
      if (!silent) reportHistory(error?.message || t('chat.historyLoadFailed'))
    } finally {
      historyLoading.value = false
    }
  }

  async function switchConversation(conversationId) {
    if (loading.value || conversationId === activeConversationId.value) return
    activeConversationId.value = conversationId
    messages.value = []
    await loadHistory(conversationId)
  }

  async function retryHistory() {
    if (activeConversationId.value) await loadHistory(activeConversationId.value)
    else await loadConversations()
  }

  function newConversation() {
    if (loading.value) return
    activeConversationId.value = null
    messages.value = []
    selectedImages.value = []
    historyError.value = ''
  }

  async function deleteConversation(conversationId) {
    if (loading.value) return
    try {
      await api(`/api/chat/conversations/${conversationId}`, { method: 'DELETE' })
      conversations.value = conversations.value.filter((item) => item.id !== conversationId)
      if (activeConversationId.value === conversationId) newConversation()
    } catch (error) {
      report(error?.message || t('chat.deleteFailed'))
    }
  }

  async function clearHistory() {
    if (!activeConversationId.value || loading.value) return
    try {
      await api(`/api/chat/history?conversation_id=${encodeURIComponent(activeConversationId.value)}`, { method: 'DELETE' })
      messages.value = []
      notify(t('chat.cleared'), { type: 'success' })
    } catch (error) {
      report(error?.message || t('chat.clearFailed'))
    }
  }

  function isImageFile(file) {
    return Boolean(file?.type?.startsWith('image/'))
  }

  async function addFiles(files) {
    const provided = Array.from(files || [])
    const imageFiles = provided.filter(isImageFile)
    if (provided.length && !imageFiles.length) {
      report(t('chat.imagesOnly'), 'warning')
      return
    }
    const remaining = MAX_IMAGES - selectedImages.value.length
    if (remaining <= 0) {
      report(t('chat.imageLimit', { n: MAX_IMAGES }), 'warning')
      return
    }
    if (imageFiles.length > remaining) report(t('chat.imageLimit', { n: MAX_IMAGES }), 'warning')
    for (const file of imageFiles.slice(0, remaining)) {
      try {
        const dataUrl = await compressImageFile(file)
        if (selectedImages.value.length >= MAX_IMAGES) break
        selectedImages.value.push({ dataUrl, file })
      } catch {
        report(t('chat.imageFailed', { name: file.name || t('chat.image') }), 'warning')
      }
    }
  }

  function onImagesSelected(event) {
    addFiles(event.target.files || [])
    if (imageInput.value) imageInput.value.value = ''
  }

  function onDragOver() {
    dragActive.value = true
  }

  function onDragLeave(event) {
    if (!event.currentTarget.contains(event.relatedTarget)) dragActive.value = false
  }

  function onDrop(event) {
    dragActive.value = false
    if (!loading.value && event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files)
  }

  function onPaste(event) {
    const files = event.clipboardData?.files
    if (!files?.length || !Array.from(files).some(isImageFile)) return
    event.preventDefault()
    addFiles(files)
  }

  function removeImage(index) {
    selectedImages.value.splice(index, 1)
  }

  function previewImage(url) {
    previewUrl.value = url
    previewOpen.value = true
  }

  async function ensureConversation() {
    if (activeConversationId.value) return activeConversationId.value
    const data = await api('/api/chat/conversations', { method: 'POST' })
    activeConversationId.value = data?.id || null
    if (!activeConversationId.value) throw new Error(t('chat.conversationCreateFailed'))
    return activeConversationId.value
  }

  async function sendMessage() {
    const content = input.value.trim()
    const images = selectedImages.value.map((item) => item.dataUrl)
    if ((!content && !images.length) || loading.value) return

    messages.value.push({ role: 'user', content, images: images.length ? [...images] : null })
    messages.value.push({
      role: 'assistant',
      content: '',
      streaming: true,
      metadata: activeRoleCard.value?.slug
        ? { source: 'main_agent', role_card: { slug: activeRoleCard.value.slug } }
        : null,
    })
    const responseIndex = messages.value.length - 1
    const retryDraft = { content, images: [...images] }
    input.value = ''
    selectedImages.value = []
    loading.value = true
    historyError.value = ''
    await scrollToBottom()

    try {
      const conversationId = await ensureConversation()
      controller = new AbortController()
      const body = { content: prepareContent(content), conversation_id: conversationId }
      if (images.length) body.images = images
      const response = await authFetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (response.status === 402) {
        messages.value[responseIndex].content = t('billing.insufficient')
        messages.value[responseIndex].failed = true
        messages.value[responseIndex].retryDraft = retryDraft
        notify(t('billing.insufficient'), { type: 'warning' })
        throw new Error('INSUFFICIENT_BALANCE')
      }
      if (!response.ok || !response.body) {
        throw new Error(await responseErrorMessage(response, t('chat.requestFailed')))
      }

      let streamFailure = ''
      await consumeChatStream(response, {
        onChunk(chunk) {
          messages.value[responseIndex].content += chunk
          messages.value[responseIndex].credits = tokensToCredits(estimateTokens(messages.value[responseIndex].content))
          messages.value[responseIndex].creditsIsEstimate = true
          scheduleScroll()
        },
        onUsage(usage) {
          if (usage.credits || usage.tokens) {
            messages.value[responseIndex].credits = usage.credits || tokensToCredits(usage.tokens)
            messages.value[responseIndex].creditsIsEstimate = false
          }
        },
        onError(message) {
          streamFailure = message
        },
      })
      if (streamFailure) throw new Error(streamFailure)
    } catch (error) {
      if (error.name !== 'AbortError' && error.message !== 'INSUFFICIENT_BALANCE') {
        messages.value[responseIndex].content = error?.message || t('agent.connectError')
        messages.value[responseIndex].failed = true
        messages.value[responseIndex].retryDraft = retryDraft
        report(t('chat.sendFailed'), 'error')
      }
    } finally {
      const message = messages.value[responseIndex]
      if (message) {
        messages.value[responseIndex] = { ...message, streaming: false }
        if (options.extractTasks) {
          const taskData = extractTaskPayload(message.content)
          if (taskData) messages.value[responseIndex] = { ...messages.value[responseIndex], taskData, taskSaved: false }
        }
      }
      loading.value = false
      controller = null
      await loadConversations({ silent: true })
      await options.afterMessageComplete?.()
      await scrollToBottom()
    }
  }

  function stopGeneration() {
    controller?.abort()
    const last = messages.value.at(-1)
    if (last?.streaming) last.streaming = false
    loading.value = false
  }

  function restoreFailedDraft(index) {
    const draft = messages.value[index]?.retryDraft
    if (!draft || loading.value) return
    input.value = draft.content || ''
    selectedImages.value = (draft.images || []).map((dataUrl) => ({ dataUrl, file: null }))
    messages.value[index].failed = false
    notify(t('chat.draftRestored'), { type: 'info' })
  }

  async function saveTaskFromChat(index) {
    const message = messages.value[index]
    if (!message?.taskData || message.saving) return
    message.saving = true
    try {
      const result = await api('/api/chat/save-tasks', {
        method: 'POST',
        body: JSON.stringify(message.taskData),
      })
      if (!result?.ok) throw new Error(t('chat.saveFailed'))
      message.taskSaved = true
      message.savedInfo = result
      notify(t('chat.taskSaved'), { type: 'success' })
      await options.afterTaskSaved?.(result)
    } catch (error) {
      report(error?.message || t('chat.saveFailedBackend'))
    } finally {
      message.saving = false
    }
  }

  async function initialize() {
    historyLoading.value = true
    await Promise.all([loadActiveRoleCard(), loadConversations()])
    if (conversations.value.length) {
      activeConversationId.value = conversations.value[0].id
      await loadHistory(activeConversationId.value)
    }
    historyLoading.value = false
  }

  onMounted(() => {
    stopRoleCardListener = onRoleCardChanged((roleCard) => {
      activeRoleCard.value = roleCard
    })
    if (options.autoLoad !== false) initialize()
  })

  onBeforeUnmount(() => {
    controller?.abort()
    stopRoleCardListener?.()
    if (scrollFrame != null) window.cancelAnimationFrame(scrollFrame)
  })

  return {
    activeConversationId,
    activeRoleCard,
    addFiles,
    clearHistory,
    conversations,
    creditLabel,
    deleteConversation,
    dragActive,
    historyError,
    historyLoading,
    imageInput,
    input,
    loadConversations,
    loadHistory,
    loading,
    messageContainer,
    messages,
    newConversation,
    onDragLeave,
    onDragOver,
    onDrop,
    onImagesSelected,
    onPaste,
    previewImage,
    previewOpen,
    previewUrl,
    removeImage,
    renderMarkdown: renderChatMarkdown,
    restoreFailedDraft,
    retryHistory,
    saveTaskFromChat,
    scrollToBottom,
    selectedImages,
    sendMessage,
    stopGeneration,
    switchConversation,
  }
}
