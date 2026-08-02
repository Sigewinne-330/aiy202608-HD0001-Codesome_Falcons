<template>
  <div>
    <div class="text-h6 font-weight-bold mb-4">📊 仪表盘</div>

    <!-- 统计卡片 -->
    <v-row class="mb-4">
      <v-col cols="6" md="3">
        <v-card class="text-center pa-4" color="primary" variant="tonal">
          <div class="text-h4 font-weight-bold">{{ stats.totalTasks }}</div>
          <div class="text-caption">总任务数</div>
        </v-card>
      </v-col>
      <v-col cols="6" md="3">
        <v-card class="text-center pa-4" color="warning" variant="tonal">
          <div class="text-h4 font-weight-bold">{{ stats.pendingTasks }}</div>
          <div class="text-caption">待办任务</div>
        </v-card>
      </v-col>
      <v-col cols="6" md="3">
        <v-card class="text-center pa-4" color="error" variant="tonal">
          <div class="text-h4 font-weight-bold">{{ stats.overdueCount }}</div>
          <div class="text-caption">逾期项</div>
        </v-card>
      </v-col>
      <v-col cols="6" md="3">
        <v-card class="text-center pa-4" color="success" variant="tonal">
          <div class="text-h4 font-weight-bold">{{ stats.completionRate }}%</div>
          <div class="text-caption">完成率</div>
        </v-card>
      </v-col>
    </v-row>

    <!-- 即将到期 & 最近任务 -->
    <v-row>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>
            <v-icon color="warning" class="mr-2">mdi-alert-circle-outline</v-icon>
            即将到期
          </v-card-title>
          <v-list v-if="upcomingDeadlines.length > 0" lines="two">
            <v-list-item v-for="d in upcomingDeadlines" :key="d.id">
              <template v-slot:prepend>
                <v-icon :color="d.priority === 'urgent' ? 'error' : 'warning'">
                  mdi-calendar-alert
                </v-icon>
              </template>
              <v-list-item-title>{{ d.title }}</v-list-item-title>
              <v-list-item-subtitle>
                {{ d.due_date }} · {{ d.subject || '无科目' }}
              </v-list-item-subtitle>
            </v-list-item>
          </v-list>
          <v-card-text v-else class="text-center py-4 text-caption text-grey">
            暂无即将到期的 Deadline 🎉
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>
            <v-icon color="primary" class="mr-2">mdi-progress-clock</v-icon>
            进行中的任务
          </v-card-title>
          <v-list v-if="inProgressTasks.length > 0" lines="two">
            <v-list-item v-for="t in inProgressTasks" :key="t.id">
              <template v-slot:prepend>
                <v-progress-circular
                  :model-value="t.progress || 0"
                  :color="t.status === 'overdue' ? 'error' : 'primary'"
                  size="36"
                  width="3"
                >
                  {{ t.progress || 0 }}%
                </v-progress-circular>
              </template>
              <v-list-item-title>{{ t.title }}</v-list-item-title>
              <v-list-item-subtitle>
                <v-chip size="x-small" variant="tonal" class="mr-1">
                  {{ t.priority }}
                </v-chip>
                {{ t.subject || '' }}
              </v-list-item-subtitle>
            </v-list-item>
          </v-list>
          <v-card-text v-else class="text-center py-4 text-caption text-grey">
            没有进行中的任务
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const tasks = ref([])
const upcomingDeadlines = ref([])

const API_BASE = '/api'

const stats = computed(() => {
  const total = tasks.value.length
  const pending = tasks.value.filter(t => t.status !== 'done').length
  const overdue = tasks.value.filter(t => t.status === 'overdue').length
  const done = tasks.value.filter(t => t.status === 'done').length
  const rate = total > 0 ? Math.round((done / total) * 100) : 0
  const overdueDeadlines = upcomingDeadlines.value.filter(d => d.status === 'overdue').length
  return {
    totalTasks: total,
    pendingTasks: pending,
    overdueCount: overdue + overdueDeadlines,
    completionRate: rate,
  }
})

const inProgressTasks = computed(() =>
  tasks.value.filter(t => t.status === 'in_progress' || t.status === 'overdue')
)

async function loadData() {
  try {
    const [taskRes, deadlineRes] = await Promise.all([
      fetch(`${API_BASE}/tasks`).then(r => r.json()),
      fetch(`${API_BASE}/deadlines/upcoming?days=7`).then(r => r.json()),
    ])

    // 展平任务树
    function flatten(tree, result = []) {
      for (const t of tree) {
        result.push(t)
        if (t.subtasks) flatten(t.subtasks, result)
      }
      return result
    }
    tasks.value = flatten(taskRes)
    upcomingDeadlines.value = deadlineRes
  } catch { /* ignore */ }
}

onMounted(loadData)
</script>
