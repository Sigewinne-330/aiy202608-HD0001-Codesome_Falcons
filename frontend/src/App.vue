<template>
  <v-app>
    <GlobalFeedback />
    <template v-if="isAuthenticated && !isLanding">
      <WorkspaceNavigation
        v-model="navigationOpen"
        @open-agent="openGlobalAgent"
        @open-settings="openSettings"
      />

      <v-app-bar class="workspace-bar" height="60" flat>
        <v-btn
          class="navigation-trigger"
          icon="mdi-menu"
          variant="text"
          :aria-label="$t('app.navigation')"
          @click="navigationOpen = !navigationOpen"
        />

        <div class="page-identity">
          <span class="page-identity__product">IBuddy</span>
          <span class="page-identity__divider" aria-hidden="true" />
          <strong>{{ currentPageTitle }}</strong>
        </div>

        <v-tooltip :text="$t('app.openTaskList')" location="bottom">
          <template #activator="{ props }">
            <v-btn
              v-bind="props"
              class="task-quick-trigger"
              icon="mdi-format-list-checks"
              variant="text"
              :aria-label="$t('app.openTaskList')"
              @click="taskDrawer = true"
            />
          </template>
        </v-tooltip>

        <v-spacer />

        <v-menu location="bottom end" :close-on-content-click="false">
          <template #activator="{ props }">
            <v-btn v-bind="props" class="upcoming-trigger" icon variant="text" :aria-label="$t('app.upcoming')">
              <v-badge :content="reminders.length" :model-value="reminders.length > 0" color="error" floating>
                <v-icon icon="mdi-bell-outline" />
              </v-badge>
            </v-btn>
          </template>
          <v-card class="upcoming-menu" width="360" max-width="calc(100vw - 28px)">
            <div class="upcoming-menu__header">
              <div>
                <div class="upcoming-menu__eyebrow">{{ $t('app.nextSevenDays') }}</div>
                <strong>{{ $t('app.upcoming') }}</strong>
              </div>
              <v-btn variant="text" size="small" to="/reminders">{{ $t('reminders.title') }}</v-btn>
            </div>
            <v-divider />
            <v-list v-if="reminders.length" density="comfortable" lines="two" max-height="420" class="overflow-y-auto">
              <v-list-item
                v-for="item in reminders.slice(0, 8)"
                :key="`${item.type}-${item.id}`"
                :title="item.title"
                :subtitle="`${formatReminderDate(item.date)} · ${item.subject || $t('common.uncategorized')}`"
                :prepend-icon="item.type === 'deadline' ? 'mdi-calendar-alert-outline' : 'mdi-check-circle-outline'"
                @click="openReminder(item)"
              />
            </v-list>
            <div v-else class="upcoming-menu__empty">
              <v-icon icon="mdi-check-circle-outline" size="28" />
              <span>{{ $t('app.noUpcoming') }}</span>
            </div>
          </v-card>
        </v-menu>

        <!-- 交流风格快捷选择：与提醒设置共享 role_card_id -->
        <v-menu v-model="styleMenuOpen" location="bottom end" :close-on-content-click="false">
          <template #activator="{ props: menuProps }">
            <v-btn
              v-bind="menuProps"
              class="style-trigger"
              variant="text"
              prepend-icon="mdi-account-star-outline"
              :loading="styleSaving"
            >
              <span class="style-trigger__name">{{ currentStyleName }}</span>
              <template #append>
                <v-icon icon="mdi-chevron-down" size="16" />
              </template>
            </v-btn>
          </template>
          <v-card min-width="250" rounded="lg">
            <v-list density="compact">
              <v-list-subheader>{{ $t('reminders.roleCard') }}</v-list-subheader>
              <div v-if="styleLoading" class="d-flex justify-center py-3">
                <v-progress-circular indeterminate size="20" width="2" color="primary" />
              </div>
              <template v-else>
                <v-list-item :active="styleSelectedId == null" @click="selectStyle(null)">
                  <template #prepend>
                    <v-icon icon="mdi-star-circle-outline" size="20" class="mr-1" />
                  </template>
                  <v-list-item-title>{{ $t('reminders.roleCardDefault') }}</v-list-item-title>
                </v-list-item>
                <v-list-item
                  v-for="card in styleCards"
                  :key="card.id"
                  :active="styleSelectedId === card.id"
                  @click="selectStyle(card.id)"
                >
                  <template #prepend>
                    <v-icon :icon="styleCardIcon(card.slug)" size="20" class="mr-1" />
                  </template>
                  <v-list-item-title>{{ roleCardDisplayName(card) }}</v-list-item-title>
                </v-list-item>
              </template>
            </v-list>
            <v-divider />
            <v-list density="compact">
              <v-list-item prepend-icon="mdi-upload-outline" @click="openStyleImport">
                <v-list-item-title>{{ $t('reminders.importRoleCard') }}</v-list-item-title>
              </v-list-item>
              <v-list-item prepend-icon="mdi-cog-outline" @click="goStyleSettings">
                <v-list-item-title>{{ $t('reminders.goSettings') }}</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-card>
        </v-menu>

        <v-btn
          class="agent-trigger"
          prepend-icon="mdi-creation-outline"
          variant="tonal"
          color="primary"
          @click="openGlobalAgent"
        >
          Agent
        </v-btn>
        <button
          class="account-trigger"
          type="button"
          :aria-label="$t('app.openAccount')"
          :title="$t('app.account')"
          @click="openAccountSettings"
        >
          <v-avatar color="primary" size="36">
            <span class="text-white text-body-2 font-weight-bold">{{ userInitial }}</span>
          </v-avatar>
        </button>
      </v-app-bar>

      <v-navigation-drawer
        v-model="taskDrawer"
        temporary
        :scrim="false"
        width="370"
        class="workspace-drawer task-drawer"
      >
        <TaskDrawer @close="taskDrawer = false" />
      </v-navigation-drawer>

      <v-navigation-drawer
        v-model="agentDrawer"
        temporary
        :scrim="false"
        location="right"
        :width="agentDrawerWidth"
        class="workspace-drawer agent-drawer"
      >
        <AgentDrawer :context="agentContext" @close="agentDrawer = false" />
        <div
          class="agent-resizer"
          role="separator"
          aria-orientation="vertical"
          :title="$t('app.resizeAgent')"
          @mousedown.prevent="startAgentResize"
        />
      </v-navigation-drawer>

      <button
        v-if="taskDrawer || agentDrawer"
        class="drawer-backdrop"
        type="button"
        :aria-label="$t('common.cancel')"
        @click="closeDrawers"
      />

      <v-main class="workspace-main">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </v-main>

      <SettingsDialog v-model="settingsOpen" :initial-section="settingsSection" @logout="handleLogout" />

      <!-- 顶栏"导入角色卡"直达：打开选择器并自动展开导入区 -->
      <RoleCardPicker
        v-model="stylePickerOpen"
        :cards="styleCards"
        :selected-id="styleSelectedId"
        open-import
        @select="selectStyle"
        @imported="onStyleImported"
        @unauthorized="handleLogout"
      />
    </template>

    <v-main v-else>
      <router-view v-slot="{ Component }">
        <transition name="page-fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </v-main>
  </v-app>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useTheme } from 'vuetify'
import { api, onUnauthorized, useAuth } from '@/stores/auth'
import TaskDrawer from '@/components/TaskDrawer.vue'
import AgentDrawer from '@/components/AgentDrawer.vue'
import SettingsDialog from '@/components/SettingsDialog.vue'
import RoleCardPicker from '@/components/RoleCardPicker.vue'
import WorkspaceNavigation from '@/components/WorkspaceNavigation.vue'
import GlobalFeedback from '@/components/GlobalFeedback.vue'
import { onTasksChanged } from '@/services/taskSync'
import { onOpenAgent } from '@/services/agentContext'
import { getPreferences, updatePreferences, listRoleCards, ApiError } from '@/services/reminders'
import { roleCardDisplayName } from '@/services/roleCardVisuals'
import { notifyRoleCardChanged } from '@/services/roleCardVisuals'
import { initializeTheme } from '@/services/theme'
import { notify } from '@/services/feedback'
import { flattenTasks } from '@/utils/tasks'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const theme = useTheme()
const { user, isAuthenticated, logout, restoreSession } = useAuth()

// Landing 介绍页是所有人的第一界面：即使已登录也走干净布局（无顶栏/侧栏）
const isLanding = computed(() => route.name === 'Landing')

const navigationOpen = ref(true)
const taskDrawer = ref(false)
const agentDrawer = ref(false)
const agentContext = ref(null)
const settingsOpen = ref(false)
const reminders = ref([])

// ---- Agent 抽屉：覆盖式浮层，默认 520px（比原 420 大），支持拖拽调整并记住偏好 ----
const AGENT_WIDTH_KEY = 'ibuddy.agentDrawerWidth'
const MIN_AGENT_WIDTH = 360
const MAX_AGENT_WIDTH = 780
// 兼容分屏时代存下的 Split key，取到像素值则沿用，否则默认 520
const storedWidth = parseInt(localStorage.getItem('ibuddy.agentDrawerWidthSplit'), 10) || parseInt(localStorage.getItem(AGENT_WIDTH_KEY), 10)
const agentDrawerWidth = ref(Math.min(MAX_AGENT_WIDTH, Math.max(MIN_AGENT_WIDTH, storedWidth || 520)))
try { localStorage.removeItem('ibuddy.agentDrawerWidthSplit') } catch { /* ignore */ }

let agentResizing = false
let agentResizeStartX = 0
let agentResizeStartWidth = 0

function startAgentResize(event) {
  agentResizing = true
  agentResizeStartX = event.clientX
  agentResizeStartWidth = agentDrawerWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('mousemove', onAgentResize)
  window.addEventListener('mouseup', stopAgentResize)
}

function onAgentResize(event) {
  if (!agentResizing) return
  // 抽屉在右侧：向左拖动 => 变宽
  const delta = agentResizeStartX - event.clientX
  agentDrawerWidth.value = Math.min(MAX_AGENT_WIDTH, Math.max(MIN_AGENT_WIDTH, agentResizeStartWidth + delta))
}

function stopAgentResize() {
  if (!agentResizing) return
  agentResizing = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  window.removeEventListener('mousemove', onAgentResize)
  window.removeEventListener('mouseup', stopAgentResize)
  try {
    localStorage.setItem(AGENT_WIDTH_KEY, String(agentDrawerWidth.value))
  } catch { /* ignore */ }
}

const currentPageTitle = computed(() => route.meta.titleKey ? t(route.meta.titleKey) : t('app.defaultTitle'))
const userInitial = computed(() => (user.value?.username || 'I').charAt(0).toUpperCase())

async function loadUpcoming() {
  if (!isAuthenticated.value) return
  try {
    const [taskData, deadlineData] = await Promise.all([
      api('/api/tasks'),
      api('/api/deadlines/upcoming?days=7'),
    ])

    const tasks = flattenTasks(taskData)
    const deadlines = Array.isArray(deadlineData) ? deadlineData : []
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const nextWeek = new Date(today)
    nextWeek.setDate(nextWeek.getDate() + 7)

    const taskItems = tasks
      .filter((item) => item.task_type !== 'process')
      .filter((item) => item.deadline && !['done', 'completed'].includes(item.status))
      .filter((item) => {
        const date = new Date(`${item.deadline}T00:00:00`)
        return date >= today && date <= nextWeek
      })
      .map((item) => ({ ...item, type: 'task', date: item.deadline }))

    const deadlineItems = deadlines.map((item) => ({ ...item, type: 'deadline', date: item.due_date }))
    reminders.value = [...taskItems, ...deadlineItems].sort((a, b) => a.date.localeCompare(b.date))
  } catch (error) {
    reminders.value = []
    if (!(error instanceof ApiError && error.status === 401)) {
      notify(error.message || t('common.requestFailed'), { type: 'error' })
    }
  }
}

function openReminder(item) {
  const target = item.type === 'deadline' ? '/deadlines' : '/tasks'
  router.push({ path: target, query: { focus: item.id } })
}

function formatReminderDate(value) {
  if (!value) return ''
  const date = new Date(`${value}T00:00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((date - today) / 86400000)
  if (days === 0) return t('common.today')
  if (days === 1) return t('common.tomorrow')
  return t('common.monthDay', { month: date.getMonth() + 1, day: date.getDate() })
}

function handleLogout() {
  settingsOpen.value = false
  logout()
  router.push('/')  // 退出后回到介绍页（所有人的第一界面）
}

function openGlobalAgent() {
  agentContext.value = null
  agentDrawer.value = true
}

function handleUnauthorized(event) {
  const redirect = event?.detail?.redirect || route.fullPath || '/calendar'
  if (route.path === '/login') return
  settingsOpen.value = false
  taskDrawer.value = false
  agentDrawer.value = false
  notify(t('auth.sessionExpired'), { type: 'warning', timeout: 5200 })
  router.replace({ path: '/login', query: { redirect } })
}

function openSettings() {
  settingsSection.value = 'account'
  settingsOpen.value = true
}

// ---- 顶栏交流风格选择：懒加载偏好与卡片列表，选择即保存 ----
const styleMenuOpen = ref(false)
const styleCards = ref([])
const styleSelectedId = ref(null)
const styleDefaultName = ref('')
const styleDefaultSlug = ref('')
const styleLoaded = ref(false)
const styleLoading = ref(false)
const styleSaving = ref(false)
const settingsSection = ref('account')

const currentStyleName = computed(() => {
  if (styleSelectedId.value != null) {
    const card = styleCards.value.find((c) => c.id === styleSelectedId.value)
    if (card) return roleCardDisplayName(card)
    // 列表未加载时，用偏好里缓存的 slug 走同一套翻译
    return roleCardDisplayName({ slug: styleDefaultSlug.value, name: styleDefaultName.value })
  }
  return styleDefaultName.value || t('reminders.roleCardDefault')
})

function styleCardIcon(slug) {
  const map = {
    'friendly-warm-guy': 'mdi-account-heart-outline',
    'tech-geek': 'mdi-laptop',
    'sweet-high-school-girl': 'mdi-flower-outline',
  }
  return map[slug] || 'mdi-account-star-outline'
}

watch(styleMenuOpen, async (open) => {
  if (!open || styleLoaded.value) return
  styleLoading.value = true
  try {
    const [prefs, cards] = await Promise.all([getPreferences(), listRoleCards()])
    styleCards.value = Array.isArray(cards) ? cards : cards?.items || []
    styleSelectedId.value = prefs?.role_card?.id ?? null
    styleDefaultName.value = prefs?.role_card?.name || ''
    styleDefaultSlug.value = prefs?.role_card?.slug || ''
    notifyRoleCardChanged(prefs?.role_card || null)
    styleLoaded.value = true
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) handleLogout()
  } finally {
    styleLoading.value = false
  }
})

async function selectStyle(id) {
  if (styleSaving.value) return
  if (id === styleSelectedId.value) {
    styleMenuOpen.value = false
    return
  }
  styleSaving.value = true
  try {
    const updated = await updatePreferences({ role_card_id: id })
    styleSelectedId.value = updated?.role_card?.id ?? null
    styleDefaultName.value = updated?.role_card?.name || styleDefaultName.value
    styleDefaultSlug.value = updated?.role_card?.slug || styleDefaultSlug.value
    notifyRoleCardChanged(updated?.role_card || null)
    styleMenuOpen.value = false
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) handleLogout()
  } finally {
    styleSaving.value = false
  }
}

function goStyleSettings() {
  styleMenuOpen.value = false
  settingsSection.value = 'reminders'
  settingsOpen.value = true
}

// ---- 顶栏导入角色卡：从菜单直达 Picker 的导入区 ----
const stylePickerOpen = ref(false)

function openStyleImport() {
  styleMenuOpen.value = false
  stylePickerOpen.value = true
}

// 导入成功：刷新卡片列表并自动选中新卡（selectStyle 内部会保存偏好）
async function onStyleImported(newId) {
  try {
    const cards = await listRoleCards()
    styleCards.value = Array.isArray(cards) ? cards : cards?.items || []
    if (newId != null) await selectStyle(newId)
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) handleLogout()
  }
}

function openAccountSettings() {
  settingsSection.value = 'account'
  settingsOpen.value = true
}

function handleOpenAgent(context) {
  agentContext.value = context
  agentDrawer.value = true
}

function closeDrawers() {
  taskDrawer.value = false
  agentDrawer.value = false
}

let drawerScrollLocked = false
let previousBodyOverflow = ''
let previousHtmlOverflow = ''
let previousBodyOverscrollBehavior = ''
let previousHtmlOverscrollBehavior = ''

function syncDrawerScrollLock(isOpen) {
  if (typeof document === 'undefined') return

  if (isOpen && !drawerScrollLocked) {
    previousBodyOverflow = document.body.style.overflow
    previousHtmlOverflow = document.documentElement.style.overflow
    previousBodyOverscrollBehavior = document.body.style.overscrollBehavior
    previousHtmlOverscrollBehavior = document.documentElement.style.overscrollBehavior

    document.body.style.overflow = 'hidden'
    document.documentElement.style.overflow = 'hidden'
    document.body.style.overscrollBehavior = 'none'
    document.documentElement.style.overscrollBehavior = 'none'
    drawerScrollLocked = true
    return
  }

  if (!isOpen && drawerScrollLocked) {
    document.body.style.overflow = previousBodyOverflow
    document.documentElement.style.overflow = previousHtmlOverflow
    document.body.style.overscrollBehavior = previousBodyOverscrollBehavior
    document.documentElement.style.overscrollBehavior = previousHtmlOverscrollBehavior
    drawerScrollLocked = false
  }
}

watch([taskDrawer, agentDrawer], ([taskOpen, agentOpen]) => {
  syncDrawerScrollLock(taskOpen || agentOpen)
})

watch(isAuthenticated, (authenticated) => {
  if (authenticated) loadUpcoming()
})

let stopTheme = null

onMounted(async () => {
  stopTheme = initializeTheme(theme)
  await restoreSession()
  await loadUpcoming()
})

const stopTaskSync = onTasksChanged(loadUpcoming)
const stopOpenAgent = onOpenAgent(handleOpenAgent)
const stopUnauthorized = onUnauthorized(handleUnauthorized)
onBeforeUnmount(() => {
  stopTaskSync()
  stopOpenAgent()
  stopUnauthorized()
  stopTheme?.()
  syncDrawerScrollLock(false)
})
</script>

<style>
.workspace-bar {
  border-bottom: 1px solid var(--ib-border) !important;
  background: color-mix(in srgb, var(--ib-surface) 92%, transparent) !important;
  backdrop-filter: blur(16px);
  padding: 0 14px;
}

.navigation-trigger { display: none !important; }

.page-identity {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  color: var(--ib-text-secondary);
  white-space: nowrap;
}

.page-identity__product { color: var(--ib-text-muted); font-size: 12px; font-weight: 700; }
.page-identity__divider { width: 1px; height: 16px; background: var(--ib-border-strong); }
.page-identity strong { overflow: hidden; color: var(--ib-text); font-size: 14px; text-overflow: ellipsis; }
.task-quick-trigger { margin-left: 8px; color: var(--ib-text-secondary) !important; }
.upcoming-trigger { color: var(--ib-text-secondary) !important; }

.upcoming-menu { overflow: hidden; }
.upcoming-menu__header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px; }
.upcoming-menu__eyebrow { margin-bottom: 3px; color: var(--ib-text-muted); font-size: 10px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.upcoming-menu__empty { display: grid; min-height: 150px; place-items: center; align-content: center; gap: 10px; color: var(--ib-text-secondary); }

.account-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  margin: 0 8px 0 12px;
  padding: 4px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  transition: background-color .16s ease, transform .16s ease;
}

.account-trigger:hover { background: var(--ib-primary-soft); }
.account-trigger:active { transform: scale(.96); }
.account-trigger:focus-visible { outline: 3px solid color-mix(in srgb, var(--ib-primary) 30%, transparent); outline-offset: 2px; }

.style-trigger { margin-right: 6px; color: var(--ib-text-secondary); text-transform: none; letter-spacing: 0; }
.style-trigger__name { max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
@media (max-width: 720px) {
  .style-trigger__name { display: none; }
}

.workspace-main {
  background: var(--ib-background);
}

.workspace-drawer {
  top: 60px !important;
  height: calc(100% - 60px) !important;
  border-color: var(--ib-border) !important;
  background: var(--ib-surface) !important;
  z-index: 1005 !important;
  box-shadow: var(--ib-shadow-overlay) !important;
  overscroll-behavior: contain;
}

.drawer-backdrop {
  position: fixed;
  z-index: 1001;
  inset: 60px 0 0;
  width: 100%;
  border: 0;
  background: color-mix(in srgb, var(--ib-text) 10%, transparent);
  backdrop-filter: blur(1.5px);
  cursor: pointer;
  touch-action: none;
  overscroll-behavior: contain;
}

/* Agent 抽屉拖拽调整宽度手柄 */
.agent-resizer {
  position: absolute;
  top: 0;
  left: -5px;
  width: 12px;
  height: 100%;
  z-index: 1102;
  cursor: col-resize;
  touch-action: none;
}
.agent-resizer::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 4px;
  transform: translateY(-50%);
  width: 3px;
  height: 52px;
  border-radius: 3px;
  background: var(--ib-border-strong);
  opacity: 0;
  transition: opacity .15s ease, background .15s ease;
  pointer-events: none;
}
.agent-resizer:hover::after,
.agent-resizer:active::after {
  opacity: 1;
  background: color-mix(in srgb, var(--ib-primary) 55%, transparent);
}

.page-fade-enter-active,
.page-fade-leave-active { transition: opacity 0.18s ease, transform 0.18s ease; }
.page-fade-enter-from { opacity: 0; transform: translateY(4px); }
.page-fade-leave-to { opacity: 0; }

@media (max-width: 959px) {
  .navigation-trigger { display: inline-grid !important; }
}

@media (max-width: 700px) {
  .workspace-bar { padding: 0 8px; }
  .page-identity__product,
  .page-identity__divider { display: none; }
  .page-identity strong { max-width: 124px; }
  .task-quick-trigger { display: none !important; }
  .style-trigger { min-width: 40px !important; padding-inline: 7px !important; }
  .style-trigger .v-btn__prepend { margin: 0 !important; }
  .agent-trigger .v-btn__content { font-size: 0; }
  .account-trigger { margin-left: 4px; margin-right: 2px; }
}
</style>
