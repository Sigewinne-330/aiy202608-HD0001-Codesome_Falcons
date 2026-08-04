<template>
  <section class="progress-page">
    <template v-if="detailTimeline && selectedCategoryMeta">
      <TimelineManager
        :timeline="detailTimeline"
        :category-meta="selectedCategoryMeta"
        :template-nodes="templateFor(selectedCategoryMeta.key, detailTimeline.subject)"
        @back="leaveTimeline"
        @changed="loadTasks"
        @removed="handleTimelineRemoved"
      />
    </template>

    <template v-else-if="selectedCategoryMeta">
      <header class="category-header">
        <v-btn icon="mdi-arrow-left" variant="tonal" :aria-label="$t('progress.backOverview')" @click="router.push('/progress')" />
        <span class="category-icon large" :style="{ background: selectedCategoryMeta.softColor, color: selectedCategoryMeta.color }">{{ selectedCategoryMeta.key }}</span>
        <div class="category-header__copy">
          <div class="eyebrow">{{ $t('progress.eyebrowCategory') }}</div>
          <h1>{{ categoryTitle(selectedCategoryMeta.key) }}</h1>
          <p>{{ categoryDescription(selectedCategoryMeta.key) }}</p>
        </div>
        <div class="header-actions">
          <v-btn prepend-icon="mdi-creation-outline" color="primary" variant="tonal" @click="askAgentForCategory">{{ $t('progress.askAgent') }}</v-btn>
          <v-btn prepend-icon="mdi-plus" color="primary" variant="flat" @click="openCreateTimeline()">{{ createButtonLabel }}</v-btn>
        </div>
      </header>

      <div class="category-summary-grid">
        <v-card rounded="xl" elevation="0">
          <span>{{ $t('progress.categoryProgress') }}</span><strong>{{ selectedCategoryStats.progress }}%</strong>
          <v-progress-linear :model-value="selectedCategoryStats.progress" :color="selectedCategoryMeta.vuetifyColor" height="7" rounded />
        </v-card>
        <v-card rounded="xl" elevation="0">
          <span>{{ $t('progress.currentRisk') }}</span><strong>{{ selectedCategoryStats.configured ? riskLabel(selectedCategoryStats.risk) : $t('progress.notPlanned') }}</strong>
          <v-progress-linear :model-value="selectedCategoryStats.risk" :color="riskColor(selectedCategoryStats.risk)" height="7" rounded />
        </v-card>
        <v-card rounded="xl" elevation="0">
          <span>{{ $t('progress.timelines') }}</span><strong>{{ selectedCategoryStats.count }}</strong>
          <small>{{ $t('progress.milestoneCount', { n: selectedCategoryStats.nodeCount }) }}</small>
        </v-card>
        <v-card rounded="xl" elevation="0">
          <span>{{ $t('progress.nextDeadline') }}</span><strong class="next-date">{{ selectedCategoryStats.next ? formatDate(selectedCategoryStats.next.deadline) : '—' }}</strong>
          <small>{{ selectedCategoryStats.next?.title || $t('progress.noUpcoming') }}</small>
        </v-card>
      </div>

      <div v-if="selectedCategoryMeta.groups?.length" class="group-tabs">
        <button v-for="group in selectedCategoryMeta.groups" :key="group" type="button" :class="{ active: activeGroup === group }" @click="activeGroup = group">
          {{ groupLabel(group) }}
          <span>{{ groupCount(group) }}</span>
        </button>
      </div>

      <div v-if="visibleTimelines.length" class="timeline-grid">
        <button v-for="timeline in visibleTimelines" :key="timeline.id" type="button" class="timeline-card" @click="openTimeline(timeline)">
          <div class="timeline-card__top">
            <span class="timeline-avatar" :style="{ background: selectedCategoryMeta.softColor, color: selectedCategoryMeta.color }">
              {{ timelineBadge(timeline) }}
            </span>
            <div>
              <h2>{{ timeline.title }}</h2>
              <p>{{ timeline.subject || $t('progress.noGroup') }}</p>
            </div>
            <v-icon icon="mdi-arrow-top-right" color="grey-lighten-1" />
          </div>
          <div class="timeline-card__progress">
            <strong>{{ timelineProgress(timeline) }}%</strong>
            <span>{{ timelineStatus(timeline) }}</span>
          </div>
          <v-progress-linear :model-value="timelineProgress(timeline)" :color="selectedCategoryMeta.vuetifyColor" height="7" rounded />
          <div class="timeline-card__meta">
            <span><v-icon icon="mdi-format-list-checks" size="14" />{{ $t('progress.milestoneCount', { n: timeline.subtasks?.length || 0 }) }}</span>
            <span><v-icon icon="mdi-calendar-outline" size="14" />{{ timelineNext(timeline) ? formatDate(timelineNext(timeline).deadline) : $t('progress.noUpcoming') }}</span>
            <span :class="`risk-text-${riskLevel(timelineRisk(timeline))}`"><v-icon icon="mdi-alert-circle-outline" size="14" />{{ riskLabel(timelineRisk(timeline)) }}</span>
          </div>
        </button>
      </div>

      <div v-else class="category-empty">
        <span><v-icon icon="mdi-timeline-plus-outline" size="42" /></span>
        <h2>{{ $t('progress.emptyCategoryTitle') }}</h2>
        <p>{{ emptyCategoryDescription }}</p>
        <div>
          <v-btn color="primary" variant="tonal" prepend-icon="mdi-creation-outline" @click="askAgentForCategory">{{ $t('progress.planWithAgent') }}</v-btn>
          <v-btn color="primary" variant="flat" prepend-icon="mdi-plus" @click="openCreateTimeline()">{{ createButtonLabel }}</v-btn>
        </div>
      </div>
    </template>

    <template v-else>
      <header class="page-header">
        <div>
          <div class="eyebrow">{{ $t('progress.eyebrow') }}</div>
          <h1>{{ $t('progress.title') }}</h1>
          <p>{{ $t('progress.subtitle') }}</p>
        </div>
        <v-btn color="primary" variant="tonal" prepend-icon="mdi-refresh" :loading="loading" @click="loadTasks">{{ $t('progress.refresh') }}</v-btn>
      </header>

      <v-card class="overall-card" rounded="xl" elevation="0">
        <div class="overall-card__copy">
          <span class="section-tag">{{ $t('progress.overall') }}</span>
          <h2>{{ overallSummary.title }}</h2>
          <p>{{ overallSummary.description }}</p>
          <div v-if="overall.next" class="overall-next"><v-icon icon="mdi-calendar-clock-outline" size="16" />{{ $t('progress.nextItem', { name: overall.next.title, date: formatDate(overall.next.deadline) }) }}</div>
        </div>
        <div class="overall-score">
          <v-progress-circular :model-value="overall.progress" :color="overall.configured ? riskColor(overall.risk) : 'grey-lighten-1'" size="108" width="9">
            <div><strong>{{ overall.progress }}%</strong><span>{{ $t('progress.completed') }}</span></div>
          </v-progress-circular>
        </div>
        <div class="overall-bars">
          <div class="status-bar">
            <div><span>{{ $t('progress.overallProgress') }}</span><strong>{{ overall.progress }}%</strong></div>
            <v-progress-linear :model-value="overall.progress" color="primary" height="7" rounded />
          </div>
          <div class="status-bar">
            <div><span>{{ $t('progress.currentRisk') }}</span><strong>{{ overall.configured ? riskLabel(overall.risk) : $t('progress.notPlanned') }}</strong></div>
            <v-progress-linear :model-value="overall.risk" :color="riskColor(overall.risk)" height="7" rounded />
          </div>
        </div>
      </v-card>

      <div class="category-grid">
        <button v-for="category in categoryStats" :key="category.key" type="button" class="category-card" @click="router.push(`/progress/${category.key.toLowerCase()}`)">
          <div class="category-card__header">
            <span class="category-icon" :style="{ background: category.softColor, color: category.color }">{{ category.key }}</span>
            <span class="category-meta">{{ $t('progress.timelineItems', { n: category.count }) }}</span>
            <v-icon icon="mdi-arrow-top-right" size="20" color="grey-lighten-1" />
          </div>
          <div class="category-card__status">
            <strong>{{ category.progress }}%</strong>
            <span>{{ category.configured ? categoryStatus(category) : $t('progress.notPlanned') }}</span>
          </div>
          <div class="card-bars">
            <div><span>{{ $t('progress.progress') }}</span><strong>{{ category.progress }}%</strong><v-progress-linear :model-value="category.progress" :color="category.vuetifyColor" height="6" rounded /></div>
            <div><span>{{ $t('progress.risk') }}</span><strong>{{ category.configured ? riskLabel(category.risk) : '—' }}</strong><v-progress-linear :model-value="category.risk" :color="riskColor(category.risk)" height="6" rounded /></div>
          </div>
          <div class="category-next"><v-icon icon="mdi-calendar-outline" size="14" />{{ category.next ? `${category.next.title} · ${formatDate(category.next.deadline)}` : $t('progress.noUpcoming') }}</div>
        </button>
      </div>
    </template>

    <v-dialog v-model="createDialog" max-width="540">
      <v-card rounded="xl">
        <v-card-title class="dialog-title">{{ createDialogTitle }}</v-card-title>
        <v-card-text class="dialog-body">
          <v-select v-if="selectedCategoryMeta?.groups?.length" v-model="timelineForm.subject" :label="$t('progress.groupType')" :items="selectedCategoryMeta.groups.map((value) => ({ value, title: groupLabel(value) }))" item-title="title" item-value="value" variant="outlined" />
          <v-text-field v-else v-model="timelineForm.subject" :label="subjectFieldLabel" variant="outlined" />
          <v-text-field v-model="timelineForm.title" :label="$t('progress.timelineName')" :placeholder="titlePlaceholder" variant="outlined" />
          <v-text-field v-model="timelineForm.deadline" :label="$t('progress.finalDeadline')" type="date" variant="outlined" />
          <v-select v-model="timelineForm.priority" :label="$t('progress.importance')" :items="priorityOptions" item-title="title" item-value="value" variant="outlined" />
          <v-checkbox v-model="timelineForm.useTemplate" :label="$t('progress.createDefaultMilestones')" color="primary" hide-details />
        </v-card-text>
        <v-card-actions class="dialog-actions">
          <v-spacer />
          <v-btn variant="text" @click="createDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" variant="flat" :loading="saving" :disabled="!canCreateTimeline" @click="createTimeline">{{ $t('common.create') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <div v-if="loading" class="page-loading"><v-progress-circular indeterminate color="primary" size="42" /></div>
    <v-snackbar v-model="errorVisible" color="error" timeout="3500">{{ errorMessage }}</v-snackbar>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { authFetch } from '@/stores/auth'
import TimelineManager from '@/components/TimelineManager.vue'
import { notifyTasksChanged, onTasksChanged } from '@/services/taskSync'
import { openAgent } from '@/services/agentContext'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const tasks = ref([])
const loading = ref(true)
const saving = ref(false)
const createDialog = ref(false)
const errorVisible = ref(false)
const errorMessage = ref('')
const activeGroup = ref('')

const categoryDefinitions = [
  { key: 'IA', color: '#3f6ee8', softColor: '#edf2ff', vuetifyColor: 'primary', groups: null },
  { key: 'EE', color: '#7c55d9', softColor: '#f2edff', vuetifyColor: 'deep-purple', groups: null },
  { key: 'TOK', color: '#d48124', softColor: '#fff4e6', vuetifyColor: 'warning', groups: ['Essay', 'Exhibition'] },
  { key: 'CAS', color: '#22986b', softColor: '#e9f8f1', vuetifyColor: 'success', groups: ['Experience', 'Project', 'Reflection', 'Evidence'] },
]

const emptyTimelineForm = () => ({ title: '', subject: '', deadline: '', priority: 'medium', useTemplate: true })
const timelineForm = ref(emptyTimelineForm())

const priorityOptions = computed(() => [
  { title: t('common.low'), value: 'low' },
  { title: t('common.medium'), value: 'medium' },
  { title: t('common.high'), value: 'high' },
  { title: t('common.urgent'), value: 'urgent' },
])

const selectedCategoryMeta = computed(() => {
  const key = String(route.params.category || '').toUpperCase()
  return categoryDefinitions.find((item) => item.key === key) || null
})

function detectLegacyCategory(task) {
  const text = `${task.subject || ''} ${task.title || ''}`.toUpperCase()
  if (/\bTOK\b|THEORY OF KNOWLEDGE/.test(text)) return 'TOK'
  if (/\bCAS\b|CREATIVITY.*ACTIVITY.*SERVICE/.test(text)) return 'CAS'
  if (/\bEE\b|EXTENDED ESSAY/.test(text)) return 'EE'
  if (/\bIA\b|INTERNAL ASSESSMENT/.test(text)) return 'IA'
  return ''
}

function taskCategory(task) {
  return String(task.category || detectLegacyCategory(task)).toUpperCase()
}

function statusProgress(status) {
  if (status === 'done' || status === 'completed') return 100
  if (status === 'in_progress') return 50
  return 0
}

function timelineProgress(timeline) {
  const nodes = timeline.subtasks || []
  if (!nodes.length) return timeline.task_type === 'process' ? 0 : (timeline.status === 'done' ? 100 : Number(timeline.progress || 0))
  return Math.round(nodes.reduce((sum, node) => sum + statusProgress(node.status), 0) / nodes.length)
}

function itemRisk(item) {
  if (item.status === 'done' || item.status === 'completed') return 0
  if (!item.deadline) return 25
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((new Date(`${item.deadline}T00:00:00`) - today) / 86400000)
  let base = 18
  if (days < 0) base = 100
  else if (days <= 3) base = 88
  else if (days <= 7) base = 72
  else if (days <= 14) base = 52
  else if (days <= 30) base = 32
  const statusFactor = item.status === 'in_progress' ? 0.72 : 1
  const priorityFactor = { low: 0.75, medium: 0.9, high: 1.05, urgent: 1.18 }[item.priority] || 0.9
  return Math.min(100, Math.round(base * statusFactor * priorityFactor))
}

function timelineRisk(timeline) {
  const nodes = timeline.subtasks?.length ? timeline.subtasks : [timeline]
  const scores = nodes.filter((item) => !['done', 'completed'].includes(item.status)).map(itemRisk)
  if (!scores.length) return 0
  const average = scores.reduce((sum, value) => sum + value, 0) / scores.length
  return Math.round(Math.max(...scores) * 0.6 + average * 0.4)
}

function timelineNext(timeline) {
  const nodes = timeline.subtasks?.length ? timeline.subtasks : [timeline]
  return [...nodes].filter((item) => item.deadline && !['done', 'completed'].includes(item.status)).sort((a, b) => a.deadline.localeCompare(b.deadline))[0] || null
}

const categoryStats = computed(() => categoryDefinitions.map((definition) => {
  const timelines = tasks.value.filter((task) => taskCategory(task) === definition.key)
  const scores = timelines.map(timelineRisk)
  const nextItems = timelines.map(timelineNext).filter(Boolean).sort((a, b) => a.deadline.localeCompare(b.deadline))
  return {
    ...definition,
    timelines,
    configured: timelines.length > 0,
    count: timelines.length,
    nodeCount: timelines.reduce((sum, task) => sum + (task.subtasks?.length || 0), 0),
    progress: timelines.length ? Math.round(timelines.reduce((sum, item) => sum + timelineProgress(item), 0) / timelines.length) : 0,
    risk: scores.length ? Math.round(Math.max(...scores) * 0.6 + (scores.reduce((sum, value) => sum + value, 0) / scores.length) * 0.4) : 0,
    next: nextItems[0] || null,
  }
}))

const selectedCategoryStats = computed(() => categoryStats.value.find((item) => item.key === selectedCategoryMeta.value?.key) || { timelines: [], progress: 0, risk: 0, count: 0, nodeCount: 0, next: null, configured: false })
const categoryTimelines = computed(() => selectedCategoryStats.value.timelines || [])

const selectedTimeline = computed(() => {
  const taskId = Number(route.params.taskId)
  if (!taskId) return null
  return categoryTimelines.value.find((item) => item.id === taskId) || null
})

const inlineEeTimeline = computed(() => selectedCategoryMeta.value?.key === 'EE' && !route.params.taskId && categoryTimelines.value.length === 1 ? categoryTimelines.value[0] : null)
const detailTimeline = computed(() => selectedTimeline.value || inlineEeTimeline.value)

const overall = computed(() => {
  const configured = categoryStats.value.filter((item) => item.configured)
  const risks = configured.map((item) => item.risk)
  const nextItems = configured.map((item) => item.next).filter(Boolean).sort((a, b) => a.deadline.localeCompare(b.deadline))
  return {
    configured: configured.length > 0,
    progress: configured.length ? Math.round(configured.reduce((sum, item) => sum + item.progress, 0) / configured.length) : 0,
    risk: risks.length ? Math.round(Math.max(...risks) * 0.55 + (risks.reduce((sum, value) => sum + value, 0) / risks.length) * 0.45) : 0,
    next: nextItems[0] || null,
  }
})

const overallSummary = computed(() => {
  if (!overall.value.configured) return { title: t('progress.s1Title'), description: t('progress.s1Desc') }
  if (overall.value.risk >= 70) return { title: t('progress.s2Title'), description: t('progress.s2Desc') }
  if (overall.value.risk >= 40) return { title: t('progress.s3Title'), description: t('progress.s3Desc') }
  return { title: t('progress.s4Title'), description: t('progress.s4Desc') }
})

const visibleTimelines = computed(() => {
  if (!selectedCategoryMeta.value?.groups?.length || !activeGroup.value) return categoryTimelines.value
  return categoryTimelines.value.filter((item) => String(item.subject || '').toLowerCase() === activeGroup.value.toLowerCase())
})

const createButtonLabel = computed(() => selectedCategoryMeta.value?.key === 'IA' ? t('progress.addSubject') : selectedCategoryMeta.value?.key === 'CAS' ? t('progress.addRecord') : t('progress.addTimeline'))
const createDialogTitle = computed(() => selectedCategoryMeta.value?.key === 'IA' ? t('progress.createSubjectTimeline') : t('progress.createTimeline'))
const subjectFieldLabel = computed(() => selectedCategoryMeta.value?.key === 'IA' ? t('progress.subjectName') : t('progress.subjectOptional'))
const titlePlaceholder = computed(() => selectedCategoryMeta.value?.key === 'IA' ? t('progress.iaTitlePlaceholder') : selectedCategoryMeta.value?.key === 'EE' ? t('progress.eeTitlePlaceholder') : t('progress.timelineTitlePlaceholder'))
const canCreateTimeline = computed(() => {
  if (!selectedCategoryMeta.value) return false
  if (selectedCategoryMeta.value.key === 'IA' && !timelineForm.value.subject.trim()) return false
  if (selectedCategoryMeta.value.groups?.length && !timelineForm.value.subject) return false
  return Boolean(timelineForm.value.title.trim() || timelineForm.value.subject)
})
const emptyCategoryDescription = computed(() => t(`progress.empty${selectedCategoryMeta.value?.key || 'IA'}Desc`))

function categoryTitle(key) { return t(`progress.${key.toLowerCase()}Title`) }
function categoryDescription(key) { return t(`progress.${key.toLowerCase()}Desc`) }
function groupLabel(group) { return t(`progress.group${group}`) }
function groupCount(group) { return categoryTimelines.value.filter((item) => String(item.subject || '').toLowerCase() === group.toLowerCase()).length }
function timelineBadge(timeline) { return (timeline.subject || selectedCategoryMeta.value?.key || '').slice(0, 3).toUpperCase() }
function riskLevel(value) { return value >= 70 ? 'high' : value >= 40 ? 'medium' : 'low' }
function riskLabel(value) { return value >= 70 ? t('progress.highRisk') : value >= 40 ? t('progress.watchRisk') : t('progress.lowRisk') }
function riskColor(value) { return value >= 70 ? 'error' : value >= 40 ? 'warning' : 'success' }
function categoryStatus(category) { return category.risk >= 70 ? t('progress.needAction') : category.progress >= 80 ? t('progress.almostDone') : t('progress.steady') }
function timelineStatus(timeline) { const value = timelineProgress(timeline); return value === 100 ? t('progress.done') : value > 0 ? t('progress.inProgress') : t('progress.pending') }

function formatDate(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat(locale.value, { month: 'short', day: 'numeric' }).format(new Date(`${value}T00:00:00`))
}

function templateFor(category, subject = '') {
  if (category === 'IA') return ['iaTopic', 'iaResearch', 'iaDraft', 'iaFeedback', 'iaFinal'].map((key) => t(`progress.${key}`))
  if (category === 'EE') return ['eeTopic', 'eeQuestion', 'eeSources', 'eeWriting', 'eeReflection', 'eeSubmission'].map((key) => t(`progress.${key}`))
  if (category === 'TOK' && String(subject).toLowerCase() === 'exhibition') return ['tokPlan', 'tokPrepare', 'tokComplete'].map((key) => t(`progress.${key}`))
  if (category === 'TOK') return ['tokPlan', 'tokDraft', 'tokRevise', 'tokComplete'].map((key) => t(`progress.${key}`))
  if (category === 'CAS' && ['Reflection', 'Evidence'].includes(subject)) return [t('progress.casComplete')]
  if (category === 'CAS') return ['casStart', 'casProgress', 'casComplete'].map((key) => t(`progress.${key}`))
  return []
}

function openCreateTimeline(group = '') {
  timelineForm.value = emptyTimelineForm()
  const fallbackGroup = group || activeGroup.value || selectedCategoryMeta.value?.groups?.[0] || ''
  timelineForm.value.subject = fallbackGroup
  createDialog.value = true
}

function defaultTimelineTitle() {
  const category = selectedCategoryMeta.value?.key
  const subject = timelineForm.value.subject.trim()
  if (category === 'IA') return `${subject} IA`
  if (category === 'EE') return timelineForm.value.title.trim() || t('progress.eeTitlePlaceholder')
  if (category === 'TOK') return `TOK ${subject}`
  return timelineForm.value.title.trim() || subject
}

function distributedDate(index, total, deadline) {
  if (!deadline) return null
  const start = new Date(); start.setHours(0, 0, 0, 0)
  const end = new Date(`${deadline}T00:00:00`)
  const date = new Date(start.getTime() + Math.max(0, end - start) * ((index + 1) / total))
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

async function apiRequest(path, options = {}) {
  const response = await authFetch(path, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${response.status}`)
  }
  return response.json().catch(() => ({}))
}

async function createTimeline() {
  saving.value = true
  let created = null
  try {
    const title = timelineForm.value.title.trim() || defaultTimelineTitle()
    created = await apiRequest('/api/tasks', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        task_type: 'process', title, description: '', category: selectedCategoryMeta.value.key,
        subject: timelineForm.value.subject || null, deadline: timelineForm.value.deadline || null,
        priority: timelineForm.value.priority, estimated_hours: 0,
      }),
    })
    if (timelineForm.value.useTemplate) {
      const nodes = templateFor(selectedCategoryMeta.value.key, timelineForm.value.subject)
      for (let index = 0; index < nodes.length; index += 1) {
        await apiRequest('/api/tasks/sub-tasks', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
            task_id: created.id, name: nodes[index], notice_time: distributedDate(index, nodes.length, timelineForm.value.deadline),
            level: index === nodes.length - 1 ? 'high' : 'medium', status: 'pending',
          }),
        })
      }
    }
    createDialog.value = false
    notifyTasksChanged()
    await loadTasks()
    if (selectedCategoryMeta.value.key !== 'EE') await router.push(`/progress/${selectedCategoryMeta.value.key.toLowerCase()}/${created.id}`)
  } catch (error) {
    if (created?.id) await authFetch(`/api/tasks/${created.id}`, { method: 'DELETE' }).catch(() => {})
    errorMessage.value = error.message
    errorVisible.value = true
  } finally {
    saving.value = false
  }
}

function openTimeline(timeline) { router.push(`/progress/${selectedCategoryMeta.value.key.toLowerCase()}/${timeline.id}`) }
function leaveTimeline() { router.push(detailTimeline.value && selectedCategoryMeta.value?.key === 'EE' && !route.params.taskId ? '/progress' : `/progress/${selectedCategoryMeta.value.key.toLowerCase()}`) }
function handleTimelineRemoved() { router.push(`/progress/${selectedCategoryMeta.value.key.toLowerCase()}`); loadTasks() }
function askAgentForCategory() { openAgent({ category: selectedCategoryMeta.value.key, subject: activeGroup.value || null, title: categoryTitle(selectedCategoryMeta.value.key) }) }

async function loadTasks() {
  loading.value = true
  try {
    const response = await authFetch('/api/tasks')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    tasks.value = await response.json()
  } catch (error) {
    errorMessage.value = error.message
    errorVisible.value = true
  } finally {
    loading.value = false
  }
}

watch(() => selectedCategoryMeta.value?.key, () => { activeGroup.value = selectedCategoryMeta.value?.groups?.[0] || '' }, { immediate: true })
let stopTaskSync
onMounted(() => { loadTasks(); stopTaskSync = onTasksChanged(loadTasks) })
onBeforeUnmount(() => stopTaskSync?.())
</script>

<style scoped>
.progress-page { position: relative; min-height: calc(100vh - 64px); padding: 28px clamp(22px, 5vw, 70px) 110px; color: #1e2942; }
.page-header, .category-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.category-header { align-items: center; }.category-header__copy { flex: 1; }.header-actions { display: flex; gap: 9px; }
.eyebrow { color: #4a6ce2; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
.page-header h1, .category-header h1 { margin-top: 4px; font-size: clamp(28px, 3vw, 39px); letter-spacing: -.04em; }.page-header p, .category-header p { margin-top: 7px; color: #7f899d; font-size: 12px; }
.overall-card { display: grid; grid-template-columns: 1.2fr auto 1fr; align-items: center; gap: 38px; padding: 28px 32px; border: 1px solid rgba(39,53,83,.09); background: linear-gradient(135deg, rgba(255,255,255,.96), rgba(244,247,255,.96)) !important; box-shadow: 0 18px 50px rgba(31,44,75,.07) !important; }
.section-tag { display: inline-flex; padding: 4px 9px; border-radius: 999px; color: #4169e8; background: #edf2ff; font-size: 10px; font-weight: 750; }.overall-card__copy h2 { margin-top: 12px; font-size: 22px; }.overall-card__copy p { max-width: 410px; margin-top: 7px; color: #808a9f; font-size: 11px; }.overall-next { display: flex; align-items: center; gap: 6px; margin-top: 13px; color: #5e6c87; font-size: 10px; }
.overall-score strong, .overall-score span { display: block; }.overall-score strong { font-size: 21px; }.overall-score span { color: #8f98aa; font-size: 9px; }
.overall-bars { display: grid; gap: 17px; }.status-bar > div { display: flex; justify-content: space-between; margin-bottom: 7px; color: #8b94a5; font-size: 10px; }.status-bar strong { color: #4e596f; }
.category-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }.category-card { padding: 22px; border: 1px solid rgba(39,53,83,.09); border-radius: 20px; color: #24304a; background: rgba(255,255,255,.94); box-shadow: 0 12px 34px rgba(31,44,75,.055); cursor: pointer; text-align: left; transition: transform .18s, box-shadow .18s; }.category-card:hover { transform: translateY(-3px); box-shadow: 0 18px 38px rgba(31,44,75,.1); }
.category-card__header { display: flex; align-items: center; gap: 11px; }.category-icon { min-width: 47px; height: 39px; display: inline-grid; place-items: center; padding: 0 10px; border-radius: 12px; font-size: 14px; font-weight: 850; }.category-icon.large { height: 54px; min-width: 66px; border-radius: 16px; font-size: 18px; }.category-meta { flex: 1; color: #8d96a8; font-size: 10px; }.category-card__status { display: flex; align-items: baseline; gap: 9px; margin: 18px 0 14px; }.category-card__status strong { font-size: 24px; }.category-card__status span { color: #7e889c; font-size: 11px; }
.card-bars { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }.card-bars > div > span, .card-bars > div > strong { display: inline-block; margin-bottom: 6px; font-size: 9px; }.card-bars > div > span { color: #8b94a5; }.card-bars > div > strong { float: right; color: #59657b; }.category-next { display: flex; align-items: center; gap: 5px; margin-top: 14px; overflow: hidden; color: #8c96a8; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.category-summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }.category-summary-grid .v-card { padding: 18px; border: 1px solid rgba(39,53,83,.09); background: rgba(255,255,255,.94) !important; }.category-summary-grid span, .category-summary-grid strong, .category-summary-grid small { display: block; }.category-summary-grid span { color: #8791a4; font-size: 10px; }.category-summary-grid strong { margin: 7px 0 10px; font-size: 20px; }.category-summary-grid small { overflow: hidden; color: #929bad; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.category-summary-grid .next-date { font-size: 14px; }
.group-tabs { display: flex; gap: 8px; margin: 20px 0 14px; overflow-x: auto; }.group-tabs button { display: inline-flex; align-items: center; gap: 8px; padding: 8px 13px; border: 1px solid #e2e6ef; border-radius: 999px; color: #68758d; background: white; cursor: pointer; font-size: 11px; }.group-tabs button.active { border-color: #8298eb; color: #3559cd; background: #edf2ff; }.group-tabs span { min-width: 18px; padding: 1px 5px; border-radius: 999px; color: #65718a; background: rgba(100,115,150,.1); font-size: 9px; text-align: center; }
.timeline-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-top: 18px; }.timeline-card { padding: 20px; border: 1px solid rgba(39,53,83,.09); border-radius: 18px; color: #27344d; background: rgba(255,255,255,.95); cursor: pointer; text-align: left; transition: transform .17s, box-shadow .17s; }.timeline-card:hover { transform: translateY(-2px); box-shadow: 0 14px 34px rgba(31,44,75,.08); }.timeline-card__top { display: grid; grid-template-columns: auto minmax(0,1fr) auto; align-items: center; gap: 11px; }.timeline-avatar { width: 43px; height: 43px; display: grid; place-items: center; border-radius: 13px; font-size: 10px; font-weight: 850; }.timeline-card h2 { overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }.timeline-card p { margin-top: 3px; color: #929bad; font-size: 9px; }.timeline-card__progress { display: flex; align-items: baseline; gap: 8px; margin: 17px 0 8px; }.timeline-card__progress strong { font-size: 22px; }.timeline-card__progress span { color: #8791a4; font-size: 10px; }.timeline-card__meta { display: flex; flex-wrap: wrap; gap: 11px; margin-top: 13px; color: #8c96a8; font-size: 9px; }.timeline-card__meta span { display: inline-flex; align-items: center; gap: 4px; }.risk-text-high { color: #d34b5c !important; }.risk-text-medium { color: #cf8125 !important; }.risk-text-low { color: #27966c !important; }
.category-empty { min-height: 390px; display: flex; flex-direction: column; align-items: center; justify-content: center; margin-top: 18px; padding: 36px; border: 1px dashed #d9dfeb; border-radius: 22px; color: #7f899c; background: rgba(255,255,255,.62); text-align: center; }.category-empty > span { width: 76px; height: 76px; display: grid; place-items: center; border-radius: 23px; color: #5271dc; background: #edf2ff; }.category-empty h2 { margin-top: 16px; color: #334059; font-size: 18px; }.category-empty p { max-width: 430px; margin-top: 6px; font-size: 11px; }.category-empty > div { display: flex; gap: 9px; margin-top: 18px; }
.dialog-title { padding: 22px 24px 8px; font-weight: 750; }.dialog-body { padding: 18px 24px 4px !important; }.dialog-actions { padding: 12px 24px 22px; }.page-loading { position: fixed; inset: 64px 0 0; z-index: 4; display: grid; place-items: center; background: rgba(248,249,252,.68); backdrop-filter: blur(3px); }
@media (max-width: 900px) { .category-summary-grid { grid-template-columns: 1fr 1fr; }.category-header { align-items: flex-start; flex-wrap: wrap; }.header-actions { width: 100%; justify-content: flex-end; }.overall-card { grid-template-columns: 1fr auto; }.overall-bars { grid-column: 1 / -1; grid-template-columns: 1fr 1fr; } }
@media (max-width: 700px) { .progress-page { padding: 20px 14px 110px; }.page-header { align-items: flex-start; }.category-grid, .timeline-grid { grid-template-columns: 1fr; }.category-summary-grid { grid-template-columns: 1fr 1fr; }.header-actions .v-btn { flex: 1; }.overall-card { grid-template-columns: 1fr; }.overall-score { justify-self: start; }.overall-bars { grid-template-columns: 1fr; }.card-bars { grid-template-columns: 1fr 1fr; } }
@media (max-width: 480px) { .category-summary-grid { grid-template-columns: 1fr; }.category-empty > div { flex-direction: column; width: 100%; } }
</style>
