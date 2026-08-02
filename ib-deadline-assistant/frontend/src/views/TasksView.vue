<template>
  <div class="h-100">
    <div class="d-flex align-center mb-4">
      <v-icon size="28" color="primary" class="mr-2">mdi-clipboard-list-outline</v-icon>
      <div>
        <div class="text-h6 font-weight-bold">任务管理</div>
        <div class="text-caption text-grey">任务管理、进度跟踪、高效执行</div>
      </div>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-plus" @click="openCreate">
        新建任务
      </v-btn>
    </div>

    <!-- 筛选 -->
    <v-row class="mb-4">
      <v-col cols="auto">
        <v-chip-group v-model="filter" mandatory>
          <v-chip value="all" variant="tonal">全部</v-chip>
          <v-chip value="todo" variant="tonal" color="warning">待办</v-chip>
          <v-chip value="in_progress" variant="tonal" color="primary">进行中</v-chip>
          <v-chip value="done" variant="tonal" color="success">已完成</v-chip>
          <v-chip value="overdue" variant="tonal" color="error">已逾期</v-chip>
        </v-chip-group>
      </v-col>
    </v-row>

    <!-- 任务列表 -->
    <v-row v-if="tasks.length > 0">
      <v-col cols="12" md="6" v-for="task in filteredTasks" :key="task.id">
        <v-card :border="task.status === 'overdue'" :color="task.status === 'overdue' ? 'error' : undefined" variant="outlined">
          <v-card-item>
            <template v-slot:prepend>
              <v-checkbox
                :model-value="task.status === 'done'"
                :color="task.status === 'overdue' ? 'error' : 'primary'"
                @update:model-value="toggleDone(task)"
                hide-details
              />
            </template>
            <v-card-title class="text-body-1 font-weight-bold">{{ task.title }}</v-card-title>
            <template v-slot:append>
              <v-btn icon="mdi-dots-vertical" variant="text" size="small" />
            </template>

            <v-card-subtitle v-if="task.description" class="text-caption mt-1">
              {{ task.description }}
            </v-card-subtitle>

            <div class="d-flex align-center gap-2 mt-2 flex-wrap">
              <v-chip v-if="task.subject" size="x-small" variant="tonal" color="primary">
                {{ task.subject }}
              </v-chip>
              <v-chip size="x-small" :color="priorityColor(task.priority)" variant="tonal">
                {{ priorityLabel(task.priority) }}
              </v-chip>
              <v-chip v-if="task.deadline" size="x-small" variant="tonal" color="grey">
                📅 {{ task.deadline }}
              </v-chip>
              <v-chip v-if="task.estimated_hours" size="x-small" variant="tonal" color="grey">
                ⏱ {{ task.estimated_hours }}h
              </v-chip>
            </div>

            <!-- 进度条 -->
            <div class="mt-3" v-if="task.status !== 'done'">
              <div class="d-flex justify-space-between text-caption text-grey mb-1">
                <span>进度</span>
                <span>{{ task.progress || 0 }}%</span>
              </div>
              <v-progress-linear
                :model-value="task.progress || 0"
                :color="task.status === 'overdue' ? 'error' : 'primary'"
                height="6"
                rounded
              />
            </div>

            <!-- 子任务 -->
            <div v-if="task.subtasks && task.subtasks.length > 0" class="mt-3">
              <div class="text-caption text-grey mb-1">子任务 ({{ task.subtasks.length }})</div>
              <div v-for="sub in task.subtasks" :key="sub.id" class="d-flex align-center py-1">
                <v-icon size="14" color="grey" class="mr-1">mdi-chevron-right</v-icon>
                <span class="text-caption" :class="{ 'text-decoration-line-through': sub.status === 'done' }">
                  {{ sub.title }}
                </span>
                <v-spacer />
                <v-chip size="x-small" variant="text">
                  {{ sub.status === 'done' ? '✅' : '⏳' }}
                </v-chip>
              </div>
            </div>
          </v-card-item>
        </v-card>
      </v-col>
    </v-row>

    <v-sheet v-else class="d-flex flex-column align-center justify-center pa-8" rounded="lg">
      <v-icon size="60" color="grey-lighten-1">mdi-clipboard-text-outline</v-icon>
      <div class="text-h6 text-grey-darken-1 mt-3">还没有任务</div>
      <div class="text-body-2 text-grey mt-1">创建一个任务，或者在任务规划页面生成执行计划</div>
      <v-btn color="primary" class="mt-4" @click="openCreate">创建第一个任务</v-btn>
    </v-sheet>

    <!-- 创建任务对话框 -->
    <v-dialog v-model="dialog" max-width="500">
      <v-card title="新建任务">
        <v-card-text>
          <v-text-field v-model="form.title" label="任务名称" variant="outlined" density="comfortable" class="mb-2" />
          <v-textarea v-model="form.description" label="描述（可选）" variant="outlined" density="comfortable" rows="2" class="mb-2" />
          <v-text-field v-model="form.subject" label="分类/标签（可选）" variant="outlined" density="comfortable" class="mb-2" />
          <v-select
            v-model="form.priority"
            label="优先级"
            :items="['low','medium','high','urgent']"
            variant="outlined"
            density="comfortable"
            class="mb-2"
          />
          <v-text-field v-model="form.deadline" label="截止日期 YYYY-MM-DD" variant="outlined" density="comfortable" class="mb-2" />
          <v-text-field v-model="form.estimated_hours" label="预计耗时（小时）" type="number" variant="outlined" density="comfortable" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="dialog = false">取消</v-btn>
          <v-btn color="primary" @click="createTask" :disabled="!form.title">创建</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const tasks = ref([])
const filter = ref('all')
const dialog = ref(false)
const form = ref({
  title: '',
  description: '',
  subject: '',
  priority: 'medium',
  deadline: '',
  estimated_hours: 0,
})

const API_BASE = '/api'

const filteredTasks = computed(() => {
  if (filter.value === 'all') return tasks.value
  return tasks.value.filter(t => t.status === filter.value)
})

function priorityColor(p) {
  return { low: 'grey', medium: 'primary', high: 'warning', urgent: 'error' }[p] || 'grey'
}
function priorityLabel(p) {
  return { low: '低', medium: '中', high: '高', urgent: '紧急' }[p] || p
}

async function loadTasks() {
  try {
    const res = await fetch(`${API_BASE}/tasks`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    tasks.value = await res.json()
  } catch { /* ignore */ }
}

function openCreate() {
  form.value = { title: '', description: '', subject: '', priority: 'medium', deadline: '', estimated_hours: 0 }
  dialog.value = true
}

async function createTask() {
  try {
    const res = await fetch(`${API_BASE}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    if (res.ok) {
      dialog.value = false
      await loadTasks()
    }
  } catch { /* ignore */ }
}

async function toggleDone(task) {
  const newStatus = task.status === 'done' ? 'todo' : 'done'
  try {
    await fetch(`${API_BASE}/tasks/${task.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus, progress: newStatus === 'done' ? 100 : task.progress }),
    })
    await loadTasks()
  } catch { /* ignore */ }
}

onMounted(loadTasks)
</script>

<style scoped>
.gap-2 { gap: 8px; }
</style>
