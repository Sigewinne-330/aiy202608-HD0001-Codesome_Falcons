<template>
  <section class="urgent-page">
    <header class="page-header">
      <div>
        <v-btn variant="text" size="small" prepend-icon="mdi-arrow-left" class="back-button" @click="router.push('/calendar')">返回日历</v-btn>
        <div class="eyebrow">PRIORITY QUEUE</div>
        <h1>紧急待处理项</h1>
        <p>展示未来 14 天内和已经逾期的项目，并按 Priority 从高到低排列。</p>
      </div>
      <div class="urgent-summary">
        <div><strong>{{ urgentItems.length }}</strong><span>待处理</span></div>
        <div class="danger"><strong>{{ overdueCount }}</strong><span>已逾期</span></div>
      </div>
    </header>

    <v-card class="urgent-list-card" rounded="xl" elevation="0">
      <div class="list-toolbar">
        <div class="d-flex align-center ga-2">
          <v-icon icon="mdi-alert-decagram-outline" color="error" />
          <span class="font-weight-bold">Deadline 队列</span>
        </div>
        <v-chip-group v-model="filter" mandatory selected-class="text-primary">
          <v-chip value="all" size="small" variant="outlined">全部</v-chip>
          <v-chip value="urgent" size="small" variant="outlined">紧急</v-chip>
          <v-chip value="high" size="small" variant="outlined">高优先级</v-chip>
        </v-chip-group>
      </div>

      <div v-if="loading" class="urgent-empty">
        <v-progress-circular indeterminate color="primary" />
        <span>正在检查 Deadline…</span>
      </div>

      <div v-else-if="filteredItems.length" class="urgent-list">
        <button
          v-for="(item, index) in filteredItems"
          :key="`${item.type}-${item.id}`"
          type="button"
          class="urgent-item"
          @click="openItem(item)"
        >
          <span class="rank">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="priority-marker" :class="`priority-marker--${item.priority}`">
            <v-icon :icon="item.type === 'deadline' ? 'mdi-calendar-alert' : 'mdi-checkbox-blank-circle-outline'" size="20" />
          </span>
          <span class="urgent-item__body">
            <span class="urgent-item__title">{{ item.title }}</span>
            <span class="urgent-item__meta">
              <span>{{ item.subject || '未分类' }}</span>
              <span>{{ item.type === 'deadline' ? 'Deadline' : '任务' }}</span>
            </span>
          </span>
          <v-chip :color="priorityColor(item.priority)" variant="tonal" size="small">{{ priorityLabel(item.priority) }}</v-chip>
          <span class="due-block" :class="{ overdue: item.daysLeft < 0 }">
            <strong>{{ dueLabel(item.daysLeft) }}</strong>
            <small>{{ formatDate(item.date) }}</small>
          </span>
          <v-icon icon="mdi-chevron-right" color="grey-lighten-1" />
        </button>
      </div>

      <div v-else class="urgent-empty">
        <v-icon icon="mdi-check-circle-outline" color="success" size="52" />
        <strong>当前没有符合条件的紧急项</strong>
        <span>可以回到日历继续安排接下来的工作。</span>
      </div>
    </v-card>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'

const router = useRouter()
const { token } = useAuth()
const items = ref([])
const loading = ref(true)
const filter = ref('all')

const urgentItems = computed(() => items.value
  .filter((item) => item.daysLeft <= 14)
  .sort((a, b) => priorityWeight(b.priority) - priorityWeight(a.priority) || a.daysLeft - b.daysLeft))

const filteredItems = computed(() => filter.value === 'all'
  ? urgentItems.value
  : urgentItems.value.filter((item) => item.priority === filter.value))

const overdueCount = computed(() => urgentItems.value.filter((item) => item.daysLeft < 0).length)

function flatten(nodes, output = []) {
  for (const item of nodes || []) {
    output.push(item)
    flatten(item.subtasks, output)
  }
  return output
}

function daysUntil(value) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const date = new Date(`${value}T00:00:00`)
  return Math.round((date - today) / 86400000)
}

function priorityWeight(priority) {
  return { urgent: 4, high: 3, medium: 2, low: 1 }[priority] || 0
}

function priorityLabel(priority) {
  return { urgent: '紧急', high: '高', medium: '中', low: '低' }[priority] || '普通'
}

function priorityColor(priority) {
  return { urgent: 'error', high: 'warning', medium: 'primary', low: 'success' }[priority] || 'primary'
}

function dueLabel(days) {
  if (days < 0) return `逾期 ${Math.abs(days)} 天`
  if (days === 0) return '今天到期'
  if (days === 1) return '明天到期'
  return `还剩 ${days} 天`
}

function formatDate(value) {
  const date = new Date(`${value}T00:00:00`)
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function openItem(item) {
  router.push({ path: item.type === 'deadline' ? '/deadlines' : '/tasks', query: { focus: item.id } })
}

async function loadItems() {
  loading.value = true
  try {
    const headers = token.value ? { Authorization: `Bearer ${token.value}` } : {}
    const [taskResponse, deadlineResponse] = await Promise.all([
      fetch('/api/tasks', { headers }),
      fetch('/api/deadlines', { headers }),
    ])
    const tasks = taskResponse.ok ? flatten(await taskResponse.json()) : []
    const deadlines = deadlineResponse.ok ? await deadlineResponse.json() : []

    const taskItems = tasks
      .filter((item) => item.deadline && !['done', 'completed'].includes(item.status))
      .map((item) => ({ ...item, type: 'task', date: item.deadline, daysLeft: daysUntil(item.deadline) }))
    const deadlineItems = deadlines
      .filter((item) => !['done', 'completed'].includes(item.status))
      .map((item) => ({ ...item, type: 'deadline', date: item.due_date, daysLeft: daysUntil(item.due_date) }))
    items.value = [...taskItems, ...deadlineItems]
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadItems)
</script>

<style scoped>
.urgent-page { min-height: calc(100vh - 64px); padding: 28px clamp(22px, 5vw, 70px) 110px; color: #1e2942; }
.page-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; margin-bottom: 24px; }
.back-button { margin-left: -12px; margin-bottom: 10px; color: #69758d; }
.eyebrow { color: #df4458; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
.page-header h1 { margin-top: 4px; font-size: clamp(28px, 3vw, 39px); letter-spacing: -.04em; }
.page-header p { margin-top: 8px; color: #7f899d; font-size: 13px; }
.urgent-summary { display: flex; gap: 10px; }
.urgent-summary > div { min-width: 106px; padding: 14px 18px; border: 1px solid #e7eaf1; border-radius: 16px; background: rgba(255,255,255,.8); }
.urgent-summary strong, .urgent-summary span { display: block; }
.urgent-summary strong { font-size: 21px; }
.urgent-summary span { margin-top: 2px; color: #8992a4; font-size: 10px; }
.urgent-summary .danger strong { color: #de4555; }
.urgent-list-card { overflow: hidden; border: 1px solid rgba(28,42,71,.09); background: rgba(255,255,255,.94) !important; box-shadow: 0 18px 50px rgba(31,44,75,.07) !important; }
.list-toolbar { min-height: 72px; display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 12px 22px; border-bottom: 1px solid #edf0f5; }
.urgent-list { padding: 8px 12px; }
.urgent-item { width: 100%; min-height: 76px; display: flex; align-items: center; gap: 14px; padding: 10px 12px; border: 0; border-bottom: 1px solid #f0f2f6; color: #27334c; background: transparent; cursor: pointer; text-align: left; transition: background .15s, transform .15s; }
.urgent-item:last-child { border-bottom: 0; }
.urgent-item:hover { background: #fafbfe; transform: translateX(2px); }
.rank { width: 24px; color: #abb2c0; font-size: 10px; font-weight: 750; }
.priority-marker { width: 38px; height: 38px; flex: 0 0 38px; display: grid; place-items: center; border-radius: 12px; color: #4169e8; background: #eef2ff; }
.priority-marker--urgent { color: #df4458; background: #fff0f2; }
.priority-marker--high { color: #eb8b26; background: #fff5e9; }
.urgent-item__body { flex: 1; min-width: 0; }
.urgent-item__title { display: block; font-size: 14px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.urgent-item__meta { display: flex; gap: 9px; margin-top: 5px; color: #8d96a7; font-size: 10px; }
.due-block { min-width: 90px; text-align: right; }
.due-block strong, .due-block small { display: block; }
.due-block strong { color: #5b667b; font-size: 11px; }
.due-block small { margin-top: 3px; color: #9aa2b1; font-size: 9px; }
.due-block.overdue strong { color: #df4458; }
.urgent-empty { min-height: 350px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: #8c95a7; font-size: 12px; }
.urgent-empty strong { color: #465168; font-size: 15px; }
@media (max-width: 720px) {
  .urgent-page { padding: 20px 14px 110px; }
  .urgent-summary { display: none; }
  .list-toolbar { align-items: flex-start; flex-direction: column; }
  .urgent-item { gap: 9px; }
  .rank, .urgent-item .v-chip { display: none; }
  .due-block { min-width: 72px; }
}
</style>
