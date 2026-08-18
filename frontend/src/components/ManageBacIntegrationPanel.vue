<template>
  <section class="managebac-panel">
    <v-alert
      v-if="errorMessage"
      type="error"
      variant="tonal"
      density="compact"
      closable
      class="mb-5"
      @click:close="errorMessage = ''"
    >
      {{ errorMessage }}
    </v-alert>
    <v-alert
      v-if="successMessage"
      type="success"
      variant="tonal"
      density="compact"
      closable
      class="mb-5"
      @click:close="successMessage = ''"
    >
      {{ successMessage }}
    </v-alert>

    <div v-if="loading" class="managebac-loading">
      <v-progress-circular indeterminate color="primary" size="34" />
      <span>{{ $t('managebac.loading') }}</span>
    </div>

    <template v-else-if="!connection.connected">
      <div class="intro-card">
        <v-avatar color="indigo" variant="tonal" size="48">
          <v-icon icon="mdi-calendar-sync-outline" size="27" />
        </v-avatar>
        <div>
          <div class="text-subtitle-1 font-weight-bold">{{ $t('managebac.connectTitle') }}</div>
          <p>{{ $t('managebac.connectDescription') }}</p>
        </div>
      </div>

      <v-text-field
        v-model="feedUrl"
        :label="$t('managebac.feedUrl')"
        :placeholder="$t('managebac.feedPlaceholder')"
        :type="showUrl ? 'text' : 'password'"
        :append-inner-icon="showUrl ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
        variant="outlined"
        autocomplete="off"
        spellcheck="false"
        :disabled="busy"
        @click:append-inner="showUrl = !showUrl"
      />

      <v-alert type="warning" variant="tonal" density="compact" class="mb-5">
        {{ $t('managebac.securityNotice') }}
      </v-alert>

      <div class="connect-actions">
        <v-btn
          variant="outlined"
          prepend-icon="mdi-open-in-new"
          href="https://help.managebac.com/hc/en-us/articles/360018804712-Managing-your-Calendars"
          target="_blank"
          rel="noopener noreferrer"
        >
          {{ $t('managebac.howToGet') }}
        </v-btn>
        <v-spacer />
        <v-btn
          variant="tonal"
          color="primary"
          :loading="operation === 'validate'"
          :disabled="!canSubmit || busy"
          @click="validateFeed"
        >
          {{ $t('managebac.validate') }}
        </v-btn>
        <v-btn
          color="primary"
          :loading="operation === 'connect'"
          :disabled="!canSubmit || busy"
          @click="connectFeed"
        >
          {{ $t('managebac.connect') }}
        </v-btn>
      </div>

      <div v-if="validation" class="validation-card">
        <div class="validation-card__heading">
          <v-icon icon="mdi-check-decagram-outline" color="success" />
          <div>
            <strong>{{ $t('managebac.validationSuccess') }}</strong>
            <small>{{ validation.feed_host }}</small>
          </div>
        </div>
        <div class="validation-stats">
          <span>{{ $t('managebac.totalItems', { n: validation.total_items }) }}</span>
          <span>{{ $t('managebac.importableItems', { n: validation.importable_items }) }}</span>
          <span>{{ $t('managebac.skippedItems', { n: validation.skipped_items }) }}</span>
        </div>
        <div v-if="validation.preview?.length" class="preview-list">
          <div v-for="item in validation.preview" :key="`${item.title}-${item.deadline}`">
            <v-icon icon="mdi-clipboard-text-outline" size="17" />
            <span><strong>{{ item.title }}</strong><small>{{ item.subject || $t('common.uncategorized') }} · {{ formatDeadline(item.deadline) }}</small></span>
          </div>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="status-card">
        <div class="status-card__main">
          <v-avatar color="indigo" variant="tonal" size="48">
            <v-icon icon="mdi-school-outline" size="27" />
          </v-avatar>
          <div>
            <div class="d-flex align-center ga-2 flex-wrap">
              <strong>{{ connection.feed_host }}</strong>
              <v-chip size="x-small" variant="tonal" :color="statusColor">
                {{ statusLabel }}
              </v-chip>
            </div>
            <small>{{ $t('managebac.privateFeedStored') }}</small>
          </div>
        </div>
        <v-switch
          :model-value="connection.enabled"
          color="primary"
          hide-details
          :disabled="busy || connection.status === 'reconnect_required'"
          :aria-label="$t('managebac.autoSync')"
          @update:model-value="toggleEnabled"
        />
      </div>

      <v-alert v-if="connection.status === 'reconnect_required'" type="warning" variant="tonal" class="mb-5">
        {{ $t('managebac.reconnectRequired') }}
      </v-alert>
      <v-alert v-else-if="connection.last_error_code" type="warning" variant="tonal" density="compact" class="mb-5">
        {{ integrationErrorMessage(connection.last_error_code) }}
      </v-alert>

      <div v-if="connection.status === 'reconnect_required'" class="reconnect-card">
        <strong>{{ $t('managebac.reconnectTitle') }}</strong>
        <p>{{ $t('managebac.reconnectDescription') }}</p>
        <v-text-field
          v-model="feedUrl"
          :label="$t('managebac.feedUrl')"
          :placeholder="$t('managebac.feedPlaceholder')"
          :type="showUrl ? 'text' : 'password'"
          :append-inner-icon="showUrl ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
          variant="outlined"
          density="comfortable"
          autocomplete="off"
          spellcheck="false"
          :disabled="busy"
          @click:append-inner="showUrl = !showUrl"
        />
        <div class="d-flex justify-end">
          <v-btn
            color="primary"
            :loading="operation === 'connect'"
            :disabled="!canSubmit || busy"
            @click="connectFeed"
          >
            {{ $t('managebac.reconnectAction') }}
          </v-btn>
        </div>
      </div>

      <div class="sync-grid">
        <div><span>{{ $t('managebac.lastSuccess') }}</span><strong>{{ formatDateTime(connection.last_success_at) }}</strong></div>
        <div><span>{{ $t('managebac.nextSync') }}</span><strong>{{ connection.enabled ? formatDateTime(connection.next_sync_at) : $t('managebac.paused') }}</strong></div>
        <div><span>{{ $t('managebac.interval') }}</span><strong>{{ $t('managebac.minutes', { n: connection.sync_interval_minutes }) }}</strong></div>
      </div>

      <div class="connected-actions">
        <v-btn
          color="primary"
          prepend-icon="mdi-sync"
          :loading="operation === 'sync'"
          :disabled="busy"
          @click="syncNow"
        >
          {{ $t('managebac.syncNow') }}
        </v-btn>
        <v-btn
          variant="outlined"
          color="error"
          prepend-icon="mdi-link-off"
          :disabled="busy"
          @click="disconnectDialog = true"
        >
          {{ $t('managebac.disconnect') }}
        </v-btn>
      </div>

      <div class="runs-section">
        <div class="runs-section__heading">
          <strong>{{ $t('managebac.recentRuns') }}</strong>
          <v-btn icon="mdi-refresh" size="x-small" variant="text" :aria-label="$t('managebac.refresh')" @click="loadRuns" />
        </div>
        <div v-if="!runs.length" class="runs-empty">{{ $t('managebac.noRuns') }}</div>
        <div v-for="run in runs" v-else :key="run.id" class="run-row">
          <v-icon :icon="run.status === 'success' ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline'" :color="run.status === 'success' ? 'success' : 'warning'" size="19" />
          <div>
            <strong>{{ triggerLabel(run.trigger) }}</strong>
            <small>{{ formatDateTime(run.started_at) }}</small>
          </div>
          <span v-if="run.status === 'success'">
            {{ $t('managebac.runSummary', { added: run.added_count, updated: run.updated_count }) }}
          </span>
          <span v-else class="text-error">{{ integrationErrorMessage(run.error_code) }}</span>
        </div>
      </div>
    </template>

    <v-dialog v-model="disconnectDialog" max-width="500">
      <v-card rounded="xl">
        <v-card-title>{{ $t('managebac.disconnectTitle') }}</v-card-title>
        <v-card-text>
          <p>{{ $t('managebac.disconnectDescription') }}</p>
          <v-checkbox v-model="deleteImportedTasks" color="error" hide-details>
            <template #label>{{ $t('managebac.deleteImportedTasks') }}</template>
          </v-checkbox>
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" @click="disconnectDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="error" :loading="operation === 'disconnect'" @click="disconnectFeed">{{ $t('managebac.confirmDisconnect') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ApiError,
  createDisconnectedManageBacState,
  isManageBacFeedCandidate,
  managebacApi,
  normalizeManageBacConnection,
} from '@/services/managebac'
import { notifyTasksChanged } from '@/services/taskSync'

const emit = defineEmits(['unauthorized'])
const { t, te, locale } = useI18n()

const loading = ref(true)
const operation = ref('')
const connection = ref(createDisconnectedManageBacState())
const feedUrl = ref('')
const showUrl = ref(false)
const validation = ref(null)
const runs = ref([])
const errorMessage = ref('')
const successMessage = ref('')
const disconnectDialog = ref(false)
const deleteImportedTasks = ref(false)

const busy = computed(() => Boolean(operation.value))
const canSubmit = computed(() => isManageBacFeedCandidate(feedUrl.value))
const statusColor = computed(() => ({ active: 'success', paused: 'grey', error: 'warning', reconnect_required: 'error' }[connection.value.status] || 'primary'))
const statusLabel = computed(() => t(`managebac.status.${connection.value.status || 'pending'}`))

function setError(error) {
  if (error instanceof ApiError && error.status === 401) {
    emit('unauthorized')
    return
  }
  errorMessage.value = error instanceof ApiError
    ? integrationErrorMessage(error.code, error.kind === 'transport' ? 'network' : null)
    : t('managebac.unknownError')
}

const errorAliases = Object.freeze({
  invalid_url: 'invalidUrl',
  invalid_scheme: 'invalidUrl',
  embedded_credentials: 'invalidUrl',
  url_fragment: 'invalidUrl',
  missing_host: 'invalidUrl',
  invalid_port: 'invalidUrl',
  missing_path: 'invalidUrl',
  url_too_long: 'invalidUrl',
  host_not_allowed: 'invalidHost',
  unsafe_target: 'invalidHost',
  dns_failed: 'network',
  dns_empty: 'network',
  dns_invalid: 'network',
  network_error: 'network',
  too_many_redirects: 'network',
  redirect_without_location: 'network',
  feed_too_large: 'feedTooLarge',
  invalid_calendar: 'invalidCalendar',
  empty_calendar: 'invalidCalendar',
  credential_key_missing: 'serverConfiguration',
  credential_key_invalid: 'serverConfiguration',
  credential_decrypt_failed: 'reconnect',
  sync_rate_limited: 'inProgress',
  sync_in_progress: 'inProgress',
})

function integrationErrorMessage(code, alias = null) {
  const normalizedCode = String(code || '')
  let key = alias || errorAliases[normalizedCode]
  if (!key && normalizedCode === 'http_403') key = 'providerDenied'
  if (!key && /^http_(401|404|410)$/.test(normalizedCode)) key = 'reconnect'
  if (!key && /^http_/.test(normalizedCode)) key = 'network'
  const localeKey = key ? `managebac.errors.${key}` : ''
  if (localeKey && te(localeKey)) return t(localeKey)
  return normalizedCode
    ? t('managebac.syncFailedWithCode', { code: normalizedCode })
    : t('managebac.unknownError')
}

function formatDateTime(value) {
  if (!value) return t('managebac.never')
  const date = new Date(value.endsWith?.('Z') || /[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`)
  if (Number.isNaN(date.getTime())) return t('managebac.never')
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function formatDeadline(value) {
  if (!value) return t('managebac.never')
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return t('managebac.never')
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function triggerLabel(trigger) {
  return t(`managebac.trigger.${trigger || 'automatic'}`)
}

async function loadStatus() {
  loading.value = true
  try {
    connection.value = normalizeManageBacConnection(await managebacApi.status())
    if (connection.value.connected) await loadRuns()
  } catch (error) {
    setError(error)
  } finally {
    loading.value = false
  }
}

async function loadRuns() {
  try {
    const response = await managebacApi.runs(10)
    runs.value = response.items || []
  } catch (error) {
    setError(error)
  }
}

async function validateFeed() {
  operation.value = 'validate'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    validation.value = await managebacApi.validate(feedUrl.value.trim())
  } catch (error) {
    validation.value = null
    setError(error)
  } finally {
    operation.value = ''
  }
}

async function connectFeed() {
  operation.value = 'connect'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const response = await managebacApi.connect(feedUrl.value.trim())
    connection.value = normalizeManageBacConnection(response.connection)
    validation.value = response.validation
    feedUrl.value = ''
    showUrl.value = false
    successMessage.value = t('managebac.connectedSummary', {
      added: response.sync.added_count,
      updated: response.sync.updated_count,
    })
    notifyTasksChanged()
    await loadRuns()
  } catch (error) {
    setError(error)
  } finally {
    operation.value = ''
  }
}

async function syncNow() {
  operation.value = 'sync'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const result = await managebacApi.sync()
    if (result.status === 'success') {
      successMessage.value = t('managebac.syncedSummary', { added: result.added_count, updated: result.updated_count })
      notifyTasksChanged()
    } else {
      errorMessage.value = t('managebac.syncFailedWithCode', { code: result.error_code || 'unknown' })
    }
    connection.value = normalizeManageBacConnection(await managebacApi.status())
    await loadRuns()
  } catch (error) {
    setError(error)
  } finally {
    operation.value = ''
  }
}

async function toggleEnabled(enabled) {
  operation.value = 'toggle'
  errorMessage.value = ''
  try {
    connection.value = normalizeManageBacConnection(await managebacApi.setEnabled(Boolean(enabled)))
    successMessage.value = enabled ? t('managebac.resumed') : t('managebac.pausedSuccess')
  } catch (error) {
    setError(error)
  } finally {
    operation.value = ''
  }
}

async function disconnectFeed() {
  operation.value = 'disconnect'
  errorMessage.value = ''
  try {
    const result = await managebacApi.disconnect(deleteImportedTasks.value)
    connection.value = createDisconnectedManageBacState(connection.value.sync_interval_minutes)
    runs.value = []
    validation.value = null
    disconnectDialog.value = false
    successMessage.value = t('managebac.disconnectedSummary', { n: result.deleted_tasks })
    if (deleteImportedTasks.value) notifyTasksChanged()
    deleteImportedTasks.value = false
  } catch (error) {
    setError(error)
  } finally {
    operation.value = ''
  }
}

onMounted(loadStatus)
</script>

<style scoped>
.managebac-panel { min-height: 280px; }
.managebac-loading { min-height: 260px; display: grid; place-content: center; justify-items: center; gap: 12px; color: #7a8394; }
.intro-card, .status-card { display: flex; align-items: center; gap: 15px; padding: 18px; margin-bottom: 22px; border: 1px solid #e5e8f2; border-radius: 17px; background: #f8f9fd; }
.intro-card p, .status-card small { display: block; margin-top: 4px; color: #7e8798; font-size: 13px; }
.status-card { justify-content: space-between; }
.status-card__main { display: flex; align-items: center; gap: 14px; min-width: 0; }
.connect-actions, .connected-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.validation-card { margin-top: 22px; padding: 18px; border: 1px solid #cfe8dc; border-radius: 16px; background: #f4fbf7; }
.reconnect-card { margin-bottom: 22px; padding: 18px; border: 1px solid #f1d7a8; border-radius: 16px; background: #fffaf0; }
.reconnect-card p { margin: 5px 0 15px; color: #7b7162; font-size: 13px; }
.validation-card__heading { display: flex; align-items: center; gap: 11px; }
.validation-card__heading small { display: block; color: #738177; }
.validation-stats { display: flex; gap: 15px; margin-top: 15px; color: #607064; font-size: 12px; flex-wrap: wrap; }
.preview-list { display: grid; gap: 9px; margin-top: 14px; }
.preview-list > div { display: flex; align-items: flex-start; gap: 9px; }
.preview-list span, .preview-list small { display: block; }
.preview-list small { margin-top: 2px; color: #7d887f; font-size: 11px; }
.sync-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
.sync-grid > div { padding: 15px; border: 1px solid #e8eaf0; border-radius: 14px; }
.sync-grid span, .sync-grid strong { display: block; }
.sync-grid span { margin-bottom: 6px; color: #8a92a1; font-size: 11px; }
.sync-grid strong { color: #2e3542; font-size: 13px; }
.runs-section { margin-top: 25px; padding-top: 20px; border-top: 1px solid #eceef3; }
.runs-section__heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.runs-empty { padding: 20px 0; color: #929aa8; text-align: center; font-size: 13px; }
.run-row { display: grid; grid-template-columns: 22px minmax(120px, 1fr) auto; align-items: center; gap: 9px; padding: 11px 0; border-bottom: 1px solid #f0f1f4; font-size: 12px; }
.run-row strong, .run-row small { display: block; }
.run-row small { margin-top: 2px; color: #929aa7; font-size: 10px; }
@media (max-width: 700px) {
  .sync-grid { grid-template-columns: 1fr; }
  .connect-actions .v-spacer { display: none; }
  .run-row { grid-template-columns: 22px 1fr; }
  .run-row > span { grid-column: 2; }
}
</style>
