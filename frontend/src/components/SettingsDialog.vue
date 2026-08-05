<template>
  <v-dialog v-model="dialogOpen" max-width="980" class="settings-overlay" scrollable>
    <v-card class="settings-card" rounded="xl" elevation="18">
      <div class="settings-layout">
        <aside class="settings-nav">
          <div class="settings-nav__top">
            <v-btn icon="mdi-close" variant="text" size="small" :aria-label="$t('settings.close')" @click="dialogOpen = false" />
            <div class="settings-nav__title">{{ $t('settings.title') }}</div>
          </div>

          <button
            v-for="item in sections"
            :key="item.value"
            type="button"
            :class="{ active: activeSection === item.value }"
            @click="activeSection = item.value"
          >
            <v-icon :icon="item.icon" size="20" />
            <span>{{ $t(item.titleKey) }}</span>
          </button>
        </aside>

        <main class="settings-content">
          <div class="settings-content__scroll scroll-container">
          <template v-if="activeSection === 'account'">
            <SettingsHeading :title="$t('settings.account')" :subtitle="$t('settings.accountSub')" />
            <div class="profile-row">
              <v-avatar color="primary" size="62">
                <span class="text-h6 text-white font-weight-bold">{{ userInitial }}</span>
              </v-avatar>
              <div>
                <div class="text-subtitle-1 font-weight-bold">{{ user?.username || $t('settings.defaultUser') }}</div>
                <div class="text-body-2 text-medium-emphasis">{{ user?.email || $t('settings.noEmail') }}</div>
              </div>
            </div>

            <div class="setting-block">
              <div class="setting-label">{{ $t('settings.displayName') }}</div>
              <v-text-field v-model="settings.displayName" variant="outlined" density="comfortable" hide-details />
            </div>
            <div class="setting-block">
              <div class="setting-label">{{ $t('settings.language') }}</div>
              <v-select
                v-model="settings.language"
                :items="languageOptions"
                item-title="title"
                item-value="value"
                variant="outlined"
                density="comfortable"
                hide-details
              />
            </div>
            <v-divider class="my-6" />
            <div class="setting-row">
              <div>
                <div class="setting-label">{{ $t('settings.logoutLabel') }}</div>
                <div class="setting-help">{{ $t('settings.logoutHelp') }}</div>
              </div>
              <v-btn color="error" variant="tonal" @click="$emit('logout')">{{ $t('settings.logout') }}</v-btn>
            </div>
          </template>

          <template v-else-if="activeSection === 'connections'">
            <SettingsHeading :title="$t('settings.connections')" :subtitle="$t('settings.connectionsSub')" />
            <div v-for="connection in connections" :key="connection.key" class="connection-card">
              <v-avatar :color="connection.color" variant="tonal" size="42">
                <v-icon :icon="connection.icon" />
              </v-avatar>
              <div class="connection-copy">
                <div class="font-weight-bold">{{ $t(connection.titleKey) }}</div>
                <div class="text-caption text-medium-emphasis">{{ $t(connection.descKey) }}</div>
              </div>
              <v-text-field
                v-if="connection.key !== 'wechat'"
                v-model="settings.connections[connection.key]"
                :placeholder="$t(connection.placeholderKey)"
                variant="outlined"
                density="compact"
                hide-details
                class="connection-field"
              />
              <v-btn v-else variant="outlined" @click="settings.connections.wechat = settings.connections.wechat ? '' : $t('settings.wechatConnected')">
                {{ settings.connections.wechat ? $t('settings.unbind') : $t('settings.connectWechat') }}
              </v-btn>
            </div>
            <v-alert type="info" variant="tonal" density="compact" class="mt-5">
              {{ $t('settings.connectionsInfo') }}
            </v-alert>
          </template>

          <template v-else-if="activeSection === 'time'">
            <SettingsHeading :title="$t('settings.time')" :subtitle="$t('settings.timeSub')" />
            <div class="setting-block">
              <div class="setting-label">{{ $t('settings.workDays') }}</div>
              <v-chip-group v-model="settings.workDays" multiple selected-class="text-primary">
                <v-chip v-for="day in weekDays" :key="day.value" :value="day.value" filter variant="outlined">{{ day.label }}</v-chip>
              </v-chip-group>
            </div>
            <div class="time-grid">
              <div class="setting-block">
                <div class="setting-label">{{ $t('settings.focusPeriod') }}</div>
                <div class="time-fields">
                  <v-text-field v-model="settings.focusStart" type="time" variant="outlined" density="comfortable" hide-details />
                  <span>{{ $t('settings.to') }}</span>
                  <v-text-field v-model="settings.focusEnd" type="time" variant="outlined" density="comfortable" hide-details />
                </div>
              </div>
              <div class="setting-block">
                <div class="setting-label">{{ $t('settings.quietPeriod') }}</div>
                <div class="time-fields">
                  <v-text-field v-model="settings.quietStart" type="time" variant="outlined" density="comfortable" hide-details />
                  <span>{{ $t('settings.to') }}</span>
                  <v-text-field v-model="settings.quietEnd" type="time" variant="outlined" density="comfortable" hide-details />
                </div>
              </div>
            </div>
            <div class="setting-row mt-2">
              <div>
                <div class="setting-label">{{ $t('settings.autoSchedule') }}</div>
                <div class="setting-help">{{ $t('settings.autoScheduleHelp') }}</div>
              </div>
              <v-switch v-model="settings.autoSchedule" color="primary" hide-details />
            </div>
            <div class="setting-row">
              <div>
                <div class="setting-label">{{ $t('reminders.managedTitle') }}</div>
                <div class="setting-help">{{ $t('reminders.managedHelp') }}</div>
              </div>
              <v-btn variant="outlined" prepend-icon="mdi-bell-outline" @click="goReminderSettings">
                {{ $t('reminders.goSettings') }}
              </v-btn>
            </div>
          </template>

          <template v-else-if="activeSection === 'reminders'">
            <SettingsHeading :title="$t('reminders.tabSettings')" :subtitle="$t('reminders.subtitle')" />
            <ReminderSettingsPanel ref="reminderPanel" external-save @unauthorized="handleReminderUnauthorized" />
          </template>

          <template v-else>
            <SettingsHeading :title="$t('settingsBilling.balanceTitle')" :subtitle="$t('settingsBilling.balanceDesc')" />
            <div class="subscription-card">
              <div>
                <div class="subscription-badge">{{ $t('billing.balance') }}</div>
                <div class="text-h5 font-weight-bold mt-3">
                  {{ balance.toLocaleString() }}
                  <span style="font-size: 13px; font-weight: 500;">{{ $t('billing.creditsUnit') }}</span>
                </div>
                <div class="text-body-2 text-medium-emphasis mt-1">{{ $t('billing.tokensPerCredit') }}</div>
              </div>
              <v-icon icon="mdi-wallet-outline" size="50" color="primary" />
            </div>
            <div class="feature-list">
              <div>
                <v-icon icon="mdi-chart-line" color="success" size="20" />
                <span>{{ $t('billing.todaySpent') }}: -{{ summary.today_spent.toLocaleString() }}</span>
              </div>
              <div>
                <v-icon icon="mdi-calendar-month" color="success" size="20" />
                <span>{{ $t('billing.monthSpent') }}: -{{ summary.month_spent.toLocaleString() }}</span>
              </div>
            </div>
            <v-btn color="primary" size="large" block class="mt-6" prepend-icon="mdi-cash-plus" @click="goBilling">
              {{ $t('settingsBilling.goRecharge') }}
            </v-btn>
          </template>
          </div>

          <div class="settings-actions">
            <span v-if="activeSection === 'reminders' && reminderPanel?.saveMessage" class="saved-hint" :class="{ 'saved-hint--error': reminderPanel.saveIsError }">
              <v-icon :icon="reminderPanel.saveIsError ? 'mdi-alert-circle-outline' : 'mdi-check-circle'" size="17" />
              {{ reminderPanel.saveMessage }}
            </span>
            <span v-else-if="saved" class="saved-hint"><v-icon icon="mdi-check-circle" size="17" /> {{ $t('settings.savedHint') }}</span>
            <v-spacer />
            <v-btn variant="text" @click="dialogOpen = false">{{ $t('common.cancel') }}</v-btn>
            <v-btn
              color="primary"
              :loading="activeSection === 'reminders' && reminderPanel?.saving"
              :disabled="activeSection === 'reminders' && reminderPanel ? (!reminderPanel.dirty || !reminderPanel.dispatchTimeValid) : false"
              @click="saveSettings"
            >
              {{ $t('common.save') }}
            </v-btn>
          </div>
        </main>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, defineComponent, h, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useI18n } from 'vue-i18n'
import { setLocale, SUPPORTED_LOCALES, LOCALE_NAMES } from '@/i18n'
import ReminderSettingsPanel from '@/components/ReminderSettingsPanel.vue'

const props = defineProps({
  modelValue: Boolean,
  // 打开时定位到哪个分区（account/connections/time/subscription/reminders）
  initialSection: { type: String, default: 'account' },
})
const emit = defineEmits(['update:modelValue', 'logout'])
const { user, token, logout } = useAuth()
const { locale } = useI18n()
const router = useRouter()
const balance = ref(0)
const summary = ref({ today_spent: 0, month_spent: 0 })

function billingHeaders() {
  return token.value ? { Authorization: `Bearer ${token.value}` } : {}
}

async function loadBalance() {
  try {
    const res = await fetch('/api/billing/summary', { headers: billingHeaders() })
    if (res.ok) {
      const data = await res.json()
      balance.value = data.balance || 0
      summary.value = data
    }
  } catch {
    /* ignore */
  }
}

function goBilling() {
  dialogOpen.value = false
  router.push('/billing')
}

function goReminderSettings() {
  // 提醒设置已集成进本对话框，直接切换分区（完整历史页仍在 /reminders）
  activeSection.value = 'reminders'
}

function handleReminderUnauthorized() {
  dialogOpen.value = false
  logout()
  router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
}

const SettingsHeading = defineComponent({
  props: { title: String, subtitle: String },
  setup(headingProps) {
    return () => h('div', { class: 'settings-heading' }, [
      h('h2', headingProps.title),
      h('p', headingProps.subtitle),
    ])
  },
})

const dialogOpen = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const activeSection = ref('account')
const saved = ref(false)
// 提醒设置面板实例（external-save 模式下由本对话框底部按钮统一保存）
const reminderPanel = ref(null)
const storageKey = 'ibuddy_preferences'
const defaultSettings = {
  displayName: '',
  language: locale.value,
  connections: { phone: '', email: '', wechat: '' },
  workDays: [1, 2, 3, 4, 5],
  focusStart: '16:00',
  focusEnd: '20:00',
  quietStart: '23:00',
  quietEnd: '07:00',
  autoSchedule: true,
}

const languageOptions = SUPPORTED_LOCALES.map((code) => ({ title: LOCALE_NAMES[code], value: code }))

// 兼容旧格式：'简体中文' / 'English' → locale code
const legacyLangMap = { '简体中文': 'zh-CN', 'English': 'en' }

function normalizeLanguage(value) {
  if (legacyLangMap[value]) return legacyLangMap[value]
  return SUPPORTED_LOCALES.includes(value) ? value : locale.value
}

function loadSettings() {
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || '{}')
    // 显式忽略遗留的假提醒设置，确保后续保存不再写回
    delete stored.reminderLead
    return {
      ...defaultSettings,
      ...stored,
      language: normalizeLanguage(stored.language),
      connections: { ...defaultSettings.connections, ...(stored.connections || {}) },
    }
  } catch {
    return { ...defaultSettings, connections: { ...defaultSettings.connections } }
  }
}

const settings = reactive(loadSettings())

// 语言切换即时生效并持久化
watch(() => settings.language, (lang) => {
  if (lang) setLocale(lang)
})

const sections = [
  { value: 'account', titleKey: 'settings.account', icon: 'mdi-account-circle-outline' },
  { value: 'connections', titleKey: 'settings.connections', icon: 'mdi-link-variant' },
  { value: 'time', titleKey: 'settings.time', icon: 'mdi-clock-outline' },
  { value: 'reminders', titleKey: 'reminders.tabSettings', icon: 'mdi-bell-cog-outline' },
  { value: 'subscription', titleKey: 'settingsBilling.balanceTitle', icon: 'mdi-wallet-outline' },
]

const connections = [
  { key: 'phone', titleKey: 'settings.phone', descKey: 'settings.phoneDesc', placeholderKey: 'settings.phonePlaceholder', icon: 'mdi-cellphone', color: 'primary' },
  { key: 'email', titleKey: 'settings.email', descKey: 'settings.emailDesc', placeholderKey: 'settings.emailPlaceholder', icon: 'mdi-email-outline', color: 'warning' },
  { key: 'wechat', titleKey: 'settings.wechat', descKey: 'settings.wechatDesc', icon: 'mdi-wechat', color: 'success' },
]

const weekDays = [
  { label: '一', value: 1 }, { label: '二', value: 2 }, { label: '三', value: 3 },
  { label: '四', value: 4 }, { label: '五', value: 5 }, { label: '六', value: 6 }, { label: '日', value: 0 },
]

const userInitial = computed(() => (user.value?.username || 'I').charAt(0).toUpperCase())

async function saveSettings() {
  // 提醒设置分区：委托面板走后端 API 保存（面板自身的保存栏已隐藏）
  if (activeSection.value === 'reminders' && reminderPanel.value) {
    await reminderPanel.value.save()
    return
  }
  localStorage.setItem(storageKey, JSON.stringify(settings))
  saved.value = true
  window.setTimeout(() => { saved.value = false }, 1800)
}

watch(dialogOpen, (isOpen) => {
  if (isOpen) {
    activeSection.value = props.initialSection || 'account'
    if (!settings.displayName) settings.displayName = user.value?.username || ''
    loadBalance()
  }
})
</script>

<style scoped>
:global(.settings-overlay .v-overlay__scrim) { background: rgba(20, 25, 38, .32) !important; opacity: 1 !important; backdrop-filter: blur(10px); }
.settings-card { height: min(720px, calc(100vh - 52px)); overflow: hidden !important; border: 1px solid rgba(36, 47, 71, .12); }
.settings-layout { height: 100%; min-height: 0; display: grid; grid-template-columns: 230px minmax(0, 1fr); grid-template-rows: minmax(0, 1fr); }
.settings-nav { min-height: 0; overflow-y: auto; padding: 14px 12px; background: #f7f7f8; border-right: 1px solid #e6e7eb; }
.settings-nav__top { display: flex; align-items: center; gap: 12px; padding: 2px 4px 17px; }
.settings-nav__title { font-size: 17px; font-weight: 750; }
.settings-nav > button { width: 100%; display: flex; align-items: center; gap: 11px; padding: 11px 13px; margin-bottom: 5px; border: 0; border-radius: 11px; color: #424958; background: transparent; cursor: pointer; font-size: 14px; text-align: left; }
.settings-nav > button:hover { background: #ededee; }
.settings-nav > button.active { color: #202430; background: #e8e8e9; font-weight: 650; }
.settings-content { min-width: 0; min-height: 0; height: 100%; display: flex; flex-direction: column; overflow: hidden; }
.settings-content__scroll { flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 28px 34px 34px; }
:deep(.settings-heading) { padding-bottom: 20px; margin-bottom: 22px; border-bottom: 1px solid #ebedf1; }
:deep(.settings-heading h2) { font-size: 21px; color: #202633; }
:deep(.settings-heading p) { margin-top: 5px; color: #858d9d; font-size: 13px; }
.profile-row { display: flex; align-items: center; gap: 16px; padding: 18px; margin-bottom: 22px; border-radius: 16px; background: #f7f8fc; }
.setting-block { margin-bottom: 20px; }
.setting-label { margin-bottom: 7px; color: #2e3545; font-size: 13px; font-weight: 650; }
.setting-help { color: #8c94a3; font-size: 12px; }
.setting-row { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 17px 0; border-bottom: 1px solid #eff1f4; }
.connection-card { display: flex; align-items: center; gap: 14px; padding: 17px 0; border-bottom: 1px solid #edf0f4; }
.connection-copy { flex: 1; min-width: 150px; }
.connection-field { flex: 0 1 235px; }
.time-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.time-fields { display: flex; align-items: center; gap: 9px; }
.time-fields span { color: #8f97a6; font-size: 12px; }
.compact-select { max-width: 180px; }
.subscription-card { display: flex; align-items: center; justify-content: space-between; padding: 26px; border-radius: 20px; color: #fff; background: linear-gradient(135deg, #243760, #4b55b9); box-shadow: 0 18px 36px rgba(53, 64, 145, .24); }
.subscription-badge { display: inline-flex; padding: 4px 9px; border-radius: 999px; background: rgba(255,255,255,.14); font-size: 11px; }
.feature-list { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 24px; }
.feature-list > div { display: flex; align-items: center; gap: 9px; font-size: 13px; }
.settings-actions { flex: 0 0 auto; display: flex; align-items: center; gap: 8px; padding: 15px 28px; border-top: 1px solid #e8ebf0; background: rgba(255,255,255,.94); backdrop-filter: blur(12px); }
.saved-hint { display: inline-flex; align-items: center; gap: 5px; color: #299467; font-size: 12px; }
.saved-hint--error { color: #c0473d; }
@media (max-width: 720px) {
  .settings-card { height: calc(100vh - 20px); }
  .settings-layout { grid-template-columns: 78px 1fr; }
  .settings-nav { padding: 12px 8px; }
  .settings-nav__title, .settings-nav > button span { display: none; }
  .settings-nav > button { justify-content: center; padding: 12px; }
  .settings-content__scroll { padding: 24px 18px; }
  .settings-actions { padding: 13px 18px; }
  .time-grid, .feature-list { grid-template-columns: 1fr; }
  .connection-card { flex-wrap: wrap; }
  .connection-field { flex-basis: 100%; }
}
</style>
