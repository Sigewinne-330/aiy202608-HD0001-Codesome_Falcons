<template>
  <section class="progress-page">
    <template v-if="!selectedCategory">
      <header class="page-header">
        <div>
          <v-btn variant="text" size="small" prepend-icon="mdi-arrow-left" class="back-button" @click="router.push('/calendar')">返回日历</v-btn>
          <div class="eyebrow">PROGRESS & RISK</div>
          <h1>进度管理</h1>
          <p>同时观察完成进度和当前风险，及时把精力放在最需要处理的分类。</p>
        </div>
        <v-chip color="primary" variant="tonal" prepend-icon="mdi-sync" @click="loadTasks">同步任务</v-chip>
      </header>

      <v-card class="overall-card" rounded="xl" elevation="0">
        <div class="overall-card__copy">
          <span class="section-tag">总状态</span>
          <h2>{{ overallSummary.title }}</h2>
          <p>{{ overallSummary.description }}</p>
        </div>
        <div class="overall-score">
          <v-progress-circular :model-value="overall.progress" :color="riskColor(overall.risk)" size="104" width="9">
            <div><strong>{{ overall.progress }}%</strong><span>完成</span></div>
          </v-progress-circular>
        </div>
        <div class="status-bars overall-bars">
          <StatusBar label="整体进度" :value="overall.progress" color="primary" />
          <StatusBar label="当前风险" :value="overall.risk" :color="riskColor(overall.risk)" :risk="true" />
        </div>
      </v-card>

      <div class="category-grid">
        <button
          v-for="category in categoryStats"
          :key="category.key"
          type="button"
          class="category-card"
          @click="router.push(`/progress/${category.key.toLowerCase()}`)"
        >
          <div class="category-card__header">
            <span class="category-icon" :style="{ background: category.softColor, color: category.color }">{{ category.key }}</span>
            <span class="category-meta">{{ category.count }} 项任务</span>
            <v-icon icon="mdi-arrow-top-right" size="20" color="grey-lighten-1" />
          </div>
          <div class="category-card__status">
            <strong>{{ category.progress }}%</strong>
            <span>{{ categoryStatus(category) }}</span>
          </div>
          <div class="status-bars">
            <StatusBar label="进度" :value="category.progress" :color="category.vuetifyColor" />
            <StatusBar label="风险" :value="category.risk" :color="riskColor(category.risk)" :risk="true" />
          </div>
        </button>
      </div>
    </template>

    <template v-else>
      <header class="detail-header">
        <v-btn icon="mdi-arrow-left" variant="tonal" aria-label="返回进度总览" @click="router.push('/progress')" />
        <span class="category-icon large" :style="{ background: selectedCategory.softColor, color: selectedCategory.color }">{{ selectedCategory.key }}</span>
        <div>
          <div class="eyebrow">CATEGORY MANAGEMENT</div>
          <h1>{{ selectedCategory.key }} 管理页</h1>
          <p>集中管理 {{ selectedCategory.key }} 的任务、进度和 Deadline 风险。</p>
        </div>
      </header>

      <div class="detail-summary-grid">
        <v-card rounded="xl" elevation="0">
          <span>分类进度</span><strong>{{ selectedCategory.progress }}%</strong>
          <v-progress-linear :model-value="selectedCategory.progress" :color="selectedCategory.vuetifyColor" height="8" rounded />
        </v-card>
        <v-card rounded="xl" elevation="0">
          <span>当前风险</span><strong>{{ selectedCategory.risk }}%</strong>
          <v-progress-linear :model-value="selectedCategory.risk" :color="riskColor(selectedCategory.risk)" height="8" rounded />
        </v-card>
        <v-card rounded="xl" elevation="0">
          <span>任务数量</span><strong>{{ selectedCategory.count }}</strong>
          <small>{{ selectedCategory.doneCount }} 项已完成</small>
        </v-card>
      </div>

      <v-card class="category-task-list" rounded="xl" elevation="0">
        <div class="task-list-title">{{ selectedCategory.key }} 任务</div>
        <button
          v-for="task in selectedCategory.tasks"
          :key="task.id"
          type="button"
          class="progress-task"
          @click="router.push({ path: '/tasks', query: { focus: task.id } })"
        >
          <v-icon :icon="isDone(task) ? 'mdi-check-circle' : 'mdi-circle-outline'" :color="isDone(task) ? 'success' : 'grey'" />
          <span class="progress-task__copy">
            <strong>{{ task.title }}</strong>
            <small>{{ task.deadline ? formatDate(task.deadline) : '暂无 Deadline' }}</small>
          </span>
          <span class="task-progress">{{ task.progress || 0 }}%</span>
          <v-progress-linear :model-value="task.progress || 0" :color="selectedCategory.vuetifyColor" height="5" rounded />
          <v-icon icon="mdi-chevron-right" color="grey-lighten-1" />
        </button>
        <div v-if="selectedCategory.tasks.length === 0" class="task-list-empty">
          <v-icon icon="mdi-folder-open-outline" size="46" color="grey-lighten-1" />
          <span>该分类还没有任务</span>
          <v-btn color="primary" variant="tonal" size="small" @click="router.push('/tasks')">前往添加</v-btn>
        </div>
      </v-card>
    </template>

    <div v-if="loading" class="page-loading">
      <v-progress-circular indeterminate color="primary" size="42" />
    </div>
  </section>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const { token } = useAuth()
const tasks = ref([])
const loading = ref(true)

const StatusBar = defineComponent({
  props: { label: String, value: Number, color: String, risk: Boolean },
  setup(props) {
    return () => h('div', { class: 'status-bar' }, [
      h('div', { class: 'status-bar__label' }, [
        h('span', props.label),
        h('strong', props.risk ? riskLabel(props.value) : `${props.value}%`),
      ]),
      h('div', { class: 'status-bar__track' }, [
        h('i', { style: { width: `${props.value}%`, background: colorHex(props.color) } }),
      ]),
    ])
  },
})

const categoryDefinitions = [
  { key: 'IA', color: '#3f6ee8', softColor: '#edf2ff', vuetifyColor: 'primary' },
  { key: 'EE', color: '#7c55d9', softColor: '#f2edff', vuetifyColor: 'deep-purple' },
  { key: 'TOK', color: '#d48124', softColor: '#fff4e6', vuetifyColor: 'warning' },
  { key: 'CAS', color: '#22986b', softColor: '#e9f8f1', vuetifyColor: 'success' },
]

const categoryStats = computed(() => categoryDefinitions.map((definition) => {
  const categoryTasks = tasks.value.filter((task) => detectCategory(task) === definition.key)
  const progress = average(categoryTasks.map((task) => isDone(task) ? 100 : Number(task.progress || 0)))
  const risk = average(categoryTasks.map(taskRisk))
  return {
    ...definition,
    tasks: categoryTasks,
    count: categoryTasks.length,
    doneCount: categoryTasks.filter(isDone).length,
    progress,
    risk,
  }
}))

const overall = computed(() => ({
  progress: average(tasks.value.map((task) => isDone(task) ? 100 : Number(task.progress || 0))),
  risk: average(tasks.value.filter((task) => !isDone(task)).map(taskRisk)),
}))

const overallSummary = computed(() => {
  if (!tasks.value.length) return { title: '等待建立第一项计划', description: '添加 IA、EE、TOK 或 CAS 任务后，这里会汇总你的整体状态。' }
  if (overall.value.risk >= 70) return { title: '需要立即关注', description: '多个 Deadline 已接近或逾期，建议先处理高风险项目。' }
  if (overall.value.risk >= 40) return { title: '进展中，存在风险', description: '整体节奏尚可，但仍有项目需要提前推进。' }
  return { title: '整体状态良好', description: '当前进度稳定，继续保持现有节奏。' }
})

const selectedCategory = computed(() => {
  const key = String(route.params.category || '').toUpperCase()
  return categoryStats.value.find((category) => category.key === key) || null
})

function flatten(nodes, output = []) {
  for (const item of nodes || []) {
    output.push(item)
    flatten(item.subtasks, output)
  }
  return output
}

function detectCategory(task) {
  const text = `${task.subject || ''} ${task.title || ''}`.toUpperCase()
  if (/\bTOK\b|THEORY OF KNOWLEDGE/.test(text)) return 'TOK'
  if (/\bCAS\b|CREATIVITY.*ACTIVITY.*SERVICE/.test(text)) return 'CAS'
  if (/\bEE\b|EXTENDED ESSAY/.test(text)) return 'EE'
  if (/\bIA\b|INTERNAL ASSESSMENT/.test(text)) return 'IA'
  return ''
}

function average(values) {
  if (!values.length) return 0
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)
}

function isDone(task) {
  return ['done', 'completed'].includes(task.status)
}

function taskRisk(task) {
  if (isDone(task)) return 0
  if (!task.deadline) return 20
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const due = new Date(`${task.deadline}T00:00:00`)
  const days = Math.round((due - today) / 86400000)
  let base = 20
  if (days < 0) base = 100
  else if (days <= 3) base = 90
  else if (days <= 7) base = 75
  else if (days <= 14) base = 58
  else if (days <= 30) base = 38
  return Math.max(0, Math.round(base - Number(task.progress || 0) * 0.25))
}

function riskLabel(value) {
  if (value >= 70) return '高风险'
  if (value >= 40) return '需关注'
  return '低风险'
}

function riskColor(value) {
  if (value >= 70) return 'error'
  if (value >= 40) return 'warning'
  return 'success'
}

function colorHex(color) {
  return { primary: '#4169e8', 'deep-purple': '#7c55d9', warning: '#e59a38', success: '#2ca676', error: '#df4b5d' }[color] || color
}

function categoryStatus(category) {
  if (!category.count) return '尚未开始'
  if (category.risk >= 70) return '需要立即处理'
  if (category.progress >= 80) return '接近完成'
  return '稳步推进中'
}

function formatDate(value) {
  const date = new Date(`${value}T00:00:00`)
  return `${date.getMonth() + 1}月${date.getDate()}日 Deadline`
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
.progress-page { position: relative; min-height: calc(100vh - 64px); padding: 28px clamp(22px, 5vw, 70px) 110px; color: #1e2942; }
.page-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; margin-bottom: 24px; }
.back-button { margin-left: -12px; margin-bottom: 10px; color: #69758d; }
.eyebrow { color: #4a6ce2; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
.page-header h1, .detail-header h1 { margin-top: 4px; font-size: clamp(28px, 3vw, 39px); letter-spacing: -.04em; }
.page-header p, .detail-header p { margin-top: 8px; color: #7f899d; font-size: 13px; }
.overall-card { display: grid; grid-template-columns: 1.2fr auto 1fr; align-items: center; gap: 40px; padding: 28px 32px; border: 1px solid rgba(39,53,83,.09); background: linear-gradient(135deg, rgba(255,255,255,.96), rgba(244,247,255,.96)) !important; box-shadow: 0 18px 50px rgba(31,44,75,.07) !important; }
.section-tag { display: inline-flex; padding: 4px 9px; border-radius: 999px; color: #4169e8; background: #edf2ff; font-size: 10px; font-weight: 750; }
.overall-card__copy h2 { margin-top: 12px; font-size: 22px; }
.overall-card__copy p { max-width: 390px; margin-top: 7px; color: #808a9f; font-size: 12px; }
.overall-score :deep(.v-progress-circular__content) > div { text-align: center; }
.overall-score strong, .overall-score span { display: block; }
.overall-score strong { font-size: 21px; }
.overall-score span { color: #8f98aa; font-size: 9px; }
.status-bars { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.overall-bars { grid-template-columns: 1fr; }
:deep(.status-bar__label) { display: flex; align-items: center; justify-content: space-between; margin-bottom: 7px; color: #8b94a5; font-size: 10px; }
:deep(.status-bar__label strong) { color: #4e596f; font-size: 10px; }
:deep(.status-bar__track) { height: 7px; overflow: hidden; border-radius: 999px; background: #edf0f5; }
:deep(.status-bar__track i) { display: block; height: 100%; border-radius: inherit; }
.category-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
.category-card { padding: 22px; border: 1px solid rgba(39,53,83,.09); border-radius: 20px; color: #24304a; background: rgba(255,255,255,.94); box-shadow: 0 12px 34px rgba(31,44,75,.055); cursor: pointer; text-align: left; transition: transform .18s, box-shadow .18s; }
.category-card:hover { transform: translateY(-3px); box-shadow: 0 18px 38px rgba(31,44,75,.1); }
.category-card__header { display: flex; align-items: center; gap: 11px; }
.category-icon { min-width: 47px; height: 39px; display: inline-grid; place-items: center; padding: 0 10px; border-radius: 12px; font-size: 14px; font-weight: 850; letter-spacing: .02em; }
.category-icon.large { height: 54px; min-width: 66px; border-radius: 16px; font-size: 18px; }
.category-meta { flex: 1; color: #8d96a8; font-size: 10px; }
.category-card__status { display: flex; align-items: baseline; gap: 9px; margin: 18px 0 14px; }
.category-card__status strong { font-size: 24px; }
.category-card__status span { color: #7e889c; font-size: 11px; }
.detail-header { display: flex; align-items: center; gap: 16px; margin-bottom: 26px; }
.detail-summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.detail-summary-grid .v-card { padding: 20px; border: 1px solid rgba(39,53,83,.09); }
.detail-summary-grid span, .detail-summary-grid strong, .detail-summary-grid small { display: block; }
.detail-summary-grid span { color: #858fa2; font-size: 11px; }
.detail-summary-grid strong { margin: 7px 0 11px; font-size: 24px; }
.detail-summary-grid small { color: #9aa2b1; font-size: 10px; }
.category-task-list { margin-top: 18px; overflow: hidden; border: 1px solid rgba(39,53,83,.09); background: rgba(255,255,255,.94) !important; }
.task-list-title { padding: 20px 22px; border-bottom: 1px solid #edf0f5; font-weight: 750; }
.progress-task { width: 100%; display: grid; grid-template-columns: auto minmax(150px, 1fr) auto minmax(120px, .6fr) auto; align-items: center; gap: 14px; padding: 15px 22px; border: 0; border-bottom: 1px solid #f0f2f6; color: #303c54; background: transparent; cursor: pointer; text-align: left; }
.progress-task:hover { background: #fafbfe; }
.progress-task__copy strong, .progress-task__copy small { display: block; }
.progress-task__copy strong { font-size: 13px; }
.progress-task__copy small { margin-top: 4px; color: #929bad; font-size: 9px; }
.task-progress { color: #59657d; font-size: 11px; font-weight: 700; }
.task-list-empty { min-height: 260px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: #8e97a9; font-size: 12px; }
.page-loading { position: fixed; inset: 64px 0 0; z-index: 4; display: grid; place-items: center; background: rgba(248,249,252,.72); backdrop-filter: blur(3px); }
@media (max-width: 800px) {
  .progress-page { padding: 20px 14px 110px; }
  .overall-card { grid-template-columns: 1fr auto; gap: 18px; }
  .overall-bars { grid-column: 1 / -1; grid-template-columns: 1fr 1fr; }
  .category-grid { grid-template-columns: 1fr; }
  .detail-summary-grid { grid-template-columns: 1fr; }
  .progress-task { grid-template-columns: auto 1fr auto; }
  .progress-task > .v-progress-linear, .task-progress { display: none; }
}
</style>
