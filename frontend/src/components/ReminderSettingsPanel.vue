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

      <!-- 每日汇总提醒（cadence）设置项已按需求暂时移除；
           脚本中的 cadence 数据流与编辑逻辑完整保留，恢复时只需还原此区块 -->

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

      <!-- 保存区（external-save 模式下隐藏，由父级统一保存按钮驱动） -->
      <div v-if="!externalSave" class="save-bar">
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
import { notifyRoleCardChanged, roleCardDisplayName } from '@/services/roleCardVisuals'

defineProps({
  // true 时隐藏面板自带保存栏，由父容器（如 SettingsDialog 底部按钮）调 save() 统一保存
  externalSave: { type: Boolean, default: false },
})
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

// 响应式快照：dirty computed 依赖它，外部（SettingsDialog 保存按钮）读取 dirty 时才能正确触发重算
const snapshot = ref(null)
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

// ---- 每日汇总提醒节奏：提前(锁) + 当天(锁) + 逾期(基础锁+自定义可删) ----
// cadence_offsets 语义：正数=截止前 N 天，0=当天，负数=逾期 N 天
const BASE_CADENCE = [2, 1, 0, -1, -3, -7]

// 提前段：正数 offset，降序展示（前 2 天 → 前 1 天）
const beforeDays = computed(() =>
  BASE_CADENCE.filter((o) => o > 0 && form.cadence_offsets.includes(o)).sort((a, b) => b - a),
)
// 逾期基础段：负数 offset 转天数，升序（第 1 天 → 第 7 天）
const overdueBaseDays = computed(() =>
  BASE_CADENCE.filter((o) => o < 0 && form.cadence_offsets.includes(o)).map((o) => -o).sort((a, b) => a - b),
)
// 逾期自定义段：可增删
const overdueCustomDays = computed(() =>
  form.cadence_offsets.filter((o) => !BASE_CADENCE.includes(o)).map((o) => -o).sort((a, b) => a - b),
)

function beforeDayLabel(d) {
  return t('reminders.cadenceBeforeDay', { n: d }, d)
}
function overdueDayLabel(d) {
  return t('reminders.cadenceOverdueDay', { n: d }, d)
}

// 人话总结：随配置实时变化，如"截止前 2 天、前 1 天和当天提醒你；逾期后第 1、3、7 天继续追催"
const cadenceSummary = computed(() => {
  const before = beforeDays.value.map(beforeDayLabel).join(t('reminders.cadenceListSep'))
  const overdue = [...overdueBaseDays.value, ...overdueCustomDays.value]
    .sort((a, b) => a - b)
    .map((d) => String(d))
    .join(t('reminders.cadenceListSep'))
  return t('reminders.cadenceSummary', { before, overdue })
})

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

const currentRoleCard = computed(() => {
  if (form.role_card_id == null) return preferences.value?.role_card || null
  return roleCards.value.find((c) => c.id === form.role_card_id) || preferences.value?.role_card || null
})
const currentRoleCardName = computed(() =>
  currentRoleCard.value ? roleCardDisplayName(currentRoleCard.value) : t('reminders.roleCardDefault'),
)
const currentRoleCardDescription = computed(
  () => currentRoleCard.value?.description || t('reminders.roleCardHelp'),
)

const dirty = computed(() => snapshot.value && Object.keys(buildPatch()).length > 0)

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
  snapshot.value = {
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
  const b = snapshot.value[key]
  if (Array.isArray(a) && Array.isArray(b)) {
    const sort = (arr) => [...arr].sort((x, y) => x - y)
    return JSON.stringify(sort(a)) === JSON.stringify(sort(b))
  }
  return a === b
}

function buildPatch() {
  if (!snapshot.value) return {}
  const patch = {}
  for (const key of Object.keys(snapshot.value)) {
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

// 供父容器（SettingsDialog 底部统一保存按钮）驱动
defineExpose({ save, dirty, saving, dispatchTimeValid, saveMessage, saveIsError })
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
  max-width: 460px;
}
/* 三段式时间线：提前(蓝) → 当天(橙) → 逾期(红) */
.cadence-timeline {
  display: flex;
  align-items: stretch;
  gap: 4px;
}
.cadence-zone {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  border-radius: 12px;
}
.cadence-zone--before { background: #eef4ff; }
.cadence-zone--due { background: #fff4e5; }
.cadence-zone--overdue { background: #fdeeee; }
.cadence-zone__label {
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 7px;
}
.cadence-zone--before .cadence-zone__label { color: #3567d6; }
.cadence-zone--due .cadence-zone__label { color: #c07a1f; }
.cadence-zone--overdue .cadence-zone__label { color: #c04545; }
.cadence-zone__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.cadence-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 9px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.85);
  font-size: 12px;
  font-weight: 600;
  color: #3a4356;
  white-space: nowrap;
}
.cadence-chip .v-icon { color: #9aa5b5; }
.cadence-chip--custom {
  background: #fff;
  border: 1px dashed #e0a3a0;
  color: #c04545;
}
.cadence-chip__remove {
  border: 0;
  background: none;
  padding: 0 0 0 2px;
  font-size: 14px;
  line-height: 1;
  color: #c04545;
  cursor: pointer;
}
.cadence-chip__remove:disabled { opacity: 0.4; cursor: not-allowed; }
.cadence-arrow {
  align-self: center;
  color: #b8c0cf;
  flex: 0 0 auto;
}
.cadence-add {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}
.cadence-input {
  max-width: 150px;
}
.cadence-error {
  color: #c04545;
  font-size: 12px;
  margin-top: 5px;
}
@media (max-width: 640px) {
  .cadence-timeline { flex-direction: column; }
  .cadence-arrow { transform: rotate(90deg); align-self: flex-start; margin-left: 12px; }
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
