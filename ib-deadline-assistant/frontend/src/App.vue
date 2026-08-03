<template>
  <v-app>
    <template v-if="isAuthenticated">
      <v-app-bar class="workspace-bar" height="64" flat>
        <v-btn
          icon="mdi-format-list-bulleted"
          variant="text"
          aria-label="打开任务列表"
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
        <v-avatar class="ml-3" color="primary" size="36">
          <span class="text-white text-body-2 font-weight-bold">{{ userInitial }}</span>
        </v-avatar>
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
        width="420"
        class="workspace-drawer agent-drawer"
      >
        <AgentDrawer @close="agentDrawer = false" />
      </v-navigation-drawer>

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
                <div class="text-overline text-warning font-weight-bold">即将到来</div>
                <div class="text-body-1 font-weight-bold">{{ activeReminder.title }}</div>
                <div class="text-caption text-medium-emphasis mt-1">
                  {{ formatReminderDate(activeReminder.date) }} · {{ activeReminder.subject || '未分类' }}
                </div>
              </div>
              <v-btn
                icon="mdi-close"
                variant="text"
                size="x-small"
                aria-label="关闭提醒"
                @click="reminderVisible = false"
              />
            </div>
            <div class="reminder-action" @click="openReminder(activeReminder)">
              查看对应任务
              <v-icon icon="mdi-arrow-right" size="17" />
            </div>
          </v-card-text>
        </v-card>
      </v-slide-x-reverse-transition>

      <div class="quick-actions" aria-label="快捷入口">
        <v-tooltip text="紧急待处理项" location="left">
          <template #activator="{ props }">
            <v-btn v-bind="props" icon="mdi-alert-outline" color="error" elevation="8" aria-label="打开紧急待处理项" @click="router.push('/urgent')" />
          </template>
        </v-tooltip>
        <v-tooltip text="进度管理" location="left">
          <template #activator="{ props }">
            <v-btn v-bind="props" icon="mdi-chart-timeline-variant" color="primary" elevation="8" aria-label="打开进度管理" @click="router.push('/progress')" />
          </template>
        </v-tooltip>
        <v-tooltip text="设置" location="left">
          <template #activator="{ props }">
            <v-btn v-bind="props" icon="mdi-cog-outline" color="grey-darken-3" elevation="8" aria-label="打开设置" @click="settingsOpen = true" />
          </template>
        </v-tooltip>
      </div>

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
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import TaskDrawer from '@/components/TaskDrawer.vue'
import AgentDrawer from '@/components/AgentDrawer.vue'
import SettingsDialog from '@/components/SettingsDialog.vue'

const router = useRouter()
const route = useRoute()
const { user, token, isAuthenticated, logout, restoreSession } = useAuth()

const taskDrawer = ref(false)
const agentDrawer = ref(false)
const settingsOpen = ref(false)
const reminders = ref([])
const reminderVisible = ref(true)

const currentPageTitle = computed(() => route.meta.title || '日历工作台')
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
  if (days === 0) return '今天'
  if (days === 1) return '明天'
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function handleLogout() {
  settingsOpen.value = false
  logout()
  router.push('/login')
}

watch(isAuthenticated, (authenticated) => {
  if (authenticated) loadUpcoming()
})

onMounted(async () => {
  await restoreSession()
  await loadUpcoming()
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
  box-shadow: 0 20px 50px rgba(20, 30, 60, 0.15) !important;
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
