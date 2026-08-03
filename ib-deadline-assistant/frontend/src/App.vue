<template>
  <v-app>
    <template v-if="isAuthenticated">
      <v-app-bar class="workspace-bar" height="64" flat>
        <v-btn
          icon="mdi-format-list-bulleted"
          variant="text"
          :aria-label="$t('app.openTaskList')"
          @click="taskDrawer = true"
        />

        <button class="brand-button" type="button" @click="router.push('/calendar')">
          <span class="brand-mark">IB</span>
          <span class="brand-copy">
            <strong>IBuddy</strong>
            <small>{{ currentPageTitle }}</small>
          </span>
        </button>

        <v-spacer />

        <v-btn
          class="agent-trigger"
          prepend-icon="mdi-creation-outline"
          variant="tonal"
          color="primary"
          @click="agentDrawer = true"
        >
          Agent
        </v-btn>
        <button
          class="account-trigger"
          type="button"
          :aria-label="$t('app.openAccount')"
          :title="$t('app.account')"
          @click="settingsOpen = true"
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
        <AgentDrawer @close="agentDrawer = false" />
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

      <v-slide-x-reverse-transition>
        <v-card
          v-if="activeReminder && reminderVisible && !agentDrawer"
          class="reminder-popover"
          rounded="xl"
          elevation="12"
          role="status"
        >
          <v-card-text class="pa-4">
            <div class="d-flex align-start">
              <v-avatar color="warning" variant="tonal" size="38" class="mr-3">
                <v-icon icon="mdi-bell-ring-outline" />
              </v-avatar>
              <div class="reminder-copy" @click="openReminder(activeReminder)">
                <div class="text-overline text-warning font-weight-bold">{{ $t('app.comingSoon') }}</div>
                <div class="text-body-1 font-weight-bold">{{ activeReminder.title }}</div>
                <div class="text-caption text-medium-emphasis mt-1">
                  {{ formatReminderDate(activeReminder.date) }} · {{ activeReminder.subject || $t('common.uncategorized') }}
                </div>
              </div>
              <v-btn
                icon="mdi-close"
                variant="text"
                size="x-small"
                :aria-label="$t('app.closeReminder')"
                @click="reminderVisible = false"
              />
            </div>
            <div class="reminder-action" @click="openReminder(activeReminder)">
              {{ $t('app.viewTask') }}
              <v-icon icon="mdi-arrow-right" size="17" />
            </div>
          </v-card-text>
        </v-card>
      </v-slide-x-reverse-transition>

      <transition name="quick-actions-fade">
        <div v-show="!agentDrawer" class="quick-actions" :aria-label="$t('app.quickActions')">
          <v-tooltip :text="$t('app.urgent')" location="left">
            <template #activator="{ props }">
              <v-btn v-bind="props" icon="mdi-alert-outline" color="error" elevation="8" :aria-label="$t('app.openUrgent')" @click="router.push('/urgent')" />
            </template>
          </v-tooltip>
          <v-tooltip :text="$t('app.progress')" location="left">
            <template #activator="{ props }">
              <v-btn v-bind="props" icon="mdi-chart-timeline-variant" color="primary" elevation="8" :aria-label="$t('app.openProgress')" @click="router.push('/progress')" />
            </template>
          </v-tooltip>
          <v-tooltip :text="$t('app.settings')" location="left">
            <template #activator="{ props }">
              <v-btn v-bind="props" icon="mdi-cog-outline" color="grey-darken-3" elevation="8" :aria-label="$t('app.openSettings')" @click="settingsOpen = true" />
            </template>
          </v-tooltip>
        </div>
      </transition>

      <SettingsDialog v-model="settingsOpen" @logout="handleLogout" />
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
import { useAuth } from '@/stores/auth'
import TaskDrawer from '@/components/TaskDrawer.vue'
import AgentDrawer from '@/components/AgentDrawer.vue'
import SettingsDialog from '@/components/SettingsDialog.vue'
import { onTasksChanged } from '@/services/taskSync'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const { user, token, isAuthenticated, logout, restoreSession } = useAuth()

const taskDrawer = ref(false)
const agentDrawer = ref(false)
const settingsOpen = ref(false)
const reminders = ref([])
const reminderVisible = ref(true)

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

const currentPageTitle = computed(() => route.meta.titleKey ? t(`nav.${route.meta.titleKey}`) : t('app.defaultTitle'))
const userInitial = computed(() => (user.value?.username || 'I').charAt(0).toUpperCase())
const activeReminder = computed(() => reminders.value[0] || null)

function authHeaders() {
  return token.value ? { Authorization: `Bearer ${token.value}` } : {}
}

function flattenTasks(nodes, output = []) {
  for (const task of nodes || []) {
    output.push(task)
    flattenTasks(task.subtasks, output)
  }
  return output
}

async function loadUpcoming() {
  if (!isAuthenticated.value) return
  try {
    const [taskResponse, deadlineResponse] = await Promise.all([
      fetch('/api/tasks', { headers: authHeaders() }),
      fetch('/api/deadlines/upcoming?days=7', { headers: authHeaders() }),
    ])

    const tasks = taskResponse.ok ? flattenTasks(await taskResponse.json()) : []
    const deadlines = deadlineResponse.ok ? await deadlineResponse.json() : []
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
    reminderVisible.value = true
  } catch {
    reminders.value = []
  }
}

function openReminder(item) {
  const target = item.type === 'deadline' ? '/deadlines' : '/tasks'
  router.push({ path: target, query: { focus: item.id } })
  reminderVisible.value = false
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
  router.push('/login')
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

onMounted(async () => {
  await restoreSession()
  await loadUpcoming()
})

const stopTaskSync = onTasksChanged(loadUpcoming)
onBeforeUnmount(() => {
  stopTaskSync()
  syncDrawerScrollLock(false)
})
</script>

<style>
.workspace-bar {
  border-bottom: 1px solid rgba(20, 34, 66, 0.08) !important;
  background: rgba(255, 255, 255, 0.94) !important;
  backdrop-filter: blur(18px);
  padding: 0 18px;
}

.brand-button {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  border: 0;
  background: transparent;
  cursor: pointer;
  color: #17233d;
  text-align: left;
  padding: 4px 8px;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: linear-gradient(135deg, #3265f5, #7348e8);
  color: white;
  font-size: 13px;
  font-weight: 800;
  box-shadow: 0 8px 22px rgba(50, 101, 245, 0.24);
}

.brand-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.08;
}

.brand-copy strong { font-size: 17px; }
.brand-copy small { margin-top: 4px; color: #8790a5; font-size: 10px; }

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

.account-trigger:hover { background: rgba(50, 101, 245, .10); }
.account-trigger:active { transform: scale(.96); }
.account-trigger:focus-visible { outline: 3px solid rgba(50, 101, 245, .30); outline-offset: 2px; }

.workspace-main {
  background:
    radial-gradient(circle at 12% 5%, rgba(76, 111, 255, 0.10), transparent 28%),
    radial-gradient(circle at 88% 88%, rgba(102, 75, 230, 0.08), transparent 28%),
    #f7f8fc;
}

.workspace-drawer {
  top: 64px !important;
  height: calc(100% - 64px) !important;
  border: 0 !important;
  z-index: 1005 !important;
  box-shadow: 0 20px 50px rgba(20, 30, 60, 0.15) !important;
  overscroll-behavior: contain;
}

.drawer-backdrop {
  position: fixed;
  z-index: 1001;
  inset: 64px 0 0;
  width: 100%;
  border: 0;
  background: rgba(25, 35, 66, .08);
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
  background: rgba(61, 84, 146, 0.18);
  opacity: 0;
  transition: opacity .15s ease, background .15s ease;
  pointer-events: none;
}
.agent-resizer:hover::after,
.agent-resizer:active::after {
  opacity: 1;
  background: rgba(50, 101, 245, 0.5);
}

.reminder-popover {
  position: fixed !important;
  z-index: 1100;
  top: 82px;
  right: 24px;
  width: min(360px, calc(100vw - 48px));
  border: 1px solid rgba(255, 169, 46, 0.28);
  background: rgba(255, 255, 255, 0.97) !important;
}

.reminder-copy { flex: 1; min-width: 0; cursor: pointer; }
.reminder-action {
  margin: 13px 0 0 51px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #315dda;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.quick-actions {
  position: fixed;
  right: 25px;
  bottom: 26px;
  z-index: 1050;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.quick-actions .v-btn { width: 48px; height: 48px; }

/* Agent 抽屉打开时：三个快捷按钮收回去（淡出+下沉），关闭时弹回来 */
.quick-actions-fade-enter-active,
.quick-actions-fade-leave-active { transition: opacity .2s ease, transform .2s ease; }
.quick-actions-fade-enter-from,
.quick-actions-fade-leave-to { opacity: 0; transform: translateY(18px) scale(.96); }

.page-fade-enter-active,
.page-fade-leave-active { transition: opacity 0.18s ease, transform 0.18s ease; }
.page-fade-enter-from { opacity: 0; transform: translateY(4px); }
.page-fade-leave-to { opacity: 0; }

@media (max-width: 700px) {
  .brand-copy small { display: none; }
  .workspace-bar { padding: 0 8px; }
  .agent-trigger .v-btn__content { font-size: 0; }
  .quick-actions { right: 14px; bottom: 16px; }
  .reminder-popover { right: 14px; top: 74px; width: calc(100vw - 28px); }
}
</style>
