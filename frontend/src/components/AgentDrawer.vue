<template>
  <section class="agent-panel" :aria-label="$t('agent.title')">
    <header class="agent-header">
      <RoleCardAvatar
        :slug="activeRoleCard?.slug"
        :title="activeRoleCard?.name"
        :size="40"
        :icon-size="20"
      />
      <div class="agent-identity">
        <strong>{{ $t('agent.title') }}</strong>
        <div>
          <span class="agent-status"><i />{{ $t('agent.status') }}</span>
          <button
            type="button"
            class="balance-pill"
            :class="{ 'balance-pill--low': balance < 1000 }"
            :aria-label="$t('billing.balance')"
            @click="goBilling"
          >
            <v-icon icon="mdi-lightning-bolt-outline" size="12" />
            {{ balance.toLocaleString() }}
          </button>
        </div>
      </div>
      <v-spacer />

      <v-menu location="bottom end" max-width="calc(100vw - 24px)">
        <template #activator="{ props: menuProps }">
          <v-btn
            v-bind="menuProps"
            icon="mdi-message-text-outline"
            variant="text"
            size="small"
            :aria-label="$t('agent.history')"
            :disabled="loading"
          />
        </template>
        <v-card class="agent-history-menu" width="280">
          <div class="agent-history-menu__title">
            <strong>{{ $t('agent.history') }}</strong>
            <small>{{ $t('chat.conversationCount', { n: conversations.length }) }}</small>
          </div>
          <v-divider />
          <div class="agent-history-list scroll-container">
            <button
              v-for="conversation in conversations"
              :key="conversation.id"
              type="button"
              :class="{ active: conversation.id === activeConversationId }"
              @click="switchConversation(conversation.id)"
            >
              <v-icon icon="mdi-message-outline" size="16" />
              <span>{{ conversation.title || $t('agent.newConversation') }}</span>
              <v-btn
                icon="mdi-close"
                size="x-small"
                variant="text"
                :aria-label="$t('chat.deleteConversation')"
                @click.stop="deleteConversation(conversation.id)"
              />
            </button>
            <div v-if="!conversations.length" class="agent-history-empty">{{ $t('agent.noHistory') }}</div>
          </div>
        </v-card>
      </v-menu>

      <v-btn
        icon="mdi-plus"
        variant="text"
        size="small"
        :aria-label="$t('agent.newConversation')"
        :disabled="loading"
        @click="newConversation"
      />
      <v-btn icon="mdi-close" variant="text" size="small" :aria-label="$t('agent.close')" @click="$emit('close')" />
    </header>

    <v-alert v-if="historyError" type="error" variant="tonal" density="compact" closable class="agent-alert">
      {{ historyError }}
      <template #append>
        <v-btn size="x-small" variant="text" @click="retryHistory">{{ $t('common.retry') }}</v-btn>
      </template>
    </v-alert>

    <div
      ref="messageContainer"
      class="agent-messages scroll-container"
      role="log"
      aria-live="polite"
      :aria-label="$t('chat.messages')"
    >
      <div v-if="historyLoading && !messages.length" class="agent-welcome">
        <v-progress-circular indeterminate color="primary" size="28" />
        <span>{{ $t('chat.loadingHistory') }}</span>
      </div>

      <div v-else-if="!messages.length" class="agent-welcome">
        <span class="agent-welcome__icon"><v-icon icon="mdi-creation-outline" size="28" /></span>
        <strong>{{ $t('agent.welcomeTitle') }}</strong>
        <p>{{ $t('agent.welcomeSub') }}</p>
        <button v-for="suggestion in suggestions" :key="suggestion" type="button" @click="sendSuggestion(suggestion)">
          <span>{{ $t(suggestion) }}</span>
          <v-icon icon="mdi-arrow-up-right" size="14" />
        </button>
      </div>

      <article
        v-for="(message, index) in messages"
        v-else
        :key="index"
        class="agent-message"
        :class="`agent-message--${message.role}`"
      >
        <RoleCardAvatar
          v-if="message.role === 'assistant'"
          :slug="messageRoleCardSlug(message, activeRoleCard?.slug)"
          :size="28"
          :icon-size="15"
        />
        <div class="agent-bubble">
          <div v-if="message.metadata?.source === 'reminder'" class="agent-message-context">
            <v-icon icon="mdi-bell-ring-outline" size="14" />
            <span>{{ $t('reminders.chatChip') }}</span>
            <v-btn size="x-small" variant="text" @click="goReminderDetail(message.metadata)">
              {{ $t('reminders.viewDetail') }}
            </v-btn>
          </div>
          <div v-else-if="message.metadata?.source === 'task_relative_reminder'" class="agent-message-context">
            <v-icon icon="mdi-bell-outline" size="14" />
            <span>{{ $t('reminders.taskChatChip') }}</span>
            <v-btn
              v-if="message.metadata?.task_id"
              size="x-small"
              variant="text"
              @click="goTaskReminderDetail(message.metadata)"
            >
              {{ $t('reminders.viewDetail') }}
            </v-btn>
          </div>

          <div v-if="message.images?.length" class="agent-images">
            <button
              v-for="(image, imageIndex) in message.images"
              :key="imageIndex"
              type="button"
              :aria-label="$t('chat.previewImage', { n: imageIndex + 1 })"
              @click="previewImage(image)"
            >
              <img :src="image" :alt="$t('chat.imageNumber', { n: imageIndex + 1 })" />
            </button>
          </div>

          <div v-if="message.streaming && !message.content" class="typing-dots" :aria-label="$t('chat.thinking')">
            <i /><i /><i />
          </div>
          <div v-else-if="message.role === 'user'" class="agent-text" v-text="message.content" />
          <div
            v-else-if="['reminder', 'task_relative_reminder'].includes(message.metadata?.source)"
            class="agent-text"
            v-text="message.content"
          />
          <div
            v-else
            :key="`markdown-${index}-${message.streaming ? 1 : 0}`"
            class="agent-markdown"
            v-html="renderMarkdown(message.content)"
          />

          <div v-if="message.role === 'assistant' && message.credits" class="agent-message-meta">
            <v-icon icon="mdi-lightning-bolt-outline" size="11" />
            {{ creditLabel(message) }} {{ $t('chat.creditsUnit') }}
          </div>
          <v-btn
            v-if="message.failed"
            size="x-small"
            variant="tonal"
            color="primary"
            prepend-icon="mdi-restore"
            class="mt-2"
            @click="restoreFailedDraft(index)"
          >
            {{ $t('chat.restoreDraft') }}
          </v-btn>
        </div>
      </article>
    </div>

    <div v-if="contextLabel" class="agent-context">
      <v-icon icon="mdi-chart-timeline-variant" size="14" />
      <span>{{ contextLabel }}</span>
    </div>

    <div class="agent-composer" :class="{ 'agent-composer--drag': dragActive }">
      <div v-if="selectedImages.length" class="composer-images">
        <div v-for="(image, index) in selectedImages" :key="index">
          <img :src="image.dataUrl" :alt="$t('chat.imageNumber', { n: index + 1 })" />
          <button type="button" :aria-label="$t('chat.removeImage')" @click="removeImage(index)">
            <v-icon icon="mdi-close" size="12" />
          </button>
        </div>
      </div>
      <div
        class="agent-composer__row"
        @dragover.prevent="onDragOver"
        @dragenter.prevent="dragActive = true"
        @dragleave="onDragLeave"
        @drop.prevent="onDrop"
      >
        <input ref="imageInput" class="visually-hidden" type="file" accept="image/*" multiple @change="onImagesSelected" />
        <v-btn
          icon="mdi-image-outline"
          variant="text"
          size="small"
          :aria-label="$t('chat.addImage')"
          :disabled="loading || selectedImages.length >= 5"
          @click="imageInput?.click()"
        />
        <v-textarea
          v-model="input"
          :placeholder="$t('agent.placeholder')"
          rows="1"
          max-rows="5"
          auto-grow
          variant="solo-filled"
          flat
          hide-details
          :disabled="loading"
          @keydown.enter.exact.prevent="sendMessage"
          @paste="onPaste"
        />
        <v-btn
          :icon="loading ? 'mdi-stop' : 'mdi-arrow-up'"
          :color="loading ? undefined : 'primary'"
          :variant="loading ? 'outlined' : 'flat'"
          :aria-label="loading ? $t('chat.stop') : $t('chat.send')"
          :disabled="!loading && !input.trim() && !selectedImages.length"
          @click="loading ? stopGeneration() : sendMessage()"
        />
      </div>
      <small>{{ $t('agent.note') }}</small>
    </div>

    <v-dialog v-model="previewOpen" max-width="min(900px, 92vw)" @click:outside="previewOpen = false">
      <v-card class="agent-image-dialog">
        <v-btn icon="mdi-close" variant="tonal" :aria-label="$t('common.close')" @click="previewOpen = false" />
        <v-img :src="previewUrl" contain max-height="82vh" />
      </v-card>
    </v-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import RoleCardAvatar from '@/components/RoleCardAvatar.vue'
import { useChatSession } from '@/composables/useChatSession'
import { api } from '@/stores/auth'
import { messageRoleCardSlug } from '@/services/roleCardVisuals'
import { notifyTasksChanged } from '@/services/taskSync'

const props = defineProps({ context: { type: Object, default: null } })
const emit = defineEmits(['close'])
const router = useRouter()
const { t } = useI18n()
const balance = ref(0)
const suggestions = ['agent.suggestion1', 'agent.suggestion2', 'agent.suggestion3']

const contextLabel = computed(() => {
  if (!props.context) return ''
  return [props.context.category, props.context.subject || props.context.title].filter(Boolean).join(' · ')
})

function contextualize(content) {
  if (!props.context) return content
  const context = {
    category: props.context.category || null,
    task_id: props.context.taskId || props.context.task_id || null,
    subject: props.context.subject || null,
    title: props.context.title || null,
  }
  return `[PROGRESS_CONTEXT]${JSON.stringify(context)}[/PROGRESS_CONTEXT]\n`
    + 'Use this exact timeline context. Only manage milestones, dates, priorities, and completion states; do not provide academic-content advice.\n\n'
    + content
}

function stripContext(content) {
  return String(content || '').replace(/^\[PROGRESS_CONTEXT\][\s\S]*?\[\/PROGRESS_CONTEXT\]\n[^\n]*\n\n/, '')
}

async function loadBalance() {
  try {
    const data = await api('/api/billing/summary')
    balance.value = data?.balance || 0
  } catch {
    balance.value = 0
  }
}

async function afterMessageComplete() {
  notifyTasksChanged()
  await loadBalance()
}

const {
  activeConversationId,
  activeRoleCard,
  conversations,
  creditLabel,
  deleteConversation,
  dragActive,
  historyError,
  historyLoading,
  imageInput,
  input,
  loadConversations,
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
  renderMarkdown,
  restoreFailedDraft,
  retryHistory,
  selectedImages,
  sendMessage,
  stopGeneration,
  switchConversation,
} = useChatSession({
  prepareContent: contextualize,
  sanitizeHistoryContent: stripContext,
  afterMessageComplete,
})

function sendSuggestion(key) {
  input.value = t(key)
  sendMessage()
}

function goBilling() {
  emit('close')
  router.push('/billing')
}

function goReminderDetail(metadata) {
  if (!metadata?.digest_id) return
  emit('close')
  router.push({ path: '/reminders', query: { tab: 'history', digest: metadata.digest_id } })
}

function goTaskReminderDetail(metadata) {
  if (!metadata?.task_id) return
  emit('close')
  router.push({ path: '/tasks', query: { focus: metadata.task_id } })
}

onMounted(loadBalance)
</script>

<style scoped>
.agent-panel { height: 100%; display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto auto; overflow: hidden; color: var(--ib-text); background: var(--ib-surface); }
.agent-header { display: flex; align-items: center; gap: 9px; min-height: 64px; padding: 10px 12px 10px 16px; border-bottom: 1px solid var(--ib-border); }
.agent-identity { display: grid; min-width: 0; gap: 3px; }
.agent-identity > strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.agent-identity > div { display: flex; align-items: center; gap: 8px; }
.agent-status { display: inline-flex; align-items: center; gap: 5px; color: var(--ib-text-muted); font-size: 9px; }
.agent-status i { width: 6px; height: 6px; border-radius: 50%; background: var(--ib-success); }
.balance-pill { display: inline-flex; align-items: center; gap: 3px; padding: 2px 6px; border: 1px solid var(--ib-border); border-radius: 999px; color: var(--ib-primary-strong); background: var(--ib-primary-soft); cursor: pointer; font-size: 9px; font-weight: 700; }
.balance-pill--low { color: var(--ib-warning); background: color-mix(in srgb, var(--ib-warning) 10%, var(--ib-surface)); }
.agent-alert { margin: 8px 10px 0; }
.agent-messages { min-height: 0; overflow-y: auto; padding: 18px 16px; }
.agent-welcome { display: grid; min-height: 100%; place-items: center; align-content: center; gap: 9px; color: var(--ib-text-secondary); text-align: center; }
.agent-welcome__icon { display: grid; width: 58px; height: 58px; place-items: center; border-radius: 18px; color: var(--ib-primary-strong); background: var(--ib-primary-soft); }
.agent-welcome strong { margin-top: 4px; color: var(--ib-text); font-size: 15px; }
.agent-welcome p { max-width: 330px; margin: 0 0 8px; font-size: 10px; line-height: 1.5; }
.agent-welcome > button { width: min(100%, 360px); display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 11px; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-sm); color: var(--ib-text-secondary); background: var(--ib-surface); cursor: pointer; text-align: left; font-size: 10px; }
.agent-welcome > button:hover { border-color: var(--ib-primary); color: var(--ib-primary-strong); background: var(--ib-primary-soft); }
.agent-message { display: flex; align-items: flex-start; gap: 7px; margin-bottom: 13px; }
.agent-message--user { justify-content: flex-end; }
.agent-bubble { max-width: 86%; overflow: hidden; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-md); color: var(--ib-text); background: var(--ib-surface); }
.agent-message--user .agent-bubble { border-color: color-mix(in srgb, var(--ib-primary) 30%, var(--ib-border)); background: var(--ib-primary-soft); }
.agent-text, .agent-markdown, .typing-dots { padding: 10px 12px; font-size: 11px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.agent-message-context { display: flex; align-items: center; gap: 6px; padding: 4px 6px 4px 9px; border-bottom: 1px solid var(--ib-border); color: var(--ib-primary-strong); font-size: 9px; font-weight: 700; }
.agent-message-context .v-btn { margin-left: auto; }
.typing-dots { display: flex; gap: 4px; }
.typing-dots i { width: 5px; height: 5px; border-radius: 50%; background: var(--ib-primary); animation: typing 1s ease-in-out infinite; }
.typing-dots i:nth-child(2) { animation-delay: .14s; }
.typing-dots i:nth-child(3) { animation-delay: .28s; }
@keyframes typing { 0%, 60%, 100% { opacity: .35; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-2px); } }
.agent-images { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; padding: 8px 8px 0; }
.agent-images button { overflow: hidden; padding: 0; border: 1px solid var(--ib-border); border-radius: 8px; background: transparent; cursor: zoom-in; }
.agent-images img { display: block; width: 105px; height: 78px; object-fit: cover; }
.agent-message-meta { display: flex; align-items: center; justify-content: flex-end; gap: 3px; padding: 5px 8px; border-top: 1px solid var(--ib-border); color: var(--ib-text-muted); font-size: 8px; }
.agent-markdown :deep(p) { margin: 0 0 .7em; }
.agent-markdown :deep(p:last-child) { margin-bottom: 0; }
.agent-markdown :deep(pre) { max-width: 100%; overflow-x: auto; padding: 9px; border-radius: 7px; background: var(--ib-surface-subtle); }
.agent-markdown :deep(code) { font-family: 'SFMono-Regular', Consolas, monospace; font-size: .9em; }
.agent-markdown :deep(a) { color: var(--ib-primary-strong); }
.agent-markdown :deep(.katex-display) { max-width: 100%; overflow-x: auto; overflow-y: hidden; }
.agent-context { display: flex; align-items: center; gap: 6px; padding: 7px 14px; border-top: 1px solid var(--ib-border); color: var(--ib-primary-strong); background: var(--ib-primary-soft); font-size: 9px; }
.agent-context span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-composer { padding: 10px 12px 8px; border-top: 1px solid var(--ib-border); background: var(--ib-surface); }
.agent-composer__row { display: flex; align-items: flex-end; gap: 5px; padding: 5px; border: 1px solid var(--ib-border-strong); border-radius: var(--ib-radius-md); background: var(--ib-surface-subtle); }
.agent-composer__row:focus-within, .agent-composer--drag .agent-composer__row { border-color: var(--ib-primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ib-primary) 14%, transparent); }
.agent-composer__row :deep(.v-field) { background: transparent !important; box-shadow: none !important; }
.agent-composer > small { display: block; margin-top: 6px; color: var(--ib-text-muted); font-size: 8px; text-align: center; }
.composer-images { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 7px; }
.composer-images > div { position: relative; }
.composer-images img { display: block; width: 54px; height: 54px; border: 1px solid var(--ib-border); border-radius: 8px; object-fit: cover; }
.composer-images button { position: absolute; top: -4px; right: -4px; display: grid; width: 18px; height: 18px; place-items: center; padding: 0; border: 1px solid var(--ib-border); border-radius: 50%; color: var(--ib-text); background: var(--ib-surface); cursor: pointer; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; }
.agent-history-menu__title { display: flex; align-items: baseline; justify-content: space-between; padding: 13px 14px; }
.agent-history-menu__title strong { color: var(--ib-text); font-size: 12px; }
.agent-history-menu__title small { color: var(--ib-text-muted); font-size: 9px; }
.agent-history-list { max-height: 320px; overflow-y: auto; padding: 6px; }
.agent-history-list > button { width: 100%; display: grid; grid-template-columns: 18px minmax(0, 1fr) 28px; align-items: center; gap: 7px; padding: 7px; border: 0; border-radius: 8px; color: var(--ib-text-secondary); background: transparent; cursor: pointer; text-align: left; }
.agent-history-list > button:hover { background: var(--ib-surface-subtle); }
.agent-history-list > button.active { color: var(--ib-primary-strong); background: var(--ib-primary-soft); }
.agent-history-list > button > span { overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.agent-history-empty { padding: 30px 16px; color: var(--ib-text-muted); font-size: 10px; text-align: center; }
.agent-image-dialog { position: relative; overflow: hidden; }
.agent-image-dialog > .v-btn { position: absolute; z-index: 1; top: 9px; right: 9px; }

@media (max-width: 520px) {
  .agent-header { padding-left: 12px; }
  .agent-identity .agent-status { display: none; }
  .agent-messages { padding: 14px 10px; }
  .agent-bubble { max-width: 90%; }
}
</style>
