<template>
  <div class="settings-panel">
    <div v-if="loading" class="panel-loading">
      <v-progress-circular indeterminate color="primary" size="36" />
    </div>

    <v-alert v-else-if="loadError" type="error" variant="tonal" class="mb-4">
      {{ loadError }}
      <v-btn size="small" variant="text" class="ml-2" @click="loadAll">{{ $t('common.retry') }}</v-btn>
    </v-alert>

    <template v-else>
      <!-- 总开关 -->
      <div class="setting-row">
        <div>
          <div class="setting-label">{{ $t('reminders.enabled') }}</div>
          <div class="setting-help">{{ $t('reminders.enabledHelp') }}</div>
        </div>
        <v-switch v-model="form.enabled" color="primary" hide-details :aria-label="$t('reminders.enabled')" />
      </div>

      <!-- 提醒内容语言 -->
      <div class="setting-row">
        <div>
          <div class="setting-label">{{ $t('reminders.language') }}</div>
          <div class="setting-help">{{ $t('reminders.languageHelp') }}</div>
        </div>
        <v-select
          v-model="form.language"
          :items="languageOptions"
          item-title="title"
          item-value="value"
          variant="outlined"
          density="compact"
          hide-details
          class="field-220"
          :disabled="!form.enabled"
        />
      </div>

      <!-- 时区 -->
      <div class="setting-row">
        <div>
          <div class="setting-label">{{ $t('reminders.timezone') }}</div>
          <div class="setting-help">{{ $t('reminders.timezoneHelp') }}</div>
        </div>
        <v-autocomplete
          v-model="form.timezone"
          :items="timezoneOptions"
          variant="outlined"
          density="compact"
          hide-details
          class="field-280"
          :disabled="!form.enabled"
          :no-data-text="$t('reminders.timezoneEmpty')"
        />
      </div>

      <!-- 每日派发时间（可编辑，HH:MM） -->
      <div class="setting-row">
        <div>
          <div class="setting-label">{{ $t('reminders.sendTime') }}</div>
          <div class="setting-help">{{ $t('reminders.sendTimeHelp') }}</div>
        </div>
        <v-text-field
          v-model="form.daily_dispatch_time"
          type="time"
          variant="outlined"
          density="compact"
          class="field-160"
          :disabled="!form.enabled"
          :error="!dispatchTimeValid"
          :error-messages="dispatchTimeValid ? '' : $t('reminders.sendTimeInvalid')"
          prepend-inner-icon="mdi-clock-outline"
        />
      </div>

      <!-- 提醒档位：基础档位只读 + 自定义逾期档位可增删 -->
      <div class="setting-row setting-row--top">
        <div>
          <div class="setting-label">{{ $t('reminders.cadence') }}</div>
          <div class="setting-help">{{ $t('reminders.cadenceHelp') }}</div>
        </div>
        <div class="cadence-editor">
          <div class="cadence-chips">
            <v-chip
              v-for="offset in baseCadenceOffsets"
              :key="'base-' + offset"
              size="small"
              variant="outlined"
              prepend-icon="mdi-lock-outline"
            >
              {{ cadenceLabel(offset) }}
            </v-chip>
            <v-chip
              v-for="offset in customCadenceOffsets"
              :key="'custom-' + offset"
              size="small"
              color="primary"
              variant="tonal"
              closable
              :close-icon="'mdi-close'"
              :disabled="!form.enabled"
              @click:close="removeCustomCadence(offset)"
            >
              {{ cadenceLabel(offset) }}
            </v-chip>
          </div>
          <div class="cadence-add">
            <v-text-field
              v-model="cadenceInput"
              type="number"
              min="2"
              max="365"
              density="compact"
              variant="outlined"
              hide-details
              :placeholder="$t('reminders.cadenceAddPlaceholder')"
              class="cadence-input"
              :disabled="!form.enabled"
              @keyup.enter="addCustomCadence"
            />
            <v-btn
              size="small"
              variant="text"
              color="primary"
              :disabled="!form.enabled || !canAddCadence"
              @click="addCustomCadence"
            >
              {{ $t('reminders.cadenceAdd') }}
            </v-btn>
          </div>
          <div v-if="cadenceError" class="cadence-error">{{ cadenceError }}</div>
        </div>
      </div>

      <!-- 任务级默认提醒（分钟偏移） -->
      <div class="setting-row setting-row--top">
        <div>
          <div class="setting-label">{{ $t('reminders.taskOffsets') }}</div>
          <div class="setting-help">{{ $t('reminders.taskOffsetsHelp') }}</div>
        </div>
        <ReminderOffsetsEditor
          v-model="form.default_task_reminder_offsets_minutes"
          :disabled="!form.enabled"
        />
      </div>

      <!-- 邮件渠道 -->
      <div class="setting-row">
        <div>
          <div class="setting-label">{{ $t('reminders.emailChannel') }}</div>
          <div class="setting-help">{{ $t('reminders.emailChannelHelp') }}</div>
        </div>
        <v-switch
          v-model="form.email_enabled"
          color="primary"
          hide-details
          :disabled="!form.enabled"
          :aria-label="$t('reminders.emailChannel')"
        />
      </div>

      <!-- 站内聊天渠道 -->
      <div class="setting-row">
        <div>
          <div class="setting-label">{{ $t('reminders.chatChannel') }}</div>
          <div class="setting-help">{{ $t('reminders.chatChannelHelp') }}</div>
        </div>
        <v-switch
          v-model="form.chat_enabled"
          color="primary"
          hide-details
          :disabled="!form.enabled"
          :aria-label="$t('reminders.chatChannel')"
        />
      </div>

      <!-- 提醒语气（角色卡） -->
      <div class="setting-row">
        <div>
          <div class="setting-label">{{ $t('reminders.roleCard') }}</div>
          <div class="setting-help">{{ currentRoleCardDescription }}</div>
        </div>
        <v-btn
          variant="outlined"
          prepend-icon="mdi-account-star-outline"
          :disabled="!form.enabled"
          @click="pickerOpen = true"
        >
          {{ currentRoleCardName }}
        </v-btn>
      </div>

      <!-- 保存区 -->
      <div class="save-bar">
        <span v-if="saveMessage" class="save-message" :class="{ 'save-message--error': saveIsError }">
          <v-icon :icon="saveIsError ? 'mdi-alert-circle-outline' : 'mdi-check-circle-outline'" size="16" />
          {{ saveMessage }}
        </span>
        <v-spacer />
        <v-btn
          color="primary"
          :loading="saving"
          :disabled="!dirty || !dispatchTimeValid"
          @click="save"
        >
          {{ $t('common.save') }}
        </v-btn>
      </div>
    </template>

    <RoleCardPicker
      v-model="pickerOpen"
      :cards="roleCards"
      :selected-id="form.role_card_id"
      @select="onRoleCardSelected"
      @imported="onRoleCardImported"
      @unauthorized="$emit('unauthorized')"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getPreferences, updatePreferences, listRoleCards, ApiError } from '@/services/reminders'
import RoleCardPicker from '@/components/RoleCardPicker.vue'
import ReminderOffsetsEditor from '@/components/ReminderOffsetsEditor.vue'
import { notifyRoleCardChanged } from '@/services/roleCardVisuals'

const emit = defineEmits(['unauthorized'])
const { t } = useI18n()

const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const saveMessage = ref('')
const saveIsError = ref(false)
const pickerOpen = ref(false)

const form = reactive({
  enabled: true,
  language: 'zh-CN',
  timezone: 'Asia/Shanghai',
  daily_dispatch_time: '09:00',
  default_task_reminder_offsets_minutes: [5, 1440],
  cadence_offsets: [2, 1, 0, -1, -3, -7],
  email_enabled: true,
  chat_enabled: true,
  role_card_id: null,
})

let snapshot = null
const preferences = ref(null)
const roleCards = ref([])

const languageOptions = [
  { title: '简体中文', value: 'zh-CN' },
  { title: '繁體中文', value: 'zh-TW' },
  { title: 'English', value: 'en' },
]

// ---- 时区选项：优先 Intl.supportedValuesOf，缺失时用内置常用列表 ----
const COMMON_TIMEZONES = [
  'Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Taipei', 'Asia/Singapore', 'Asia/Tokyo', 'Asia/Seoul',
  'Asia/Bangkok', 'Asia/Jakarta', 'Asia/Dubai', 'Asia/Kolkata',
  'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Moscow',
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Toronto', 'America/Vancouver', 'America/Sao_Paulo',
  'Australia/Sydney', 'Pacific/Auckland', 'UTC',
]

const timezoneOptions = computed(() => {
  let zones
  try {
    zones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : COMMON_TIMEZONES
  } catch {
    zones = COMMON_TIMEZONES
  }
  const pinned = COMMON_TIMEZONES.filter((z) => zones.includes(z))
  const rest = zones.filter((z) => !pinned.includes(z))
  const merged = [...pinned, ...rest]
  // 保证后端当前值始终可回显
  if (form.timezone && !merged.includes(form.timezone)) merged.unshift(form.timezone)
  return merged
})

// ---- 提醒档位：基础档位不可删，仅可追加 D+2~D+365（即 offset -2~-365，排除基础档） ----
const BASE_CADENCE = [2, 1, 0, -1, -3, -7]

const baseCadenceOffsets = computed(() =>
  BASE_CADENCE.filter((o) => form.cadence_offsets.includes(o)),
)
const customCadenceOffsets = computed(() =>
  form.cadence_offsets.filter((o) => !BASE_CADENCE.includes(o)).sort((a, b) => a - b),
)

const cadenceInput = ref('')
const cadenceError = ref('')

const cadenceInputDays = computed(() => {
  const n = Number(cadenceInput.value)
  return Number.isInteger(n) ? n : null
})
const canAddCadence = computed(() => {
  const d = cadenceInputDays.value
  if (d == null || d < 2 || d > 365) return false
  return !form.cadence_offsets.includes(-d)
})

function addCustomCadence() {
  const d = cadenceInputDays.value
  if (d == null || d < 2 || d > 365) {
    cadenceError.value = t('reminders.cadenceRangeError')
    return
  }
  if (form.cadence_offsets.includes(-d)) {
    cadenceError.value = t('reminders.cadenceDuplicate')
    return
  }
  form.cadence_offsets = [...form.cadence_offsets, -d]
  cadenceInput.value = ''
  cadenceError.value = ''
}

function removeCustomCadence(offset) {
  if (BASE_CADENCE.includes(offset)) return
  form.cadence_offsets = form.cadence_offsets.filter((o) => o !== offset)
  cadenceError.value = ''
}

// 每日派发时间：严格 HH:MM（零填充）
const DISPATCH_TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/
const dispatchTimeValid = computed(() => DISPATCH_TIME_RE.test(form.daily_dispatch_time || ''))

function cadenceLabel(offset) {
  if (offset > 0) return `D-${offset}`
  if (offset === 0) return t('reminders.cadenceToday')
  return t('reminders.cadenceOverdue', { n: -offset })
}

const currentRoleCard = computed(() => {
  if (form.role_card_id == null) return preferences.value?.role_card || null
  return roleCards.value.find((c) => c.id === form.role_card_id) || preferences.value?.role_card || null
})
const currentRoleCardName = computed(() => currentRoleCard.value?.name || t('reminders.roleCardDefault'))
const currentRoleCardDescription = computed(
  () => currentRoleCard.value?.description || t('reminders.roleCardHelp'),
)

const dirty = computed(() => snapshot && Object.keys(buildPatch()).length > 0)

function applyPreferences(prefs) {
  preferences.value = prefs
  form.enabled = prefs.enabled
  form.language = prefs.language
  form.timezone = prefs.timezone
  form.daily_dispatch_time = prefs.daily_dispatch_time || '09:00'
  form.default_task_reminder_offsets_minutes =
    Array.isArray(prefs.default_task_reminder_offsets_minutes)
      ? [...prefs.default_task_reminder_offsets_minutes]
      : [5, 1440]
  form.cadence_offsets = Array.isArray(prefs.cadence_offsets)
    ? [...prefs.cadence_offsets]
    : [...BASE_CADENCE]
  form.email_enabled = prefs.email_enabled
  form.chat_enabled = prefs.chat_enabled
  form.role_card_id = prefs.role_card?.id ?? null
  cadenceInput.value = ''
  cadenceError.value = ''
  snapshot = {
    enabled: form.enabled,
    language: form.language,
    timezone: form.timezone,
    daily_dispatch_time: form.daily_dispatch_time,
    default_task_reminder_offsets_minutes: [...form.default_task_reminder_offsets_minutes],
    cadence_offsets: [...form.cadence_offsets],
    email_enabled: form.email_enabled,
    chat_enabled: form.chat_enabled,
    role_card_id: form.role_card_id,
  }
}

// 数组字段按排序后的集合比较，避免顺序差异造成假 dirty
function fieldEquals(key) {
  const a = form[key]
  const b = snapshot[key]
  if (Array.isArray(a) && Array.isArray(b)) {
    const sort = (arr) => [...arr].sort((x, y) => x - y)
    return JSON.stringify(sort(a)) === JSON.stringify(sort(b))
  }
  return a === b
}

function buildPatch() {
  if (!snapshot) return {}
  const patch = {}
  for (const key of Object.keys(snapshot)) {
    if (!fieldEquals(key)) {
      // cadence_offsets 语义为完整集合：有变化时整体提交
      patch[key] = Array.isArray(form[key]) ? [...form[key]] : form[key]
    }
  }
  return patch
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const [prefs, cards] = await Promise.all([getPreferences(), listRoleCards()])
    roleCards.value = Array.isArray(cards) ? cards : cards?.items || []
    applyPreferences(prefs)
  } catch (err) {
    if (handleAuthError(err)) return
    loadError.value = friendlyError(err, t('reminders.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!dispatchTimeValid.value) {
    showSaveMessage(t('reminders.sendTimeInvalid'), true)
    return
  }
  const patch = buildPatch()
  if (Object.keys(patch).length === 0) {
    showSaveMessage(t('reminders.nothingToSave'), false)
    return
  }
  saving.value = true
  try {
    const updated = await updatePreferences(patch)
    applyPreferences(updated)
    notifyRoleCardChanged(updated?.role_card || null)
    showSaveMessage(t('reminders.saved'), false)
  } catch (err) {
    if (handleAuthError(err)) return
    showSaveMessage(friendlyError(err, t('reminders.saveFailed')), true)
  } finally {
    saving.value = false
  }
}

function onRoleCardSelected(id) {
  form.role_card_id = id
}

// 导入成功后：刷新卡片列表并选中新卡（仍需点保存才会写入偏好）
async function onRoleCardImported(newId) {
  try {
    const cards = await listRoleCards()
    roleCards.value = Array.isArray(cards) ? cards : cards?.items || []
    if (newId != null) form.role_card_id = newId
    showSaveMessage(t('reminders.importSuccess'), false)
  } catch (err) {
    handleAuthError(err)
  }
}

function handleAuthError(err) {
  if (err instanceof ApiError && err.status === 401) {
    emit('unauthorized')
    return true
  }
  return false
}

function friendlyError(err, fallback) {
  // 422 等 HTTP 错误：直接展示后端 detail；网络错误：固定文案
  if (err instanceof ApiError && err.kind === 'http') return err.message
  if (err instanceof ApiError && err.kind === 'transport') return t('reminders.networkError')
  return fallback
}

let messageTimer = null
function showSaveMessage(text, isError) {
  saveMessage.value = text
  saveIsError.value = isError
  window.clearTimeout(messageTimer)
  messageTimer = window.setTimeout(() => { saveMessage.value = '' }, 2500)
}

onMounted(loadAll)
</script>

<style scoped>
.panel-loading {
  display: flex;
  justify-content: center;
  padding: 60px 0;
}
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 0;
  border-bottom: 1px solid #eff1f4;
}
.setting-row--top {
  align-items: flex-start;
}
.setting-label {
  color: #2e3545;
  font-size: 14px;
  font-weight: 600;
}
.setting-help {
  color: #8c94a3;
  font-size: 12px;
  margin-top: 3px;
  max-width: 460px;
}
.field-160 { max-width: 160px; }
.field-220 { max-width: 220px; }
.field-280 { max-width: 280px; }
.cadence-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 420px;
}
.cadence-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}
.cadence-add {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}
.cadence-input {
  max-width: 200px;
}
.cadence-error {
  color: #c04545;
  font-size: 12px;
  text-align: right;
}
.save-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 20px;
}
.save-message {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #299467;
  font-size: 13px;
}
.save-message--error {
  color: #c04545;
}
</style>
