<template>
  <div class="task-panel">
    <div class="task-panel__header">
      <div>
        <div class="text-h6 font-weight-bold">{{ $t('taskDrawer.title') }}</div>
        <div class="text-caption text-medium-emphasis">{{ $t('taskDrawer.subtitle') }}</div>
      </div>
      <v-btn icon="mdi-close" variant="text" size="small" :aria-label="$t('taskDrawer.close')" @click="$emit('close')" />
    </div>

    <div class="task-panel__summary">
      <div>
        <span class="summary-number">{{ pendingCount }}</span>
        <span class="summary-label">{{ $t('taskDrawer.pending') }}</span>
      </div>
      <v-progress-circular :model-value="completionRate" color="success" size="52" width="5">
        <span class="text-caption font-weight-bold">{{ completionRate }}%</span>
      </v-progress-circular>
    </div>

    <WorkSessionControls :tasks="workTaskOptions" />

    <div class="task-panel__toolbar">
      <v-text-field
        v-model="search"
        prepend-inner-icon="mdi-magnify"
        :placeholder="$t('taskDrawer.searchPlaceholder')"
        density="compact"
        variant="solo-filled"
        flat
        hide-details
        clearable
      />
      <v-btn icon="mdi-plus" color="primary" variant="flat" :aria-label="$t('taskDrawer.newTask')" @click="openCreateTask" />
    </div>

    <div class="task-panel__list scroll-container">
      <div v-if="loading" class="task-panel__empty">
        <v-progress-circular indeterminate color="primary" size="30" />
        <span>{{ $t('taskDrawer.loading') }}</span>
      </div>

      <template v-for="task in filteredTasks" v-else :key="task.id">
        <!-- 父任务行 -->
        <button
          type="button"
          class="drawer-task"
          :class="{ 'drawer-task--parent': task.subtasks?.length }"
          @click="task.subtasks?.length ? toggleExpand(task.id) : openTask(task)"
        >
          <span class="drawer-task__state" :class="`priority-${task.priority}`">
            <v-icon
              v-if="task.subtasks?.length"
              :icon="expanded.has(task.id) ? 'mdi-chevron-down' : 'mdi-chevron-right'"
              size="16"
            />
            <v-icon v-else :icon="isDone(task) ? 'mdi-check' : 'mdi-circle-outline'" size="16" />
          </span>
          <span class="drawer-task__body">
            <span class="drawer-task__title">{{ task.title }}</span>
            <span class="drawer-task__meta">
              <span v-if="task.subject">{{ task.subject }}</span>
              <span v-if="task.deadline">{{ formatDate(task.deadline) }}</span>
              <span v-if="task.subtasks?.length" class="drawer-task__subcount">{{ task.subtasks.length }} 项子任务</span>
            </span>
            <v-progress-linear
              :model-value="task.progress || 0"
              :color="priorityColor(task.priority)"
              height="3"
              rounded
              class="mt-2"
            />
          </span>
        </button>

        <!-- 子任务列表（缩进嵌套） -->
        <div v-if="task.subtasks?.length && expanded.has(task.id)" class="drawer-subtasks">
          <button
            v-for="sub in task.subtasks"
            :key="sub.id"
            type="button"
            class="drawer-task drawer-task--child"
            :class="{ 'drawer-task--done': isDone(sub) }"
            @click="openTask(sub)"
          >
            <span class="drawer-task__state" :class="`priority-${sub.priority}`">
              <v-icon :icon="isDone(sub) ? 'mdi-check' : 'mdi-circle-outline'" size="14" />
            </span>
            <span class="drawer-task__body">
              <span class="drawer-task__title">{{ sub.title }}</span>
              <span class="drawer-task__meta">
                <span v-if="sub.deadline">{{ formatDate(sub.deadline) }}</span>
              </span>
            </span>
            <v-icon icon="mdi-chevron-right" size="16" color="grey-lighten-1" />
          </button>
        </div>
      </template>

      <div v-if="!loading && filteredTasks.length === 0" class="task-panel__empty">
        <v-icon icon="mdi-checkbox-marked-circle-outline" color="success" size="42" />
        <span>{{ search ? $t('taskDrawer.noMatch') : $t('taskDrawer.noPending') }}</span>
      </div>
    </div>

    <div class="task-panel__footer">
      <v-btn
        variant="tonal"
        color="primary"
        block
        :prepend-icon="isTasksPage ? 'mdi-calendar-arrow-left' : 'mdi-view-list-outline'"
        @click="handleFooterAction"
      >
        {{ isTasksPage ? $t('taskDrawer.backCalendar') : $t('taskDrawer.openTasks') }}
      </v-btn>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuth } from '@/stores/auth'
import { onTasksChanged } from '@/services/taskSync'
import WorkSessionControls from '@/components/WorkSessionControls.vue'

const emit = defineEmits(['close'])

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const { token } = useAuth()
const tasks = ref([])       // 原始树
const loading = ref(true)
const search = ref('')
const expanded = ref(new Set())
const isTasksPage = computed(() => route.path === '/tasks')

/** 递归 flatten 用于计数和完成率计算 */
function flatten(nodes, output = []) {
  for (const task of nodes || []) {
    output.push(task)
    flatten(task.subtasks, output)
  }
  return output
}

/** 根据搜索关键词过滤任务树 */
function filterTree(nodes, keyword) {
  if (!nodes) return []
  const results = []
  for (const task of nodes) {
    const titleMatch = !keyword || `${task.title} ${task.subject || ''}`.toLowerCase().includes(keyword)
    const filteredSubtasks = filterTree(task.subtasks, keyword)
    const hasMatchingSubtasks = filteredSubtasks.length > 0
    if (titleMatch || hasMatchingSubtasks) {
      results.push({ ...task, subtasks: filteredSubtasks })
    }
  }
  return results
}

const filteredTasks = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return filterTree(tasks.value, keyword)
    .filter((task) => !isDone(task) || (task.subtasks?.length))
    .sort((a, b) => priorityWeight(b.priority) - priorityWeight(a.priority))
})

const allFlattened = computed(() => flatten(tasks.value))
const workTaskOptions = computed(() => {
  const result = []
  function visit(nodes, child = false) {
    for (const task of nodes || []) {
      if (!isDone(task)) result.push({ id: task.id, title: task.title, source_type: child ? 'subtask' : 'task' })
      visit(task.subtasks, true)
    }
  }
  visit(tasks.value)
  return result
})

const pendingCount = computed(() => allFlattened.value.filter((task) => !isDone(task)).length)
const completionRate = computed(() => {
  if (!allFlattened.value.length) return 0
  return Math.round((allFlattened.value.filter(isDone).length / allFlattened.value.length) * 100)
})

function toggleExpand(id) {
  const s = new Set(expanded.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  expanded.value = s
}

function isDone(task) {
  return ['done', 'completed'].includes(task.status)
}

function priorityWeight(priority) {
  return { urgent: 4, high: 3, medium: 2, low: 1 }[priority] || 0
}

function priorityColor(priority) {
  return { urgent: 'error', high: 'warning', medium: 'primary', low: 'success' }[priority] || 'primary'
}

function formatDate(value) {
  const date = new Date(`${value}T00:00:00`)
  return t('common.monthDay', { month: date.getMonth() + 1, day: date.getDate() })
}

function openTask(task) {
  router.push({ path: '/tasks', query: { focus: task.id } })
}

function goToTasks() {
  emit('close')
  router.push('/tasks')
}

function openCreateTask() {
  emit('close')
  router.push({ path: '/tasks', query: { create: '1' } })
}

function handleFooterAction() {
  emit('close')
  router.push(isTasksPage.value ? '/calendar' : '/tasks')
}

async function loadTasks() {
  loading.value = true
  try {
    const headers = token.value ? { Authorization: `Bearer ${token.value}` } : {}
    const response = await fetch('/api/tasks', { headers })
    tasks.value = response.ok ? await response.json() : []
  } catch {
    tasks.value = []
  } finally {
    loading.value = false
  }
}

let stopTaskSync

onMounted(() => {
  loadTasks()
  stopTaskSync = onTasksChanged(loadTasks)
})

onBeforeUnmount(() => stopTaskSync?.())
</script>

<style scoped>
.task-panel { height: 100%; display: flex; flex-direction: column; background: #fff; }
.task-panel__header { display: flex; align-items: center; justify-content: space-between; padding: 24px 22px 16px; }
.task-panel__summary { margin: 0 18px 16px; padding: 16px 18px; display: flex; align-items: center; justify-content: space-between; border-radius: 18px; color: #fff; background: linear-gradient(135deg, #3265f5, #7251e7); box-shadow: 0 14px 30px rgba(50, 101, 245, 0.22); }
.summary-number { display: block; font-size: 28px; font-weight: 800; line-height: 1; }
.summary-label { display: block; margin-top: 5px; font-size: 12px; opacity: .78; }
.task-panel__toolbar { display: flex; gap: 10px; padding: 0 18px 14px; }
.task-panel__list { flex: 1; min-height: 0; overflow-y: auto; padding: 0 12px 12px; }
.drawer-task { width: 100%; display: flex; align-items: center; gap: 11px; border: 0; background: transparent; padding: 13px 10px; border-radius: 14px; cursor: pointer; text-align: left; color: #1e2942; transition: background .16s ease, transform .16s ease; }
.drawer-task:hover { background: #f4f6fc; transform: translateX(2px); }
.drawer-task--parent { font-weight: 600; }
.drawer-task--child { padding-left: 26px; border-radius: 10px; }
.drawer-task--done { opacity: .55; }
.drawer-task--done .drawer-task__title { text-decoration: line-through; }
.drawer-task__state { width: 28px; height: 28px; flex: 0 0 28px; border-radius: 9px; display: grid; place-items: center; }
.drawer-task--child .drawer-task__state { width: 22px; height: 22px; border-radius: 7px; }
.drawer-subtasks { position: relative; margin-left: 18px; padding-left: 12px; border-left: 2px solid #e8e4f3; }
.drawer-task__state { width: 28px; height: 28px; flex: 0 0 28px; border-radius: 9px; display: grid; place-items: center; }
.priority-urgent { color: #e54545; background: #fff0f0; }
.priority-high { color: #ed941c; background: #fff6e9; }
.priority-medium { color: #4169e8; background: #eef2ff; }
.priority-low { color: #25a572; background: #eaf9f2; }
.drawer-task__body { flex: 1; min-width: 0; display: block; }
.drawer-task__title { display: block; font-size: 14px; font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.drawer-task__meta { display: flex; gap: 8px; margin-top: 4px; color: #8a94a9; font-size: 11px; }
.drawer-task__subcount { color: #7e6fa4; font-weight: 600; }
.task-panel__empty { min-height: 180px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: #929bad; font-size: 13px; }
.task-panel__footer { padding: 14px 18px 20px; border-top: 1px solid #edf0f6; }
</style>
