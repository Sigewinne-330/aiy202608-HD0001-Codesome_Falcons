<template>
  <section class="chat-page ib-page">
    <header class="ib-page-header chat-header">
      <div>
        <div class="ib-eyebrow">{{ $t('chat.eyebrow') }}</div>
        <h1 class="ib-page-title">{{ $t('chat.title') }}</h1>
        <p class="ib-page-subtitle">{{ $t('chat.subtitle') }}</p>
      </div>
      <v-btn
        variant="outlined"
        prepend-icon="mdi-delete-outline"
        :disabled="!activeConversationId || loading"
        @click="clearHistory"
      >
        {{ $t('chat.clear') }}
      </v-btn>
    </header>

    <div class="chat-layout">
      <aside class="conversation-panel ib-panel" :aria-label="$t('chat.conversationList')">
        <div class="conversation-panel__header">
          <div>
            <strong>{{ $t('chat.conversations') }}</strong>
            <small>{{ $t('chat.conversationCount', { n: conversations.length }) }}</small>
          </div>
          <v-btn
            icon="mdi-plus"
            size="small"
            color="primary"
            variant="tonal"
            :aria-label="$t('chat.newConversation')"
            :disabled="loading"
            @click="newConversation"
          />
        </div>

        <div class="conversation-list scroll-container">
          <button
            v-for="conversation in conversations"
            :key="conversation.id"
            type="button"
            class="conversation-item"
            :class="{ 'conversation-item--active': conversation.id === activeConversationId }"
            @click="switchConversation(conversation.id)"
          >
            <v-icon icon="mdi-message-outline" size="17" />
            <span>
              <strong>{{ conversation.title || $t('chat.newConversationTip') }}</strong>
              <small>{{ formatConversationTime(conversation.update_time) }}</small>
            </span>
            <v-btn
              icon="mdi-close"
              size="x-small"
              variant="text"
              :aria-label="$t('chat.deleteConversation')"
              @click.stop="deleteConversation(conversation.id)"
            />
          </button>

          <div v-if="historyLoading && !conversations.length" class="conversation-state">
            <v-progress-circular indeterminate size="24" width="2" color="primary" />
            <span>{{ $t('common.loading') }}</span>
          </div>
          <div v-else-if="!conversations.length" class="conversation-state">
            <v-icon icon="mdi-message-plus-outline" size="26" />
            <span>{{ $t('chat.noConversation') }}</span>
          </div>
        </div>
      </aside>

      <main class="chat-surface ib-panel">
        <v-alert
          v-if="historyError"
          type="error"
          variant="tonal"
          density="compact"
          closable
          class="chat-alert"
        >
          {{ historyError }}
          <template #append>
            <v-btn size="small" variant="text" @click="retryHistory">{{ $t('common.retry') }}</v-btn>
          </template>
        </v-alert>

        <div
          ref="messageContainer"
          class="chat-messages scroll-container"
          role="log"
          aria-live="polite"
          :aria-label="$t('chat.messages')"
        >
          <div v-if="historyLoading && !messages.length" class="chat-empty">
            <v-progress-circular indeterminate color="primary" />
            <span>{{ $t('chat.loadingHistory') }}</span>
          </div>

          <div v-else-if="!messages.length" class="chat-empty">
            <span class="chat-empty__icon"><v-icon icon="mdi-creation-outline" size="34" /></span>
            <h2>{{ $t('chat.hello') }}</h2>
            <p>{{ $t('chat.intro') }}</p>
            <div class="suggestion-list">
              <button v-for="suggestion in suggestions" :key="suggestion" type="button" @click="sendSuggestion(suggestion)">
                <span>{{ $t(suggestion) }}</span>
                <v-icon icon="mdi-arrow-up-right" size="15" />
              </button>
            </div>
          </div>

          <article
            v-for="(message, index) in messages"
            v-else
            :key="index"
            class="chat-message"
            :class="`chat-message--${message.role}`"
          >
            <RoleCardAvatar
              v-if="message.role === 'assistant'"
              :slug="messageRoleCardSlug(message, activeRoleCard?.slug)"
              :size="32"
              :icon-size="17"
              icon="mdi-creation-outline"
            />

            <div class="message-bubble">
              <div v-if="message.metadata?.source === 'reminder'" class="message-context">
                <v-icon icon="mdi-bell-ring-outline" size="15" />
                <span>{{ $t('reminders.chatChip') }}</span>
                <v-btn size="x-small" variant="text" @click="goReminderDetail(message.metadata)">
                  {{ $t('reminders.viewDetail') }}
                </v-btn>
              </div>
              <div v-else-if="message.metadata?.source === 'task_relative_reminder'" class="message-context">
                <v-icon icon="mdi-bell-outline" size="15" />
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

              <div v-if="message.images?.length" class="message-images">
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

              <div v-if="message.streaming && !message.content" class="typing-state">
                <v-progress-circular indeterminate size="16" width="2" color="primary" />
                <span>{{ $t('chat.thinking') }}</span>
              </div>
              <div v-else-if="message.role === 'user'" class="message-text" v-text="message.content" />
              <div
                v-else-if="['reminder', 'task_relative_reminder'].includes(message.metadata?.source)"
                class="message-text"
                v-text="message.content"
              />
              <div
                v-else
                :key="`markdown-${index}-${message.streaming ? 1 : 0}`"
                class="message-markdown"
                v-html="renderMarkdown(message.content)"
              />

              <div v-if="message.role === 'assistant' && message.credits" class="message-meta">
                <v-icon icon="mdi-lightning-bolt-outline" size="13" />
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

              <div v-if="!message.streaming && message.taskData" class="message-task-action">
                <span>
                  <v-icon icon="mdi-clipboard-list-outline" size="17" />
                  {{ $t('chat.subtaskCount', { n: message.taskData.subtasks?.length || 0 }) }}
                </span>
                <v-btn
                  v-if="!message.taskSaved"
                  size="small"
                  color="primary"
                  variant="tonal"
                  prepend-icon="mdi-plus"
                  :loading="message.saving"
                  @click="saveTaskFromChat(index)"
                >
                  {{ $t('chat.addToTasks') }}
                </v-btn>
                <v-chip v-else size="small" color="success" variant="tonal" prepend-icon="mdi-check">
                  {{ $t('chat.added') }}
                </v-chip>
              </div>
            </div>
          </article>
        </div>

        <div class="chat-composer" :class="{ 'chat-composer--drag': dragActive }">
          <div v-if="selectedImages.length" class="composer-images">
            <div v-for="(image, index) in selectedImages" :key="index">
              <img :src="image.dataUrl" :alt="$t('chat.imageNumber', { n: index + 1 })" />
              <button type="button" :aria-label="$t('chat.removeImage')" @click="removeImage(index)">
                <v-icon icon="mdi-close" size="13" />
              </button>
            </div>
          </div>

          <div
            class="composer-row"
            @dragover.prevent="onDragOver"
            @dragenter.prevent="dragActive = true"
            @dragleave="onDragLeave"
            @drop.prevent="onDrop"
          >
            <input
              ref="imageInput"
              class="visually-hidden"
              type="file"
              accept="image/*"
              multiple
              @change="onImagesSelected"
            />
            <v-btn
              icon="mdi-image-outline"
              variant="text"
              :aria-label="$t('chat.addImage')"
              :disabled="loading || selectedImages.length >= 5"
              @click="imageInput?.click()"
            />
            <v-textarea
              v-model="input"
              :placeholder="$t('chat.placeholder')"
              rows="1"
              max-rows="6"
              auto-grow
              hide-details
              variant="solo-filled"
              flat
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
      </main>
    </div>

    <v-dialog v-model="previewOpen" max-width="min(900px, 92vw)" @click:outside="previewOpen = false">
      <v-card class="image-preview-dialog">
        <v-btn icon="mdi-close" variant="tonal" :aria-label="$t('common.close')" @click="previewOpen = false" />
        <v-img :src="previewUrl" contain max-height="82vh" />
      </v-card>
    </v-dialog>
  </section>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import RoleCardAvatar from '@/components/RoleCardAvatar.vue'
import { useChatSession } from '@/composables/useChatSession'
import { messageRoleCardSlug } from '@/services/roleCardVisuals'
import { notifyTasksChanged } from '@/services/taskSync'

const router = useRouter()
const { t } = useI18n()
const suggestions = ['chat.suggestion1', 'chat.suggestion2', 'chat.suggestion3', 'chat.suggestion4']

const {
  activeConversationId,
  activeRoleCard,
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
  saveTaskFromChat,
  selectedImages,
  sendMessage,
  stopGeneration,
  switchConversation,
} = useChatSession({ extractTasks: true, afterTaskSaved: notifyTasksChanged })

function formatConversationTime(value) {
  if (!value) return ''
  const date = new Date(value)
  const now = new Date()
  if (date.toDateString() === now.toDateString()) {
    return `${t('chat.todayPrefix')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  }
  return t('common.monthDay', { month: date.getMonth() + 1, day: date.getDate() })
}

function sendSuggestion(key) {
  input.value = t(key)
  sendMessage()
}

function goReminderDetail(metadata) {
  if (metadata?.digest_id) router.push({ path: '/reminders', query: { tab: 'history', digest: metadata.digest_id } })
}

function goTaskReminderDetail(metadata) {
  if (metadata?.task_id) router.push({ path: '/tasks', query: { focus: metadata.task_id } })
}
</script>

<style scoped>
.chat-page { display: flex; flex-direction: column; }
.chat-header { align-items: center; }
.chat-layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); min-height: min(720px, calc(100vh - 196px)); gap: 16px; }
.conversation-panel { display: flex; min-height: 0; flex-direction: column; overflow: hidden; }
.conversation-panel__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px; border-bottom: 1px solid var(--ib-border); }
.conversation-panel__header > div { display: grid; gap: 2px; }
.conversation-panel__header strong { color: var(--ib-text); font-size: 13px; }
.conversation-panel__header small { color: var(--ib-text-muted); font-size: 10px; }
.conversation-list { flex: 1; min-height: 0; overflow-y: auto; padding: 8px; }
.conversation-item { width: 100%; display: grid; grid-template-columns: 18px minmax(0, 1fr) 28px; align-items: center; gap: 8px; padding: 10px 8px; border: 0; border-radius: var(--ib-radius-sm); color: var(--ib-text-secondary); background: transparent; cursor: pointer; text-align: left; }
.conversation-item:hover { background: var(--ib-surface-subtle); }
.conversation-item--active { color: var(--ib-primary-strong); background: var(--ib-primary-soft); }
.conversation-item > span { display: grid; min-width: 0; gap: 3px; }
.conversation-item strong { overflow: hidden; font-size: 11px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.conversation-item small { color: var(--ib-text-muted); font-size: 9px; }
.conversation-state { display: grid; min-height: 170px; place-items: center; align-content: center; gap: 10px; padding: 18px; color: var(--ib-text-muted); font-size: 11px; text-align: center; }
.chat-surface { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; min-width: 0; min-height: 0; overflow: hidden; }
.chat-alert { margin: 12px 12px 0; }
.chat-messages { min-height: 0; overflow-y: auto; padding: clamp(18px, 3vw, 34px); }
.chat-empty { display: grid; min-height: 100%; place-items: center; align-content: center; gap: 10px; color: var(--ib-text-secondary); text-align: center; }
.chat-empty__icon { display: grid; width: 64px; height: 64px; place-items: center; border-radius: 20px; color: var(--ib-primary-strong); background: var(--ib-primary-soft); }
.chat-empty h2 { margin: 7px 0 0; color: var(--ib-text); font-size: 18px; }
.chat-empty p { max-width: 470px; margin: 0; line-height: 1.55; }
.suggestion-list { width: min(100%, 560px); display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
.suggestion-list button { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 11px 12px; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-sm); color: var(--ib-text-secondary); background: var(--ib-surface); cursor: pointer; text-align: left; }
.suggestion-list button:hover { border-color: var(--ib-primary); color: var(--ib-primary-strong); background: var(--ib-primary-soft); }
.chat-message { display: flex; align-items: flex-start; gap: 9px; margin: 0 auto 18px; max-width: 900px; }
.chat-message--user { justify-content: flex-end; }
.message-bubble { min-width: 0; max-width: min(82%, 760px); overflow: hidden; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-md); color: var(--ib-text); background: var(--ib-surface-subtle); }
.chat-message--assistant .message-bubble { background: var(--ib-surface); }
.chat-message--user .message-bubble { border-color: color-mix(in srgb, var(--ib-primary) 32%, var(--ib-border)); background: var(--ib-primary-soft); }
.message-text, .message-markdown, .typing-state { padding: 12px 14px; font-size: 13px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.typing-state { display: flex; align-items: center; gap: 8px; color: var(--ib-text-secondary); }
.message-context { display: flex; align-items: center; gap: 7px; min-height: 32px; padding: 4px 7px 4px 10px; border-bottom: 1px solid var(--ib-border); color: var(--ib-primary-strong); font-size: 10px; font-weight: 700; }
.message-context .v-btn { margin-left: auto; }
.message-images { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; padding: 10px 10px 0; }
.message-images button { overflow: hidden; padding: 0; border: 1px solid var(--ib-border); border-radius: 9px; background: transparent; cursor: zoom-in; }
.message-images img { display: block; width: 128px; max-width: 100%; height: 96px; object-fit: cover; }
.message-meta { display: flex; align-items: center; justify-content: flex-end; gap: 4px; padding: 6px 10px; border-top: 1px solid var(--ib-border); color: var(--ib-text-muted); font-size: 9px; }
.message-task-action { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 10px; border-top: 1px solid var(--ib-border); }
.message-task-action > span { display: flex; align-items: center; gap: 5px; color: var(--ib-text-secondary); font-size: 10px; }
.message-markdown :deep(p) { margin: 0 0 .75em; }
.message-markdown :deep(p:last-child) { margin-bottom: 0; }
.message-markdown :deep(pre) { max-width: 100%; overflow-x: auto; padding: 12px; border-radius: 8px; background: var(--ib-surface-subtle); }
.message-markdown :deep(code) { font-family: 'SFMono-Regular', Consolas, monospace; font-size: .9em; }
.message-markdown :deep(a) { color: var(--ib-primary-strong); }
.message-markdown :deep(.katex-display) { max-width: 100%; overflow-x: auto; overflow-y: hidden; }
.chat-composer { padding: 12px 14px; border-top: 1px solid var(--ib-border); background: var(--ib-surface); }
.composer-row { display: flex; align-items: flex-end; gap: 8px; padding: 6px; border: 1px solid var(--ib-border-strong); border-radius: var(--ib-radius-md); background: var(--ib-surface-subtle); transition: border-color var(--ib-duration-normal), box-shadow var(--ib-duration-normal); }
.composer-row:focus-within, .chat-composer--drag .composer-row { border-color: var(--ib-primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ib-primary) 15%, transparent); }
.composer-row :deep(.v-field) { background: transparent !important; box-shadow: none !important; }
.composer-images { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.composer-images > div { position: relative; }
.composer-images img { display: block; width: 62px; height: 62px; border: 1px solid var(--ib-border); border-radius: 9px; object-fit: cover; }
.composer-images button { position: absolute; top: -5px; right: -5px; display: grid; width: 20px; height: 20px; place-items: center; padding: 0; border: 1px solid var(--ib-border); border-radius: 50%; color: var(--ib-text); background: var(--ib-surface); cursor: pointer; }
.chat-composer > small { display: block; margin-top: 7px; color: var(--ib-text-muted); font-size: 9px; text-align: center; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; }
.image-preview-dialog { position: relative; overflow: hidden; background: var(--ib-surface) !important; }
.image-preview-dialog > .v-btn { position: absolute; z-index: 1; top: 10px; right: 10px; }

@media (max-width: 800px) {
  .chat-header { align-items: flex-start; }
  .chat-layout { grid-template-columns: 1fr; min-height: calc(100dvh - 226px); }
  .conversation-panel { min-height: auto; }
  .conversation-panel__header { padding: 10px 12px; }
  .conversation-list { display: flex; gap: 6px; overflow-x: auto; padding: 8px; }
  .conversation-item { min-width: 190px; width: auto; }
  .conversation-state { min-width: 100%; min-height: 58px; grid-auto-flow: column; }
  .chat-surface { min-height: 620px; }
  .suggestion-list { grid-template-columns: 1fr; }
  .message-bubble { max-width: 88%; }
}

@media (max-width: 520px) {
  .chat-page { padding-inline: 10px; }
  .chat-messages { padding: 18px 10px; }
  .chat-message { gap: 6px; }
  .message-bubble { max-width: 91%; }
  .message-images img { width: 104px; height: 82px; }
  .chat-composer { padding: 10px; }
}
</style>
