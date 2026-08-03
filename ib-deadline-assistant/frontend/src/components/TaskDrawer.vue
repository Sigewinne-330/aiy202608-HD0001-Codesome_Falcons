<template>
  <div class="task-panel">
    <div class="task-panel__header">
      <div>
        <div class="text-h6 font-weight-bold">任务列表</div>
        <div class="text-caption text-medium-emphasis">今天要推进的事情</div>
      </div>
      <v-btn icon="mdi-close" variant="text" size="small" aria-label="关闭任务列表" @click="$emit('close')" />
    </div>

    <div class="task-panel__summary">
      <div>
        <span class="summary-number">{{ pendingCount }}</span>
        <span class="summary-label">待处理</span>
      </div>
      <v-progress-circular :model-value="completionRate" color="success" size="52" width="5">
        <span class="text-caption font-weight-bold">{{ completionRate }}%</span>
      </v-progress-circular>
    </div>

    <div class="task-panel__toolbar">
      <v-text-field
        v-model="search"
        prepend-inner-icon="mdi-magnify"
        placeholder="搜索任务"
        density="compact"
        variant="solo-filled"
        flat
        hide-details
        clearable
      />
      <v-btn icon="mdi-plus" color="primary" variant="flat" aria-label="新建任务" @click="goToTasks" />
    </div>

    <div class="task-panel__list scroll-container">
      <div v-if="loading" class="task-panel__empty">
        <v-progress-circular indeterminate color="primary" size="30" />
        <span>正在加载任务…</span>
      </div>

      <button
        v-for="task in filteredTasks"
        v-else
        :key="task.id"
        type="button"
        class="drawer-task"
        @click="openTask(task)"
      >
        <span class="drawer-task__state" :class="`priority-${task.priority}`">
          <v-icon :icon="isDone(task) ? 'mdi-check' : 'mdi-circle-outline'" size="16" />
        </span>
        <span class="drawer-task__body">
          <span class="drawer-task__title">{{ task.title }}</span>
          <span class="drawer-task__meta">
            <span v-if="task.subject">{{ task.subject }}</span>
            <span v-if="task.deadline">{{ formatDate(task.deadline) }}</span>
          </span>
          <v-progress-linear
            :model-value="task.progress || 0"
            :color="priorityColor(task.priority)"
            height="3"
            rounded
            class="mt-2"
          />
        </span>
        <v-icon icon="mdi-chevron-right" size="18" color="grey-lighten-1" />
      </button>

      <div v-if="!loading && filteredTasks.length === 0" class="task-panel__empty">
        <v-icon icon="mdi-checkbox-marked-circle-outline" color="success" size="42" />
        <span>{{ search ? '没有匹配的任务' : '暂时没有待处理任务' }}</span>
      </div>
    </div>

    <div class="task-panel__footer">
      <v-btn variant="tonal" color="primary" block prepend-icon="mdi-view-list-outline" @click="goToTasks">
        打开任务管理
      </v-btn>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'

defineEmits(['close'])

const router = useRouter()
const { token } = useAuth()
const tasks = ref([])
const loading = ref(true)
const search = ref('')

function flatten(nodes, output = []) {
  for (const task of nodes || []) {
    output.push(task)
    flatten(task.subtasks, output)
  }
  return output
}

const filteredTasks = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return tasks.value
    .filter((task) => !isDone(task))
    .filter((task) => !keyword || `${task.title} ${task.subject || ''}`.toLowerCase().includes(keyword))
    .sort((a, b) => priorityWeight(b.priority) - priorityWeight(a.priority))
})

const pendingCount = computed(() => tasks.value.filter((task) => !isDone(task)).length)
const completionRate = computed(() => {
  if (!tasks.value.length) return 0
  return Math.round((tasks.value.filter(isDone).length / tasks.value.length) * 100)
})

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
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function openTask(task) {
  router.push({ path: '/tasks', query: { focus: task.id } })
}

function goToTasks() {
  router.push('/tasks')
}

async function loadTasks() {
  loading.value = true
  try {
    const headers = token.value ? { Authorization: `Bearer ${token.value}` } : {}
    const response = await fetch('/api/tasks', { headers })
    tasks.value = response.ok ? flatten(await response.json()) : []
  } catch {
    tasks.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadTasks)
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
.drawer-task__state { width: 28px; height: 28px; flex: 0 0 28px; border-radius: 9px; display: grid; place-items: center; }
.priority-urgent { color: #e54545; background: #fff0f0; }
.priority-high { color: #ed941c; background: #fff6e9; }
.priority-medium { color: #4169e8; background: #eef2ff; }
.priority-low { color: #25a572; background: #eaf9f2; }
.drawer-task__body { flex: 1; min-width: 0; display: block; }
.drawer-task__title { display: block; font-size: 14px; font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.drawer-task__meta { display: flex; gap: 8px; margin-top: 4px; color: #8a94a9; font-size: 11px; }
.task-panel__empty { min-height: 180px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: #929bad; font-size: 13px; }
.task-panel__footer { padding: 14px 18px 20px; border-top: 1px solid #edf0f6; }
</style>
