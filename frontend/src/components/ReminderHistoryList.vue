<template>
  <div class="history-list">
    <div v-if="initialLoading" class="panel-loading">
      <v-progress-circular indeterminate color="primary" size="36" />
    </div>

    <v-alert v-else-if="loadError" type="error" variant="tonal" class="mb-4">
      {{ loadError }}
      <v-btn size="small" variant="text" class="ml-2" @click="reload">{{ $t('common.retry') }}</v-btn>
    </v-alert>

    <!-- 空状态 -->
    <div v-else-if="items.length === 0" class="empty-state">
      <v-icon icon="mdi-bell-sleep-outline" size="64" color="grey-lighten-1" />
      <div class="empty-title">{{ $t('reminders.historyEmptyTitle') }}</div>
      <div class="empty-desc">{{ $t('reminders.historyEmptyDesc') }}</div>
      <div class="empty-actions">
        <v-btn color="primary" variant="tonal" prepend-icon="mdi-clipboard-list-outline" @click="goTasks">
          {{ $t('reminders.goTasks') }}
        </v-btn>
        <v-btn variant="outlined" prepend-icon="mdi-calendar-month" @click="goCalendar">
          {{ $t('reminders.goCalendar') }}
        </v-btn>
      </div>
    </div>

    <template v-else>
      <v-alert v-if="anchorNotFound" type="info" variant="tonal" density="compact" class="mb-4">
        {{ $t('reminders.digestNotFound') }}
      </v-alert>

      <v-card
        v-for="item in items"
        :key="item.id"
        :id="`digest-${item.id}`"
        class="digest-card"
        :class="{ 'digest-card--anchored': anchoredId === item.id }"
        rounded="xl"
        elevation="0"
      >
        <div class="digest-head" @click="toggleExpand(item.id)">
          <div class="digest-head__main">
            <div class="digest-subject" v-text="item.subject || $t('reminders.noSubject')" />
            <div class="digest-meta">
              <span>{{ item.local_date }}</span>
              <span v-if="item.generation_mode" class="digest-mode">
                {{ item.generation_mode === 'llm' ? $t('reminders.modeLlm') : $t('reminders.modeTemplate') }}
              </span>
            </div>
          </div>
          <div class="digest-channels">
            <v-chip
              v-for="channel in ['chat', 'email']"
              :key="channel"
              size="x-small"
              :color="statusColor(deliveryFor(item, channel)?.status)"
              variant="tonal"
              :prepend-icon="channel === 'chat' ? 'mdi-message-text-outline' : 'mdi-email-outline'"
            >
              {{ statusLabel(deliveryFor(item, channel)?.status, channel) }}
            </v-chip>
          </div>
          <v-icon :icon="expandedIds.has(item.id) ? 'mdi-chevron-up' : 'mdi-chevron-down'" color="grey" />
        </div>

        <div v-if="expandedIds.has(item.id)" class="digest-body">
          <div v-if="item.body_text" v-text="item.body_text" class="reminder-plain-text" />

          <div v-if="item.item_snapshot?.length" class="snapshot-list">
            <div v-for="(snap, idx) in item.item_snapshot" :key="idx" class="snapshot-item">
              <v-chip size="x-small" variant="outlined" class="mr-2">{{ itemTypeLabel(snap.item_type) }}</v-chip>
              <span class="snapshot-title" v-text="snap.title" />
              <span v-if="snap.due_date" class="snapshot-due">{{ snap.due_date }}</span>
              <v-chip v-if="snap.cadence_label" size="x-small" color="primary" variant="tonal" class="ml-2">
                {{ snap.cadence_label }}
              </v-chip>
            </div>
          </div>

          <div v-for="d in errorDeliveries(item)" :key="d.channel" class="delivery-error">
            {{ channelName(d.channel) }}：{{ friendlyErrorText(d.last_error_code) }}
          </div>
        </div>
      </v-card>

      <div v-if="hasMore" class="load-more">
        <v-btn variant="outlined" :loading="loadingMore" :disabled="loadingMore" @click="loadMore">
          {{ $t('reminders.loadMore') }}
        </v-btn>
      </div>
    </template>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getHistory, ApiError } from '@/services/reminders'

const PAGE_SIZE = 20

const props = defineProps({
  digestAnchor: { type: Number, default: null },
})
const emit = defineEmits(['unauthorized'])

const router = useRouter()
const { t } = useI18n()

const items = ref([])
const expandedIds = ref(new Set())
const initialLoading = ref(true)
const loadingMore = ref(false)
const loadError = ref('')
const hasMore = ref(false)
const anchorNotFound = ref(false)
const anchoredId = ref(null)

let offset = 0
let anchorResolved = false

function deliveryFor(item, channel) {
  if (!Array.isArray(item.deliveries)) return null
  return item.deliveries.find((d) => d.channel === channel) || null
}

function errorDeliveries(item) {
  if (!Array.isArray(item.deliveries)) return []
  return item.deliveries.filter((d) => d.last_error_code)
}

function statusColor(status) {
  const map = {
    delivered: 'success',
    pending: 'blue-grey',
    attempting: 'blue-grey',
    retryable: 'warning',
    failed: 'error',
    skipped: 'grey',
  }
  return map[status] || 'grey'
}

function statusLabel(status, channel) {
  const name = channelName(channel)
  if (!status) return `${name} · ${t('reminders.deliveryNone')}`
  const key = {
    delivered: 'deliveryDelivered',
    pending: 'deliveryPending',
    attempting: 'deliveryAttempting',
    retryable: 'deliveryRetryable',
    failed: 'deliveryFailed',
    skipped: 'deliverySkipped',
  }[status]
  return `${name} · ${key ? t(`reminders.${key}`) : t('reminders.deliveryUnknown')}`
}

function channelName(channel) {
  return channel === 'email' ? t('reminders.channelEmail') : t('reminders.channelChat')
}

// 错误码 → 用户文案；未知错误统一兜底，绝不展示原始错误
const ERROR_TEXT_KEYS = {
  smtp_auth_failed: 'errorSmtpAuth',
  smtp_transient_failure: 'errorSmtpTransient',
  smtp_recipient_rejected: 'errorSmtpRecipient',
  smtp_timeout: 'errorSmtpTimeout',
  channel_disabled: 'errorChannelDisabled',
}

function friendlyErrorText(code) {
  const key = ERROR_TEXT_KEYS[code]
  return key ? t(`reminders.${key}`) : t('reminders.errorGeneric')
}

function itemTypeLabel(type) {
  const map = { task: 'itemTypeTask', subtask: 'itemTypeSubtask', deadline: 'itemTypeDeadline' }
  return t(`reminders.${map[type] || 'itemTypeOther'}`)
}

function toggleExpand(id) {
  const next = new Set(expandedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedIds.value = next
}

async function fetchPage() {
  const data = await getHistory({ limit: PAGE_SIZE, offset })
  const page = Array.isArray(data?.items) ? data.items : []
  const seen = new Set(items.value.map((i) => i.id))
  const fresh = page.filter((i) => !seen.has(i.id))
  items.value = [...items.value, ...fresh]
  offset += page.length
  hasMore.value = page.length >= PAGE_SIZE
  return page
}

async function reload() {
  items.value = []
  expandedIds.value = new Set()
  offset = 0
  anchorResolved = false
  anchorNotFound.value = false
  initialLoading.value = true
  loadError.value = ''
  try {
    await fetchPage()
  } catch (err) {
    if (handleAuthError(err)) return
    loadError.value = err instanceof ApiError && err.kind === 'transport'
      ? t('reminders.networkError')
      : t('reminders.loadFailed')
    return
  } finally {
    initialLoading.value = false
  }
  // 注意在 initialLoading 复位后再做定位，否则首屏无法连续翻页查找 digest
  await resolveAnchor()
}

async function loadMore() {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  try {
    await fetchPage()
    await resolveAnchor()
  } catch (err) {
    if (handleAuthError(err)) return
    // 失败不改变 offset，下次重试同一页
  } finally {
    loadingMore.value = false
  }
}

// digest 精确定位：在已加载记录中查找 → 展开并滚动；未找到且还有下一页则继续分页
async function resolveAnchor() {
  if (anchorResolved || props.digestAnchor == null) return
  const found = items.value.find((i) => i.id === props.digestAnchor)
  if (found) {
    anchorResolved = true
    anchoredId.value = found.id
    expandedIds.value = new Set([...expandedIds.value, found.id])
    await nextTick()
    document.getElementById(`digest-${found.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    return
  }
  if (hasMore.value && !initialLoading.value) {
    // 由 loadMore 继续；首屏加载时直接连翻
    if (!loadingMore.value) await loadMore()
    return
  }
  if (!hasMore.value) {
    anchorResolved = true
    anchorNotFound.value = true
  }
}

function handleAuthError(err) {
  if (err instanceof ApiError && err.status === 401) {
    emit('unauthorized')
    return true
  }
  return false
}

function goTasks() {
  router.push('/tasks')
}
function goCalendar() {
  router.push('/calendar')
}

watch(() => props.digestAnchor, () => {
  anchorResolved = false
  anchorNotFound.value = false
  resolveAnchor()
})

onMounted(reload)
</script>

<style scoped>
.panel-loading {
  display: flex;
  justify-content: center;
  padding: 60px 0;
}
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 20px;
  text-align: center;
}
.empty-title {
  font-size: 16px;
  font-weight: 600;
  color: #3a4254;
  margin-top: 14px;
}
.empty-desc {
  color: #8c94a3;
  font-size: 13px;
  margin-top: 6px;
  max-width: 420px;
}
.empty-actions {
  display: flex;
  gap: 12px;
  margin-top: 20px;
}
.digest-card {
  border: 1px solid #e8ebf0;
  margin-bottom: 12px;
  transition: border-color 0.2s;
}
.digest-card--anchored {
  border-color: rgb(var(--v-theme-primary));
}
.digest-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  cursor: pointer;
}
.digest-head__main {
  flex: 1;
  min-width: 0;
}
.digest-subject {
  font-weight: 600;
  color: #232a3a;
  font-size: 14px;
}
.digest-meta {
  display: flex;
  gap: 10px;
  color: #8c94a3;
  font-size: 12px;
  margin-top: 3px;
}
.digest-mode {
  color: #6c7a96;
}
.digest-channels {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.digest-body {
  padding: 0 18px 16px;
  border-top: 1px solid #f0f2f5;
}
.reminder-plain-text {
  white-space: pre-wrap;
  color: #3a4254;
  font-size: 13px;
  line-height: 1.7;
  padding: 14px 0 4px;
}
.snapshot-list {
  margin-top: 10px;
  border-top: 1px dashed #e8ebf0;
  padding-top: 10px;
}
.snapshot-item {
  display: flex;
  align-items: center;
  padding: 6px 0;
  font-size: 13px;
}
.snapshot-title {
  color: #2e3545;
}
.snapshot-due {
  color: #8c94a3;
  font-size: 12px;
  margin-left: 8px;
}
.delivery-error {
  margin-top: 8px;
  color: #b26a00;
  font-size: 12px;
}
.load-more {
  display: flex;
  justify-content: center;
  padding: 12px 0 24px;
}
</style>
