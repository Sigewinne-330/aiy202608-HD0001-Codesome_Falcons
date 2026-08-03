<template>
  <v-dialog v-model="dialogOpen" max-width="980" class="settings-overlay" scrollable>
    <v-card class="settings-card" rounded="xl" elevation="18">
      <div class="settings-layout">
        <aside class="settings-nav">
          <div class="settings-nav__top">
            <v-btn icon="mdi-close" variant="text" size="small" aria-label="关闭设置" @click="dialogOpen = false" />
            <div class="settings-nav__title">设置</div>
          </div>

          <button
            v-for="item in sections"
            :key="item.value"
            type="button"
            :class="{ active: activeSection === item.value }"
            @click="activeSection = item.value"
          >
            <v-icon :icon="item.icon" size="20" />
            <span>{{ item.title }}</span>
          </button>
        </aside>

        <main class="settings-content scroll-container">
          <template v-if="activeSection === 'account'">
            <SettingsHeading title="账号管理" subtitle="管理你的 IBuddy 个人资料与登录状态" />
            <div class="profile-row">
              <v-avatar color="primary" size="62">
                <span class="text-h6 text-white font-weight-bold">{{ userInitial }}</span>
              </v-avatar>
              <div>
                <div class="text-subtitle-1 font-weight-bold">{{ user?.username || 'IBuddy 用户' }}</div>
                <div class="text-body-2 text-medium-emphasis">{{ user?.email || '尚未设置邮箱' }}</div>
              </div>
            </div>

            <div class="setting-block">
              <div class="setting-label">显示名称</div>
              <v-text-field v-model="settings.displayName" variant="outlined" density="comfortable" hide-details />
            </div>
            <div class="setting-block">
              <div class="setting-label">界面语言</div>
              <v-select v-model="settings.language" :items="['简体中文', 'English']" variant="outlined" density="comfortable" hide-details />
            </div>
            <v-divider class="my-6" />
            <div class="setting-row">
              <div>
                <div class="setting-label">退出当前账号</div>
                <div class="setting-help">退出后需要重新登录才能查看任务。</div>
              </div>
              <v-btn color="error" variant="tonal" @click="$emit('logout')">退出登录</v-btn>
            </div>
          </template>

          <template v-else-if="activeSection === 'connections'">
            <SettingsHeading title="链接" subtitle="连接联系方式，用于接收提醒与账号验证" />
            <div v-for="connection in connections" :key="connection.key" class="connection-card">
              <v-avatar :color="connection.color" variant="tonal" size="42">
                <v-icon :icon="connection.icon" />
              </v-avatar>
              <div class="connection-copy">
                <div class="font-weight-bold">{{ connection.title }}</div>
                <div class="text-caption text-medium-emphasis">{{ connection.description }}</div>
              </div>
              <v-text-field
                v-if="connection.key !== 'wechat'"
                v-model="settings.connections[connection.key]"
                :placeholder="connection.placeholder"
                variant="outlined"
                density="compact"
                hide-details
                class="connection-field"
              />
              <v-btn v-else variant="outlined" @click="settings.connections.wechat = settings.connections.wechat ? '' : '已绑定微信'">
                {{ settings.connections.wechat ? '解除绑定' : '连接微信' }}
              </v-btn>
            </div>
            <v-alert type="info" variant="tonal" density="compact" class="mt-5">
              联系方式会保存在当前设备；正式的验证码与微信授权流程将在服务端接入后启用。
            </v-alert>
          </template>

          <template v-else-if="activeSection === 'time'">
            <SettingsHeading title="时间偏好" subtitle="让 Agent 在适合你的时段安排任务和提醒" />
            <div class="setting-block">
              <div class="setting-label">每周工作日</div>
              <v-chip-group v-model="settings.workDays" multiple selected-class="text-primary">
                <v-chip v-for="day in weekDays" :key="day.value" :value="day.value" filter variant="outlined">{{ day.label }}</v-chip>
              </v-chip-group>
            </div>
            <div class="time-grid">
              <div class="setting-block">
                <div class="setting-label">偏好专注时段</div>
                <div class="time-fields">
                  <v-text-field v-model="settings.focusStart" type="time" variant="outlined" density="comfortable" hide-details />
                  <span>至</span>
                  <v-text-field v-model="settings.focusEnd" type="time" variant="outlined" density="comfortable" hide-details />
                </div>
              </div>
              <div class="setting-block">
                <div class="setting-label">不工作时段</div>
                <div class="time-fields">
                  <v-text-field v-model="settings.quietStart" type="time" variant="outlined" density="comfortable" hide-details />
                  <span>至</span>
                  <v-text-field v-model="settings.quietEnd" type="time" variant="outlined" density="comfortable" hide-details />
                </div>
              </div>
            </div>
            <div class="setting-row mt-2">
              <div>
                <div class="setting-label">默认提前提醒</div>
                <div class="setting-help">日程开始前多久发送通知</div>
              </div>
              <v-select
                v-model="settings.reminderLead"
                :items="reminderOptions"
                item-title="title"
                item-value="value"
                variant="outlined"
                density="compact"
                hide-details
                class="compact-select"
              />
            </div>
            <div class="setting-row">
              <div>
                <div class="setting-label">允许 Agent 自动安排空闲时间</div>
                <div class="setting-help">Agent 会避开不工作时间，并优先使用偏好时段。</div>
              </div>
              <v-switch v-model="settings.autoSchedule" color="primary" hide-details />
            </div>
          </template>

          <template v-else>
            <SettingsHeading title="订阅" subtitle="查看当前方案与可用能力" />
            <div class="subscription-card">
              <div>
                <div class="subscription-badge">当前方案</div>
                <div class="text-h5 font-weight-bold mt-3">IBuddy Free</div>
                <div class="text-body-2 text-medium-emphasis mt-1">基础日历、任务管理与 Agent 对话</div>
              </div>
              <v-icon icon="mdi-diamond-stone" size="50" color="primary" />
            </div>
            <div class="feature-list">
              <div v-for="feature in planFeatures" :key="feature">
                <v-icon icon="mdi-check-circle" color="success" size="20" />
                <span>{{ feature }}</span>
              </div>
            </div>
            <v-btn color="primary" size="large" block class="mt-6" disabled>升级方案（即将开放）</v-btn>
          </template>

          <div class="settings-actions">
            <span v-if="saved" class="saved-hint"><v-icon icon="mdi-check-circle" size="17" /> 已保存</span>
            <v-spacer />
            <v-btn variant="text" @click="dialogOpen = false">取消</v-btn>
            <v-btn color="primary" @click="saveSettings">保存设置</v-btn>
          </div>
        </main>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, defineComponent, h, reactive, ref, watch } from 'vue'
import { useAuth } from '@/stores/auth'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue', 'logout'])
const { user } = useAuth()

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
const storageKey = 'ibuddy_preferences'
const defaultSettings = {
  displayName: '',
  language: '简体中文',
  connections: { phone: '', email: '', wechat: '' },
  workDays: [1, 2, 3, 4, 5],
  focusStart: '16:00',
  focusEnd: '20:00',
  quietStart: '23:00',
  quietEnd: '07:00',
  reminderLead: 30,
  autoSchedule: true,
}

function loadSettings() {
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || '{}')
    return {
      ...defaultSettings,
      ...stored,
      connections: { ...defaultSettings.connections, ...(stored.connections || {}) },
    }
  } catch {
    return { ...defaultSettings, connections: { ...defaultSettings.connections } }
  }
}

const settings = reactive(loadSettings())

const sections = [
  { value: 'account', title: '账号管理', icon: 'mdi-account-circle-outline' },
  { value: 'connections', title: '链接', icon: 'mdi-link-variant' },
  { value: 'time', title: '时间偏好', icon: 'mdi-clock-outline' },
  { value: 'subscription', title: '订阅', icon: 'mdi-credit-card-outline' },
]

const connections = [
  { key: 'phone', title: '手机号', description: '用于安全验证和短信提醒', placeholder: '输入手机号', icon: 'mdi-cellphone', color: 'primary' },
  { key: 'email', title: '邮箱', description: '用于登录、通知和周报', placeholder: '输入邮箱地址', icon: 'mdi-email-outline', color: 'warning' },
  { key: 'wechat', title: '微信', description: '接收日程提醒并快速打开任务', icon: 'mdi-wechat', color: 'success' },
]

const weekDays = [
  { label: '一', value: 1 }, { label: '二', value: 2 }, { label: '三', value: 3 },
  { label: '四', value: 4 }, { label: '五', value: 5 }, { label: '六', value: 6 }, { label: '日', value: 0 },
]

const reminderOptions = [
  { title: '提前 10 分钟', value: 10 },
  { title: '提前 30 分钟', value: 30 },
  { title: '提前 1 小时', value: 60 },
  { title: '提前 1 天', value: 1440 },
]

const planFeatures = ['月度日历与任务抽屉', 'Deadline 风险识别', '分类进度管理', '基础 Agent 对话']
const userInitial = computed(() => (user.value?.username || 'I').charAt(0).toUpperCase())

function saveSettings() {
  localStorage.setItem(storageKey, JSON.stringify(settings))
  saved.value = true
  window.setTimeout(() => { saved.value = false }, 1800)
}

watch(dialogOpen, (isOpen) => {
  if (isOpen && !settings.displayName) settings.displayName = user.value?.username || ''
})
</script>

<style scoped>
:global(.settings-overlay .v-overlay__scrim) { background: rgba(20, 25, 38, .32) !important; opacity: 1 !important; backdrop-filter: blur(10px); }
.settings-card { height: min(720px, calc(100vh - 52px)); overflow: hidden !important; border: 1px solid rgba(36, 47, 71, .12); }
.settings-layout { height: 100%; display: grid; grid-template-columns: 230px 1fr; }
.settings-nav { padding: 14px 12px; background: #f7f7f8; border-right: 1px solid #e6e7eb; }
.settings-nav__top { display: flex; align-items: center; gap: 12px; padding: 2px 4px 17px; }
.settings-nav__title { font-size: 17px; font-weight: 750; }
.settings-nav > button { width: 100%; display: flex; align-items: center; gap: 11px; padding: 11px 13px; margin-bottom: 5px; border: 0; border-radius: 11px; color: #424958; background: transparent; cursor: pointer; font-size: 14px; text-align: left; }
.settings-nav > button:hover { background: #ededee; }
.settings-nav > button.active { color: #202430; background: #e8e8e9; font-weight: 650; }
.settings-content { min-width: 0; overflow-y: auto; padding: 28px 34px 86px; position: relative; }
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
.settings-actions { position: absolute; left: 0; right: 0; bottom: 0; display: flex; align-items: center; gap: 8px; padding: 15px 28px; border-top: 1px solid #e8ebf0; background: rgba(255,255,255,.94); backdrop-filter: blur(12px); }
.saved-hint { display: inline-flex; align-items: center; gap: 5px; color: #299467; font-size: 12px; }
@media (max-width: 720px) {
  .settings-card { height: calc(100vh - 20px); }
  .settings-layout { grid-template-columns: 78px 1fr; }
  .settings-nav { padding: 12px 8px; }
  .settings-nav__title, .settings-nav > button span { display: none; }
  .settings-nav > button { justify-content: center; padding: 12px; }
  .settings-content { padding: 24px 18px 86px; }
  .time-grid, .feature-list { grid-template-columns: 1fr; }
  .connection-card { flex-wrap: wrap; }
  .connection-field { flex-basis: 100%; }
}
</style>
